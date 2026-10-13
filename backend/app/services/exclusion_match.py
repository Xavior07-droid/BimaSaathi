"""Semantic exclusion match (A22). Used by R's rule R3 (claim checker); R7 calls `match_exclusion`.

    diagnosis + policy.exclusions -> Gemini (exclusion_match_v1, numbered list) -> validate ExclusionMatchOutput
        -> CODE maps the returned indexes to the policy's own exclusion text + source (the model never writes a citation)
        -> ExclusionMatch(verdict, hits, reason, method)

Verdicts (the model returns the first three; "unclear" is produced by code only):
    match     clearly inside an exclusion                       -> rule status "fail"
    possible  might apply / depends on facts we do not have     -> rule status "at_risk"
    no_match  no LISTED exclusion applies (NOT "covered")       -> rule status "pass"
    unclear   we could not check (no exclusions on file, AI busy or off, bad output) -> rule status "at_risk"

Failure never turns into a pass: if the AI is unavailable the result is "possible" (cheap keyword overlap) or "unclear".
Privacy: only the diagnosis text and the policy's exclusion wording go to Gemini (no name, no policy number). The diagnosis is
health data and the free Gemini tier may use inputs, which is why the consent screen warns users to upload only sample/anonymised data.
Reasons are English only (the claim UI shows them as-is).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from app.models.policy import ExclusionItem, ExclusionMatchOutput, Source
from app.models.schema_export import gemini_schema
from app.prompts import load_prompt
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiClient

log = logging.getLogger("bimasaathi.exclusion_match")

PROMPT_NAME = "exclusion_match_v1"
MAX_DIAGNOSIS_CHARS = 200
MAX_EXCLUSIONS = 60          # extract_v1 keeps at most 40; the cap protects the prompt size
MAX_HITS = 3
MAX_REASON_CHARS = 240

Verdict = Literal["match", "possible", "no_match", "unclear"]
RULE_STATUS = {"match": "fail", "possible": "at_risk", "no_match": "pass", "unclear": "at_risk"}


class DiagnosisError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class ExclusionHit:
    text: str
    source: Source


@dataclass
class ExclusionMatch:
    verdict: Verdict
    hits: list[ExclusionHit] = field(default_factory=list)
    reason: str = ""
    method: Literal["gemini", "keyword", "none"] = "none"
    model: str | None = None
    note: str | None = None            # why a fallback was used (logs / tests; not shown to users)

    @property
    def rule_status(self) -> str:
        """pass | fail | at_risk, for R's rule result."""
        return RULE_STATUS[self.verdict]

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "rule_status": self.rule_status, "reason": self.reason, "method": self.method,
                "exclusions": [{"text": h.text, "source": h.source.model_dump()} for h in self.hits]}


# ------------------------------------------------------------------ input
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏‪-‮⁦-⁩]")


def clean_diagnosis(text: object) -> str:
    """Plain text only: no control/bidi characters, no angle brackets (cannot close our <diagnosis> tag), no {{ }}."""
    if not isinstance(text, str):
        raise DiagnosisError("invalid_diagnosis", "Please enter the diagnosis or treatment.")
    t = _CTRL.sub(" ", text).replace("<", " ").replace(">", " ").replace("{{", " ").replace("}}", " ")
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        raise DiagnosisError("invalid_diagnosis", "Please enter the diagnosis or treatment.")
    if len(t) > MAX_DIAGNOSIS_CHARS:
        raise DiagnosisError("diagnosis_too_long", f"Please keep the diagnosis under {MAX_DIAGNOSIS_CHARS} characters.")
    return t


def numbered(exclusions: list[ExclusionItem]) -> str:
    return "\n".join(f"{i}. {e.text}" for i, e in enumerate(exclusions))


# ------------------------------------------------------------------ keyword fallback (MOCK mode / AI unavailable)
# Concept triggers: a concept is "present" in a text if any trigger occurs at a word start. Never returns no_match.
_CONCEPTS: dict[str, tuple[str, ...]] = {
    "dental": ("dent", "tooth", "teeth", "root canal", "molar", "gingiv", "denture"),
    "cosmetic": ("cosmetic", "plastic", "aesthetic", "rhinoplast", "liposuction", "botox"),
    "fertility": ("infertil", "fertil", "ivf", "iui", "assisted reproduc", "surrogac"),
    "obesity": ("obes", "bariatric", "weight"),
    "adventure": ("adventure", "paraglid", "skydiv", "bungee", "scuba", "trekking", "mountaineer", "racing"),
    "war": ("war ", "war,", "nuclear", "terror"),
    "self_harm": ("self-inflicted", "self inflicted", "self harm", "self-harm", "suicide"),
    "substance": ("alcohol", "drug abuse", "substance", "addiction"),
    "hiv": ("hiv", "aids"),
    "mental": ("psychiatr", "mental", "depress", "anxiety"),
    "congenital": ("congenital", "birth defect"),
    "maternity": ("pregnan", "maternity", "caesarean", "cesarean", "childbirth"),
    "pre_existing": ("pre-existing", "pre existing"),
}
_GENERIC = {"treatment", "treatments", "surgery", "surgeries", "disease", "diseases", "injury", "injuries", "hospital",
            "hospitalisation", "hospitalization", "charges", "expenses", "medical", "condition", "conditions",
            "unless", "except", "caused", "needed", "other", "policy", "arising", "related", "including"}
_WORD = re.compile(r"[a-z]{5,}")


def _concepts(text: str) -> set[str]:
    low = " " + text.casefold() + " "
    return {c for c, trig in _CONCEPTS.items() if any(re.search(r"(?<![a-z])" + re.escape(t), low) for t in trig)}


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in _WORD.findall(text.casefold()) if w not in _GENERIC}


def keyword_match(diagnosis: str, exclusions: list[ExclusionItem]) -> list[int]:
    """Indexes of exclusions that share a concept or a meaningful word with the diagnosis."""
    d_conc, d_words = _concepts(diagnosis), _words(diagnosis)
    out = []
    for i, e in enumerate(exclusions):
        if d_conc & _concepts(e.text) or d_words & _words(e.text):
            out.append(i)
    return out


def _keyword_result(diagnosis: str, exclusions: list[ExclusionItem], note: str) -> ExclusionMatch:
    idx = keyword_match(diagnosis, exclusions)[:MAX_HITS]
    if not idx:
        return ExclusionMatch("unclear", [], "We could not check this diagnosis against the exclusions automatically. Please confirm with your insurer.",
                              "none", note=note)
    hits = [ExclusionHit(exclusions[i].text, exclusions[i].source) for i in idx]
    return ExclusionMatch("possible", hits, f"This may fall under the exclusion \"{hits[0].text}\". This was a keyword check only, so please confirm with your insurer.",
                          "keyword", note=note)


# ------------------------------------------------------------------ the call
async def _call(gemini, text: str, system: str, schema: dict, model: str):
    return await gemini.generate_json(text, schema=schema, system=system, temperature=0.0, model=model, purpose="exclusion_match")


async def _call_with_fallback(gemini, text, system, schema, model: str):
    """Fast model; if it is overloaded, the Flash-Lite model once. Returns (result, model_used)."""
    try:
        return await _call(gemini, text, system, schema, model), model
    except GeminiBusy:
        if model == "fallback":
            raise
        log.warning("fast model busy; using the fallback model")
        return await _call(gemini, text, system, schema, "fallback"), "fallback"


async def _ask_model(exclusions, diagnosis, gemini) -> tuple[ExclusionMatchOutput | None, str | None]:
    prompt = load_prompt(PROMPT_NAME)
    schema = gemini_schema(ExclusionMatchOutput)
    base = prompt.render_user(diagnosis=diagnosis, exclusions=numbered(exclusions))
    model, note, used = "fast", "", None
    for _attempt in (1, 2):                                  # 2nd attempt = one retry with the validation error
        try:
            res, model = await _call_with_fallback(gemini, base + note, prompt.system, schema, model)
            used = res.model
            return ExclusionMatchOutput.model_validate(res.data), used
        except GeminiBadOutput as e:
            last = e.message
        except ValidationError as e:
            last = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in
                             e.errors(include_url=False, include_context=False, include_input=False))[:400]
        note = f"\n\nYour previous answer was REJECTED: {last}\nReturn corrected JSON only."
    return None, used


_DIGITS = re.compile(r"\d[\d,.]*")


def _safe_reason(reason: str, diagnosis: str, hits: list[ExclusionHit]) -> str:
    """The reason is model text: keep it short, and never let it carry a number that is not in the inputs."""
    reason = re.sub(r"\s+", " ", reason).strip()[:MAX_REASON_CHARS]
    known = diagnosis + " " + " ".join(h.text for h in hits)
    if not reason or any(n not in known for n in _DIGITS.findall(reason)):
        return f"This may fall under the exclusion \"{hits[0].text}\"." if hits else ""
    return reason


def finalize(out: ExclusionMatchOutput, exclusions: list[ExclusionItem], diagnosis: str, model: str | None) -> ExclusionMatch:
    """All the 'code decides' rules: indexes must exist, citations come from the policy, not the model."""
    if out.verdict == "no_match":
        return ExclusionMatch("no_match", [], "", "gemini", model)
    seen: list[int] = []
    for i in out.matched:
        if isinstance(i, int) and 0 <= i < len(exclusions) and i not in seen:
            seen.append(i)
    seen = seen[:MAX_HITS]
    if not seen:                                              # said match/possible but pointed at nothing real: cannot cite it
        log.warning("exclusion match: verdict %s with no valid index", out.verdict)
        return ExclusionMatch("unclear", [], "We could not check this diagnosis against the exclusions automatically. Please confirm with your insurer.",
                              "gemini", model, note="no_valid_index")
    hits = [ExclusionHit(exclusions[i].text, exclusions[i].source) for i in seen]
    return ExclusionMatch(out.verdict, hits, _safe_reason(out.reason, diagnosis, hits), "gemini", model)


async def match_exclusion(diagnosis: str, exclusions: list[ExclusionItem], gemini: GeminiClient) -> ExclusionMatch:
    """Does `diagnosis` fall under one of the policy's `exclusions`? Raises DiagnosisError for bad input only.

    Never raises for AI trouble (busy / bad output): that degrades to a keyword check or "unclear", never to a pass.
    A bad API key or model ID (GeminiRequestError) still raises: it is a config bug, not a runtime condition.
    """
    d = clean_diagnosis(diagnosis)
    excl = list(exclusions)[:MAX_EXCLUSIONS]
    if not excl:
        # "Not listed is not excluded": an empty list means we know nothing, so we cannot say no_match.
        return ExclusionMatch("unclear", [], "No exclusions were found in this policy's data, so this cannot be checked. Please confirm with your insurer.",
                              "none", note="no_exclusions")
    if gemini.mock_mode:
        return _keyword_result(d, excl, "mock_mode")
    try:
        out, model = await _ask_model(excl, d, gemini)
    except GeminiBusy:
        log.warning("exclusion match: AI busy, using the keyword check")
        return _keyword_result(d, excl, "ai_busy")
    if out is None:
        return _keyword_result(d, excl, "bad_output")
    return finalize(out, excl, d, model)
