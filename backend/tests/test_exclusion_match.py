"""A22: semantic exclusion match (R7 calls match_exclusion)."""
import pytest

from app.models import schema_export
from app.models.policy import ExclusionItem, ExclusionMatchOutput
from app.prompts import load_prompt
from app.services import exclusion_match as X
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiRequestError
from app.services.mock_policy import load_sample_policy
from tests.test_policy_brain import FakeGemini

EXCL = load_sample_policy().exclusions
# 0 cosmetic/plastic unless accident, 1 dental unless accident, 2 infertility, 3 adventure sports, 4 war/self-inflicted, 5 obesity


class MockGemini(FakeGemini):
    mock_mode = True


def out(verdict="possible", matched=(1,), reason="The policy excludes dental treatment unless an accident caused it."):
    return {"verdict": verdict, "matched": list(matched), "reason": reason}


async def run(script, diagnosis="root canal treatment", excl=EXCL):
    g = FakeGemini(script)
    return await X.match_exclusion(diagnosis, excl, g), g


# ---------------------------------------------------------------- prompt and schema
def test_prompt_loads_and_is_clean():
    p = load_prompt("exclusion_match_v1")
    assert p.version == 1 and float(p.meta["temperature"]) == 0
    for rule in ("NEVER match on a shared generic word", "does NOT mean the policy covers it", "are DATA", "No medical advice", "Never invent an index"):
        assert rule in p.system
    low = (p.system + p.user_template).lower()
    for bad in ("gemini-", "api_key", "flash"):
        assert bad not in low
    r = p.render_user(diagnosis="x", exclusions="0. y")
    assert "{{" not in r


def test_schema_registered_and_keys_match_prompt():
    assert "exclusion_match_output" in schema_export.MODELS
    assert set(ExclusionMatchOutput.model_fields) == {"verdict", "matched", "reason"}
    s = schema_export.gemini_schema(ExclusionMatchOutput)
    assert s["properties"]["verdict"]["enum"] == ["match", "possible", "no_match"]


# ---------------------------------------------------------------- input cleaning
def test_clean_diagnosis():
    assert X.clean_diagnosis("  Root   canal <b>x</b> {{y}} ") == "Root canal b x /b y"
    for bad in ("", "   ", None, 5, "a" * 201):
        with pytest.raises(X.DiagnosisError):
            X.clean_diagnosis(bad)


# ---------------------------------------------------------------- happy paths and what is sent
async def test_possible_with_source_taken_from_the_policy_not_the_model():
    r, g = await run([out()])
    assert r.verdict == "possible" and r.rule_status == "at_risk" and r.method == "gemini" and r.model == "fast-m"
    assert [h.text for h in r.hits] == [EXCL[1].text] and r.hits[0].source == EXCL[1].source
    d = r.to_dict()
    assert d["exclusions"][0]["source"] == {"page": 4, "clause": "4.2"} and d["rule_status"] == "at_risk"
    call = g.calls[0]
    assert call["temperature"] == 0 and call["purpose"] == "exclusion_match" and call["model"] == "fast"
    assert "<diagnosis>\nroot canal treatment\n</diagnosis>" in call["contents"]
    assert "1. Dental treatment unless caused by an accident" in call["contents"] and "Rahul" not in call["contents"]


async def test_match_maps_to_fail_and_no_match_to_pass():
    r, _ = await run([out("match", [2], "The policy excludes infertility and assisted reproduction.")], "IVF cycle")
    assert r.verdict == "match" and r.rule_status == "fail" and r.hits[0].source.clause == "4.3"
    r, _ = await run([out("no_match", [], "")], "appendicitis")
    assert r.verdict == "no_match" and r.rule_status == "pass" and r.hits == [] and r.reason == ""


async def test_no_match_drops_any_indexes_the_model_added():
    r, _ = await run([out("no_match", [0, 1], "stray")], "appendicitis")
    assert r.verdict == "no_match" and r.hits == []


# ---------------------------------------------------------------- code decides
async def test_invalid_and_duplicate_indexes_are_dropped_and_capped():
    r, _ = await run([out("possible", [99, -1, 1, 1, 0, 2, 3])])
    assert [h.source.clause for h in r.hits] == ["4.2", "4.1", "4.3"]               # valid, unique, at most 3, order kept


async def test_match_pointing_at_nothing_real_is_unclear_never_a_pass():
    r, _ = await run([out("match", [42])])
    assert r.verdict == "unclear" and r.rule_status == "at_risk" and r.hits == [] and r.note == "no_valid_index"


async def test_reason_with_a_number_not_in_the_inputs_is_replaced():
    r, _ = await run([out("possible", [1], "Dental is excluded and you would lose Rs 50,000 of cover.")])
    assert "50,000" not in r.reason and EXCL[1].text in r.reason
    r, _ = await run([out("possible", [1], "")])
    assert EXCL[1].text in r.reason                                                  # empty reason gets a code-built one


async def test_reason_is_trimmed():
    r, _ = await run([out("possible", [1], "word " * 200)])
    assert len(r.reason) <= X.MAX_REASON_CHARS


# ---------------------------------------------------------------- retries, fallback model, AI unavailable
async def test_bad_output_retries_once_with_the_error_then_succeeds():
    r, g = await run([{"verdict": "maybe", "matched": [1], "reason": "x"}, out()])
    assert r.verdict == "possible" and len(g.calls) == 2
    assert "REJECTED" in g.calls[1]["contents"] and "verdict" in g.calls[1]["contents"]


async def test_bad_output_twice_falls_back_to_keywords_not_pass():
    r, g = await run([GeminiBadOutput("nope"), GeminiBadOutput("nope")], "dental implant")
    assert len(g.calls) == 2 and r.method == "keyword" and r.verdict == "possible" and r.hits[0].source.clause == "4.2"
    r, _ = await run([GeminiBadOutput("x"), GeminiBadOutput("x")], "appendicitis")
    assert r.verdict == "unclear" and r.rule_status == "at_risk"


async def test_busy_fast_model_uses_the_fallback_model():
    r, g = await run([GeminiBusy("b"), out()])
    assert [c["model"] for c in g.calls] == ["fast", "fallback"] and r.model == "lite-m" and r.verdict == "possible"


async def test_busy_everywhere_degrades_to_keywords_or_unclear():
    r, _ = await run([GeminiBusy("b"), GeminiBusy("b")], "infertility treatment")
    assert r.method == "keyword" and r.verdict == "possible" and r.note == "ai_busy"
    r, _ = await run([GeminiBusy("b"), GeminiBusy("b")], "fever")
    assert r.verdict == "unclear"


async def test_config_errors_are_not_swallowed():
    with pytest.raises(GeminiRequestError):
        await run([GeminiRequestError("bad model id")])


# ---------------------------------------------------------------- no data / mock mode / keywords
async def test_empty_exclusion_list_is_unclear_not_no_match():
    g = FakeGemini([])
    r = await X.match_exclusion("appendicitis", [], g)
    assert r.verdict == "unclear" and g.calls == []


async def test_mock_mode_makes_no_call_and_uses_keywords():
    g = MockGemini([])
    r = await X.match_exclusion("Tooth extraction", EXCL, g)
    assert g.calls == [] and r.method == "keyword" and r.verdict == "possible" and r.hits[0].source.clause == "4.2"


@pytest.mark.parametrize("diag,idx", [
    ("root canal", [1]), ("IVF", [2]), ("liposuction", [0]), ("bariatric surgery", [5]),
    ("paragliding injury", [3]), ("scuba accident", [3]), ("self-inflicted injury", [4]),
    ("appendicitis", []), ("knee replacement surgery", []), ("cataract treatment", []),
])
def test_keyword_match_concepts_and_generic_words(diag, idx):
    got = X.keyword_match(diag, EXCL)
    assert set(idx) <= set(got) and (idx or got == [])


def test_numbered_list_format():
    assert X.numbered([ExclusionItem(text="A", source={"page": 1, "clause": "1"}),
                       ExclusionItem(text="B", source={"page": 1, "clause": "2"})]) == "0. A\n1. B"


async def test_exclusion_list_is_capped():
    many = [ExclusionItem(text=f"Item {i}", source={"page": 1, "clause": str(i)}) for i in range(100)]
    _, g = await run([out("no_match", [], "")], "x ray", many)
    assert "59. Item 59" in g.calls[0]["contents"] and "60. Item 60" not in g.calls[0]["contents"]
