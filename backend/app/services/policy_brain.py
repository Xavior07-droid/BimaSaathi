"""Policy Brain extraction (A9): document bytes -> validated PolicyBrain.

Flow:  parse (A7) -> call 1 on the FAST model -> Pydantic + document checks
       -> on failure ONE retry with the error appended -> then the FALLBACK (Flash-Lite) model
       -> else ExtractionFailed.   Overload (GeminiBusy) on the fast model skips straight to the fallback.

Scanned path (A10): when the text layer is unusable (>= 50% of pages under 100 characters, or a photo),
the PDF is NOT attached; each page is rendered to a 150 DPI JPEG and sent as "[Page N]" label + image so the
model can cite real page numbers. Rendering happens once per document, not once per retry.

Summaries / red flags (second Gemini call) are A16; this returns a PolicyBrain with plain_summary=None.
MOCK mode (empty GEMINI_API_KEY) returns the sample policy and calls nothing.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Literal
from datetime import date, datetime, timezone

from pydantic import ValidationError

from app.models.policy import ExtractionMeta, PolicyBrain, PolicyExtraction
from app.models.schema_export import gemini_schema
from app.prompts import load_prompt
from app.services.gemini import (GeminiBadOutput, GeminiBusy, GeminiClient, GeminiError, get_gemini,
                                 image_part, pdf_part)
from app.services.mock_policy import load_sample_policy
from app.services.pdf import (MAX_IMAGE_PAGES, PageImage, ParsedDocument, parse_document,
                              render_page_images)

log = logging.getLogger("bimasaathi.policy_brain")

PROMPT_NAME = "extract_v1"
MAX_ERRORS_IN_RETRY = 10
MAX_IMAGE_PAYLOAD_BYTES = 14_000_000    # Gemini inline request limit is ~20 MB; leave room for text + base64
LOW_DPI = 100                           # second try when 150 DPI pages are too heavy together

InputMode = Literal["pdf", "pdf_with_image_pages", "page_images", "pdf_native_scan"]


class ExtractionFailed(GeminiError):
    """All attempts (fast, fast+error, fallback) produced output that failed validation."""
    error_code = "extraction_failed"


@dataclass
class ExtractionOutcome:
    extraction: PolicyExtraction
    model: str
    calls: int                     # logical Gemini calls made (1-3)
    retried: bool                  # needed the error-appended retry
    used_fallback: bool
    warnings: list[str] = field(default_factory=list)
    confidence: float | None = None
    prompt_label: str = ""
    total_tokens: int = 0
    input_mode: str = ""           # how the document was sent (see InputMode)
    image_pages: int = 0           # page images attached (0 unless input_mode == "page_images")


# ------------------------------------------------------------------ contents
@dataclass
class DocumentInput:
    """What goes to Gemini besides the instructions: attachments + the page-tagged text block."""
    parts: list
    document_text: str
    mode: InputMode
    image_pages: int = 0


def document_text(parsed: ParsedDocument, image_note: str) -> str:
    """'[Page N]' blocks. A page without a text layer gets a one-line note instead of an empty block, so the
    model knows to read that page from the image / attached PDF rather than concluding it is blank."""
    blocks = []
    for p in parsed.pages:
        body = image_note if p.needs_image and not p.text else p.text
        blocks.append(f"[Page {p.number}]\n{body}")
    return "\n\n".join(blocks)


def _page_image_parts(images: list[PageImage]) -> list:
    parts: list = []
    for im in images:
        parts.append(f"[Page {im.number}]")           # label precedes its image (extract_v1 prompt relies on this)
        parts.append(image_part(im.data, im.mime_type))
    return parts


def _render_within_budget(data: bytes) -> list[PageImage] | None:
    """150 DPI first; if the pages together are too heavy for one request, retry at 100 DPI; else None."""
    for dpi in (None, LOW_DPI):
        images = render_page_images(data) if dpi is None else render_page_images(data, dpi=dpi)
        total = sum(len(i.data) for i in images)
        if total <= MAX_IMAGE_PAYLOAD_BYTES:
            return images
        log.warning("page images too heavy (%d pages, %d bytes at dpi=%s)", len(images), total, dpi or "default")
    return None


def build_document_input(data: bytes, parsed: ParsedDocument) -> DocumentInput:
    """Decide how to show the document to the model (CPU-bound; call via asyncio.to_thread)."""
    # photo: always a single page image
    if parsed.kind == "image":
        images = render_page_images(data)
        return DocumentInput(_page_image_parts(images), document_text(parsed, "Read this page from its image."),
                             "page_images", len(images))

    pdf_note = "No text layer on this page: read it from the attached PDF."
    if parsed.is_scanned:
        if parsed.page_count <= MAX_IMAGE_PAGES:
            images = _render_within_budget(data)
            if images is not None:
                return DocumentInput(_page_image_parts(images),
                                     document_text(parsed, "No text layer: read this page from its image above."),
                                     "page_images", len(images))
        # too many pages / too heavy as images: let Gemini read the scanned PDF itself (its own page rendering)
        log.warning("scanned PDF sent as native PDF (pages=%d)", parsed.page_count)
        return DocumentInput([pdf_part(data)], document_text(parsed, pdf_note), "pdf_native_scan")

    mode: InputMode = "pdf_with_image_pages" if parsed.image_page_numbers else "pdf"
    return DocumentInput([pdf_part(data)], document_text(parsed, pdf_note), mode)


def _error_note(errors: list[str]) -> str:
    lines = "\n".join(f"- {e}" for e in errors[:MAX_ERRORS_IN_RETRY])
    return ("\n\nYour previous answer was REJECTED for these problems:\n" + lines +
            "\nReturn the corrected JSON object only. Fix these problems without inventing facts; use null where unsure.")


def _validation_messages(exc: ValidationError) -> list[str]:
    out = []
    for e in exc.errors(include_url=False, include_context=False, include_input=False):
        loc = ".".join(str(x) for x in e["loc"]) or "(root)"
        out.append(f"{loc}: {e['msg']}")
    return out


# ------------------------------------------------------------------ document checks
def check_against_document(ex: PolicyExtraction, parsed: ParsedDocument) -> list[str]:
    """HARD problems (trigger retry): a cited page that does not exist."""
    problems = []
    items = [*ex.sub_limits, *ex.covered, *ex.exclusions]
    for it in items:
        if it.source.page > parsed.page_count:
            problems.append(f"source.page {it.source.page} does not exist (document has {parsed.page_count} pages)")
    return problems


_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"]


def _normalise(text: str) -> str:
    t = text.translate(_DEVANAGARI).lower()
    return re.sub(r"(?<=\d),(?=\d)", "", t)          # 5,00,000 / 500,000 -> 500000


def _has_number(norm: str, n: int) -> bool:
    return re.search(rf"(?<!\d){n}(?!\d)", norm) is not None


def _has_date(norm: str, d: date) -> bool:
    m_full, m_abbr = _MONTHS[d.month - 1], _MONTHS[d.month - 1][:3]
    day = rf"0?{d.day}(?:st|nd|rd|th)?"
    pats = [rf"(?<!\d)0?{d.day}[/\-.]0?{d.month}[/\-.]{d.year}(?!\d)",
            rf"(?<!\d){day}\s+(?:{m_full}|{m_abbr})\.?,?\s+{d.year}(?!\d)",
            rf"(?:{m_full}|{m_abbr})\.?\s+{day},?\s+{d.year}(?!\d)"]
    return any(re.search(p, norm) for p in pats)


def grounding(ex: PolicyExtraction, parsed: ParsedDocument) -> tuple[float | None, list[str]]:
    """Share of extracted key facts found in the document's own text layer.

    Not a probability of correctness: it only measures "does the document contain this value". Facts written
    only in words ("Ten Lakh") count as unverified. None when the text layer is unusable (scanned/photo).
    """
    if parsed.is_scanned:
        return None, []
    norm = _normalise("\n".join(p.text for p in parsed.pages))
    checks: list[tuple[str, bool]] = []
    if ex.sum_insured is not None:
        checks.append(("sum_insured", _has_number(norm, ex.sum_insured)))
    if ex.premium is not None:
        checks.append(("premium", _has_number(norm, ex.premium)))
    for name in ("start_date", "end_date", "renewal_date"):
        v = getattr(ex, name)
        if v is not None:
            checks.append((name, _has_date(norm, v)))
    if ex.policy_no:
        checks.append(("policy_no", ex.policy_no.lower() in norm))
    if not checks:
        return None, []
    warnings = [f"{n} not found in the document text" for n, ok in checks if not ok]
    return round(sum(ok for _, ok in checks) / len(checks), 2), warnings


# ------------------------------------------------------------------ extraction
DEFAULT_PLAN: tuple[str, ...] = ("fast", "fast", "fallback")   # attempt 1, retry-with-error, fallback model


async def extract_policy(data: bytes, parsed: ParsedDocument | None = None,
                         gemini: GeminiClient | None = None,
                         plan: tuple[str, ...] = DEFAULT_PLAN) -> ExtractionOutcome:
    """`plan` is for the A14 evaluation script only (e.g. ("fast",) = first-attempt accuracy of the Flash model)."""
    gemini = gemini or get_gemini()
    parsed = parsed or await asyncio.to_thread(parse_document, data)
    prompt = load_prompt(PROMPT_NAME)
    schema = gemini_schema(PolicyExtraction)
    doc_in = await asyncio.to_thread(build_document_input, data, parsed)      # render images ONCE, not per retry
    base_text = prompt.render_user(page_count=parsed.page_count, document_text=doc_in.document_text)
    log.info("extract input mode=%s pages=%d image_pages=%d", doc_in.mode, parsed.page_count, doc_in.image_pages)

    plan = list(plan)
    errors: list[str] = []
    calls = tokens = rejections = 0
    i = 0
    while i < len(plan):
        which = plan[i]
        note = _error_note(errors) if errors else ""
        contents = [*doc_in.parts, base_text + note]
        try:
            calls += 1
            res = await gemini.generate_json(contents, schema=schema, system=prompt.system,
                                             temperature=float(prompt.meta.get("temperature", 0)),
                                             model=which, purpose="extract")
            tokens += res.total_tokens or 0
            ex = PolicyExtraction.model_validate(res.data)
            errors = check_against_document(ex, parsed)
            if errors:
                raise _Rejected(errors)
        except GeminiBusy:
            if which == "fallback" or "fallback" not in plan:
                raise
            log.warning("fast model busy; jumping to fallback model")
            i = plan.index("fallback")
            continue
        except GeminiBadOutput as e:
            errors = [e.message]
        except ValidationError as e:
            errors = _validation_messages(e)
        except _Rejected as e:
            errors = e.errors
        else:
            conf, warns = grounding(ex, parsed)
            if warns:
                log.warning("grounding warnings: %s", warns)
            return ExtractionOutcome(extraction=ex, model=res.model, calls=calls, retried=rejections > 0,
                                     used_fallback=(which == "fallback"), warnings=warns, confidence=conf,
                                     prompt_label=prompt.label, total_tokens=tokens,
                                     input_mode=doc_in.mode, image_pages=doc_in.image_pages)
        rejections += 1
        log.warning("extraction attempt %d (%s) rejected: %d problem(s)", i + 1, which, len(errors))
        i += 1
    raise ExtractionFailed("We could not read this policy reliably. Try a clearer copy.")


class _Rejected(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# ------------------------------------------------------------------ public entry
def new_policy_id() -> str:
    return uuid.uuid4().hex[:16]


async def ingest_document(data: bytes, gemini: GeminiClient | None = None,
                          policy_id: str | None = None, parsed: ParsedDocument | None = None) -> PolicyBrain:
    """bytes -> PolicyBrain (no summary yet). Raises PdfError / GeminiBusy / ExtractionFailed.
    `parsed` lets a caller that already validated the file (A12) skip a second PyMuPDF pass."""
    gemini = gemini or get_gemini()
    if gemini.mock_mode:
        return load_sample_policy()
    parsed = parsed or await asyncio.to_thread(parse_document, data)
    out = await extract_policy(data, parsed, gemini)
    meta = ExtractionMeta(model=out.model, confidence=out.confidence, file_hash=parsed.file_hash,
                          created_at=datetime.now(timezone.utc))
    return PolicyBrain.from_parts(policy_id=policy_id or new_policy_id(), extraction=out.extraction, meta=meta)
