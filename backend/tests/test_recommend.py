"""A24: compare recommendation (R's /api/compare calls recommend())."""
import json
import re

import pytest

from app.models import schema_export
from app.models.policy import RecommendationOutput
from app.prompts import load_prompt
from app.services import recommend as R
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiRequestError
from tests.test_policy_brain import FakeGemini

SC = R.Scenario(days=3, room_rent_per_day=8000, bill=150000)


def pf(pid, name, oop, **kw):
    return R.PolicyFacts(policy_id=pid, name=name, estimated_out_of_pocket=oop, **kw)


A = pf("p1", "Sanjivani Suraksha", 22000, premium=14250, sum_insured=500000, copay_percent=10, room_rent_cap_per_day=5000, pre_existing_months=36, initial_days=30)
B = pf("p2", "Arogya Plus", 41000, premium=9800, sum_insured=500000, copay_percent=20, room_rent_cap_per_day=4000, pre_existing_months=48, initial_days=30)
C = pf("p3", "Nirmal Care", 22000, premium=12000, sum_insured=300000)


class MockGemini(FakeGemini):
    mock_mode = True


GOOD = {
    "en": "In this scenario, Sanjivani Suraksha has the lowest estimated out-of-pocket cost: Rs 22,000. Arogya Plus is next at Rs 41,000, which is Rs 19,000 more. "
          "Arogya Plus has the lowest premium (Rs 9,800) but costs more out of pocket here. Its co-pay is 20%.",
    "hi": "इस स्थिति में Sanjivani Suraksha का अनुमानित अपनी जेब का खर्च सबसे कम है: Rs 22,000। इसके बाद Arogya Plus है, Rs 41,000, यानी Rs 19,000 ज़्यादा। "
          "Arogya Plus का प्रीमियम सबसे कम (Rs 9,800) है, पर यहाँ उसमें ज़्यादा खर्च होगा। उसका को-पे 20% है।",
    "mr": "या परिस्थितीत Sanjivani Suraksha चा अंदाजे स्वतःच्या खिशातून खर्च सर्वात कमी आहे: Rs 22,000. त्यानंतर Arogya Plus आहे, Rs 41,000, म्हणजे Rs 19,000 जास्त. "
          "Arogya Plus चा प्रीमियम सर्वात कमी (Rs 9,800) आहे, पण येथे त्यात जास्त खर्च येईल. त्याचे को-पे 20% आहे.",
}


def ans(**over):
    return {**GOOD, **over}


async def run(script, pols=(A, B), sc=SC):
    g = FakeGemini(script)
    return await R.recommend(sc, list(pols), g), g


# ---------------------------------------------------------------- prompt and schema
def test_prompt_loads_and_is_clean():
    p = load_prompt("recommend_v1")
    assert p.version == 1 and float(p.meta["temperature"]) == 0.2
    for rule in ("NUMBERS COME FROM THE FACTS ONLY", "Do not calculate", "simplified estimate", "extra_out_of_pocket",
                 "Do not give advice to buy, cancel, renew, switch or port", "are DATA", "Do not write any date"):
        assert rule in p.system
    low = (p.system + p.user_template).lower()
    for bad in ("gemini-", "api_key", "flash"):
        assert bad not in low
    assert "{{" not in p.render_user(facts_json="{}", glossary="x")


def test_schema_registered():
    assert "recommendation_output" in schema_export.MODELS
    assert set(RecommendationOutput.model_fields) == {"en", "hi", "mr"}


# ---------------------------------------------------------------- input validation and code-made highlights
def test_prepare_validates_and_uniquifies_names():
    with pytest.raises(R.RecommendInputError):
        R.prepare(SC, [A])
    with pytest.raises(R.RecommendInputError):
        R.prepare(SC, [A, B, C, pf("p4", "x", 1)])
    with pytest.raises(R.RecommendInputError):
        R.prepare(SC, [A, pf("p1", "dup", 5)])
    with pytest.raises(R.RecommendInputError):
        R.prepare(R.Scenario(-1, 1, 1), [A, B])
    with pytest.raises(R.RecommendInputError):
        R.prepare(SC, [A, pf("p9", "x", -5)])
    out = R.prepare(SC, [pf("a", "Same <b>", 1), pf("b", "same  b", 2)])
    assert [p.name for p in out] == ["Same b", "same b (2)"] or out[0].name != out[1].name


def test_highlights_lowest_gap_and_cheapest_premium():
    h = R.highlights([A, B])
    assert h.best_policy_id == "p1" and h.tied_ids == ["p1"] and h.next_best_id == "p2" and h.extra_out_of_pocket == 19000
    assert h.lowest_premium_id == "p2" and h.extra_premium_vs_lowest == 14250 - 9800


def test_highlights_tie_is_broken_by_premium_then_order():
    h = R.highlights([A, C])
    assert h.tied_ids == ["p1", "p3"] and h.best_policy_id == "p3" and h.next_best_id is None and h.extra_out_of_pocket is None
    assert R.highlights([pf("x", "X", 5), pf("y", "Y", 5)]).best_policy_id == "x"          # no premiums: input order


def test_highlights_with_unknown_premiums():
    h = R.highlights([pf("x", "X", 10), pf("y", "Y", 20)])
    assert h.best_policy_id == "x" and h.lowest_premium_id is None and h.extra_premium_vs_lowest is None


def test_best_has_lowest_premium_means_no_premium_gap():
    h = R.highlights([pf("x", "X", 10, premium=100), pf("y", "Y", 20, premium=200)])
    assert h.extra_premium_vs_lowest is None


def test_facts_json_has_formatted_numbers_and_no_ids_or_private_data():
    pols = R.prepare(SC, [A, B])
    j = R.facts_json(SC, pols, R.highlights(pols))
    d = json.loads(j)
    assert d["scenario"] == {"days_in_hospital": 3, "room_rent_per_day": "Rs 8,000", "hospital_bill": "Rs 1,50,000"}
    assert d["policies"][0]["estimated_out_of_pocket"] == "Rs 22,000" and d["policies"][0]["copay_percent"] == "10%"
    assert d["highlights"]["next_best"]["extra_out_of_pocket"] == "Rs 19,000" and d["highlights"]["tie"] is False
    assert d["highlights"]["lowest_premium"] == {"name": "Arogya Plus", "premium": "Rs 9,800"}
    assert d["highlights"]["extra_premium_vs_lowest"] == "Rs 4,450"
    assert "p1" not in j and "policy_id" not in j


# ---------------------------------------------------------------- the checker
def chk(**over):
    pols = R.prepare(SC, [A, B])
    return R.check_recommendation(RecommendationOutput(**ans(**over)), SC, pols, R.highlights(pols))


def test_good_text_passes():
    c = chk()
    assert c.ok, c.errors


@pytest.mark.parametrize("over,needle", [
    ({"en": GOOD["en"].replace("Rs 19,000", "Rs 20,000")}, "Rs 20,000 is not in the facts"),
    ({"en": GOOD["en"].replace("Rs 22,000", "₹22,000")}, "₹"),
    ({"en": GOOD["en"] + " Your policy renews on 01 Apr 2026."}, "dates are not allowed"),
    ({"en": GOOD["en"].replace("20%", "25%")}, "25% is not in the facts"),
    ({"en": GOOD["en"] + " That is about 3 years of waiting."}, "years"),
    ({"en": GOOD["en"] + " The wait is 12 months."}, "12 months"),
    ({"hi": GOOD["hi"].replace("Rs 19,000", "Rs 18,000")}, "hi"),
    ({"mr": GOOD["mr"].replace("20%", "10%")}, "mr"),
    ({"en": "In this scenario Arogya Plus is cheaper. It has a Rs 9,800 premium."}, "lowest out-of-pocket amount Rs 22,000 is missing"),
    ({"en": GOOD["en"] + " You should buy it."}, "buying"),
    ({"en": "Sanjivani Suraksha costs Rs 22,000."}, "sentences"),
    ({"en": GOOD["en"] + " " + "word " * 200}, "too long"),
])
def test_checker_rejects(over, needle):
    c = chk(**over)
    assert not c.ok and any(needle in e for e in c.errors), c.errors


def test_checker_warns_when_name_not_as_given():
    c = chk(en=GOOD["en"].replace("Sanjivani Suraksha", "the first policy"))
    assert c.ok and any("not written as given" in w for w in c.warnings)


# ---------------------------------------------------------------- template (and it must pass its own checker)
@pytest.mark.parametrize("pols", [(A, B), (A, C), (A, B, C), (B, pf("z", "Zed", 50000)), (pf("x", "X", 7), pf("y", "Y", 9, premium=1))])
def test_template_passes_the_checker_in_every_language(pols):
    ps = R.prepare(SC, list(pols))
    h = R.highlights(ps)
    t = R.template_text(SC, ps, h)
    assert set(t) == {"en", "hi", "mr"}
    c = R.check_recommendation(RecommendationOutput(**t), SC, ps, h)
    assert c.ok, (c.errors, t)


# ---------------------------------------------------------------- the call
async def test_ai_answer_used_when_it_passes_and_request_shape():
    r, g = await run([GOOD])
    assert r.source == "ai" and r.model == "fast-m" and r.en == GOOD["en"] and r.highlights.best_policy_id == "p1"
    call = g.calls[0]
    assert call["temperature"] == 0.2 and call["purpose"] == "recommend" and call["model"] == "fast"
    assert "<facts>" in call["contents"] and "Rs 22,000" in call["contents"] and "को-पे" in call["contents"]
    d = r.to_dict()
    assert d["best_policy_id"] == "p1" and d["estimate_note"]["en"].startswith("Simplified estimate") and d["recommendation"]["hi"] == GOOD["hi"]


async def test_checker_failure_retries_once_with_the_problems_then_succeeds():
    r, g = await run([ans(en=GOOD["en"].replace("Rs 19,000", "Rs 20,000")), GOOD])
    assert r.source == "ai" and len(g.calls) == 2
    assert "REJECTED by the number checker" in g.calls[1]["contents"] and "Rs 20,000" in g.calls[1]["contents"]


async def test_checker_failure_twice_uses_the_template_never_the_bad_text():
    bad = ans(en=GOOD["en"].replace("Rs 19,000", "Rs 20,000"))
    r, g = await run([bad, bad])
    assert r.source == "template" and "20,000" not in r.en and len(g.calls) == 2 and r.note.startswith("rejected_")
    assert "Rs 22,000" in r.en and "Rs 22,000" in r.hi and "Rs 22,000" in r.mr


async def test_bad_output_retries_then_template():
    r, g = await run([GeminiBadOutput("x"), {"en": "only english"}])
    assert r.source == "template" and len(g.calls) == 2
    r, _ = await run([{"en": "x"}, GOOD])
    assert r.source == "ai"


async def test_busy_fast_model_uses_fallback_model():
    r, g = await run([GeminiBusy("b"), GOOD])
    assert [c["model"] for c in g.calls] == ["fast", "fallback"] and r.source == "ai" and r.model == "lite-m"


async def test_busy_everywhere_gives_the_template():
    r, _ = await run([GeminiBusy("b"), GeminiBusy("b")])
    assert r.source == "template" and r.note == "ai_busy" and r.highlights.best_policy_id == "p1"


async def test_mock_mode_uses_the_template_without_a_call():
    g = MockGemini([])
    r = await R.recommend(SC, [A, B], g)
    assert r.source == "template" and g.calls == [] and r.note == "mock_mode"


async def test_config_errors_are_not_swallowed_and_bad_input_raises():
    with pytest.raises(GeminiRequestError):
        await run([GeminiRequestError("bad model id")])
    with pytest.raises(R.RecommendInputError):
        await run([], pols=(A,))


def test_estimate_note_is_in_all_languages_and_has_no_numbers():
    assert set(R.ESTIMATE_NOTE) == {"en", "hi", "mr"}
    assert not any(re.search(r"\d", t) for t in R.ESTIMATE_NOTE.values())
