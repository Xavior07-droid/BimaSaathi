"""Extraction accuracy scoring (A14). Pure functions: no Gemini, no files read at import.

Scores a PolicyExtraction (or Policy Brain dict) against data/ground_truth.csv (10 fields x 4 policies = 40 rows)
and, separately and NOT counted in the 85%, against the extra facts in manifest.json (insurer, policy no, holder,
intimation hours, sub-limits with their page).

Row statuses
  ok            value equals the expected one (or both are null)
  wrong         a value was returned but it is not the expected one
  missing       expected a value, got null
  hallucinated  expected null (the document does not say), got a value  <- the dangerous one: reported separately
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PASS_THRESHOLD = 0.85
REPO_DATA = Path(__file__).resolve().parents[3] / "data"


# ------------------------------------------------------------------ loading
def load_ground_truth(path: Path | None = None) -> list[dict]:
    with (path or REPO_DATA / "ground_truth.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_manifest(path: Path | None = None) -> list[dict]:
    return json.loads((path or REPO_DATA / "sample_policies" / "manifest.json").read_text(encoding="utf-8"))["policies"]


def perfect_answer(p: dict) -> dict:
    """What a flawless extraction of manifest policy `p` looks like (used by --dry-run and tests)."""
    e = p["expected"]
    src = lambda page: {"page": page, "clause": "x"}
    return {
        "insurer": e["insurer"], "policy_no": e["policy_no"], "policy_type": "health", "holder_name": e["holder_name"],
        "start_date": e["start_date"], "end_date": e["end_date"], "renewal_date": e["renewal_date"],
        "sum_insured": e["sum_insured"], "premium": e["premium"], "waiting_periods": e["waiting_periods"],
        "room_rent_cap": e["room_rent_cap"], "copay_percent": e["copay_percent"],
        "sub_limits": [{"item": i, "limit": l, "source": src(pg)} for i, l, pg in e["sub_limits"]],
        "covered": [{"text": "Hospitalisation", "source": src(2)}],
        "exclusions": [{"text": "Cosmetic surgery", "source": src(e["pages"]["exclusions"])}],
        "claim_requirements": {"cashless": [], "reimbursement": [], "intimation_deadline_hours": e["intimation_deadline_hours"]},
    }


# ------------------------------------------------------------------ value comparison
@dataclass
class RowResult:
    policy_file: str
    field: str
    expected: str          # "" = expected null
    got: str               # "" = got null
    status: str            # ok | wrong | missing | hallucinated
    match_type: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _dig(data: dict, path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _render(match_type: str, v: Any) -> str:
    if v is None:
        return ""
    if match_type == "value|unit":
        n = v.get("value") if isinstance(v, dict) else None
        return "" if n is None else f"{int(n) if float(n).is_integer() else n}|{v.get('unit')}"
    return str(v)


def _equal(match_type: str, expected_cell: str, got: Any) -> bool:
    if match_type == "int":
        g = _num(got)
        return g is not None and g.is_integer() and int(g) == int(expected_cell)
    if match_type == "number":
        g = _num(got)
        return g is not None and abs(g - float(expected_cell)) < 1e-9
    if match_type == "date":
        return str(got) == expected_cell
    if match_type == "value|unit":
        ev, eu = expected_cell.split("|")
        gv = _num(got.get("value")) if isinstance(got, dict) else None
        return gv is not None and abs(gv - float(ev)) < 1e-9 and got.get("unit") == eu
    raise ValueError(f"unknown match_type {match_type!r}")


def score_row(row: dict, extraction: dict | None) -> RowResult:
    """`extraction` None = the run failed entirely (every non-null row counts as missing)."""
    mt = row["match_type"]
    if extraction is None:                       # the run failed: even "expected null" rows must not earn free points
        return RowResult(row["policy_file"], row["field"], row["expected"], "", "missing", mt)
    got = _dig(extraction, row["brain_path"])
    if row["is_null"] == "true":
        status = "ok" if got is None else "hallucinated"
    elif got is None:
        status = "missing"
    else:
        status = "ok" if _equal(mt, row["expected"], got) else "wrong"
    return RowResult(row["policy_file"], row["field"], row["expected"], _render(mt, got), status, mt)


# ------------------------------------------------------------------ extras (informational)
def _norm(s: Any) -> str:
    return re.sub(r"[\s.,]+", "", str(s or "")).casefold()


def score_extras(p: dict, extraction: dict | None) -> list[RowResult]:
    e, ex = p["expected"], extraction or {}
    f = p["file"]
    out: list[RowResult] = []

    def add(name: str, expected: Any, got: Any, same: bool):
        status = "ok" if same else ("missing" if got in (None, "") else "wrong")
        out.append(RowResult(f, name, str(expected), "" if got is None else str(got), status, "extra"))

    for k in ("insurer", "policy_no", "holder_name"):
        add(k, e[k], ex.get(k), _norm(ex.get(k)) == _norm(e[k]))
    got_h = (ex.get("claim_requirements") or {}).get("intimation_deadline_hours")
    add("intimation_deadline_hours", e["intimation_deadline_hours"], got_h, got_h == e["intimation_deadline_hours"])
    items = ex.get("sub_limits") or []
    for name, limit, page in e["sub_limits"]:
        hit = next((i for i in items if name.casefold() in str(i.get("item", "")).casefold()), None)
        add(f"sub_limit:{name}", limit, None if hit is None else hit.get("limit"), hit is not None and hit.get("limit") == limit)
        got_page = None if hit is None else (hit.get("source") or {}).get("page")
        add(f"sub_limit_page:{name}", page, got_page, got_page == page)
    return out


# ------------------------------------------------------------------ aggregate
@dataclass
class PolicyRun:
    policy_file: str
    rows: list[RowResult]
    extras: list[RowResult] = field(default_factory=list)
    error: str | None = None                 # e.g. "extraction_failed", "ai_busy"
    model: str = ""
    calls: int = 0
    retried: bool = False
    used_fallback: bool = False
    input_mode: str = ""
    seconds: float = 0.0
    tokens: int = 0
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    extraction: dict | None = None           # raw validated output, for debugging misses


@dataclass
class Summary:
    total: int
    ok: int
    hallucinated: int
    accuracy: float
    passed: bool                              # >= 85%
    clean: bool                               # passed AND zero hallucinations
    per_field: dict[str, tuple[int, int]]
    per_policy: dict[str, tuple[int, int]]
    extras_ok: int
    extras_total: int


def summarize(runs: list[PolicyRun]) -> Summary:
    rows = [r for run in runs for r in run.rows]
    ok = sum(r.ok for r in rows)
    hall = sum(r.status == "hallucinated" for r in rows)
    per_field: dict[str, list[int]] = {}
    for r in rows:
        a = per_field.setdefault(r.field, [0, 0]); a[0] += r.ok; a[1] += 1
    per_policy = {run.policy_file: (sum(r.ok for r in run.rows), len(run.rows)) for run in runs}
    extras = [r for run in runs for r in run.extras]
    acc = ok / len(rows) if rows else 0.0
    return Summary(total=len(rows), ok=ok, hallucinated=hall, accuracy=acc, passed=acc >= PASS_THRESHOLD,
                   clean=acc >= PASS_THRESHOLD and hall == 0,
                   per_field={k: (v[0], v[1]) for k, v in per_field.items()}, per_policy=per_policy,
                   extras_ok=sum(r.ok for r in extras), extras_total=len(extras))


def run_policy(p: dict, gt_rows: list[dict], extraction: dict | None, **meta) -> PolicyRun:
    rows = [score_row(r, extraction) for r in gt_rows if r["policy_file"] == p["file"]]
    return PolicyRun(policy_file=p["file"], rows=rows, extras=score_extras(p, extraction), extraction=extraction, **meta)


# ------------------------------------------------------------------ text report
def format_report(runs: list[PolicyRun], s: Summary) -> str:
    L: list[str] = []
    L.append("=" * 78)
    for run in runs:
        n_ok = sum(r.ok for r in run.rows)
        head = f"{run.policy_file[:44]:44} {n_ok:2}/{len(run.rows):2}"
        if run.error:
            L.append(f"{head}  FAILED: {run.error}")
        else:
            conf = "n/a" if run.confidence is None else f"{run.confidence:.2f}"
            L.append(f"{head}  mode={run.input_mode} calls={run.calls} retry={'Y' if run.retried else 'n'} "
                     f"fallback={'Y' if run.used_fallback else 'n'} tok={run.tokens} {run.seconds:.1f}s grounding={conf}")
        for r in run.rows:
            if not r.ok:
                L.append(f"    {r.status.upper():12} {r.field:28} expected={r.expected or 'null'!s:22} got={r.got or 'null'}")
        for w in run.warnings:
            L.append(f"    warning: {w}")
        bad_extra = [r for r in run.extras if not r.ok]
        if bad_extra:
            L.append("    (not scored) " + "; ".join(f"{r.field}: expected {r.expected} got {r.got or 'null'}" for r in bad_extra))
    L.append("-" * 78)
    L.append("Per field:   " + "  ".join(f"{k}={a}/{b}" for k, (a, b) in s.per_field.items()))
    L.append(f"Extras (not scored): {s.extras_ok}/{s.extras_total}")
    L.append(f"TOTAL: {s.ok}/{s.total} = {s.accuracy:.0%}   hallucinated (expected null, got a value): {s.hallucinated}")
    verdict = "PASS" if s.clean else ("PASS BUT HALLUCINATING (fix before relying on it)" if s.passed else "FAIL")
    L.append(f"VERDICT (>= {PASS_THRESHOLD:.0%}, zero hallucinations): {verdict}")
    L.append("=" * 78)
    return "\n".join(L)
