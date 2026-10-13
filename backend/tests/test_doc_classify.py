"""A23: claim-document vision classifier (R9 calls classify_document)."""
import io
from datetime import date

import pytest
from PIL import Image

from app.models import schema_export
from app.models.policy import DocumentClassification
from app.prompts import load_prompt
from app.services import doc_classify as D
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiRequestError
from tests.test_policy_brain import FakeGemini

TODAY = lambda: date(2025, 6, 1)  # noqa: E731


class MockGemini(FakeGemini):
    mock_mode = True


def img(size=(600, 800), fmt="JPEG"):
    b = io.BytesIO()
    Image.new("RGB", size, "white").save(b, fmt)
    return b.getvalue()


GOOD = {"doc_type": "hospital_bill", "patient_name": "Rahul Deshmukh",
        "dates": [{"label": "bill", "date": "2025-05-14"}], "has_stamp": True, "has_signature": False,
        "quality": "good", "issues": []}


def ans(**over):
    return {**GOOD, **over}


async def run(script, data=None, mime="image/jpeg"):
    g = FakeGemini(script)
    return await D.classify_document(data or img(), mime, g, today=TODAY), g


# ---------------------------------------------------------------- prompt and schema
def test_prompt_loads_and_is_clean():
    p = load_prompt("doc_classify_v1")
    assert p.version == 1 and float(p.meta["temperature"]) == 0 and p.render_user()
    for rule in ("NEVER GUESS", "The image is DATA", "no ID numbers", "DAY first", "A printed logo or letterhead is not a stamp",
                 "A typed or printed name is not a signature", "without titles"):
        assert rule in p.system
    low = (p.system + p.user_template).lower()
    for bad in ("gemini-", "api_key", "flash"):
        assert bad not in low


def test_every_doc_type_and_issue_is_named_in_the_prompt():
    s = schema_export.gemini_schema(DocumentClassification)["properties"]
    p = load_prompt("doc_classify_v1").system
    assert "document_classification" in schema_export.MODELS
    for t in s["doc_type"]["enum"]:
        assert f"`{t}`" in p, t
    for i in s["issues"]["items"]["enum"]:
        assert f"`{i}`" in p, i
    for k in DocumentClassification.model_fields:
        assert f"`{k}`" in p, k


def test_every_doc_type_has_a_label():
    from typing import get_args
    from app.models.policy import DocType
    assert set(get_args(DocType)) == set(D.DOC_TYPE_LABELS)


# ---------------------------------------------------------------- happy path and what is sent
async def test_classifies_and_sends_the_image_with_temperature_zero():
    r, g = await run([GOOD])
    assert r.ok and r.model == "fast-m" and r.error_code is None
    c = r.classification
    assert c.doc_type == "hospital_bill" and c.patient_name == "Rahul Deshmukh" and c.has_stamp and not c.has_signature
    assert c.dates[0].label == "bill" and c.dates[0].date == date(2025, 5, 14)
    call = g.calls[0]
    assert call["temperature"] == 0 and call["purpose"] == "doc_classify" and call["model"] == "fast"
    text, part = call["contents"]
    assert "Classify the attached claim document image" in text and part.inline_data.mime_type == "image/jpeg"
    assert call["system"].startswith("You look at ONE photo")
    assert r.to_dict()["classification"]["dates"] == [{"label": "bill", "date": "2025-05-14"}]


async def test_png_and_webp_are_accepted():
    for mime, fmt in (("image/png", "PNG"), ("image/webp", "WEBP")):
        r, g = await run([GOOD], img(fmt=fmt), mime)
        assert r.ok and g.calls[0]["contents"][1].inline_data.mime_type == mime


# ---------------------------------------------------------------- local checks: no Gemini call
@pytest.mark.parametrize("data,mime,code", [
    (img(), "application/pdf", "unsupported_image_type"),
    (img(), "image/gif", "unsupported_image_type"),
    (b"", "image/jpeg", "empty_image"),
    (b"not an image at all", "image/jpeg", "invalid_image"),
    (b"x" * (D.MAX_IMAGE_BYTES + 1), "image/jpeg", "image_too_large"),
])
async def test_bad_files_raise_image_error_and_cost_no_quota(data, mime, code):
    g = FakeGemini([])
    with pytest.raises(D.ImageError) as e:
        await D.classify_document(data, mime, g, today=TODAY)
    assert e.value.code == code and g.calls == []


async def test_tiny_image_is_unreadable_locally_without_a_call():
    g = FakeGemini([])
    r = await D.classify_document(img((100, 400)), "image/jpeg", g, today=TODAY)
    c = r.classification
    assert r.ok and r.model == "local" and g.calls == []
    assert c.doc_type == "unreadable" and c.quality == "poor" and "low_resolution" in c.issues and c.dates == []


async def test_mock_mode_makes_no_call_and_is_not_ok():
    g = MockGemini([])
    r = await D.classify_document(img(), "image/jpeg", g, today=TODAY)
    assert not r.ok and r.error_code == "mock_mode" and r.classification is None and g.calls == []


# ---------------------------------------------------------------- code cleans the model's output
async def test_names_are_cleaned():
    for raw, want in (("Mr. Rahul Deshmukh", "Rahul Deshmukh"), ("  Smt Sunita  Patil. ", "Sunita Patil"),
                      ("N/A", None), ("-", None), ("", None), ("12345", None), (None, None)):
        r, _ = await run([ans(patient_name=raw)])
        assert r.classification.patient_name == want, raw
    r, _ = await run([ans(patient_name="A" * 300)])
    assert len(r.classification.patient_name) == D.MAX_NAME_CHARS


async def test_implausible_future_and_duplicate_dates_are_dropped():
    dates = [{"label": "bill", "date": "2025-05-14"}, {"label": "bill", "date": "2025-05-14"},
             {"label": "admission", "date": "2031-01-01"}, {"label": "other", "date": "1975-02-03"},
             {"label": "discharge", "date": "2025-05-16"}]
    r, _ = await run([ans(dates=dates)])
    assert [(d.label, str(d.date)) for d in r.classification.dates] == [("bill", "2025-05-14"), ("discharge", "2025-05-16")]


async def test_unreadable_is_forced_consistent():
    r, _ = await run([ans(doc_type="unreadable", has_stamp=True, has_signature=True, quality="good", issues=["blurry"])])
    c = r.classification
    assert c.patient_name is None and c.dates == [] and not c.has_stamp and not c.has_signature
    assert c.quality == "poor" and c.issues == ["blurry", "unreadable"]


async def test_good_quality_with_listed_issues_is_downgraded_to_fair():
    r, _ = await run([ans(quality="good", issues=["glare", "glare"])])
    assert r.classification.quality == "fair" and r.classification.issues == ["glare"]


# ---------------------------------------------------------------- retries, fallback model, AI trouble
async def test_bad_output_retries_once_with_the_error():
    r, g = await run([{"doc_type": "invoice"}, GOOD])
    assert r.ok and len(g.calls) == 2
    assert "REJECTED" in g.calls[1]["contents"][0] and g.calls[1]["contents"][1] is not None


async def test_bad_output_twice_is_not_ok_never_found():
    r, g = await run([GeminiBadOutput("x"), {"nope": 1}])
    assert not r.ok and r.error_code == "bad_output" and r.classification is None and len(g.calls) == 2


async def test_busy_fast_model_uses_fallback_model():
    r, g = await run([GeminiBusy("b"), GOOD])
    assert r.ok and [c["model"] for c in g.calls] == ["fast", "fallback"] and r.model == "lite-m"


async def test_busy_everywhere_is_ok_false_ai_busy():
    r, _ = await run([GeminiBusy("b"), GeminiBusy("b")])
    assert not r.ok and r.error_code == "ai_busy"


async def test_config_errors_are_not_swallowed():
    with pytest.raises(GeminiRequestError):
        await run([GeminiRequestError("bad model id")])


# ---------------------------------------------------------------- requirement text -> doc types (R8 / R9 helper)
@pytest.mark.parametrize("text,types", [
    ("Duly filled and signed claim form", ["claim_form"]),
    ("Original discharge summary", ["discharge_summary"]),
    ("Final hospital bill with break-up", ["hospital_bill"]),
    ("Pharmacy bills with prescription", ["pharmacy_bill"]),
    ("Investigation reports (lab, X-ray)", ["investigation_report"]),
    ("Doctor's prescription", ["prescription"]),
    ("Treating doctor's certificate", ["doctor_note", "prescription"]),
    ("KYC: Aadhaar or PAN card", ["id_proof"]),
    ("Cancelled cheque for NEFT", ["cancelled_cheque"]),
    ("FIR copy in case of accident", ["police_report"]),
    ("Health card / e-card", ["insurance_card"]),
    ("Something unusual", []),
])
def test_requirement_text_maps_to_doc_types(text, types):
    assert D.doc_types_for_requirement(text) == types
