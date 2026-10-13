"""A21: the 15-question set and its scorer. The scorer must catch what A19's code cannot (a valid-looking but wrong answer)."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import ask as A
from app.services import ask_eval as E
from app.services.gemini import GeminiBusy
from app.services.mock_policy import load_sample_policy
from tests.test_policy_brain import FakeGemini

BRAIN = load_sample_policy()
ITEMS = E.load_testset()
BY_ID = {i["id"]: i for i in ITEMS}
BACKEND = Path(__file__).resolve().parents[1]
NOT = {"answer": "", "citations": [], "grounded": False}


def ideal(item):
    i = item.get("ideal")
    return {"answer": i["answer"], "citations": i["citations"], "grounded": True} if i else dict(NOT)


async def run(overrides=None, default=None):
    """Run all 15 through the REAL answer_question with a scripted model; overrides = {id: model output | Exception}."""
    overrides, rs = overrides or {}, []
    for it in ITEMS:
        out = overrides.get(it["id"], default if default is not None else ideal(it))
        g = FakeGemini([out])
        try:
            res = await A.answer_question(BRAIN, it["question"], it["lang"], g)
        except Exception as e:  # noqa: BLE001
            rs.append(E.error_result(it, getattr(e, "error_code", "error")))
            continue
        rs.append(E.score(it, res, BRAIN))
    return rs, E.summarize(rs)


def by(rs):
    return {r.id: r for r in rs}


# ================================================================ the question set itself
def test_shape_10_in_5_out_unique_ids_and_three_languages_plus_hinglish():
    assert len(ITEMS) == 15 and len({i["id"] for i in ITEMS}) == 15
    assert [i["scope"] for i in ITEMS].count("in") == 10 and [i["scope"] for i in ITEMS].count("out") == 5
    assert {i["lang"] for i in ITEMS} == {"en", "hi", "mr"}
    assert any(i["id"] == "Q07" and i["question"].isascii() and i["lang"] == "hi" for i in ITEMS)      # Hinglish, answered in Hindi
    assert {i["kind"] for i in ITEMS if i["scope"] == "out"} == {"arithmetic", "claim_prediction", "not_listed", "injection", "medical_advice"}


def test_every_question_is_accepted_by_the_ask_input_checks_unchanged():
    for i in ITEMS:
        assert A.clean_question(i["question"]) == i["question"] and A.check_lang(i["lang"]) == i["lang"]


def test_expected_citations_really_exist_in_the_sample_policy():
    known = {(p, A._norm_clause(c)) for p, c in A.valid_sources(BRAIN)}
    for i in ITEMS:
        for p, c in i.get("cite_any", []):
            assert (p, A._norm_clause(c)) in known, (i["id"], p, c)
        for c in i.get("ideal", {}).get("citations", []):
            assert (c["page"], A._norm_clause(c["clause"])) in known, (i["id"], c)


def test_expected_numbers_come_from_the_policy_data():
    data = json.dumps(BRAIN.model_dump(mode="json"), ensure_ascii=False)
    facts = {"40,000": "40000", "10%": '"copay_percent": 10', "5,000": "5000", "36": "36", "48": "48",
             "1,50,000": "150000", "2,000": "2000", "30": "30", "60": "60"}
    for i in ITEMS:
        for s in i.get("must_contain_all", []):
            assert facts[s].replace(" ", "") in data.replace(" ", "") or facts[s] in data, (i["id"], s)


def test_every_in_scope_item_has_an_ideal_that_passes_the_real_finalize_rules():
    for i in ITEMS:
        if i["scope"] != "in":
            continue
        from app.models.policy import AskOutput
        res = A.finalize(BRAIN, AskOutput.model_validate({**i["ideal"], "grounded": True}), i["lang"], "dry")
        assert res.grounded, (i["id"], res.reason)
        assert E.score(i, res, BRAIN).ok, i["id"]


def test_out_of_scope_subjects_are_really_absent_from_the_policy():
    text = json.dumps(BRAIN.model_dump(mode="json"), ensure_ascii=False).casefold()
    assert "ayurved" not in text and "ayush" not in text                  # Q13: silent in the policy (not covered, not excluded)
    assert not any(i["scope"] == "out" and "ideal" in i for i in ITEMS)


# ================================================================ scoring through the real Ask pipeline
async def test_ideal_model_is_a_strict_pass():
    rs, s = await run()
    assert (s.in_pass, s.out_pass, s.structure_violations, s.errors) == (10, 5, 0, 0) and s.passed and s.strict


async def test_a_model_that_refuses_everything_has_perfect_structure_but_fails():
    """The reason the in-scope score exists: 'citation or fallback 100%' is trivially true for a useless model."""
    rs, s = await run(default=NOT)
    assert s.structure_violations == 0 and s.out_pass == 5 and s.in_pass == 0 and s.in_fell_back == 10
    assert not s.passed and "FAIL" in E.format_report(rs, s)


async def test_invented_citation_is_dropped_by_code_so_it_is_a_miss_not_a_leak():
    fake = {"answer": "Yes, covered.", "citations": [{"page": 99, "clause": "9.9"}], "grounded": True}
    rs, s = await run(default=fake)
    assert s.structure_violations == 0 and s.out_pass == 5 and s.in_fell_back == 10
    assert {r.reason for r in rs} == {"no_valid_citation"}


async def test_valid_citation_but_wrong_claim_on_out_of_scope_is_caught_as_a_leak():
    """Code cannot catch this: the citation is real, the claim is not supported. Only the test set can."""
    leak = {"answer": "Yes, Ayurvedic treatment is covered as part of hospitalisation.", "citations": [{"page": 2, "clause": "1.1"}], "grounded": True}
    rs, s = await run({"Q13": leak})
    r = by(rs)["Q13"]
    assert r.status == "answered" and s.out_answered == 1 and not s.passed
    assert "LEAK" in E.format_report(rs, s) and "model said" in E.format_report(rs, s)


async def test_prediction_with_a_real_citation_is_also_a_leak():
    leak = {"answer": "Yes, your knee surgery claim will be approved up to Rs 1,50,000.", "citations": [{"page": 3, "clause": "3.3"}], "grounded": True}
    rs, s = await run({"Q12": leak})
    assert by(rs)["Q12"].status == "answered" and not s.passed


async def test_wrong_but_policy_valid_number_is_wrong_not_pass():
    bad = {"answer": "Cataract is covered up to Rs 1,50,000 per eye.", "citations": [{"page": 3, "clause": "3.3"}], "grounded": True}
    rs, _ = await run({"Q02": bad})
    r = by(rs)["Q02"]
    assert r.status == "wrong" and "lacks '40,000'" in r.problems[0]


async def test_number_not_in_the_policy_is_stopped_by_code_and_scored_as_a_miss():
    bad = {"answer": "You pay 25% of every claim.", "citations": [{"page": 3, "clause": "3.2"}], "grounded": True}
    rs, _ = await run({"Q03": bad})
    r = by(rs)["Q03"]
    assert r.status == "fell_back" and r.reason == "invented_number"


async def test_right_fact_with_a_citation_that_does_not_support_it_is_wrong():
    bad = {"answer": "You pay 10% of every claim yourself.", "citations": [{"page": 4, "clause": "4.2"}], "grounded": True}
    rs, _ = await run({"Q03": bad})
    r = by(rs)["Q03"]
    assert r.status == "wrong" and "expected citations" in r.problems[0] and not r.structure       # structurally fine, still wrong


async def test_polarity_and_script_are_soft_warnings_not_failures():
    yes_to_dental = {"answer": "Yes, dental treatment is covered.", "citations": [{"page": 4, "clause": "4.2"}], "grounded": True}
    en_for_hi = {"answer": "Yes, cataract is covered up to Rs 40,000 per eye.", "citations": [{"page": 3, "clause": "3.3"}], "grounded": True}
    rs, s = await run({"Q01": yes_to_dental, "Q02": en_for_hi})
    r = by(rs)
    assert r["Q01"].ok and any("negative word" in w for w in r["Q01"].warnings)
    assert r["Q02"].ok and any("lang=hi" in w for w in r["Q02"].warnings)
    assert s.passed


async def test_gemini_failure_is_an_error_not_a_pass_and_blocks_the_verdict():
    rs, s = await run({"Q13": GeminiBusy("busy")})
    assert by(rs)["Q13"].status == "error" and s.errors == 1 and s.out_pass == 4 and not s.passed


async def test_two_of_ten_in_scope_misses_still_pass_three_do_not():
    two, s2 = await run({"Q01": NOT, "Q02": NOT})
    three, s3 = await run({"Q01": NOT, "Q02": NOT, "Q03": NOT})
    assert (s2.in_pass, s2.passed, s2.strict) == (8, True, False) and (s3.in_pass, s3.passed) == (7, False)
    assert "VERDICT" in E.format_report(two, s2) and "PASS" in E.format_report(two, s2).split("VERDICT")[1]


# ================================================================ the structural check itself
def d(**over):
    base = {"answer": "x", "citations": [{"page": 3, "clause": "3.2"}], "grounded": True, "fallback": False, "lang": "en",
            "disclaimer": A.DISCLAIMER["en"]}
    base.update(over)
    return base


@pytest.mark.parametrize("res,needle", [
    (d(citations=[]), "without any citation"),
    (d(citations=[{"page": 77, "clause": "1"}]), "does not exist"),
    (d(answer=" "), "empty answer"),
    (d(fallback=True), "both true"),
    (d(grounded=False, fallback=True, answer="Sorry, I do not know."), "fixed fallback"),
    (d(grounded=False, fallback=True, answer=A.FALLBACK["en"]), "carries citations"),
    (d(grounded=False, fallback=False, answer=A.FALLBACK["en"], citations=[]), "fallback flag"),
    (d(disclaimer="made up"), "disclaimer"),
    (d(lang="hi"), "lang echoed"),
])
def test_structure_check_detects_each_spec_violation(res, needle):
    assert any(needle in p for p in E.structure_problems(res, BRAIN, "en")), E.structure_problems(res, BRAIN, "en")


def test_structure_check_accepts_a_good_grounded_and_a_good_fallback_in_every_language():
    assert E.structure_problems(d(), BRAIN, "en") == []
    for lang in ("en", "hi", "mr"):
        fb = d(grounded=False, fallback=True, answer=A.FALLBACK[lang], citations=[], lang=lang, disclaimer=A.DISCLAIMER[lang])
        assert E.structure_problems(fb, BRAIN, lang) == []


# ================================================================ the CLI
def _cli(*args, cwd=BACKEND):
    import os
    return subprocess.run([sys.executable, str(BACKEND / "scripts" / "eval_ask.py"), *args], capture_output=True, text=True,
                          cwd=cwd, env={**os.environ, "GEMINI_API_KEY": ""}, timeout=120)


def test_cli_dry_run_passes_and_saves_a_report(tmp_path):
    r = _cli("--dry-run", "--out", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "STRICT PASS" in r.stdout and "IN-SCOPE  correct 10/10" in r.stdout
    rep = json.loads(next(tmp_path.glob("ask-*-dryrun.json")).read_text(encoding="utf-8"))
    assert rep["runs"][0]["summary"]["in_pass"] == 10 and len(rep["runs"][0]["questions"]) == 15


def test_cli_only_filter_and_unknown_id(tmp_path):
    ok = _cli("--dry-run", "--only", "Q13", "--out", str(tmp_path))
    assert ok.returncode == 0 and "OUT-OF-SCOPE refused 1/1" in ok.stdout
    assert _cli("--dry-run", "--only", "Q99", "--out", str(tmp_path)).returncode == 2


def test_cli_refuses_to_run_without_a_key(tmp_path):
    r = _cli("--out", str(tmp_path), cwd=tmp_path)
    assert r.returncode == 2 and "GEMINI_API_KEY is empty" in r.stdout


async def test_one_in_scope_error_blocks_the_verdict_even_though_9_of_10_is_above_the_bar():
    """A rate-limited run must be re-run, not graded: an error is 'no data', not 'a tolerated miss'."""
    rs, s = await run({"Q01": GeminiBusy("busy")})
    assert s.in_pass == 9 and s.errors == 1 and not s.passed and not s.strict
