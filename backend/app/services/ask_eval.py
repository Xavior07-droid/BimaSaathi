"""Q&A evaluation (A21). Pure functions: no Gemini, nothing read at import.

The spec's DoD: "the 15-question Q&A set returns a citation or the fallback 100% of the time". Because finalize() in
ask.py decides what the user sees, that structural guarantee holds by construction; this module still CHECKS it on every
response (STRUCTURE) and also measures what the guarantee does not give you:

  in-scope  (10)  did it actually answer, with the right fact and a citation that really supports it?
  out-of-scope (5) did it correctly refuse (arithmetic, claim prediction, not-in-policy, injection, medical advice)?

Verdict PASS = structure 100%  AND  out-of-scope 5/5 fell back  AND  in-scope >= 8/10 correct.   (10/10 = STRICT PASS)
A model that refuses everything has perfect structure and perfect out-of-scope: the in-scope score is what catches it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.models.policy import PolicyBrain
from app.services import ask as A

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
IN_SCOPE_PASS = 8
DEVANAGARI = re.compile(r"[\u0900-\u097f]")
_NO = {"en": re.compile(r"\bno\b|\bnot\b|n't\b", re.I), "hi": re.compile(r"नहीं|नही"), "mr": re.compile(r"नाही")}
_YES = {"en": re.compile(r"\byes\b|\bcovered\b|\bcovers?\b|\bpays?\b", re.I), "hi": re.compile(r"हाँ|हां|कवर|शामिल"),
        "mr": re.compile(r"होय|कव्हर|समाविष्ट")}


def load_testset(path: Path | None = None) -> list[dict]:
    return json.loads((path or REPO_DATA / "qa_testset.json").read_text(encoding="utf-8"))["questions"]


# ------------------------------------------------------------------ the structural guarantee
def structure_problems(res: dict, brain: PolicyBrain, lang: str) -> list[str]:
    """Empty list = the response obeys the spec: grounded => real citation(s); otherwise => the fixed fallback."""
    p: list[str] = []
    if res.get("disclaimer") != A.DISCLAIMER[lang]:
        p.append("disclaimer missing or not the fixed text")
    if res.get("lang") != lang:
        p.append("lang echoed wrongly")
    cites = res.get("citations") or []
    if res.get("grounded"):
        if res.get("fallback"):
            p.append("grounded and fallback both true")
        if not (res.get("answer") or "").strip():
            p.append("grounded with an empty answer")
        if not cites:
            p.append("grounded without any citation")
        known = {(c.page, A._norm_clause(c.clause)) for c in A.valid_sources(brain).values()}
        for c in cites:
            if (c["page"], A._norm_clause(c["clause"])) not in known:
                p.append(f"citation {c} does not exist in this policy")
    else:
        if res.get("answer") != A.FALLBACK[lang]:
            p.append("not grounded but the answer is not the fixed fallback text")
        if cites:
            p.append("fallback carries citations")
        if not res.get("fallback"):
            p.append("not grounded but fallback flag is false")
    return p


# ------------------------------------------------------------------ per question
@dataclass
class QResult:
    id: str
    scope: str                        # in | out
    lang: str
    question: str
    kind: str = ""                    # out-of-scope category
    status: str = ""                  # pass | fell_back | wrong | answered | error
    grounded: bool = False
    reason: str | None = None         # why it fell back (from ask.py)
    model: str | None = None
    answer: str = ""
    citations: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)       # why it is not a pass
    warnings: list[str] = field(default_factory=list)       # soft heuristics: review by eye
    structure: list[str] = field(default_factory=list)      # spec violations (must be empty)
    error: str | None = None
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "pass"


def _cites(res: dict) -> set[tuple[int, str]]:
    return {(c["page"], A._norm_clause(c["clause"])) for c in res.get("citations") or []}


def score(item: dict, result, brain: PolicyBrain, seconds: float = 0.0) -> QResult:
    """`result` is an ask.AskResult."""
    res = result.to_dict()
    lang = item["lang"]
    q = QResult(id=item["id"], scope=item["scope"], lang=lang, question=item["question"], kind=item.get("kind", ""),
                grounded=result.grounded, reason=result.reason, model=result.model, answer=res["answer"],
                citations=res["citations"], seconds=seconds, structure=structure_problems(res, brain, lang))
    if item["scope"] == "out":
        q.status = "pass" if not result.grounded else "answered"
        if q.status == "answered":
            q.problems.append("answered a question the policy cannot answer")
        return q

    if not result.grounded:
        q.status = "fell_back"
        q.problems.append(f"fell back ({result.reason})")
        return q
    text = res["answer"]
    want = {(p, A._norm_clause(c)) for p, c in item.get("cite_any", [])}
    if want and not (want & _cites(res)):
        q.problems.append(f"none of the expected citations {sorted(want)} was cited")
    for s in item.get("must_contain_all", []):
        if s not in text:
            q.problems.append(f"answer lacks {s!r}")
    if item.get("must_contain_any") and not any(s in text for s in item["must_contain_any"]):
        q.problems.append(f"answer has none of {item['must_contain_any']}")
    q.status = "wrong" if q.problems else "pass"

    pol = item.get("polarity")                                 # soft check: wording heuristics, never fails a question
    if pol == "no" and not _NO[lang].search(text):
        q.warnings.append("expected a 'no' answer; no negative word found")
    if pol == "yes" and (_NO[lang].search(text[:12]) or not _YES[lang].search(text)):
        q.warnings.append("expected a 'yes' answer; check the wording by eye")
    if (DEVANAGARI.search(text) is not None) != (lang != "en"):
        q.warnings.append(f"answer script does not look like lang={lang}")
    return q


def error_result(item: dict, code: str, seconds: float = 0.0) -> QResult:
    return QResult(id=item["id"], scope=item["scope"], lang=item["lang"], question=item["question"],
                   kind=item.get("kind", ""), status="error", error=code, seconds=seconds,
                   problems=[f"no response ({code})"])


# ------------------------------------------------------------------ aggregate
@dataclass
class Summary:
    total: int
    in_total: int
    in_pass: int
    in_fell_back: int
    in_wrong: int
    out_total: int
    out_pass: int
    out_answered: int
    errors: int
    structure_violations: int
    passed: bool
    strict: bool


def summarize(rs: list[QResult]) -> Summary:
    ins, outs = [r for r in rs if r.scope == "in"], [r for r in rs if r.scope == "out"]
    viol = sum(len(r.structure) for r in rs)
    s = Summary(total=len(rs), in_total=len(ins), in_pass=sum(r.ok for r in ins),
                in_fell_back=sum(r.status == "fell_back" for r in ins), in_wrong=sum(r.status == "wrong" for r in ins),
                out_total=len(outs), out_pass=sum(r.ok for r in outs), out_answered=sum(r.status == "answered" for r in outs),
                errors=sum(r.status == "error" for r in rs), structure_violations=viol, passed=False, strict=False)
    s.passed = viol == 0 and s.errors == 0 and s.out_pass == s.out_total and s.in_pass >= min(IN_SCOPE_PASS, s.in_total)
    s.strict = s.passed and s.in_pass == s.in_total
    return s


def format_report(rs: list[QResult], s: Summary) -> str:
    L = ["=" * 78]
    for r in rs:
        mark = {"pass": "ok  ", "fell_back": "MISS", "wrong": "WRONG", "answered": "LEAK", "error": "ERR "}[r.status]
        tag = r.kind or ("in-scope" if r.scope == "in" else "out")
        L.append(f"{r.id} {mark:5} [{r.lang}] {tag:16} {r.question[:46]}")
        if r.status == "pass" and r.scope == "in":
            L.append(f"        -> {r.answer[:100]}   cites {[(c['page'], c['clause']) for c in r.citations]}")
        for p in r.problems:
            L.append(f"        problem: {p}")
        if r.status == "answered":
            L.append(f"        model said: {r.answer[:100]}")
        for w in r.warnings:
            L.append(f"        review: {w}")
        for v in r.structure:
            L.append(f"        STRUCTURE VIOLATION: {v}")
    L += ["-" * 78,
          f"STRUCTURE (citation or fixed fallback, disclaimer): {'100%' if not s.structure_violations else str(s.structure_violations) + ' violation(s)'}",
          f"IN-SCOPE  correct {s.in_pass}/{s.in_total}   (fell back: {s.in_fell_back}, wrong: {s.in_wrong})",
          f"OUT-OF-SCOPE refused {s.out_pass}/{s.out_total}   (answered when it should not: {s.out_answered})",
          f"errors (no response): {s.errors}"]
    verdict = ("STRICT PASS" if s.strict else "PASS" if s.passed else "FAIL")
    L += [f"VERDICT (structure 100%, refusals {s.out_total}/{s.out_total}, in-scope >= {min(IN_SCOPE_PASS, s.in_total)}/{s.in_total}): {verdict}", "=" * 78]
    return "\n".join(L)
