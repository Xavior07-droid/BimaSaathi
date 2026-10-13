"""A14: the scoring harness itself must be right, or the 85% number means nothing."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import extraction_eval as E
from app.services import policy_brain as PB
from app.services.gemini import GeminiBusy
from tests.test_policy_brain import CLEAN, GOOD, FakeGemini, bad

MANIFEST = E.load_manifest()
GT = E.load_ground_truth()
BACKEND = Path(__file__).resolve().parents[1]


def runs_for(mutate=None, only=None):
    out = []
    for p in MANIFEST:
        ans = E.perfect_answer(p)
        if mutate:
            mutate(p["file"][:2], ans)
        out.append(E.run_policy(p, GT, ans))
    return out


def rows(runs):
    return {(r.policy_file[:2], r.field): r for run in runs for r in run.rows}


def test_perfect_answers_score_100_percent_with_no_extras_missed():
    runs = runs_for()
    s = E.summarize(runs)
    assert (s.ok, s.total, s.hallucinated) == (40, 40, 0) and s.passed and s.clean
    assert s.extras_ok == s.extras_total == 28 and all(v == (4, 4) for v in s.per_field.values())


def test_planted_trap_guessing_is_hallucination_not_just_wrong():
    def m(n, a):
        if n == "02": a["renewal_date"] = "2026-04-01"                          # end_date + 1 day: the classic guess
        if n == "04": a["room_rent_cap"] = {"value": 3000, "unit": "per_day"}   # document only says "single private room"
    r = rows(runs_for(m))
    assert r[("02", "renewal_date")].status == "hallucinated" and r[("04", "room_rent_cap")].status == "hallucinated"
    s = E.summarize(runs_for(m))
    assert s.hallucinated == 2 and s.ok == 38 and s.passed and not s.clean      # 95% but NOT clean


@pytest.mark.parametrize("field,value,status", [
    ("sum_insured", 1000000, "wrong"),
    ("sum_insured", 500000.0, "ok"),             # float with integral value is fine
    ("sum_insured", 500000.5, "wrong"),
    ("sum_insured", True, "wrong"),              # bool is not a number
    ("sum_insured", "500000", "wrong"),          # string is not a number
    ("sum_insured", None, "missing"),
    ("start_date", "2025-01-04", "wrong"),       # day/month swap
    ("copay_percent", 10.0, "ok"),
    ("copay_percent", 0, "wrong"),
])
def test_scoring_rules_on_policy_01(field, value, status):
    def m(n, a):
        if n == "01": a[field] = value
    assert rows(runs_for(m))[("01", field)].status == status


def test_copay_nil_means_zero_and_null_is_missing_not_ok():
    zero = rows(runs_for(lambda n, a: None))[("02", "copay_percent")]
    assert zero.status == "ok" and zero.expected == "0"
    def m(n, a):
        if n == "02": a["copay_percent"] = None
    assert rows(runs_for(m))[("02", "copay_percent")].status == "missing"


@pytest.mark.parametrize("cap,status", [
    ({"value": 5000, "unit": "per_day"}, "ok"),
    ({"value": 5000.0, "unit": "per_day"}, "ok"),
    ({"value": 5000, "unit": "percent_of_sum_insured"}, "wrong"),     # right number, wrong unit
    ({"value": 500, "unit": "per_day"}, "wrong"),
    (None, "missing"),
])
def test_room_rent_cap_needs_value_and_unit(cap, status):
    def m(n, a):
        if n == "01": a["room_rent_cap"] = cap
    assert rows(runs_for(m))[("01", "room_rent_cap")].status == status


def test_percent_cap_policy_02_expected_1_percent():
    r = rows(runs_for())[("02", "room_rent_cap")]
    assert r.expected == "1|percent_of_sum_insured" and r.got == "1|percent_of_sum_insured" and r.ok


def test_failed_run_scores_every_row_missing_including_expected_nulls():
    p = MANIFEST[3]
    run = E.run_policy(p, GT, None, error="extraction_failed")
    assert len(run.rows) == 10 and all(r.status == "missing" for r in run.rows) and run.extras and all(not x.ok for x in run.extras)


def test_threshold_is_85_percent_of_40_rows():
    # 6 misses -> 34/40 = 85% passes ; 7 misses -> 33/40 = 82.5% fails
    def misses(n_miss):
        def m(name, a):
            if name == "01":
                for f in ["sum_insured", "premium", "start_date", "end_date", "copay_percent", "room_rent_cap", "renewal_date"][:n_miss]:
                    a[f] = None
        return m
    six, seven = E.summarize(runs_for(misses(6))), E.summarize(runs_for(misses(7)))
    assert (six.ok, six.passed) == (34, True) and (seven.ok, seven.passed) == (33, False)


def test_extras_catch_wrong_citation_page_for_sub_limits():
    def m(n, a):
        if n == "01": a["sub_limits"][0]["source"]["page"] = 5            # Cataract is on page 3
    extras = {r.field: r for run in runs_for(m) for r in run.extras if r.policy_file.startswith("01")}
    assert extras["sub_limit:Cataract"].ok and extras["sub_limit_page:Cataract"].status == "wrong"
    assert E.summarize(runs_for(m)).ok == 40                              # extras never change the headline score


def test_extras_match_names_loosely_but_limits_exactly():
    def m(n, a):
        if n == "01":
            a["sub_limits"] = [{"item": "Cataract surgery (per eye)", "limit": 40000, "source": {"page": 3, "clause": "x"}},
                               {"item": "Knee replacement", "limit": 99, "source": {"page": 3, "clause": "x"}}]
            a["insurer"] = "  SANJIVANI general insurance co. ltd  "
    ex = {r.field: r.status for run in runs_for(m) for r in run.extras if r.policy_file.startswith("01")}
    assert ex["sub_limit:Cataract"] == "ok" and ex["sub_limit:Knee replacement"] == "wrong"
    assert ex["sub_limit:Ambulance"] == "missing" and ex["insurer"] == "ok"


def test_report_text_names_the_misses_and_the_verdict():
    def m(n, a):
        if n == "02": a["renewal_date"] = "2026-04-01"
    runs = runs_for(m)
    text = E.format_report(runs, E.summarize(runs))
    assert "HALLUCINATED" in text and "renewal_date" in text and "PASS BUT HALLUCINATING" in text
    assert "TOTAL: 39/40" in text
    ok_text = E.format_report(runs_for(), E.summarize(runs_for()))
    assert "VERDICT (>= 85%, zero hallucinations): PASS" in ok_text and "PASS BUT" not in ok_text


# ------------------------------------------------------------------ the `plan` switch used by the script
async def test_plan_fast_only_makes_exactly_one_attempt():
    g = FakeGemini([bad(copay_percent=150), GOOD])
    with pytest.raises(PB.ExtractionFailed):
        await PB.extract_policy(CLEAN, gemini=g, plan=("fast",))
    assert len(g.calls) == 1


async def test_plan_without_fallback_reraises_busy_instead_of_crashing():
    g = FakeGemini([GeminiBusy("busy")])
    with pytest.raises(GeminiBusy):
        await PB.extract_policy(CLEAN, gemini=g, plan=("fast",))


async def test_plan_fallback_only_uses_the_fallback_model():
    g = FakeGemini([GOOD])
    out = await PB.extract_policy(CLEAN, gemini=g, plan=("fallback",))
    assert out.used_fallback and g.calls[0]["model"] == "fallback"


# ------------------------------------------------------------------ the CLI
def _run(*args, env_extra=None, cwd=BACKEND):
    import os
    env = {**os.environ, "GEMINI_API_KEY": "", **(env_extra or {})}
    return subprocess.run([sys.executable, str(BACKEND / "scripts" / "eval_extraction.py"), *args],
                          capture_output=True, text=True, cwd=cwd, env=env, timeout=120)


def test_cli_dry_run_passes_and_writes_a_report(tmp_path):
    r = _run("--dry-run", "--out", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "TOTAL: 40/40 = 100%" in r.stdout and "Gemini calls this run: 4" in r.stdout
    rep = json.loads(next(tmp_path.glob("extraction-*-dryrun.json")).read_text(encoding="utf-8"))
    assert rep["dry_run"] and rep["runs"][0]["summary"]["ok"] == 40 and len(rep["runs"][0]["policies"]) == 4


def test_cli_only_filter_and_unknown_filter(tmp_path):
    ok = _run("--dry-run", "--only", "04", "--out", str(tmp_path))
    assert ok.returncode == 0 and "TOTAL: 10/10" in ok.stdout and "01_sanjivani" not in ok.stdout
    assert _run("--dry-run", "--only", "99", "--out", str(tmp_path)).returncode == 2


def test_cli_refuses_to_run_in_mock_mode_without_a_key(tmp_path):
    r = _run("--out", str(tmp_path), cwd=tmp_path)             # cwd without a .env, key empty
    assert r.returncode == 2 and "GEMINI_API_KEY is empty" in r.stdout


def test_false_is_not_zero_percent_copay():
    """bool is an int subclass in Python: `False == 0` must not pass as 'Nil co-payment' on policy 02."""
    def m(n, a):
        if n == "02": a["copay_percent"] = False
    assert rows(runs_for(m))[("02", "copay_percent")].status == "wrong"
