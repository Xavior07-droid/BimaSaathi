#!/usr/bin/env python3
"""A21: run the 15-question Q&A set (data/qa_testset.json) against the sample policy and score it.

From backend/ with your key in .env (GEMINI_API_KEY, GEMINI_MODEL_FAST, GEMINI_MODEL_FALLBACK):

    python scripts/eval_ask.py                 # live: 15 Gemini calls (about 2 minutes under the 10/min limiter)
    python scripts/eval_ask.py --only Q05 Q13  # just those questions
    python scripts/eval_ask.py --runs 3        # repeat: are the answers stable? (3x quota)
    python scripts/eval_ask.py --dry-run       # no key: scripted ideal answers, checks the harness itself

Calls ask.answer_question directly (not the HTTP route), so the per-user 6/min throttle does not apply; the Gemini
wrapper's limiter paces the calls. Exit code 0 = PASS (see ask_eval.py), 1 = FAIL, 2 = cannot run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings                                  # noqa: E402
from app.services import ask as A                                     # noqa: E402
from app.services import ask_eval as E                                # noqa: E402
from app.services.gemini import GeminiError, GeminiResult, get_gemini  # noqa: E402
from app.services.mock_policy import load_sample_policy               # noqa: E402


class DryAskGemini:
    """Returns each question's `ideal` answer (or 'not grounded' for out-of-scope). Proves the harness, not the model."""
    mock_mode = False

    def __init__(self, items):
        self.ideal = {A.clean_question(i["question"]): i.get("ideal") for i in items}

    async def generate_json(self, text, **kw):
        q = re.search(r"<question>\s*(.*?)\s*</question>", text, re.S).group(1)
        ideal = self.ideal.get(q)
        data = ({"answer": ideal["answer"], "citations": ideal["citations"], "grounded": True} if ideal
                else {"answer": "", "citations": [], "grounded": False})
        return GeminiResult(data=data, text=json.dumps(data), model="dry-run", attempts=1, latency_ms=1, total_tokens=0)


async def run_all(items, brain, gemini) -> list[E.QResult]:
    out = []
    for it in items:
        print(f"... {it['id']} {it['question'][:50]}", flush=True)
        t0 = time.monotonic()
        try:
            res = await A.answer_question(brain, it["question"], it["lang"], gemini)
        except GeminiError as e:
            out.append(E.error_result(it, e.error_code, time.monotonic() - t0))
            continue
        out.append(E.score(it, res, brain, time.monotonic() - t0))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "eval_reports"))
    a = ap.parse_args()

    items = E.load_testset()
    if a.only:
        items = [i for i in items if i["id"] in a.only]
    if not items:
        print("No question matches --only", a.only); return 2
    brain = load_sample_policy()

    if a.dry_run:
        gemini = DryAskGemini(E.load_testset())
    else:
        s = get_settings()
        if s.mock_mode:
            print("GEMINI_API_KEY is empty (MOCK mode): nothing to evaluate. Put your key in backend/.env or use --dry-run.")
            return 2
        s.validate_for_live_gemini()
        gemini = get_gemini()
        print(f"models: fast={s.gemini_model_fast}  fallback={s.gemini_model_fallback}  prompt={A.PROMPT_NAME}")

    code, runs = 0, []
    for n in range(1, a.runs + 1):
        if a.runs > 1:
            print(f"\n##### run {n}/{a.runs}")
        rs = await run_all(items, brain, gemini)
        sm = E.summarize(rs)
        print(E.format_report(rs, sm))
        code |= 0 if sm.passed else 1
        runs.append((rs, sm))
    if a.runs > 1:
        stable = all(len({r[0][i].status for r in runs}) == 1 for i in range(len(items)))
        print(f"\nStatuses identical across {a.runs} runs: {'yes' if stable else 'NO (answers are unstable)'}")

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = out / f"ask-{stamp}{'-dryrun' if a.dry_run else ''}.json"
    path.write_text(json.dumps({"created_at": stamp, "dry_run": a.dry_run, "prompt": A.PROMPT_NAME, "runs": [
        {"summary": vars(sm), "questions": [vars(r) for r in rs]} for rs, sm in runs]}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"report saved: {path}")
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
