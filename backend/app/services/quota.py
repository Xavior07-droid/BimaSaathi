"""Gemini free-tier quota model (A27). Standard library only: no network, no SDK.

Counts LOGICAL Gemini calls per user action, from how the code is built (see tests/test_quota.py drift guards), and turns
a daily request limit (RPD) into "how many policies / user journeys per day".

Why RPD is an INPUT, not a constant: Google changes free-tier limits per model and per month, and public sources disagree
(from ~20 to ~1,500 requests/day for Flash models). Read the real number for YOUR project and models in AI Studio
(aistudio.google.com -> Usage / Rate limits) and pass it in. Limits are per project (not per key) and RPD resets at
midnight Pacific time (about 12:30 IST).

best    = every call succeeds first time
typical = best, unless a measured average is supplied (scripts/measure_quota.py --measured)
worst   = every call needs the retry-with-error and the Flash-Lite fallback (what the code allows at most)

A logical call can become up to GEMINI_MAX_RETRIES (3) HTTP requests when Google answers 429/5xx; the limiter counts each
HTTP request against RPM, and Google counts each against RPD, so `http_worst` multiplies by 3.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- constants mirrored from the code; tests/test_quota.py::test_constants_match_the_code fails if they drift ---
EXTRACT_MAX_CALLS = 3        # policy_brain.DEFAULT_PLAN = (fast, fast, fallback)
SUMMARY_MAX_CALLS = 3        # planned (A26b): same pattern as extraction
JSON_CALL_MAX = 4            # ask / recommend / doc_classify / exclusion_match / one fraud batch: 2 attempts x (fast + fallback)
FRAUD_BATCH = 12             # fraud_reason.MAX_PER_CALL
MAX_CLAIM_IMAGES = 8         # build prompt 5.3
HTTP_RETRIES = 3             # Settings.gemini_max_retries
DEFAULT_RPM = 10             # Settings.gemini_rpm

# Daily limits to show projections for. These are SCENARIOS, not facts: replace with the number AI Studio shows you.
RPD_SCENARIOS = (20, 100, 250, 500, 1000, 1500)


@dataclass(frozen=True)
class Flow:
    key: str
    title: str
    best: float
    worst: float
    planned: bool = False
    note: str = ""

    @property
    def typical(self) -> float:
        return self.best

    @property
    def http_worst(self) -> float:
        return self.worst * HTTP_RETRIES


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def flows(claim_images: int = 4, fraud_flagged: int = 15) -> dict[str, Flow]:
    n = max(0, min(int(claim_images), MAX_CLAIM_IMAGES))
    batches = ceil_div(max(0, fraud_flagged), FRAUD_BATCH)
    return {
        "ingest_cache_hit": Flow("ingest_cache_hit", "Upload a file we have seen (same sha256) or the sample policy", 0, 0,
                                 note="Firestore lookup only; this is why the hash cache matters"),
        "ingest_extract": Flow("ingest_extract", "Upload a new policy: extraction (extract_v1)", 1, EXTRACT_MAX_CALLS,
                               note="retry-with-error and the Flash-Lite plan add calls"),
        "ingest_summary": Flow("ingest_summary", "Upload a new policy: summary + red flags (summary_v1)", 1, SUMMARY_MAX_CALLS,
                               planned=True, note="NOT WIRED YET; counted because the build prompt requires this second call"),
        "ask": Flow("ask", "One question in Ask", 1, JSON_CALL_MAX),
        "claim": Flow("claim", f"One claim check with {n} document photos", n + 1, JSON_CALL_MAX * (n + 1),
                      note="1 vision call per photo + 1 semantic exclusion match; keyword match is free"),
        "compare": Flow("compare", "One comparison (recommendation text)", 1, JSON_CALL_MAX,
                        note="the calculator is pure code and costs nothing"),
        "fraud_dashboard": Flow("fraud_dashboard", f"Review dashboard load ({fraud_flagged} flagged claims)", batches, JSON_CALL_MAX * batches,
                                note="reasons are cached in memory only: a Render restart empties the cache and re-spends these calls"),
        "reminders_cron": Flow("reminders_cron", "Daily reminder cron, FCM push, .ics, policy list, suggestions", 0, 0, note="no Gemini"),
    }


def ingest_calls(case: str = "typical", with_summary: bool = True, extract_calls: float | None = None) -> float:
    f = flows()
    ex = f["ingest_extract"]
    e = {"best": ex.best, "typical": extract_calls if extract_calls is not None else ex.typical, "worst": ex.worst}[case]
    s = f["ingest_summary"]
    sm = {"best": s.best, "typical": s.typical, "worst": s.worst}[case] if with_summary else 0
    return e + sm


def journey_calls(case: str = "typical", *, ingests: float = 1, asks: float = 5, claims: float = 1, claim_images: int = 4,
                  compares: float = 1, with_summary: bool = True, extract_calls: float | None = None,
                  cache_hit_rate: float = 0.0) -> float:
    """Gemini calls for one user doing: upload -> N questions -> claim check -> comparison."""
    f = flows(claim_images)
    pick = lambda fl: {"best": fl.best, "typical": fl.typical, "worst": fl.worst}[case]  # noqa: E731
    new_ingests = ingests * (1.0 - cache_hit_rate)
    return (new_ingests * ingest_calls(case, with_summary, extract_calls)
            + asks * pick(f["ask"]) + claims * pick(f["claim"]) + compares * pick(f["compare"]))


def per_day(rpd: int, calls_each: float) -> int:
    """How many whole actions fit in `rpd` requests."""
    return 0 if calls_each <= 0 else int(rpd // calls_each)


def rpm_seconds(calls: float, rpm: int = DEFAULT_RPM) -> float:
    """Seconds of the per-minute budget one action uses if it runs alone (calls / rpm * 60).
    More than 60 means the limiter MAKES it wait; other users' calls add to this."""
    return calls / rpm * 60.0


def capacity(rpd: int, *, extract_calls: float | None = None, with_summary: bool = True, claim_images: int = 4) -> dict[str, int]:
    """Whole actions per day for one model's daily request limit."""
    j = lambda case: journey_calls(case, claim_images=claim_images, with_summary=with_summary, extract_calls=extract_calls)  # noqa: E731
    return {
        "rpd": rpd,
        "ingests_best": per_day(rpd, ingest_calls("best", with_summary)),
        "ingests_typical": per_day(rpd, ingest_calls("typical", with_summary, extract_calls)),
        "ingests_worst": per_day(rpd, ingest_calls("worst", with_summary)),
        "asks_per_day": per_day(rpd, flows()["ask"].best),
        "journeys_typical": per_day(rpd, j("typical")),
        "journeys_worst": per_day(rpd, j("worst")),
    }


def markdown_report(rpds=RPD_SCENARIOS, *, extract_calls: float | None = None, with_summary: bool = True,
                    claim_images: int = 4, rpm: int = DEFAULT_RPM) -> str:
    f = flows(claim_images)
    out = ["## Gemini calls per action", "",
           "| Action | Best | Worst | Worst HTTP requests | Note |", "| --- | ---: | ---: | ---: | --- |"]
    for fl in f.values():
        tag = " (planned)" if fl.planned else ""
        out.append(f"| {fl.title}{tag} | {fl.best:g} | {fl.worst:g} | {fl.http_worst:g} | {fl.note} |")
    jt, jw = journey_calls("typical", claim_images=claim_images, with_summary=with_summary, extract_calls=extract_calls), \
        journey_calls("worst", claim_images=claim_images, with_summary=with_summary)
    out += ["", f"One full user journey (1 upload + 5 questions + 1 claim check with {claim_images} photos + 1 comparison): "
                f"**{jt:g} calls typical, {jw:g} worst case**.", "",
            f"## Capacity per day (one model, requests/day = RPD; limiter = {rpm}/minute)", "",
            "| RPD | New policies/day (best) | (typical) | (worst) | Questions/day | Full journeys/day (typical) | (worst) |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in rpds:
        c = capacity(r, extract_calls=extract_calls, with_summary=with_summary, claim_images=claim_images)
        out.append(f"| {r} | {c['ingests_best']} | {c['ingests_typical']} | {c['ingests_worst']} | {c['asks_per_day']} | "
                   f"{c['journeys_typical']} | {c['journeys_worst']} |")
    out += ["", "## Per-minute pressure", "",
            f"- A {claim_images}-photo claim check uses {flows(claim_images)['claim'].best:g} calls = {rpm_seconds(flows(claim_images)['claim'].best, rpm):.0f} s of the {rpm}/min budget; "
            f"an 8-photo check uses {MAX_CLAIM_IMAGES + 1} calls = {rpm_seconds(MAX_CLAIM_IMAGES + 1, rpm):.0f} s. "
            f"Two people checking claims in the same minute will queue behind the limiter.",
            f"- A new upload takes {ingest_calls('best', with_summary):g} calls ({rpm_seconds(ingest_calls('best', with_summary), rpm):.0f} s of the budget) when nothing goes wrong."]
    return "\n".join(out)
