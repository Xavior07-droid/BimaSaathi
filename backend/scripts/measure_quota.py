#!/usr/bin/env python3
"""A27: how many Gemini calls does ONE policy cost, and how many policies fit in a day?

    python scripts/measure_quota.py --dry-run                 # no key, no calls: the call-count model + capacity table
    python scripts/measure_quota.py --dry-run --rpd 250 --rpd 500   # capacity for the daily limit shown in YOUR AI Studio
    python scripts/measure_quota.py                           # LIVE: ~10-14 real requests, measures calls/tokens/latency
    python scripts/measure_quota.py --only 01 04 --asks 2 --skip-vision --rpd 250

Live run (needs GEMINI_API_KEY, GEMINI_MODEL_FAST, GEMINI_MODEL_FALLBACK in backend/.env). It does:
  4 policy ingests (extract) + N Ask questions + 1 compare recommendation + 1 review-reason rewording + 1 vision call.
It counts HTTP requests (what Google bills against RPD) by summing GeminiResult.attempts, and averages tokens + latency
per purpose. Then it plugs the OBSERVED extraction calls per policy into the capacity table. Cost: it spends that many
requests of today's free quota. Reports are written to eval_reports/quota-<time>.json and .md.
Daily limit (RPD): read it in AI Studio (Usage / Rate limits) for your two models and pass --rpd. Do not trust blog posts.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import quota as Q  # noqa: E402  (stdlib only)


@dataclass
class Rec:
    purpose: str
    model: str
    ok: bool
    requests: int            # HTTP requests this logical call used (attempts); failures count the full retry budget
    latency_ms: int
    prompt_tokens: int
    output_tokens: int
    total_tokens: int
    error: str = ""


class CountingGemini:
    """Wraps a real GeminiClient and records every logical call. Services see the same interface."""

    def __init__(self, inner):
        self.inner, self.records = inner, []

    @property
    def mock_mode(self):
        return self.inner.mock_mode

    async def generate_json(self, contents, **kw):
        t0 = time.monotonic()
        purpose, model = kw.get("purpose", "generic"), kw.get("model", "fast")
        try:
            res = await self.inner.generate_json(contents, **kw)
        except Exception as e:  # noqa: BLE001 - recorded, then re-raised unchanged
            self.records.append(Rec(purpose, model, False, Q.HTTP_RETRIES, int((time.monotonic() - t0) * 1000), 0, 0, 0,
                                    getattr(e, "error_code", type(e).__name__)))
            raise
        self.records.append(Rec(purpose, res.model, True, res.attempts, res.latency_ms, res.prompt_tokens or 0,
                                res.output_tokens or 0, res.total_tokens or 0))
        return res


def summarize(records: list[Rec]) -> dict[str, dict]:
    by: dict[str, list[Rec]] = defaultdict(list)
    for r in records:
        by[r.purpose].append(r)
    out = {}
    for purpose, rs in by.items():
        n = len(rs)
        out[purpose] = {"logical_calls": n, "http_requests": sum(r.requests for r in rs), "failed": sum(not r.ok for r in rs),
                        "avg_prompt_tokens": round(sum(r.prompt_tokens for r in rs) / n),
                        "avg_output_tokens": round(sum(r.output_tokens for r in rs) / n),
                        "avg_latency_s": round(sum(r.latency_ms for r in rs) / n / 1000, 1),
                        "models": sorted({r.model for r in rs})}
    return out


def table(summary: dict[str, dict]) -> str:
    rows = ["| Purpose | Calls | HTTP requests | Failed | Avg prompt tokens | Avg output tokens | Avg latency (s) | Models |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for p, s in sorted(summary.items()):
        rows.append(f"| {p} | {s['logical_calls']} | {s['http_requests']} | {s['failed']} | {s['avg_prompt_tokens']} | "
                     f"{s['avg_output_tokens']} | {s['avg_latency_s']} | {', '.join(s['models'])} |")
    return "\n".join(rows)


async def live(a) -> tuple[list[Rec], list[dict]]:
    from PIL import Image
    from app.config import get_settings
    from app.services import ask as A
    from app.services import doc_classify as D
    from app.services import fraud_reason as F
    from app.services import policy_brain as PB
    from app.services import recommend as R
    from app.services.extraction_eval import REPO_DATA, load_manifest
    from app.services.gemini import GeminiError, get_gemini

    s = get_settings()
    if s.mock_mode:
        print("GEMINI_API_KEY is empty (MOCK mode): nothing to measure. Put your key in backend/.env or use --dry-run.")
        raise SystemExit(2)
    s.validate_for_live_gemini()
    g = CountingGemini(get_gemini())
    print(f"models: fast={s.gemini_model_fast}  fallback={s.gemini_model_fallback}  limiter {s.gemini_max_concurrent} concurrent, {s.gemini_rpm}/min")

    manifest = [p for p in load_manifest() if not a.only or any(p["file"].startswith(x) for x in a.only)]
    per_policy, first_brain = [], None
    for p in manifest:
        print(f"... ingest {p['file']}", flush=True)
        before, t0 = len(g.records), time.monotonic()
        try:
            brain = await PB.ingest_document((REPO_DATA / "sample_policies" / p["file"]).read_bytes(), gemini=g)
            first_brain = first_brain or brain
            err = ""
        except GeminiError as e:
            err = e.error_code
        mine = g.records[before:]
        per_policy.append({"file": p["file"], "extract_calls": len(mine), "http_requests": sum(r.requests for r in mine),
                           "tokens": sum(r.total_tokens for r in mine), "seconds": round(time.monotonic() - t0, 1), "error": err})

    questions = [("What is my co-pay?", "en"), ("मेरे कमरे के किराये की सीमा क्या है?", "hi"), ("waiting period kitna hai?", "mr")][: a.asks]
    if first_brain:
        for q, lang in questions:
            print(f"... ask [{lang}] {q}", flush=True)
            try:
                await A.answer_question(first_brain, q, lang, g)
            except GeminiError as e:
                print("   ask failed:", e.error_code)

    print("... compare recommendation", flush=True)
    sc = R.Scenario(days=3, room_rent_per_day=8000, bill=150000)
    pols = [R.PolicyFacts(policy_id="p1", name="Policy A", estimated_out_of_pocket=22000, premium=14250, sum_insured=500000, copay_percent=10),
            R.PolicyFacts(policy_id="p2", name="Policy B", estimated_out_of_pocket=41000, premium=9800, sum_insured=500000, copay_percent=20)]
    try:
        await R.recommend(sc, pols, g)
    except GeminiError as e:
        print("   recommend failed:", e.error_code)

    print("... review-reason rewording (1 batch)", flush=True)
    try:
        await F.reword_reasons([F.ReasonIn("c1", "F2", "Invoice INV-77841 for Rs 52,300 appears on 2 claims.")], g)
    except GeminiError as e:
        print("   reword failed:", e.error_code)

    if not a.skip_vision:
        print("... vision classify (blank test image)", flush=True)
        b = io.BytesIO()
        Image.new("RGB", (600, 800), "white").save(b, "JPEG")
        try:
            await D.classify_document(b.getvalue(), "image/jpeg", g)
        except GeminiError as e:
            print("   vision failed:", e.error_code)
    return g.records, per_policy


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="no Gemini calls: print the model only")
    ap.add_argument("--rpd", type=int, action="append", help="daily request limit from AI Studio; repeatable")
    ap.add_argument("--only", nargs="*", default=[], help="policy prefixes, e.g. 01 04")
    ap.add_argument("--asks", type=int, default=3, choices=[0, 1, 2, 3])
    ap.add_argument("--skip-vision", action="store_true")
    ap.add_argument("--claim-images", type=int, default=4)
    ap.add_argument("--no-summary", action="store_true", help="exclude the planned summary call from the numbers")
    ap.add_argument("--out", default=str(ROOT / "eval_reports"))
    a = ap.parse_args()
    rpds = tuple(a.rpd) if a.rpd else Q.RPD_SCENARIOS
    with_summary = not a.no_summary

    records, per_policy, extract_avg = [], [], None
    if not a.dry_run:
        records, per_policy = asyncio.run(live(a))
        done = [p for p in per_policy if not p["error"]]
        if done:
            extract_avg = sum(p["extract_calls"] for p in done) / len(done)

    parts = []
    if records:
        parts += ["# Measured (live)", "", "## Ingest, per policy", "",
                  "| Policy | Gemini calls | HTTP requests | Tokens | Seconds | Error |", "| --- | ---: | ---: | ---: | ---: | --- |"]
        parts += [f"| {p['file']} | {p['extract_calls']} | {p['http_requests']} | {p['tokens']} | {p['seconds']} | {p['error']} |" for p in per_policy]
        parts += ["", "## Per purpose", "", table(summarize(records)),
                  "", f"This measurement spent **{sum(r.requests for r in records)} requests** of today's free quota.",
                  f"Observed extraction calls per policy: **{extract_avg:.2f}**" if extract_avg is not None else "No policy was extracted successfully.", ""]
    parts += ["# Model", "", Q.markdown_report(rpds, extract_calls=extract_avg, with_summary=with_summary, claim_images=a.claim_images)]
    report = "\n".join(parts)
    print("\n" + report)

    if records:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        (out / f"quota-{stamp}.md").write_text(report, encoding="utf-8")
        (out / f"quota-{stamp}.json").write_text(json.dumps({"records": [asdict(r) for r in records], "per_policy": per_policy,
                                                             "summary": summarize(records), "extract_calls_avg": extract_avg}, indent=2), encoding="utf-8")
        print(f"\nSaved {out}/quota-{stamp}.md and .json. Send the .md to M.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
