#!/usr/bin/env python3
"""A14: measure extraction accuracy on the 4 sample policies against data/ground_truth.csv.

Run from backend/ with your key in .env (GEMINI_API_KEY, GEMINI_MODEL_FAST, GEMINI_MODEL_FALLBACK):

    python scripts/eval_extraction.py                 # production path: fast -> retry -> fallback
    python scripts/eval_extraction.py --plan fast     # ONE attempt on the Flash model (first-try accuracy, 4 calls)
    python scripts/eval_extraction.py --plan fallback # Flash-Lite alone (how good is the safety net?)
    python scripts/eval_extraction.py --only 02 04    # just those policies
    python scripts/eval_extraction.py --runs 3        # repeat to see run-to-run variance (3x the quota)
    python scripts/eval_extraction.py --dry-run       # no key: scripted perfect answers, checks the harness itself

Quota: one run = 4 to 12 Gemini calls (1 per policy if it passes first time). Free tier is ~10 requests/minute; the
wrapper's limiter paces calls, so a run can take 1-2 minutes. A report with the raw outputs is saved to eval_reports/.
Exit code 0 = >= 85% and no hallucinated nulls, 1 otherwise.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings                                            # noqa: E402
from app.services import extraction_eval as E                                   # noqa: E402
from app.services.gemini import GeminiError, get_gemini                         # noqa: E402
from app.services.policy_brain import extract_policy                            # noqa: E402

SAMPLES = E.REPO_DATA / "sample_policies"
PLANS = {"default": ("fast", "fast", "fallback"), "fast": ("fast",), "fallback": ("fallback",)}


class DryRunGemini:
    """Stands in for Gemini: returns the manifest's correct answer. Proves the harness, says nothing about the model."""
    mock_mode = False

    def __init__(self, manifest):
        self.by_name = {p["file"]: E.perfect_answer(p) for p in manifest}
        self.current = None

    async def generate_json(self, contents, **kw):
        from app.services.gemini import GeminiResult
        data = self.by_name[self.current]
        return GeminiResult(data=data, text=json.dumps(data), model="dry-run", attempts=1, latency_ms=1, total_tokens=0)


async def run_one(p: dict, gt: list[dict], gemini, plan) -> E.PolicyRun:
    data = (SAMPLES / p["file"]).read_bytes()
    if isinstance(gemini, DryRunGemini):
        gemini.current = p["file"]
    t0 = time.monotonic()
    try:
        out = await extract_policy(data, gemini=gemini, plan=plan)
    except GeminiError as e:
        return E.run_policy(p, gt, None, error=e.error_code, seconds=time.monotonic() - t0)
    return E.run_policy(p, gt, out.extraction.model_dump(mode="json"), model=out.model, calls=out.calls,
                        retried=out.retried, used_fallback=out.used_fallback, input_mode=out.input_mode,
                        seconds=time.monotonic() - t0, tokens=out.total_tokens, confidence=out.confidence,
                        warnings=out.warnings)


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", choices=PLANS, default="default")
    ap.add_argument("--only", nargs="*", default=[], help="policy number prefixes, e.g. 01 04")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "eval_reports"))
    ap.add_argument("--verbose", action="store_true", help="print the full extracted JSON of every policy")
    a = ap.parse_args()

    manifest = E.load_manifest()
    gt = E.load_ground_truth()
    if a.only:
        manifest = [p for p in manifest if any(p["file"].startswith(x) for x in a.only)]
    if not manifest:
        print("No policy matches --only", a.only); return 2

    if a.dry_run:
        gemini = DryRunGemini(E.load_manifest())
    else:
        s = get_settings()
        if s.mock_mode:
            print("GEMINI_API_KEY is empty (MOCK mode): nothing to evaluate. Put your key in backend/.env or use --dry-run.")
            return 2
        s.validate_for_live_gemini()
        gemini = get_gemini()
        print(f"models: fast={s.gemini_model_fast}  fallback={s.gemini_model_fallback}  plan={a.plan}  "
              f"(limiter: {s.gemini_max_concurrent} concurrent, {s.gemini_rpm}/min)")

    exit_code, all_runs = 0, []
    for n in range(1, a.runs + 1):
        if a.runs > 1:
            print(f"\n##### run {n}/{a.runs}")
        runs = []
        for p in manifest:
            print(f"... {p['file']}", flush=True)
            runs.append(await run_one(p, gt, gemini, PLANS[a.plan]))
        s_ = E.summarize(runs)
        print(E.format_report(runs, s_))
        if a.verbose:
            for r in runs:
                print(r.policy_file, json.dumps(r.extraction, indent=2, ensure_ascii=False))
        total_calls = sum(r.calls for r in runs)
        print(f"Gemini calls this run: {total_calls}  tokens: {sum(r.tokens for r in runs)}")
        exit_code |= 0 if s_.clean else 1
        all_runs.append((runs, s_))

    if a.runs > 1:
        accs = [s_.accuracy for _, s_ in all_runs]
        print(f"\nAccuracy over {a.runs} runs: min {min(accs):.0%}  max {max(accs):.0%}  "
              f"(a spread above ~5 points means the prompt is not stable)")

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = out / f"extraction-{stamp}{'-dryrun' if a.dry_run else ''}.json"
    path.write_text(json.dumps({
        "created_at": stamp, "plan": a.plan, "dry_run": a.dry_run,
        "runs": [{"summary": {"accuracy": s_.accuracy, "ok": s_.ok, "total": s_.total, "hallucinated": s_.hallucinated,
                              "per_field": s_.per_field, "per_policy": s_.per_policy},
                  "policies": [{"policy_file": r.policy_file, "error": r.error, "model": r.model, "calls": r.calls,
                                "retried": r.retried, "used_fallback": r.used_fallback, "input_mode": r.input_mode,
                                "seconds": round(r.seconds, 1), "tokens": r.tokens, "confidence": r.confidence,
                                "warnings": r.warnings,
                                "misses": [vars(x) for x in r.rows + r.extras if not x.ok],
                                "extraction": r.extraction} for r in runs]} for runs, s_ in all_runs]},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report saved: {path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
