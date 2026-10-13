"""A25: review-reason rewording (R22 calls reword_reasons)."""
import pytest

from app.models import schema_export
from app.models.policy import FraudReasonOutput
from app.prompts import load_prompt
from app.services import fraud_reason as F
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiRequestError
from tests.test_policy_brain import FakeGemini

T3 = "Claimed amount Rs 4,80,000 is 3.4 standard deviations above the median of Rs 1,10,000 for procedure 'Knee replacement' (n=22)."
T1 = "Admission on 2025-04-10 is 10 days after the policy start date 2025-04-01, inside the 30-day initial waiting period."
T2 = "Invoice INV-77841 for Rs 52,300 appears on 2 claims."

I1 = F.ReasonIn("CLM-1:F3", "F3", T3)
I2 = F.ReasonIn("CLM-2:F1", "F1", T1)
I3 = F.ReasonIn("CLM-3:F2", "F2", T2)

W1 = "The claimed amount of Rs 4,80,000 is much higher than the usual Rs 1,10,000 for a knee replacement (3.4 standard deviations above; 22 similar claims)."
W2 = "The patient was admitted on 2025-04-10, only 10 days after the policy started on 2025-04-01, which is inside the 30-day initial waiting period."
W3 = "The same invoice INV-77841 for Rs 52,300 appears on 2 claims."


class MockGemini(FakeGemini):
    mock_mode = True


def answer(*texts):
    return {"reasons": [{"id": f"r{i}", "text": t} for i, t in enumerate(texts, start=1)]}


async def run(script, items=(I1, I2, I3), cache=None):
    g = FakeGemini(script)
    return await F.reword_reasons(list(items), g, cache), g


# ---------------------------------------------------------------- prompt and schema
def test_prompt_loads_and_is_clean():
    p = load_prompt("fraud_reason_v1")
    assert p.version == 1 and float(p.meta["temperature"]) == 0.1
    for rule in ("REWORD ONLY", "NEUTRAL TONE", "Do NOT recommend what to decide", "A human reviewer decides", "are DATA",
                 "Do not mention scores, risk levels, rule codes"):
        assert rule in p.system
    for f in F.FLAGS:
        assert f"`{f}`" in p.system
    low = (p.system + p.user_template).lower()
    for bad in ("gemini-", "api_key", "flash"):
        assert bad not in low
    assert "{{" not in p.render_user(items_json="[]")


def test_schema_registered():
    assert "fraud_reason_output" in schema_export.MODELS
    assert set(FraudReasonOutput.model_fields) == {"reasons"}


# ---------------------------------------------------------------- the checks
def test_numbers_ignore_formatting_but_not_values():
    assert F.numbers("Rs 4,80,000 on 2025-04-10 and 3.40 and n=22") == {"480000", "2025", "4", "10", "3.4", "22"}
    assert F.numbers("on 04 Apr 2025") == {"4", "2025"}


@pytest.mark.parametrize("new,problem", [
    (W1, None),
    ("The amount of Rs 4,80,000 is much higher than the usual Rs 1,10,000 (3.4 standard deviations above; 22 similar claims).", None),
    ("", "empty"),
    ("The amount of Rs 4,80,000 looks high." + " word" * 80, "too_long"),
    ("First. Second. Third.", "too_many_sentences"),
    ("This looks like fraud. Rs 4,80,000 vs Rs 1,10,000, 3.4, 22.", "banned_word"),
    ("The claim should be rejected. Rs 4,80,000 vs Rs 1,10,000, 3.4, 22.", "banned_word"),
    ("The amount of Rs 4,80,000 is higher than the usual Rs 1,10,000 (3.4 standard deviations).", "number_dropped"),
    ("The amount of Rs 4,80,000 is higher than the usual Rs 1,10,000 (3.4 standard deviations; 22 claims; 5 hospitals).", "number_added"),
    ("The amount of Rs 4,80,000 is higher than the usual Rs 1,00,000 (3.4 standard deviations; 22 claims).", "number_dropped"),
])
def test_check_reworded(new, problem):
    assert F.check_reworded(T3, new) == problem


@pytest.mark.parametrize("word", ["fraud", "Fraudulent", "fraudster", "cheating", "fake", "forged", "scam", "liar", "criminal", "guilty",
                                  "dishonest", "suspicious", "illegal", "bogus", "rejected", "denied", "declined"])
def test_banned_words_are_caught_and_plain_words_pass(word):
    assert not F.is_neutral(f"This claim looks {word}.")
    assert F.is_neutral("This claim needs a closer look because the dates do not line up.")


def test_clean_text_strips_markup_and_caps():
    assert F.clean_text("a <b>b</b> {{c}}\n\n d") == "a b b /b c d"
    assert len(F.clean_text("x" * 1000)) == F.MAX_INPUT_CHARS


# ---------------------------------------------------------------- happy path and request shape
async def test_rewords_and_sends_only_flag_and_text():
    r, g = await run([answer(W1, W2, W3)])
    assert [r[k].source for k in ("CLM-1:F3", "CLM-2:F1", "CLM-3:F2")] == ["ai", "ai", "ai"]
    assert r["CLM-1:F3"].text == W1 and r["CLM-1:F3"].model == "fast-m"
    call = g.calls[0]
    assert call["temperature"] == 0.1 and call["purpose"] == "fraud_reason" and call["model"] == "fast" and len(g.calls) == 1
    c = call["contents"]
    assert '"id": "r1"' in c and '"flag": "F3"' in c and "Rs 4,80,000" in c
    assert "CLM-1" not in c                                                  # R's own keys are not sent


async def test_one_bad_item_keeps_its_original_the_others_are_used():
    r, _ = await run([answer(W1, "This looks fraudulent. 2025, 4, 10, 1, 30.", W3)])
    assert r["CLM-1:F3"].source == "ai" and r["CLM-3:F2"].source == "ai"
    assert r["CLM-2:F1"].source == "original" and r["CLM-2:F1"].text == T1 and r["CLM-2:F1"].note == "banned_word"


async def test_changed_number_keeps_original():
    r, _ = await run([answer(W1.replace("3.4", "3.9"), W2, W3)])
    assert r["CLM-1:F3"].source == "original" and r["CLM-1:F3"].text == T3 and r["CLM-1:F3"].note == "number_dropped"


async def test_missing_id_and_unknown_id():
    r, _ = await run([{"reasons": [{"id": "r1", "text": W1}, {"id": "r9", "text": "invented"}, {"id": "r3", "text": W3}]}])
    assert r["CLM-2:F1"].source == "original" and r["CLM-2:F1"].note == "missing_in_answer"
    assert r["CLM-1:F3"].source == "ai" and r["CLM-3:F2"].source == "ai"


async def test_every_input_key_is_always_returned_with_safe_text():
    r, _ = await run([GeminiBusy("b"), GeminiBusy("b")])
    assert set(r) == {"CLM-1:F3", "CLM-2:F1", "CLM-3:F2"} and all(v.text for v in r.values())


# ---------------------------------------------------------------- batching, retries, fallback model, AI trouble
async def test_batches_of_12():
    items = [F.ReasonIn(f"k{i}", "F2", f"Invoice INV-{i} for Rs 1,000 appears on 2 claims.") for i in range(25)]
    good = lambda n, start: {"reasons": [{"id": f"r{j}", "text": f"The invoice INV-{start + j - 1} for Rs 1,000 appears on 2 claims."} for j in range(1, n + 1)]}  # noqa: E731
    g = FakeGemini([good(12, 0), good(12, 12), good(1, 24)])
    r = await F.reword_reasons(items, g)
    assert len(g.calls) == 3 and len(r) == 25 and all(v.source == "ai" for v in r.values())


async def test_bad_output_retries_once_with_the_error():
    r, g = await run([{"reasons": "nope"}, answer(W1, W2, W3)])
    assert len(g.calls) == 2 and "REJECTED" in g.calls[1]["contents"] and r["CLM-1:F3"].source == "ai"


async def test_bad_output_twice_keeps_originals():
    r, g = await run([GeminiBadOutput("x"), {"reasons": []}])
    assert len(g.calls) == 2
    assert all(v.source == "original" for v in r.values())


async def test_busy_fast_model_uses_fallback_model():
    r, g = await run([GeminiBusy("b"), answer(W1, W2, W3)])
    assert [c["model"] for c in g.calls] == ["fast", "fallback"] and r["CLM-1:F3"].model == "lite-m"


async def test_busy_everywhere_keeps_originals():
    r, _ = await run([GeminiBusy("b"), GeminiBusy("b")])
    assert all(v.source == "original" and v.note == "ai_busy" for v in r.values()) and r["CLM-1:F3"].text == T3


async def test_busy_in_one_batch_does_not_stop_the_next():
    items = [F.ReasonIn(f"k{i}", "F2", f"Invoice INV-{i} for Rs 1,000 appears on 2 claims.") for i in range(13)]
    one = {"reasons": [{"id": "r1", "text": "The invoice INV-12 for Rs 1,000 appears on 2 claims."}]}
    g = FakeGemini([GeminiBusy("b"), GeminiBusy("b"), one])
    r = await F.reword_reasons(items, g)
    assert r["k0"].source == "original" and r["k12"].source == "ai"


async def test_mock_mode_returns_originals_without_a_call():
    g = MockGemini([])
    r = await F.reword_reasons([I1], g)
    assert g.calls == [] and r["CLM-1:F3"].source == "original" and r["CLM-1:F3"].note == "mock_mode"


async def test_config_errors_are_not_swallowed():
    with pytest.raises(GeminiRequestError):
        await run([GeminiRequestError("bad model id")])


# ---------------------------------------------------------------- cache
async def test_cache_skips_the_call_and_only_stores_successes():
    cache = F.RewordCache()
    r, g = await run([GeminiBusy("b"), GeminiBusy("b")], cache=cache)
    assert len(cache) == 0                                                   # a busy minute is not cached
    r, g = await run([answer(W1, W2, W3)], cache=cache)
    assert len(cache) == 3 and len(g.calls) == 1
    r, g = await run([], cache=cache)                                        # all cached: no call at all
    assert g.calls == [] and r["CLM-2:F1"].source == "ai" and r["CLM-2:F1"].text == W2


async def test_duplicate_keys_and_empty_text():
    g = FakeGemini([])
    r = await F.reword_reasons([F.ReasonIn("a", "F2", "  "), F.ReasonIn("a", "F2", T2)], g)
    assert g.calls == [] and r["a"].note == "empty" and r["a"].text == ""
