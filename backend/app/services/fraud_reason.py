"""Review-reason rewording (A25). R22 plugs this into the Review Dashboard AFTER the rules have scored and ordered the claims.

    flagged reasons written by R's rules (technical text)  ->  Gemini rewords them in simple, neutral words (batched)
        ->  CODE checks each one  ->  reworded text if it passes, otherwise the ORIGINAL text

Spec 5.6: the risk score comes from rules, never from the LLM; Gemini may only reword reasons; never call anyone a fraudster; human review
required; no auto-rejection. So this module never sees a score, a severity or a claim decision, and it can only change wording:
    - every number / amount / date in the original must still be there, and no new one may appear
    - no accusing words (fraud, cheat, fake, ...) and no decision words (reject, deny, ...)
    - short (at most 2 sentences), non-empty, one answer per input
An item that fails a check silently keeps its original text. If the AI is busy, off (mock mode) or returns bad output, every item keeps its
original text, so the dashboard always works. Reasons are English only (the Review Dashboard is an insurer-staff screen).
The data on this screen is synthetic; nothing personal is sent (reason text and a flag code only).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from app.models.policy import FraudReasonOutput
from app.models.schema_export import gemini_schema
from app.prompts import load_prompt
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiClient

log = logging.getLogger("bimasaathi.fraud_reason")

PROMPT_NAME = "fraud_reason_v1"
MAX_PER_CALL = 12
MAX_INPUT_CHARS = 300
MAX_OUTPUT_CHARS = 280
MAX_SENTENCES = 2
FLAGS = ("F1", "F2", "F3", "F4", "F5")


@dataclass(frozen=True)
class ReasonIn:
    key: str            # R's own handle, e.g. "CLM-0042:F3"; returned unchanged
    flag: str           # F1..F5
    text: str           # the technical reason written by R's rule code


@dataclass
class Reworded:
    text: str
    source: Literal["ai", "original"]
    model: str | None = None
    note: str | None = None          # why the original was kept (logs / tests only)


class RewordCache:
    """Reasons come from rules, so the same input text always gives the same rewording: keep it for the life of the process."""

    def __init__(self) -> None:
        self._d: dict[str, Reworded] = {}

    @staticmethod
    def _k(flag: str, text: str) -> str:
        return hashlib.sha256(f"{flag}\n{text}".encode()).hexdigest()

    def get(self, flag: str, text: str) -> Reworded | None:
        return self._d.get(self._k(flag, text))

    def put(self, flag: str, text: str, value: Reworded) -> None:
        self._d[self._k(flag, text)] = value

    def __len__(self) -> int:
        return len(self._d)


# ------------------------------------------------------------------ the code checks
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]")
_NUM = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?")
_SENT = re.compile(r"[.!?]+(?:\s+|$)")
_BANNED = re.compile(
    r"\b(?:fraud\w*|cheat\w*|fake\w*|forg(?:ed|ery|eries)|scam\w*|liar|lying|lied|criminal\w*|guilty|dishonest\w*|deceiv\w*|decept\w*|"
    r"suspicious|suspect\w*|illegal\w*|bogus|manipulat\w*|reject\w*|den(?:y|ied|ial|ies)|declin\w*|disallow\w*)\b", re.IGNORECASE)


def clean_text(text: str) -> str:
    """Plain text for the prompt: no control/bidi characters, no angle brackets or braces, collapsed spaces, capped."""
    t = _CTRL.sub(" ", text or "").replace("<", " ").replace(">", " ").replace("{", " ").replace("}", " ")
    return re.sub(r"\s+", " ", t).strip()[:MAX_INPUT_CHARS]


def numbers(text: str) -> set[str]:
    """Every digit group, normalised so that formatting changes do not matter: commas dropped, leading zeros dropped ('04' == '4')."""
    out = set()
    for m in _NUM.findall(text):
        n = m.replace(",", "")
        if "." in n:
            a, b = n.split(".", 1)
            n = f"{int(a)}.{b.rstrip('0') or '0'}"
        else:
            n = str(int(n))
        out.add(n)
    return out


def is_neutral(text: str) -> bool:
    """True if the text has no accusing or decision words. R can also use this on the rule-written reasons in its own tests."""
    return not _BANNED.search(text)


def check_reworded(original: str, new: str) -> str | None:
    """None if the new text is acceptable, else the reason it is not."""
    new = (new or "").strip()
    if not new:
        return "empty"
    if len(new) > MAX_OUTPUT_CHARS:
        return "too_long"
    if len([s for s in _SENT.split(new) if s.strip()]) > MAX_SENTENCES:
        return "too_many_sentences"
    if not is_neutral(new):
        return "banned_word"
    a, b = numbers(original), numbers(new)
    if a - b:
        return "number_dropped"
    if b - a:
        return "number_added"
    return None


# ------------------------------------------------------------------ the call
async def _call(gemini, text, system, schema, temperature, model):
    return await gemini.generate_json(text, schema=schema, system=system, temperature=temperature, model=model, purpose="fraud_reason")


async def _call_with_fallback(gemini, text, system, schema, temperature, model: str):
    try:
        return await _call(gemini, text, system, schema, temperature, model), model
    except GeminiBusy:
        if model == "fallback":
            raise
        log.warning("fast model busy; using the fallback model")
        return await _call(gemini, text, system, schema, temperature, "fallback"), "fallback"


async def _reword_batch(batch: list[tuple[str, ReasonIn]], gemini) -> tuple[dict[str, tuple[str, str | None]] | None, str]:
    """batch = [(id, item)]. Returns ({id: (text, model)}, '') or (None, why_not)."""
    prompt = load_prompt(PROMPT_NAME)
    schema, temp = gemini_schema(FraudReasonOutput), float(prompt.meta.get("temperature", 0.1))
    items = [{"id": i, "flag": it.flag, "text": clean_text(it.text)} for i, it in batch]
    base = prompt.render_user(items_json=json.dumps(items, ensure_ascii=False, indent=1))
    model, note, last = "fast", "", "unknown"
    for _attempt in (1, 2):                                       # 2nd attempt = one retry with the validation error
        try:
            res, model = await _call_with_fallback(gemini, base + note, prompt.system, schema, temp, model)
            out = FraudReasonOutput.model_validate(res.data)
            return {r.id: (r.text, res.model) for r in out.reasons}, ""
        except GeminiBusy:
            return None, "ai_busy"
        except GeminiBadOutput as e:
            last = e.message
        except ValidationError as e:
            last = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in
                             e.errors(include_url=False, include_context=False, include_input=False))[:400]
        note = f"\n\nYour previous answer was REJECTED: {last}\nReturn corrected JSON only."
    return None, "bad_output"


async def reword_reasons(items: list[ReasonIn], gemini: GeminiClient, cache: RewordCache | None = None) -> dict[str, Reworded]:
    """Reword rule-written reasons. Returns {item.key: Reworded}; every input key is present, and the text is ALWAYS safe to show.

    Never raises for AI trouble (busy / bad output / failed checks keep the original). A bad API key or model ID (GeminiRequestError)
    still raises: it is a config bug, not a runtime condition.
    """
    result: dict[str, Reworded] = {}
    todo: list[ReasonIn] = []
    for it in items:
        original = clean_text(it.text)
        if it.key in result:
            continue
        hit = cache.get(it.flag, original) if cache else None
        if hit:
            result[it.key] = hit
        elif not original or gemini.mock_mode:
            result[it.key] = Reworded(original, "original", None, "empty" if not original else "mock_mode")
        else:
            todo.append(it)
            result[it.key] = Reworded(original, "original", None, "pending")
    for start in range(0, len(todo), MAX_PER_CALL):
        chunk = todo[start:start + MAX_PER_CALL]
        batch = [(f"r{n}", it) for n, it in enumerate(chunk, start=1)]
        got, why = await _reword_batch(batch, gemini)
        for rid, it in batch:
            original = clean_text(it.text)
            if got is None:
                out = Reworded(original, "original", None, why)
            elif rid not in got:
                out = Reworded(original, "original", None, "missing_in_answer")
            else:
                text, model = got[rid]
                problem = check_reworded(original, text)
                out = Reworded(original, "original", None, problem) if problem else Reworded(re.sub(r"\s+", " ", text).strip(), "ai", model)
            if out.source == "original":
                log.info("reason kept as written: %s", out.note)
            result[it.key] = out
            if cache is not None and (out.source == "ai"):          # only cache successes: a busy minute must not freeze the original
                cache.put(it.flag, original, out)
    return result
