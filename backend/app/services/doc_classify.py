"""Claim-document vision classifier (A23). R9 (docs_check.py) calls `classify_document` once per image.

    image bytes (already compressed by R with Pillow) -> local checks (type, size, decodes, big enough)
        -> Gemini vision (doc_classify_v1) -> validate DocumentClassification -> code cleans it
        -> ClassifyResult(ok, classification, model, error_code)

What the model reads (doc type, patient name, dates, stamp, signature, quality) is only INPUT to R's rules. Comparing names/dates between
documents, deciding found / missing / unclear and the score are done in code by R (R10/R11), never here and never by the model.

Failure handling, so one bad image never breaks a claim check of 8:
    - AI busy / bad output twice  -> ok=False with an error_code; R shows that document as "unclear" (never "found")
    - image too small to read     -> answered locally (no Gemini call, saves free-tier quota): doc_type "unreadable"
    - MOCK mode (no API key)      -> ok=False, error_code "mock_mode" (a fake "found" would mislead); tests pass a fake client
    - bad API key / model ID      -> GeminiRequestError is raised (a config bug, not a runtime condition)
Privacy: the image goes to Gemini only for this call and is never stored. Claim documents are health data and the free Gemini tier may
use inputs, which is why the consent screen says to upload only sample or anonymised documents.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from app.models.policy import DocDate, DocumentClassification
from app.models.schema_export import gemini_schema
from app.prompts import load_prompt
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiClient, image_part

log = logging.getLogger("bimasaathi.doc_classify")

PROMPT_NAME = "doc_classify_v1"
ALLOWED_MIME = ("image/jpeg", "image/png", "image/webp")
MAX_IMAGE_BYTES = 5 * 1024 * 1024        # R compresses first; this only guards against sending something huge
MIN_SIDE_PX = 150                         # smaller than this cannot be read, so do not spend a Gemini call
MIN_YEAR = 2000
MAX_NAME_CHARS = 80


class ImageError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class ClassifyResult:
    ok: bool
    classification: DocumentClassification | None = None
    model: str | None = None              # "local" when answered without Gemini
    error_code: str | None = None         # ai_busy | bad_output | mock_mode (when ok is False)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "error_code": self.error_code,
                "classification": self.classification.model_dump(mode="json") if self.classification else None}


# ------------------------------------------------------------------ doc types and required-document matching (for R8 / R9)
DOC_TYPE_LABELS = {
    "claim_form": "Claim form", "discharge_summary": "Discharge summary", "hospital_bill": "Hospital bill",
    "pharmacy_bill": "Pharmacy bill", "investigation_report": "Investigation report", "prescription": "Doctor's prescription",
    "doctor_note": "Doctor's note or certificate", "id_proof": "ID proof", "insurance_card": "Health card / policy copy",
    "cancelled_cheque": "Cancelled cheque", "police_report": "Police / medico-legal report", "other": "Other document",
    "unreadable": "Unreadable image",
}
# Lowercase phrases in a policy's required-document text -> doc types that can satisfy it. First match wins per phrase list.
_REQUIREMENT_KEYWORDS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("claim form",), ("claim_form",)),
    (("discharge",), ("discharge_summary",)),
    (("pharmacy", "chemist", "medicine bill", "medicines bill", "prescribed medicine"), ("pharmacy_bill",)),
    (("hospital bill", "final bill", "itemised bill", "itemized bill", "original bill", "invoice", "bills"), ("hospital_bill",)),
    (("investigation", "diagnostic", "lab report", "laboratory", "pathology", "radiology", "x-ray", "xray", "scan report", "test report"), ("investigation_report",)),
    (("prescription",), ("prescription",)),
    (("doctor", "physician", "referral", "certificate", "admission note", "treating"), ("doctor_note", "prescription")),
    (("id proof", "identity", "aadhaar", "aadhar", "pan card", "kyc", "photo id"), ("id_proof",)),
    (("health card", "e-card", "ecard", "policy copy", "policy document", "insurance card"), ("insurance_card",)),
    (("cheque", "bank", "passbook", "neft"), ("cancelled_cheque",)),
    (("fir", "police", "medico", "mlc"), ("police_report",)),
)


def doc_types_for_requirement(text: str) -> list[str]:
    """Which classified doc types satisfy a required-document line such as 'Original discharge summary'. [] if we do not recognise it."""
    low = " " + re.sub(r"[^a-z0-9\- ]+", " ", text.casefold()) + " "
    for words, types in _REQUIREMENT_KEYWORDS:
        if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) for w in words):
            return list(types)
    return []


# ------------------------------------------------------------------ local checks
def check_image(data: bytes, mime_type: str) -> tuple[int, int]:
    """Raise ImageError for the wrong type / too big / not an image. Returns (width, height)."""
    if mime_type not in ALLOWED_MIME:
        raise ImageError("unsupported_image_type", "Please upload a JPG, PNG or WebP photo of the document.")
    if not data:
        raise ImageError("empty_image", "The image is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError("image_too_large", "The image is too large. Please use a smaller photo.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ImageError("invalid_image", "This file is not a readable image.") from None


def _too_small_result() -> ClassifyResult:
    doc = DocumentClassification(doc_type="unreadable", patient_name=None, dates=[], has_stamp=False, has_signature=False,
                                 quality="poor", issues=["low_resolution", "unreadable"])
    return ClassifyResult(True, doc, "local")


# ------------------------------------------------------------------ code cleans what the model read
_TITLES = re.compile(r"^(?:(?:mr|mrs|ms|miss|dr|smt|shri|sri|master|baby|late)\b\.?\s*)+", re.IGNORECASE)
_NO_NAME = {"", "n/a", "na", "nil", "none", "null", "unknown", "not available", "not mentioned", "-"}


def clean_name(name: str | None) -> str | None:
    if name is None:
        return None
    n = re.sub(r"\s+", " ", name).strip(" .,:;-")
    n = _TITLES.sub("", n).strip()
    if n.casefold() in _NO_NAME or not re.search(r"[A-Za-zऀ-ॿ]", n):
        return None
    return n[:MAX_NAME_CHARS]


def clean(doc: DocumentClassification, today: date) -> DocumentClassification:
    """Deterministic fixes: plausible dates only, no duplicates, consistent flags for unreadable images."""
    seen: set[tuple[str, date]] = set()
    dates: list[DocDate] = []
    for d in doc.dates:
        if not (MIN_YEAR <= d.date.year <= today.year + 1) or d.date > today + timedelta(days=1):
            continue                                              # a document cannot carry a future date; a misread year is dropped
        if (d.label, d.date) not in seen:
            seen.add((d.label, d.date))
            dates.append(d)
    out = doc.model_copy(update={"dates": dates, "patient_name": clean_name(doc.patient_name),
                                 "issues": list(dict.fromkeys(doc.issues))})
    if out.doc_type == "unreadable":
        issues = list(dict.fromkeys([*out.issues, "unreadable"]))
        out = out.model_copy(update={"patient_name": None, "dates": [], "has_stamp": False, "has_signature": False,
                                     "quality": "poor", "issues": issues})
    elif out.quality == "good" and out.issues:
        out = out.model_copy(update={"quality": "fair"})          # "good" with listed problems is contradictory: be cautious
    return out


# ------------------------------------------------------------------ the call
async def _call(gemini, contents, system: str, schema: dict, model: str):
    return await gemini.generate_json(contents, schema=schema, system=system, temperature=0.0, model=model, purpose="doc_classify")


async def _call_with_fallback(gemini, contents, system, schema, model: str):
    try:
        return await _call(gemini, contents, system, schema, model), model
    except GeminiBusy:
        if model == "fallback":
            raise
        log.warning("fast model busy; using the fallback model")
        return await _call(gemini, contents, system, schema, "fallback"), "fallback"


async def classify_document(data: bytes, mime_type: str, gemini: GeminiClient,
                            today: Callable[[], date] = date.today) -> ClassifyResult:
    """Classify one claim-document image. Raises ImageError for a bad file (R maps it to a 400); AI trouble returns ok=False."""
    w, h = check_image(data, mime_type)
    if min(w, h) < MIN_SIDE_PX:
        return _too_small_result()
    if gemini.mock_mode:
        return ClassifyResult(False, None, None, "mock_mode")
    prompt = load_prompt(PROMPT_NAME)
    schema = gemini_schema(DocumentClassification)
    contents = [prompt.render_user(), image_part(data, mime_type)]
    model_key, note = "fast", ""
    for _attempt in (1, 2):                                       # 2nd attempt = one retry with the validation error
        try:
            res, model_key = await _call_with_fallback(gemini, [contents[0] + note, contents[1]], prompt.system, schema, model_key)
            doc = DocumentClassification.model_validate(res.data)
            return ClassifyResult(True, clean(doc, today()), res.model)
        except GeminiBusy:
            log.warning("doc classify: AI busy")
            return ClassifyResult(False, None, None, "ai_busy")
        except GeminiBadOutput as e:
            last = e.message
        except ValidationError as e:
            last = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in
                             e.errors(include_url=False, include_context=False, include_input=False))[:400]
        note = f"\n\nYour previous answer was REJECTED: {last}\nReturn corrected JSON only."
    return ClassifyResult(False, None, None, "bad_output")
