"""Compare recommendation (A24). R's POST /api/compare calls `recommend()` AFTER the calculator has produced the numbers.

    PolicyFacts (from R's calculator / normaliser) -> code picks the highlights (lowest out-of-pocket, ties, gaps, cheapest premium)
        -> Gemini (recommend_v1) only WORDS them, en/hi/mr in one call -> code checks every number and format
        -> RecommendResult   (or a fixed code-built template if the AI is busy, off, or fails the checker twice)

Spec 5.4: numbers come from code, never from the LLM; Gemini writes a 3-4 line recommendation and must not invent numbers; label it
"simplified estimate". `best_policy_id` for the UI's best-fit badge is chosen HERE by code (lowest estimated out-of-pocket, then
lower premium, then the order given), never by the model. `ESTIMATE_NOTE` is the fixed "simplified estimate" text.
Privacy: only policy names, money figures and percentages go to Gemini: no holder name, no policy number.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from app.models.policy import RecommendationOutput
from app.models.schema_export import gemini_schema
from app.prompts import load_prompt
from app.services import summary_check as S
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiClient
from app.services.glossary import glossary_block

log = logging.getLogger("bimasaathi.recommend")

LANGS = ("en", "hi", "mr")
PROMPT_NAME = "recommend_v1"
MAX_NAME_CHARS = 60
MAX_TEXT_CHARS = 700

ESTIMATE_NOTE = {
    "en": "Simplified estimate for this scenario only. Real claims depend on the policy wording and the insurer's decision.",
    "hi": "यह सिर्फ़ इसी स्थिति का सरल अनुमान है। असली क्लेम पॉलिसी की शर्तों और बीमा कंपनी के फ़ैसले पर निर्भर करते हैं।",
    "mr": "हा फक्त याच परिस्थितीचा सोपा अंदाज आहे. प्रत्यक्ष क्लेम पॉलिसीच्या अटी आणि विमा कंपनीच्या निर्णयावर अवलंबून असतात.",
}


# ------------------------------------------------------------------ input contract (R fills these from its calculator output)
@dataclass
class Scenario:
    days: int
    room_rent_per_day: int
    bill: int


@dataclass
class PolicyFacts:
    policy_id: str
    name: str                                   # shown to the user and sent to Gemini, e.g. "Sanjivani Suraksha"; no policy number
    estimated_out_of_pocket: int                # from R's calculator
    premium: int | None = None
    sum_insured: int | None = None
    copay_percent: float | None = None
    room_rent_cap_per_day: int | None = None    # rupees per day, already resolved by code (a % of sum insured is converted by the calculator)
    pre_existing_months: int | None = None
    initial_days: int | None = None


class RecommendInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Highlights:
    best_policy_id: str                         # lowest out-of-pocket; ties broken by lower premium, then input order
    tied_ids: list[str]                         # every policy with the lowest out-of-pocket (len 1 = no tie)
    next_best_id: str | None = None             # cheapest-out-of-pocket policy that is NOT tied for lowest
    extra_out_of_pocket: int | None = None      # next_best - lowest
    lowest_premium_id: str | None = None        # lowest premium among those with a known premium (ties: lower out-of-pocket)
    extra_premium_vs_lowest: int | None = None  # best.premium - lowest premium, only when that is positive


@dataclass
class RecommendResult:
    en: str
    hi: str
    mr: str
    highlights: Highlights
    source: Literal["ai", "template"]
    model: str | None = None
    note: str | None = None                     # why the template was used (logs / tests only)

    def to_dict(self) -> dict:
        return {"recommendation": {"en": self.en, "hi": self.hi, "mr": self.mr}, "best_policy_id": self.highlights.best_policy_id,
                "estimate_note": ESTIMATE_NOTE, "source": self.source}


# ------------------------------------------------------------------ validation and the code-made highlights
def _name(raw: str) -> str:
    n = re.sub(r"[<>{}\x00-\x1f​-‏‪-‮⁦-⁩]", " ", raw or "")
    return re.sub(r"\s+", " ", n).strip()[:MAX_NAME_CHARS]


def prepare(scenario: Scenario, policies: list[PolicyFacts]) -> list[PolicyFacts]:
    """Validate and return copies with clean, unique names."""
    if not 2 <= len(policies) <= 3:
        raise RecommendInputError("compare_needs_2_or_3", "Please compare 2 or 3 policies.")
    if scenario.days < 0 or scenario.room_rent_per_day < 0 or scenario.bill < 0:
        raise RecommendInputError("invalid_scenario", "The scenario numbers cannot be negative.")
    if len({p.policy_id for p in policies}) != len(policies):
        raise RecommendInputError("duplicate_policy", "The same policy was given twice.")
    out, used = [], set()
    for p in policies:
        if p.estimated_out_of_pocket is None or p.estimated_out_of_pocket < 0:
            raise RecommendInputError("missing_estimate", "Every policy needs a calculated out-of-pocket amount.")
        base = _name(p.name) or "Policy"
        name, k = base, 2
        while name.casefold() in used:
            name, k = f"{base} ({k})", k + 1
        used.add(name.casefold())
        out.append(PolicyFacts(**{**p.__dict__, "name": name}))
    return out


def highlights(policies: list[PolicyFacts]) -> Highlights:
    inf = float("inf")
    low = min(p.estimated_out_of_pocket for p in policies)
    top = [p for p in policies if p.estimated_out_of_pocket == low]
    best = min(top, key=lambda p: (p.premium if p.premium is not None else inf, policies.index(p)))
    rest = [p for p in policies if p.estimated_out_of_pocket > low]
    nxt = min(rest, key=lambda p: (p.estimated_out_of_pocket, policies.index(p))) if rest else None
    priced = [p for p in policies if p.premium is not None]
    cheapest = min(priced, key=lambda p: (p.premium, p.estimated_out_of_pocket, policies.index(p))) if priced else None
    extra_prem = None
    if cheapest and best.premium is not None and best.premium > cheapest.premium:
        extra_prem = best.premium - cheapest.premium
    return Highlights(best.policy_id, [p.policy_id for p in top], nxt.policy_id if nxt else None,
                      nxt.estimated_out_of_pocket - low if nxt else None, cheapest.policy_id if cheapest else None, extra_prem)


def facts_json(scenario: Scenario, policies: list[PolicyFacts], h: Highlights) -> str:
    by = {p.policy_id: p for p in policies}
    nxt, cheap = (by.get(h.next_best_id), by.get(h.lowest_premium_id))
    data = {
        "scenario": {"days_in_hospital": scenario.days, "room_rent_per_day": S.format_amount(scenario.room_rent_per_day),
                     "hospital_bill": S.format_amount(scenario.bill)},
        "policies": [{k: v for k, v in {
            "name": p.name, "estimated_out_of_pocket": S.format_amount(p.estimated_out_of_pocket),
            "premium": S.format_amount(p.premium) if p.premium is not None else None,
            "sum_insured": S.format_amount(p.sum_insured) if p.sum_insured is not None else None,
            "copay_percent": f"{p.copay_percent:g}%" if p.copay_percent is not None else None,
            "room_rent_cap_per_day": S.format_amount(p.room_rent_cap_per_day) if p.room_rent_cap_per_day is not None else None,
            "pre_existing_waiting_months": p.pre_existing_months, "initial_waiting_days": p.initial_days}.items() if v is not None}
            for p in policies],
        "highlights": {k: v for k, v in {
            "lowest_out_of_pocket": [by[i].name for i in h.tied_ids], "tie": len(h.tied_ids) > 1,
            "next_best": {"name": nxt.name, "estimated_out_of_pocket": S.format_amount(nxt.estimated_out_of_pocket),
                          "extra_out_of_pocket": S.format_amount(h.extra_out_of_pocket)} if nxt else None,
            "lowest_premium": {"name": cheap.name, "premium": S.format_amount(cheap.premium)}
            if cheap and cheap.policy_id not in h.tied_ids else None,
            "extra_premium_vs_lowest": S.format_amount(h.extra_premium_vs_lowest) if h.extra_premium_vs_lowest is not None else None,
        }.items() if v is not None},
    }
    return json.dumps(data, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ the number checker (pure code)
_SENTENCE_END = re.compile(r"[.!?।]+(?:\s+|$)")
_ADVICE_EN = re.compile(r"\b(?:buy|purchase|switch|cancel|port(?:ing)?|guarantee[sd]?|best policy|you should)\b", re.IGNORECASE)


def allowed_values(scenario: Scenario, policies: list[PolicyFacts], h: Highlights) -> tuple[set[int], set[float], set[int], set[int]]:
    """(amounts, percents, day counts, month counts) the text may contain."""
    amounts = {scenario.room_rent_per_day, scenario.bill}
    percents: set[float] = set()
    days, months = {scenario.days}, set()
    for p in policies:
        amounts |= {v for v in (p.estimated_out_of_pocket, p.premium, p.sum_insured, p.room_rent_cap_per_day) if v is not None}
        if p.copay_percent is not None:
            percents.add(float(p.copay_percent))
        if p.initial_days is not None:
            days.add(p.initial_days)
        if p.pre_existing_months is not None:
            months.add(p.pre_existing_months)
    amounts |= {v for v in (h.extra_out_of_pocket, h.extra_premium_vs_lowest) if v is not None}
    return amounts, percents, days, months


@dataclass
class Check:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def retry_note(self, limit: int = 10) -> str:
        return ("\n\nYour previous answer was REJECTED by the number checker:\n" + "\n".join(f"- {e}" for e in self.errors[:limit]) +
                "\nReturn corrected JSON only. Use the exact formats and ONLY numbers from the facts.")


def check_recommendation(out: RecommendationOutput, scenario: Scenario, policies: list[PolicyFacts], h: Highlights) -> Check:
    chk = Check()
    amounts, percents, days, months = allowed_values(scenario, policies, h)
    by = {p.policy_id: p for p in policies}
    best = by[h.best_policy_id]
    per_lang: dict[str, S.Tokens] = {}
    for lang in LANGS:
        text = getattr(out, lang)
        tok = per_lang[lang] = S.extract_tokens(text, lang)
        for e in tok.format_errors:
            chk.errors.append(f"{lang}: {e}")
        for a in sorted(tok.amounts - amounts):
            chk.errors.append(f"{lang}: amount {S.format_amount(a)} is not in the facts")
        for d in sorted(tok.dates):
            chk.errors.append(f"{lang}: dates are not allowed here ({S.format_date(d)})")
        for pc in sorted(tok.percents - percents):
            chk.errors.append(f"{lang}: percentage {pc:g}% is not in the facts")
        for cls, n in sorted(tok.units):
            ok = (cls == "day" and n in days) or (cls == "month" and n in months)
            if not ok:
                chk.errors.append(f"{lang}: '{n} {cls}s' is not in the facts" if cls != "year" else f"{lang}: do not convert to years ({n} years)")
        if best.estimated_out_of_pocket not in tok.amounts:
            chk.errors.append(f"{lang}: the lowest out-of-pocket amount {S.format_amount(best.estimated_out_of_pocket)} is missing")
        n_sent = len([s for s in _SENTENCE_END.split(text.strip()) if s.strip()])
        if not 2 <= n_sent <= 5:
            chk.errors.append(f"{lang}: write 3 or 4 sentences (found {n_sent})")
        elif n_sent != 3 and n_sent != 4:
            chk.warnings.append(f"{lang}: {n_sent} sentences (3 or 4 asked)")
        if len(text) > MAX_TEXT_CHARS:
            chk.errors.append(f"{lang}: too long ({len(text)} characters)")
        if best.name.casefold() not in text.casefold():
            chk.warnings.append(f"{lang}: the policy name '{best.name}' is not written as given")
    if _ADVICE_EN.search(out.en):
        chk.errors.append("en: do not give buying/switching/cancelling advice or promises; describe this scenario only")
    base = per_lang["en"]
    for lang in ("hi", "mr"):
        o = per_lang[lang]
        for label, a, b in (("amounts", base.amounts, o.amounts), ("percentages", base.percents, o.percents), ("day/month counts", base.units, o.units)):
            if a != b:
                chk.errors.append(f"{lang} vs en: {label} differ")
    return chk


# ------------------------------------------------------------------ fixed template (AI busy / off / rejected twice). Hindi and Marathi need a native check.
def _join(names: list[str], lang: str) -> str:
    word = {"en": "and", "hi": "और", "mr": "आणि"}[lang]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} {word} {names[-1]}"


def template_text(scenario: Scenario, policies: list[PolicyFacts], h: Highlights) -> dict[str, str]:
    by = {p.policy_id: p for p in policies}
    tied, best = [by[i] for i in h.tied_ids], by[h.best_policy_id]
    names = {lang: _join([p.name for p in tied], lang) for lang in LANGS}
    A = S.format_amount
    oop, bill, rent, d = A(best.estimated_out_of_pocket), A(scenario.bill), A(scenario.room_rent_per_day), scenario.days
    tie = len(tied) > 1
    s1 = {
        "en": f"In this scenario ({d} days, room rent {rent} per day, hospital bill {bill}), " +
              (f"{names['en']} have the same lowest estimated out-of-pocket cost: {oop}." if tie
               else f"{names['en']} has the lowest estimated out-of-pocket cost: {oop}."),
        "hi": f"इस स्थिति ({d} दिन, कमरे का किराया प्रति दिन {rent}, अस्पताल का बिल {bill}) में " +
              (f"{names['hi']} का अनुमानित अपनी जेब का खर्च बराबर और सबसे कम है: {oop}।" if tie
               else f"{names['hi']} का अनुमानित अपनी जेब का खर्च सबसे कम है: {oop}।"),
        "mr": f"या परिस्थितीत ({d} दिवस, खोली भाडे दररोज {rent}, रुग्णालयाचे बिल {bill}) " +
              (f"{names['mr']} यांचा अंदाजे स्वतःच्या खिशातून खर्च समान आणि सर्वात कमी आहे: {oop}." if tie
               else f"{names['mr']} चा अंदाजे स्वतःच्या खिशातून खर्च सर्वात कमी आहे: {oop}."),
    }
    parts = {lang: [s1[lang]] for lang in LANGS}
    if h.next_best_id:
        n = by[h.next_best_id]
        n_oop, gap = A(n.estimated_out_of_pocket), A(h.extra_out_of_pocket)
        parts["en"].append(f"Next is {n.name} at {n_oop}, which is {gap} more.")
        parts["hi"].append(f"इसके बाद {n.name} है, जिसका अनुमानित खर्च {n_oop} है, यानी {gap} ज़्यादा।")
        parts["mr"].append(f"त्यानंतर {n.name} आहे, ज्याचा अंदाजे खर्च {n_oop} आहे, म्हणजे {gap} जास्त.")
    cheap = by.get(h.lowest_premium_id) if h.lowest_premium_id else None
    if cheap and cheap.policy_id not in h.tied_ids:
        pr = A(cheap.premium)
        parts["en"].append(f"{cheap.name} has the lowest premium ({pr}) but costs more out of pocket in this scenario.")
        parts["hi"].append(f"{cheap.name} का प्रीमियम सबसे कम ({pr}) है, पर इस स्थिति में उसमें अपनी जेब से ज़्यादा खर्च होगा।")
        parts["mr"].append(f"{cheap.name} चा प्रीमियम सर्वात कमी ({pr}) आहे, पण या परिस्थितीत त्यात स्वतःच्या खिशातून जास्त खर्च येईल.")
    elif tie and cheap:
        pr = A(cheap.premium)
        parts["en"].append(f"{cheap.name} has the lowest premium ({pr}).")
        parts["hi"].append(f"इनमें {cheap.name} का प्रीमियम सबसे कम ({pr}) है।")
        parts["mr"].append(f"यांपैकी {cheap.name} चा प्रीमियम सर्वात कमी ({pr}) आहे.")
    return {lang: " ".join(parts[lang]) for lang in LANGS}


# ------------------------------------------------------------------ the call
async def _call(gemini, text, system, schema, temperature, model):
    return await gemini.generate_json(text, schema=schema, system=system, temperature=temperature, model=model, purpose="recommend")


async def _call_with_fallback(gemini, text, system, schema, temperature, model: str):
    try:
        return await _call(gemini, text, system, schema, temperature, model), model
    except GeminiBusy:
        if model == "fallback":
            raise
        log.warning("fast model busy; using the fallback model")
        return await _call(gemini, text, system, schema, temperature, "fallback"), "fallback"


def _from_template(scenario, policies, h, note: str) -> RecommendResult:
    t = template_text(scenario, policies, h)
    return RecommendResult(t["en"], t["hi"], t["mr"], h, "template", None, note)


async def recommend(scenario: Scenario, policies: list[PolicyFacts], gemini: GeminiClient) -> RecommendResult:
    """3-4 line comparison note in en/hi/mr. Raises RecommendInputError for bad input only; AI trouble gives the code-built template."""
    pols = prepare(scenario, policies)
    h = highlights(pols)
    if gemini.mock_mode:
        return _from_template(scenario, pols, h, "mock_mode")
    prompt = load_prompt(PROMPT_NAME)
    schema, temp = gemini_schema(RecommendationOutput), float(prompt.meta.get("temperature", 0.2))
    base = prompt.render_user(facts_json=facts_json(scenario, pols, h), glossary=glossary_block())
    model, note, last = "fast", "", "unknown"
    for _attempt in (1, 2):                                       # 2nd attempt = one retry with what was wrong
        try:
            res, model = await _call_with_fallback(gemini, base + note, prompt.system, schema, temp, model)
            out = RecommendationOutput.model_validate(res.data)
            chk = check_recommendation(out, scenario, pols, h)
            if chk.ok:
                if chk.warnings:
                    log.info("recommendation warnings: %s", chk.warnings)
                return RecommendResult(out.en.strip(), out.hi.strip(), out.mr.strip(), h, "ai", res.model)
            last, note = "checker", chk.retry_note()
            continue
        except GeminiBusy:
            log.warning("recommendation: AI busy, using the template")
            return _from_template(scenario, pols, h, "ai_busy")
        except GeminiBadOutput as e:
            last = e.message
        except ValidationError as e:
            last = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in
                             e.errors(include_url=False, include_context=False, include_input=False))[:400]
        note = f"\n\nYour previous answer was REJECTED: {last}\nReturn corrected JSON only."
    return _from_template(scenario, pols, h, f"rejected_{last}")
