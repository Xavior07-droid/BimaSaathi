import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.models.policy import PolicyBrain
from app.services import policy_brain as PB
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiClient, GeminiRequestError, GeminiResult
from app.services.pdf import parse_document

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "sample_policies"
MANIFEST = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))["policies"]


def pdf_bytes(name):
    return (SAMPLES / name).read_bytes()


def answer_from_manifest(p):
    e = p["expected"]
    src = lambda page: {"page": page, "clause": "x"}
    return {
        "insurer": e["insurer"], "policy_no": e["policy_no"], "policy_type": "health", "holder_name": e["holder_name"],
        "start_date": e["start_date"], "end_date": e["end_date"], "renewal_date": e["renewal_date"],
        "sum_insured": e["sum_insured"], "premium": e["premium"], "waiting_periods": e["waiting_periods"],
        "room_rent_cap": e["room_rent_cap"], "copay_percent": e["copay_percent"],
        "sub_limits": [{"item": i, "limit": l, "source": src(pg)} for i, l, pg in e["sub_limits"]],
        "covered": [{"text": "Hospitalisation", "source": src(2)}],
        "exclusions": [{"text": "Cosmetic surgery", "source": src(4 if p["pages"] > 3 else 3)}],
        "claim_requirements": {"cashless": [], "reimbursement": [], "intimation_deadline_hours": e["intimation_deadline_hours"]},
    }


class FakeGemini:
    """Scripted stand-in for GeminiClient.generate_json. Items: dict -> ok, Exception -> raised."""
    mock_mode = False

    def __init__(self, script):
        self.script, self.calls = list(script), []

    async def generate_json(self, contents, **kw):
        self.calls.append({"contents": contents, **kw})
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        model = "fast-m" if kw["model"] == "fast" else "lite-m"
        return GeminiResult(data=step, text=json.dumps(step), model=model, attempts=1, latency_ms=1, total_tokens=100)


CLEAN = pdf_bytes("01_sanjivani_suraksha_clean.pdf")
GOOD = answer_from_manifest(MANIFEST[0])


def bad(**over):
    d = json.loads(json.dumps(GOOD))
    d.update(over)
    return d


async def test_first_try_success_and_request_shape():
    g = FakeGemini([GOOD])
    out = await PB.extract_policy(CLEAN, gemini=g)
    assert out.calls == 1 and not out.retried and not out.used_fallback and out.model == "fast-m"
    call = g.calls[0]
    assert call["model"] == "fast" and call["temperature"] == 0.0 and call["purpose"] == "extract"
    assert "NEVER GUESS" in call["system"] and call["schema"]["type"] == "object"
    pdf, text = call["contents"]
    assert pdf.inline_data.mime_type == "application/pdf" and "[Page 1]" in text and "5 pages" in text


async def test_retry_with_error_then_success_on_same_model():
    g = FakeGemini([bad(copay_percent=150), GOOD])
    out = await PB.extract_policy(CLEAN, gemini=g)
    assert out.retried and out.calls == 2 and not out.used_fallback
    retry_text = g.calls[1]["contents"][1]
    assert "REJECTED" in retry_text and "copay_percent" in retry_text
    assert "REJECTED" not in g.calls[0]["contents"][1]
    assert g.calls[1]["model"] == "fast"


async def test_two_failures_then_fallback_model_succeeds():
    g = FakeGemini([bad(copay_percent=150), bad(sum_insured=-1), GOOD])
    out = await PB.extract_policy(CLEAN, gemini=g)
    assert out.used_fallback and out.calls == 3 and out.model == "lite-m"
    assert [c["model"] for c in g.calls] == ["fast", "fast", "fallback"]


async def test_three_failures_raise_extraction_failed():
    g = FakeGemini([bad(copay_percent=150)] * 3)
    with pytest.raises(PB.ExtractionFailed) as e:
        await PB.extract_policy(CLEAN, gemini=g)
    assert e.value.error_code == "extraction_failed" and len(g.calls) == 3


async def test_invalid_json_counts_as_rejection():
    g = FakeGemini([GeminiBadOutput("Model output is not valid JSON: x"), GOOD])
    out = await PB.extract_policy(CLEAN, gemini=g)
    assert out.retried and "not valid JSON" in g.calls[1]["contents"][1]


async def test_busy_fast_model_goes_straight_to_fallback():
    g = FakeGemini([GeminiBusy("busy"), GOOD])
    out = await PB.extract_policy(CLEAN, gemini=g)
    assert [c["model"] for c in g.calls] == ["fast", "fallback"] and out.used_fallback and not out.retried


async def test_busy_fallback_propagates():
    g = FakeGemini([GeminiBusy("b"), GeminiBusy("b")])
    with pytest.raises(GeminiBusy):
        await PB.extract_policy(CLEAN, gemini=g)


async def test_request_error_is_not_retried():
    g = FakeGemini([GeminiRequestError("bad key")])
    with pytest.raises(GeminiRequestError):
        await PB.extract_policy(CLEAN, gemini=g)
    assert len(g.calls) == 1


async def test_cited_page_beyond_document_is_rejected_and_retried():
    wrong = bad(covered=[{"text": "x", "source": {"page": 9, "clause": "1"}}])
    g = FakeGemini([wrong, GOOD])
    out = await PB.extract_policy(CLEAN, gemini=g)
    assert out.retried and "page 9 does not exist" in g.calls[1]["contents"][1]


async def test_hallucinated_number_lowers_confidence_but_is_not_rejected():
    g = FakeGemini([bad(sum_insured=777777)])
    out = await PB.extract_policy(CLEAN, gemini=g)
    assert out.calls == 1 and any("sum_insured" in w for w in out.warnings) and out.confidence < 1


async def test_scanned_document_has_no_confidence():
    g = FakeGemini([answer_from_manifest(MANIFEST[3])])
    out = await PB.extract_policy(pdf_bytes(MANIFEST[3]["file"]), gemini=g)
    assert out.confidence is None and out.warnings == []


@pytest.mark.parametrize("p", MANIFEST[:3], ids=lambda p: p["file"][:2])
async def test_grounding_verifies_ground_truth_on_every_text_sample(p):
    """Exercises the number/date matchers on real sample text: 'Rs. 10,00,000', '1st April 2025', '15/06/2025', Marathi digits."""
    g = FakeGemini([answer_from_manifest(p)])
    out = await PB.extract_policy(pdf_bytes(p["file"]), gemini=g)
    assert out.confidence == 1.0 and out.warnings == []


async def test_ingest_document_builds_valid_brain():
    brain = await PB.ingest_document(CLEAN, gemini=FakeGemini([GOOD]), policy_id="p-1")
    assert isinstance(brain, PolicyBrain) and brain.policy_id == "p-1"
    assert brain.extraction_meta.file_hash == parse_document(CLEAN).file_hash
    assert brain.extraction_meta.model == "fast-m" and brain.extraction_meta.confidence == 1.0
    assert brain.plain_summary is None and brain.red_flags == []
    PolicyBrain.model_validate(brain.to_store())


async def test_mock_mode_returns_sample_and_calls_nothing():
    g = GeminiClient(Settings(_env_file=None, gemini_api_key=""), client=SimpleNamespace())
    brain = await PB.ingest_document(b"not even a pdf", gemini=g)
    assert brain.policy_id == "sample-policy"


async def test_photo_upload_sends_image_part():
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (600, 800), "white").save(buf, "JPEG")
    g = FakeGemini([bad(sub_limits=[], covered=[], exclusions=[])])
    out = await PB.extract_policy(buf.getvalue(), gemini=g)
    label, img, text = g.calls[0]["contents"]            # A10: "[Page 1]" label, then the image, then the instructions
    assert label == "[Page 1]" and img.inline_data.mime_type == "image/jpeg" and out.confidence is None
    assert out.input_mode == "page_images" and out.image_pages == 1
