"""A26: one contract, five Gemini-calling services (mocked Gemini, no network).

Every service that talks to Gemini must: send exactly its prompt file's system text and temperature, tag the call with
its purpose, use the Flash model first and Flash-Lite when Flash is busy, let config errors (bad key / bad model ID)
through, and make ZERO calls in MOCK mode. Per-service behaviour stays in each service's own test file.
"""
import io
from pathlib import Path

import pytest
from PIL import Image

from app.models.policy import ExclusionItem  # noqa: F401  (documents the type used below)
from app.prompts import load_prompt
from app.services import ask as A
from app.services import doc_classify as D
from app.services import exclusion_match as X
from app.services import fraud_reason as F
from app.services import policy_brain as PB
from app.services import recommend as R
from app.services.gemini import GeminiBusy, GeminiRequestError
from app.services.mock_policy import load_sample_policy
from tests.fakes import FakeGemini, MockModeGemini
from tests.test_policy_brain import CLEAN

BRAIN = load_sample_policy()
SCENARIO = R.Scenario(days=3, room_rent_per_day=8000, bill=150000)
POLICIES = [
    R.PolicyFacts(policy_id="p1", name="Sanjivani Suraksha", estimated_out_of_pocket=22000, premium=14250, sum_insured=500000,
                  copay_percent=10, room_rent_cap_per_day=5000, pre_existing_months=36, initial_days=30),
    R.PolicyFacts(policy_id="p2", name="Arogya Plus", estimated_out_of_pocket=41000, premium=9800, sum_insured=500000,
                  copay_percent=20, room_rent_cap_per_day=4000, pre_existing_months=48, initial_days=30),
]
REASONS = [F.ReasonIn("CLM-1:F2", "F2", "Invoice INV-77841 for Rs 52,300 appears on 2 claims.")]


def jpeg() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(b, "JPEG")
    return b.getvalue()


async def call_ask(g):
    return await A.answer_question(BRAIN, "What is my co-pay?", "en", g)


async def call_recommend(g):
    return await R.recommend(SCENARIO, list(POLICIES), g)


async def call_fraud(g):
    return await F.reword_reasons(list(REASONS), g)


async def call_doc(g):
    return await D.classify_document(jpeg(), "image/jpeg", g)


async def call_exclusion(g):
    return await X.match_exclusion("root canal treatment", BRAIN.exclusions, g)


async def call_extract(g):
    try:
        return await PB.extract_policy(CLEAN, gemini=g)
    except PB.ExtractionFailed:          # the fake returns junk on purpose: we only inspect the request
        return None


# (id, caller, prompt, purpose). Mock-mode is checked separately because extract's mock path is ingest_document.
CASES = [
    ("ask", call_ask, "ask_v1", "ask"),
    ("recommend", call_recommend, "recommend_v1", "recommend"),
    ("fraud_reason", call_fraud, "fraud_reason_v1", "fraud_reason"),
    ("doc_classify", call_doc, "doc_classify_v1", "doc_classify"),
    ("exclusion_match", call_exclusion, "exclusion_match_v1", "exclusion_match"),
    ("extract", call_extract, "extract_v1", "extract"),
]
IDS = [c[0] for c in CASES]
JUNK = [{}, {}, {}, {}]      # schema-invalid on purpose: the request is what we check, not the answer


@pytest.mark.parametrize("_id, caller, prompt_name, purpose", CASES, ids=IDS)
async def test_request_uses_the_prompt_file_and_the_fast_model(_id, caller, prompt_name, purpose):
    g = FakeGemini(list(JUNK))
    await caller(g)
    call, prompt = g.calls[0], load_prompt(prompt_name)
    assert call["system"] == prompt.system                      # prompt text comes from the versioned file, not a copy
    assert call["temperature"] == float(prompt.meta["temperature"])
    assert call["purpose"] == purpose and call["model"] == "fast"
    assert call["schema"]["type"] == "object"                   # structured output is always requested


@pytest.mark.parametrize("_id, caller, prompt_name, purpose", CASES, ids=IDS)
async def test_busy_flash_moves_to_flash_lite(_id, caller, prompt_name, purpose):
    g = FakeGemini([GeminiBusy("busy"), *JUNK])
    await caller(g)
    assert g.models[:2] == ["fast", "fallback"]


@pytest.mark.parametrize("_id, caller, prompt_name, purpose", CASES, ids=IDS)
async def test_a_bad_key_or_model_id_is_a_loud_error_not_a_quiet_fallback(_id, caller, prompt_name, purpose):
    g = FakeGemini([GeminiRequestError("bad key")])
    with pytest.raises(GeminiRequestError):
        await caller(g)
    assert len(g.calls) == 1                                    # no retry, no fallback model


@pytest.mark.parametrize("_id, caller, prompt_name, purpose", [c for c in CASES if c[0] != "extract"], ids=[i for i in IDS if i != "extract"])
async def test_mock_mode_makes_no_gemini_call(_id, caller, prompt_name, purpose):
    g = MockModeGemini([])
    await caller(g)
    assert g.calls == []


async def test_extract_in_mock_mode_serves_the_sample_policy_without_a_call():
    g = MockModeGemini([])
    brain = await PB.ingest_document(b"not even a pdf", gemini=g)
    assert g.calls == [] and brain.policy_id == BRAIN.policy_id


async def test_fake_gemini_refuses_to_run_past_its_script():
    g = FakeGemini([{"a": 1}])
    await g.generate_json("x", model="fast")
    with pytest.raises(AssertionError):
        await g.generate_json("x", model="fast")


# ------------------------------------------------------------- source-level guards for the hard rules
APP = Path(__file__).resolve().parents[1] / "app"


def test_no_model_id_is_hardcoded_in_app_code():
    """Build prompt section 8: model IDs only from env."""
    offenders = [str(p.relative_to(APP)) for p in APP.rglob("*.py") if "gemini-" in p.read_text(encoding="utf-8").lower()
                 and p.name != "gemini.py"]
    assert offenders == []
    gem = (APP / "services" / "gemini.py").read_text(encoding="utf-8")
    assert "gemini-1" not in gem and "gemini-2" not in gem and "gemini-3" not in gem


def test_no_service_logs_prompt_or_document_text():
    """Privacy: logs may carry model, latency, tokens. A log call that interpolates a text/contents variable is a leak."""
    bad = []
    for p in (APP / "services").glob("*.py"):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            s = line.strip()
            if s.startswith(("log.", "logging.")) and any(w in s for w in ("document_text", "contents", "question", "diagnosis", "res.text", "prompt.system")):
                bad.append(f"{p.name}:{n}")
    assert bad == []
