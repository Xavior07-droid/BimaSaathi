"""Suggested questions for the Ask screen (A20): 3 chips, chosen by CODE, no Gemini call (zero quota).

The rule that shapes everything: Ask only shows an answer when it can cite a source, and only covered / exclusions /
sub_limits / red_flags items carry one (waiting periods, room cap, co-pay, dates and document lists do not). A chip the
policy cannot cite would just end in "your policy is not clear on this", so a topic is offered only when
  1. the policy actually has the fact (e.g. a room-rent cap exists), AND
  2. a citable item talks about it (e.g. a red flag mentions room rent), or the topic IS a citable list (exclusions...).
Sum insured, premium and dates are never offered: the Policy Card shows them, and Ask cannot cite them.

Chips are fixed templates, never text copied from the document (a document must not be able to put words on a button).
Stable per policy: the same policy always gets the same chips. Fewer than 3 is returned rather than padding with
questions the policy cannot answer. Hindi and Marathi wording uses the glossary's terms (so tap-to-explain still
works once the question is in the chat) but needs a native-speaker check, like the other fixed texts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from app.models.policy import PolicyBrain

MAX_SUGGESTIONS = 3
LANGS = ("en", "hi", "mr")


@dataclass(frozen=True)
class Topic:
    id: str
    group: str                                           # one chip per group first, so the 3 chips cover different ground
    text: dict[str, str]
    available: Callable[[PolicyBrain, str], bool]        # (brain, lowercase text of all citable items)


def _has(pattern: str) -> Callable[[str], bool]:
    rx = re.compile(pattern, re.IGNORECASE)
    return lambda corpus: rx.search(corpus) is not None


# words a citable item would use for each subject (English + the Hindi/Marathi words a bilingual policy would carry)
_WAIT = _has(r"wait|प्रतीक्षा|इंतज|वेटिंग")
_EXISTING = _has(r"existing|पहले से|आधीपासून|पूर्वीपासून")
# "room" alone is NOT enough: covered items say "room, boarding, nursing" without stating any cap
_ROOM = _has(r"\brent\b|room[\s-]*(?:rent|charges?|cap|limit)|किराय|भाड")
_COPAY = _has(r"co-?\s?pay|को-?\s?पे|you pay|pay(?:s)? \d+(?:\.\d+)?\s?%")
_CASHLESS = _has(r"cashless|कैशलेस|कॅशलेस")
_INTIMATE = _has(r"intimat|notif|\binform\b|tell the insurer|insurer within|सूचित|सूचना|कळव|बताना|बताएं")


def _corpus(b: PolicyBrain) -> str:
    """Text of every item that can be cited (the same four lists Ask accepts citations from)."""
    parts = [*(c.text for c in b.covered), *(e.text for e in b.exclusions), *(s.item for s in b.sub_limits),
             *(f"{r.title} {r.why_it_matters}" for r in b.red_flags)]
    return " ".join(parts).casefold()


def _wp(b: PolicyBrain):
    return b.waiting_periods


TOPICS: tuple[Topic, ...] = (
    Topic("not_covered", "coverage", {
        "en": "What is not covered by my policy?",
        "hi": "मेरी पॉलिसी में किन चीज़ों का खर्च नहीं मिलेगा?",
        "mr": "माझ्या पॉलिसीमध्ये कोणत्या गोष्टींचा खर्च मिळणार नाही?"},
        lambda b, c: bool(b.exclusions)),
    Topic("covered", "coverage", {
        "en": "What does my policy cover?",
        "hi": "मेरी पॉलिसी में किन चीज़ों का खर्च मिलता है?",
        "mr": "माझ्या पॉलिसीमध्ये कोणत्या गोष्टींचा खर्च मिळतो?"},
        lambda b, c: bool(b.covered)),
    Topic("waiting_pre_existing", "waiting", {
        "en": "How long must I wait before I can claim for an illness I already have?",
        "hi": "जो बीमारी मुझे पहले से है, उसके क्लेम के लिए कितना वेटिंग पीरियड है?",
        "mr": "मला आधीपासून असलेल्या आजाराच्या क्लेमसाठी किती वेटिंग पीरियड आहे?"},
        lambda b, c: _wp(b).pre_existing_months is not None and _WAIT(c) and _EXISTING(c)),
    Topic("waiting_general", "waiting", {
        "en": "Is there a waiting period before I can make a claim?",
        "hi": "क्लेम करने से पहले कोई वेटिंग पीरियड है क्या?",
        "mr": "क्लेम करण्यापूर्वी काही वेटिंग पीरियड आहे का?"},
        lambda b, c: (_wp(b).initial_days is not None or _wp(b).specific_diseases_months is not None) and _WAIT(c)),
    Topic("room_rent", "money", {
        "en": "Is there a limit on the hospital room rent I can choose?",
        "hi": "अस्पताल के कमरे के किराये की कोई सीमा है क्या?",
        "mr": "रुग्णालयातील खोलीच्या भाड्यावर काही मर्यादा आहे का?"},
        lambda b, c: b.room_rent_cap is not None and _ROOM(c)),
    Topic("copay", "money", {
        "en": "Do I have to pay part of the hospital bill myself?",
        "hi": "क्या अस्पताल के बिल का कुछ हिस्सा मुझे खुद देना होगा (को-पे)?",
        "mr": "रुग्णालयाच्या बिलाचा काही भाग मला स्वतः भरावा लागेल का (को-पे)?"},
        lambda b, c: b.copay_percent is not None and _COPAY(c)),
    Topic("sub_limits", "money", {
        "en": "Are there limits on how much is paid for specific treatments?",
        "hi": "कुछ इलाजों के लिए भुगतान की अलग सब-लिमिट है क्या?",
        "mr": "काही उपचारांसाठी देय रकमेवर वेगळी सब-लिमिट आहे का?"},
        lambda b, c: bool(b.sub_limits)),
    Topic("cashless", "claim", {
        "en": "How do I get cashless treatment?",
        "hi": "कैशलेस इलाज कैसे मिलेगा?",
        "mr": "कॅशलेस उपचार कसे मिळतील?"},
        lambda b, c: bool(b.claim_requirements.cashless) and _CASHLESS(c)),
    Topic("intimation", "claim", {
        "en": "How soon must I inform the insurer if I am admitted to hospital?",
        "hi": "अस्पताल में भर्ती होने पर बीमा कंपनी को कितनी जल्दी सूचना देनी होगी?",
        "mr": "रुग्णालयात दाखल झाल्यावर विमा कंपनीला किती लवकर सूचना द्यावी लागेल?"},
        lambda b, c: b.claim_requirements.intimation_deadline_hours is not None and _INTIMATE(c)),
)
GROUP_ORDER = ("coverage", "waiting", "money", "claim")          # what a worried reader most wants first


def suggest(brain: PolicyBrain, lang: str) -> list[dict]:
    """Up to 3 `{id, text}` chips in `lang`, stable for a given policy."""
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {LANGS}")
    corpus = _corpus(brain)
    avail = [t for t in TOPICS if t.available(brain, corpus)]
    chosen: list[Topic] = []
    for g in GROUP_ORDER:                                         # pass 1: best topic of each group
        first = next((t for t in avail if t.group == g), None)
        if first:
            chosen.append(first)
    if len(chosen) < MAX_SUGGESTIONS:                             # pass 2: more from the same groups, same priority
        chosen += [t for t in avail if t not in chosen][:MAX_SUGGESTIONS - len(chosen)]
    return [{"id": t.id, "text": t.text[lang]} for t in chosen[:MAX_SUGGESTIONS]]
