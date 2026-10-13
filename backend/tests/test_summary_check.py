"""A17: number-consistency checker."""
import copy
import json
from datetime import date

import pytest

from app.models.policy import PolicyBrain, SummaryOutput
from app.services import summary_check as S
from app.services.mock_policy import load_sample_policy

POLICY = load_sample_policy()


def good() -> dict:
    return {"plain_summary": POLICY.plain_summary.model_dump(), "red_flags": [r.model_dump() for r in POLICY.red_flags]}


def run(mutate=None, policy=POLICY):
    d = copy.deepcopy(good())
    if mutate:
        mutate(d)
    return S.check_summary(policy, SummaryOutput.model_validate(d), page_count=5)


def sub(lang, old, new):
    def m(d):
        assert old in d["plain_summary"][lang], f"{old!r} not in {lang}"
        d["plain_summary"][lang] = d["plain_summary"][lang].replace(old, new)
    return m


# ---------------------------------------------------------------- formats
@pytest.mark.parametrize("n,expect", [(0, "0"), (999, "999"), (1000, "1,000"), (14250, "14,250"), (200000, "2,00,000"),
                                     (500000, "5,00,000"), (10000000, "1,00,00,000"), (123456789, "12,34,56,789")])
def test_format_inr(n, expect):
    assert S.format_inr(n) == expect and S.format_amount(n) == f"Rs {expect}"


def test_format_date():
    assert S.format_date(date(2025, 4, 1)) == "01 Apr 2025" and S.format_date(date(2026, 3, 31)) == "31 Mar 2026"


def test_sample_policy_passes_with_no_errors_or_warnings():
    r = run()
    assert r.ok and r.errors == [] and r.warnings == []


def test_sample_policy_red_flags_use_no_invented_numbers():
    """Regression: the first sample said 'on a Rs 1,00,000 bill you pay Rs 10,000' (violates rule 4)."""
    for rf in POLICY.red_flags:
        assert "1,00,000" not in rf.why_it_matters


# ---------------------------------------------------------------- each corruption must be caught
@pytest.mark.parametrize("lang,old,new,needle", [
    ("hi", "Rs 5,00,000", "Rs 5,50,000", "not in the policy data"),            # wrong amount
    ("en", "Rs 5,00,000", "Rs 500,000", "must be written 'Rs 5,00,000'"),      # Western grouping
    ("mr", "Rs 5,00,000", "₹5,00,000", "₹"),                                   # rupee symbol
    ("hi", "Rs 5,00,000", "Rs. 5,00,000", "must be written 'Rs 5,00,000'"),    # 'Rs.'
    ("en", "Rs 5,00,000", "5 lakh", "words"),                                  # amount in words
    ("hi", "Rs 5,00,000", "पाँच लाख", "words"),
    ("mr", "Rs 14,250", "Rs १४,२५०", "Devanagari digits"),                     # Devanagari digits
    ("en", "01 Apr 2025", "1 Apr 2025", "must be written '01 Apr 2025'"),      # not zero padded
    ("en", "01 Apr 2025", "01/04/2025", "numeric date"),
    ("en", "31 Mar 2026", "31 March 2026", "long-form date"),
    ("hi", "01 Apr 2025", "01 अप्रैल 2025", "translated month"),
    ("mr", "31 Mar 2026", "31 मार्च 2026", "translated month"),
    ("en", "01 Apr 2026", "01 Apr 2027", "not in the policy data"),             # wrong renewal date
    ("en", "10%", "15%", "not in the policy data"),
    ("en", "30 days", "45 days", "not in the policy data"),
    ("en", "36 months", "3 years", "conversion of 36 months"),
    ("hi", "36 महीने", "3 साल", "conversion of 36 months"),
])
def test_corruptions_are_errors(lang, old, new, needle):
    r = run(sub(lang, old, new))
    assert not r.ok
    assert any(needle in e for e in r.errors), r.errors


def test_missing_sum_insured_or_dates_in_one_language_is_an_error():
    r = run(sub("mr", "Rs 5,00,000 चे संरक्षण", "संरक्षण"))
    assert any("summary.mr: sum insured Rs 5,00,000 is missing" in e for e in r.errors)
    r = run(sub("hi", "से 31 Mar 2026 तक", "तक"))
    assert any("summary.hi: end_date 31 Mar 2026 is missing" in e for e in r.errors)


def test_languages_that_are_each_valid_but_disagree_are_caught():
    """en says 30 days, hi says 36 days-class value that exists in data but not for this slot -> mismatch across languages."""
    r = run(sub("hi", "30 दिन", "36 दिन"))
    assert any("day/month counts differ" in e for e in r.errors)


def test_missing_premium_or_copay_is_only_a_warning():
    r = run(sub("en", "for a yearly premium of Rs 14,250", "for a yearly premium"))
    assert any("premium" in e for e in r.errors) is False
    assert any("summary.en: premium Rs 14,250 is missing" in w for w in r.warnings)
    assert any("amounts differ" in e for e in r.errors)                  # but the languages now disagree -> error


def test_mock_policy_amounts_differ_message_shows_both_sides():
    r = run(sub("hi", "Rs 14,250", "Rs 14,520"))
    msgs = " ".join(r.errors)
    assert "amounts differ" in msgs and "Rs 14,250" in msgs and "Rs 14,520" in msgs


# ---------------------------------------------------------------- red flags
def test_red_flag_with_new_number_is_rejected():
    def m(d):
        d["red_flags"][0]["why_it_matters"] = "On a Rs 2,00,000 bill you would pay Rs 20,000."
    r = run(m)
    assert any(e.startswith("red_flags[1]") and "Rs 20,000" in e for e in r.errors)


def test_red_flag_may_repeat_numbers_from_the_policy():
    def m(d):
        d["red_flags"][1]["why_it_matters"] = "Room rent above Rs 5,000 per day also cuts other charges; cover is Rs 5,00,000."
    assert run(m).ok


def test_red_flag_numbers_written_in_policy_text_are_allowed():
    """'Rs 2,000' exists only inside the ambulance sub-limit text; '24 hours'-style numbers inside covered text too."""
    def m(d):
        d["red_flags"][3]["why_it_matters"] = "Ambulance is paid up to Rs 2,000 and day care needs less than 24 hours."
    assert run(m).ok


def test_red_flag_source_page_must_exist():
    def m(d):
        d["red_flags"][0]["source"]["page"] = 9
    assert any("outside the document" in e for e in run(m).errors)


def test_red_flag_wrong_date_and_format():
    def m(d):
        d["red_flags"][2]["title"] = "Waiting until 5 Apr 2025 or ₹ 1000"
    r = run(m)
    assert any("red_flags[3]" in e for e in r.errors)


# ---------------------------------------------------------------- nulls = unknown
def test_null_facts_need_not_appear_and_extra_ones_are_rejected():
    p = PolicyBrain.model_validate({**POLICY.to_store(), "renewal_date": None, "premium": None, "copay_percent": None})
    ok = run(lambda d: d["plain_summary"].update({k: v.replace(" Renewal is due on 01 Apr 2026.", "").replace("नवीकरण", "x") for k, v in d["plain_summary"].items()}), policy=p)
    # summaries still mention premium / renewal date that are now unknown -> not allowed
    assert any("14,250 is not in the policy data" in e for e in ok.errors)
    assert any("01 Apr 2026 is not in the policy data" in e for e in ok.errors)


def test_policy_with_no_known_facts_accepts_a_vague_summary():
    p = PolicyBrain.model_validate({"policy_id": "x", "extraction_meta": POLICY.extraction_meta.model_dump()})
    s = SummaryOutput.model_validate({"plain_summary": {"en": "A health policy.", "hi": "एक स्वास्थ्य पॉलिसी।", "mr": "एक आरोग्य पॉलिसी."}, "red_flags": []})
    r = S.check_summary(p, s)
    assert r.ok and r.warnings == []


def test_trailing_punctuation_does_not_break_amount_parsing():
    t = S.extract_tokens("Cover is Rs 5,00,000, premium Rs 14,250. Then Rs 40,000.", "en")
    assert t.amounts == {500000, 14250, 40000} and t.format_errors == []


def test_unit_tokens_per_language():
    assert S.extract_tokens("30 days and 36 months", "en").units == {("day", 30), ("month", 36)}
    assert S.extract_tokens("30 दिन और 36 महीने", "hi").units == {("day", 30), ("month", 36)}
    assert S.extract_tokens("30 दिवस आणि 36 महिने", "mr").units == {("day", 30), ("month", 36)}


def test_retry_note_lists_problems_but_no_policy_text():
    r = run(sub("hi", "Rs 5,00,000", "Rs 5,50,000"))
    note = r.retry_note()
    assert "REJECTED" in note and "5,50,000" in note and "Rahul" not in note


def test_check_is_a_pure_function_of_its_inputs():
    a, b = run(), run()
    assert (a.errors, a.warnings) == (b.errors, b.warnings)
