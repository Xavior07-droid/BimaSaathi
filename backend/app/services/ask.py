"""Grounded Q&A (A19). The model proposes; CODE decides what the user sees.

    question -> sanitise -> Gemini (ask_v1, policy JSON only) -> validate AskOutput
             -> verify every citation exists in THIS policy -> verify every number exists in THIS policy
             -> grounded answer + citations   OR   the fixed "policy is not clear" fallback in the chosen language

Spec rules enforced here: fixed fallback when grounded=false or no valid citation; disclaimer on every response;
no invented numbers; never exposes text the model wrote for an ungrounded answer.
Privacy: holder_name and policy_no are NOT sent to Gemini (not needed to answer, and the free tier may use inputs).
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from pydantic import ValidationError

from app.models.policy import AskOutput, PolicyBrain, Source
from app.models.schema_export import gemini_schema
from app.prompts import load_prompt
from app.services import summary_check as S
from app.services.gemini import GeminiBadOutput, GeminiBusy, GeminiClient
from app.services.glossary import glossary_block

log = logging.getLogger("bimasaathi.ask")

LANGS = ("en", "hi", "mr")
MAX_QUESTION_CHARS = 500
MAX_CITATIONS = 3
PROMPT_NAME = "ask_v1"

# Fixed texts (spec 5.2). Hindi and Marathi wording needs a native-speaker check before release.
FALLBACK = {
    "en": "Your policy is not clear on this. Please confirm with your insurer.",
    "hi": "आपकी पॉलिसी में इस बारे में साफ़ जानकारी नहीं है। कृपया अपनी बीमा कंपनी से पूछकर पक्का कर लें।",
    "mr": "तुमच्या पॉलिसीमध्ये याबद्दल स्पष्ट माहिती नाही. कृपया तुमच्या विमा कंपनीकडून खात्री करून घ्या.",
}
DISCLAIMER = {
    "en": "This is general information from your policy document, not medical or legal advice, and not a promise that a claim will be paid. Confirm important decisions with your insurer.",
    "hi": "यह आपके पॉलिसी दस्तावेज़ से मिली सामान्य जानकारी है। यह चिकित्सा या कानूनी सलाह नहीं है और क्लेम पास होने का वादा भी नहीं है। ज़रूरी फ़ैसलों से पहले अपनी बीमा कंपनी से पुष्टि करें।",
    "mr": "ही तुमच्या पॉलिसी दस्तावेजातील सर्वसाधारण माहिती आहे. ही वैद्यकीय किंवा कायदेशीर सल्ला नाही आणि क्लेम मंजूर होईल याची हमी नाही. महत्त्वाच्या निर्णयांपूर्वी तुमच्या विमा कंपनीकडे खात्री करा.",
}


class QuestionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class AskResult:
    answer: str
    citations: list[Source]
    grounded: bool
    lang: str
    reason: str | None = None          # why it fell back (logs / tests only; not sent to the client)
    model: str | None = None

    def to_dict(self) -> dict:
        return {"answer": self.answer, "citations": [c.model_dump() for c in self.citations], "grounded": self.grounded,
                "fallback": not self.grounded, "lang": self.lang, "disclaimer": DISCLAIMER[self.lang]}


# ------------------------------------------------------------------ input
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def clean_question(q: object) -> str:
    """Plain text only: no control/bidi characters, no angle brackets (cannot close our <question> tag), no {{ }}."""
    if not isinstance(q, str):
        raise QuestionError("invalid_question", "Please type your question.")
    q = _CTRL.sub(" ", q).replace("<", " ").replace(">", " ").replace("{{", " ").replace("}}", " ")
    q = re.sub(r"\s+", " ", q).strip()
    if not q:
        raise QuestionError("invalid_question", "Please type your question.")
    if len(q) > MAX_QUESTION_CHARS:
        raise QuestionError("question_too_long", f"Please keep your question under {MAX_QUESTION_CHARS} characters.")
    return q


def check_lang(lang: object) -> str:
    if lang not in LANGS:
        raise QuestionError("invalid_language", "Language must be en, hi or mr.")
    return lang  # type: ignore[return-value]


# ------------------------------------------------------------------ context + citations
def policy_context(brain: PolicyBrain) -> str:
    """Facts only. No AI summary (not a source), no ids/meta, and no personal identifiers."""
    data = brain.model_dump(mode="json", exclude={"plain_summary", "extraction_meta", "policy_id", "holder_name", "policy_no"})
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


_CLAUSE_PREFIX = re.compile(r"^(?:clause|cl\.?|section|sec\.?|§)\s*", re.IGNORECASE)


def _norm_clause(c: str) -> str:
    return _CLAUSE_PREFIX.sub("", c.strip()).casefold().rstrip(".")


def valid_sources(brain: PolicyBrain) -> dict[tuple[int, str], Source]:
    """Every (page, clause) the policy itself carries, keyed normalised; value = the policy's own spelling."""
    out: dict[tuple[int, str], Source] = {}
    for it in [*brain.covered, *brain.exclusions, *brain.sub_limits, *brain.red_flags]:
        out.setdefault((it.source.page, _norm_clause(it.source.clause)), it.source)
    return out


def verified_citations(brain: PolicyBrain, cited: list[Source]) -> tuple[list[Source], int]:
    known, ok, dropped = valid_sources(brain), [], 0
    for c in cited:
        real = known.get((c.page, _norm_clause(c.clause)))
        if real is None:
            dropped += 1
        elif real not in ok:
            ok.append(real)
    return ok[:MAX_CITATIONS], dropped


# ------------------------------------------------------------------ the call
def _fallback(lang: str, reason: str, model: str | None = None) -> AskResult:
    log.info("ask fallback reason=%s", reason)
    return AskResult(answer=FALLBACK[lang], citations=[], grounded=False, lang=lang, reason=reason, model=model)


async def _ask_model(gemini, text: str, system: str, schema: dict, temperature: float, model: str):
    return await gemini.generate_json(text, schema=schema, system=system, temperature=temperature, model=model, purpose="ask")


async def _ask_with_fallback(gemini, text, system, schema, temperature, model: str):
    """Fast model; if it is overloaded, the Flash-Lite model once. Returns (result, model_used)."""
    try:
        return await _ask_model(gemini, text, system, schema, temperature, model), model
    except GeminiBusy:
        if model == "fallback":
            raise
        log.warning("fast model busy; asking the fallback model")
        return await _ask_model(gemini, text, system, schema, temperature, "fallback"), "fallback"


async def answer_question(brain: PolicyBrain, question: str, lang: str, gemini: GeminiClient) -> AskResult:
    q, lang = clean_question(question), check_lang(lang)
    if gemini.mock_mode:
        out, model = _mock_output(brain, q, lang), "mock"
    else:
        out, model = await _call_gemini(brain, q, lang, gemini)
        if out is None:
            return _fallback(lang, "bad_output", model)
    return finalize(brain, out, lang, model)


async def _call_gemini(brain, q, lang, gemini) -> tuple[AskOutput | None, str]:
    prompt = load_prompt(PROMPT_NAME)
    schema, temp = gemini_schema(AskOutput), float(prompt.meta.get("temperature", 0.1))
    base = prompt.render_user(lang=lang, policy_json=policy_context(brain),
                              glossary=glossary_block() if lang != "en" else "", question=q)   # question last
    model, note = "fast", ""
    for _attempt in (1, 2):                                  # 2nd attempt = one retry with the validation error
        try:
            res, model = await _ask_with_fallback(gemini, base + note, prompt.system, schema, temp, model)
            return AskOutput.model_validate(res.data), res.model
        except GeminiBadOutput as e:
            last = e.message
        except ValidationError as e:
            last = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in
                             e.errors(include_url=False, include_context=False, include_input=False))[:400]
        note = f"\n\nYour previous answer was REJECTED: {last}\nReturn corrected JSON only."
    return None, model


def finalize(brain: PolicyBrain, out: AskOutput, lang: str, model: str | None) -> AskResult:
    """All the 'code decides' rules, in one place."""
    if not out.grounded:
        return _fallback(lang, "model_not_grounded", model)             # whatever text the model wrote is discarded
    answer = out.answer.strip()
    if not answer:
        return _fallback(lang, "empty_answer", model)
    cites, dropped = verified_citations(brain, out.citations)
    if dropped:
        log.warning("ask dropped %d citation(s) not present in the policy", dropped)
    if not cites:
        return _fallback(lang, "no_valid_citation", model)
    problems = [e for e in S.check_text(brain, answer, lang, "answer").errors
                if "not in the policy data" in e or "conversion of" in e]
    if problems:
        log.warning("ask answer used numbers not in the policy: %s", problems)
        return _fallback(lang, "invented_number", model)
    return AskResult(answer=answer, citations=cites, grounded=True, lang=lang, model=model)


# ------------------------------------------------------------------ MOCK mode (no GEMINI_API_KEY): canned answers for the sample policy
_MOCK = [
    (("cataract", "मोतियाबिंद", "मोतीबिंदू"), [(2, "1.4"), (3, "3.3")], {
        "en": "Yes, cataract treatment is covered as a day care procedure, up to {cat} per eye.",
        "hi": "हाँ, मोतियाबिंद का इलाज डे-केयर प्रक्रिया के रूप में कवर है, हर आँख के लिए {cat} तक।",
        "mr": "होय, मोतीबिंदूचा उपचार डे-केअर प्रक्रिया म्हणून कव्हर आहे, प्रत्येक डोळ्यासाठी {cat} पर्यंत."}),
    (("dental", "tooth", "teeth", "दांत", "दाँत", "दंत"), [(4, "4.2")], {
        "en": "No. This policy does not pay for dental treatment unless it is needed because of an accident.",
        "hi": "नहीं। यह पॉलिसी दाँतों के इलाज का खर्च नहीं देती, जब तक वह किसी दुर्घटना की वजह से ज़रूरी न हो।",
        "mr": "नाही. अपघातामुळे आवश्यक झाल्याखेरीज ही पॉलिसी दंत उपचारांचा खर्च देत नाही."}),
    (("co-pay", "copay", "co pay", "को-पे", "को पे", "कोपे"), [(3, "3.2")], {
        "en": "You pay {copay} of every claim yourself; the insurer pays the rest.",
        "hi": "आपको हर क्लेम का {copay} खुद देना होता है; बाकी रकम बीमा कंपनी देती है।",
        "mr": "तुम्हाला प्रत्येक क्लेमचे {copay} स्वतः भरावे लागतात; उरलेली रक्कम विमा कंपनी देते."}),
    (("room",  "कमरे", "कमरा", "खोली"), [(3, "3.1")], {
        "en": "Room rent is capped at {rent} per day. A costlier room can also reduce other charges in the same proportion.",
        "hi": "कमरे का किराया प्रति दिन {rent} तक सीमित है। महंगा कमरा लेने पर दूसरे खर्च भी उसी अनुपात में कम हो सकते हैं।",
        "mr": "खोली भाडे दररोज {rent} पर्यंत मर्यादित आहे. महागडी खोली घेतल्यास इतर खर्चही त्याच प्रमाणात कमी होऊ शकतात."}),
]


def _mock_output(brain: PolicyBrain, q: str, lang: str) -> AskOutput:
    low = q.casefold()
    cat = next((s.limit for s in brain.sub_limits if "cataract" in s.item.casefold() and s.limit), None)
    for words, cites, texts in _MOCK:
        if any(w in low for w in words):
            vals = {"cat": S.format_amount(cat) if cat else "", "copay": f"{brain.copay_percent:g}%" if brain.copay_percent else "",
                    "rent": S.format_amount(int(brain.room_rent_cap.value)) if brain.room_rent_cap and brain.room_rent_cap.unit == "per_day" else ""}
            needed = [k for k in vals if "{" + k + "}" in texts["en"]]
            if any(not vals[k] for k in needed):
                break                                            # this policy lacks the number: say "unclear" instead of guessing
            return AskOutput(answer=texts[lang].format(**vals), citations=[Source(page=p, clause=c) for p, c in cites], grounded=True)
    return AskOutput(answer="", citations=[], grounded=False)


# ------------------------------------------------------------------ per-user throttle (the Gemini free tier is ~10 requests/minute for everyone)
class QuestionLimiter:
    def __init__(self, per_minute: int = 6, clock: Callable[[], float] = time.monotonic):
        self.per_minute, self._clock = per_minute, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, uid: str) -> int:
        """0 = allowed (and counted); otherwise seconds to wait."""
        now, q = self._clock(), self._hits[uid]
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return max(1, int(60 - (now - q[0])) + 1)
        q.append(now)
        return 0
