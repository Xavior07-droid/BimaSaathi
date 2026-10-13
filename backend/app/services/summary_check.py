"""Number-consistency check for AI summaries (A17). Pure code, no LLM.

Rule (summary_v1 rule 4): numbers, dates and amounts come from the policy JSON only, written in ONE exact format
in all three languages:  dates `01 Apr 2025`, amounts `Rs 5,00,000`, percentages `10%`, waiting `30 days` / `30 दिन` / `30 दिवस`.

check_summary() verifies, for en / hi / mr and for every red flag:
  1. FORMAT   : no ₹/INR, no "lakh/crore" words, no Devanagari digits, canonical Rs grouping, canonical DD Mon YYYY dates,
                no translated month names, no months-converted-to-years.
  2. SOURCE   : every amount, date, percentage and day/month count exists in the policy data (nothing invented).
  3. REQUIRED : sum insured and start/end/renewal dates (when known) appear in every language.  (errors)
                premium, co-pay, waiting periods, room rent amount (when known) should appear.  (warnings)
  4. SAME     : the amounts, dates, percentages and day/month counts are IDENTICAL across en, hi and mr.
Errors mean "reject and regenerate"; warnings are logged only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.models.policy import PolicyExtraction, SummaryOutput

LANGS = ("en", "hi", "mr")
_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# ----------------------------------------------------------------- canonical formats (also used to build prompts/tests)
def format_inr(n: int) -> str:
    """Indian digit grouping with Western digits: 500000 -> '5,00,000'."""
    s = str(int(n))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    return re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head) + "," + tail


def format_amount(n: int) -> str:
    return f"Rs {format_inr(n)}"


def format_date(d: date) -> str:
    return f"{d.day:02d} {_MON[d.month - 1]} {d.year}"


# ----------------------------------------------------------------- token patterns
_AMOUNT = re.compile(r"(?:Rs\.?|INR)\s*(\d[\d,]*)")
_DATE_OK = re.compile(r"(?<!\d)(\d{1,2})\s+(" + "|".join(_MON) + r")\s+(\d{4})(?!\d)")
_DATE_NUMERIC = re.compile(r"(?<!\d)\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4}(?!\d)")
_DATE_LONG_EN = re.compile(r"(?<!\d)\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|June|July|August|"
                           r"September|Sept|October|November|December)\.?,?\s+\d{4}", re.I)
_DATE_NATIVE_MONTH = re.compile(
    r"(?<![\u0900-\u097F])(?:जनवरी|फरवरी|मार्च|अप्रैल|मई|जून|जुलाई|अगस्त|सितंबर|सितम्बर|अक्टूबर|नवंबर|नवम्बर|दिसंबर|दिसम्बर|"
    r"जानेवारी|फेब्रुवारी|एप्रिल|मे|जुलै|ऑगस्ट|सप्टेंबर|ऑक्टोबर|नोव्हेंबर|डिसेंबर)\s*,?\s*\d{4}")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_UNIT = {
    "en": re.compile(r"(\d+)\s*(days?|months?|years?)\b", re.I),
    "hi": re.compile(r"(\d+)\s*(दिन|महीने|महीना|महिने|साल|वर्ष)"),
    "mr": re.compile(r"(\d+)\s*(दिवसां?|दिवस|दिन|महिन्यां?|महिने|महिना|वर्षां?|वर्षे|वर्ष)"),
}
_UNIT_CLASS = {"day": ("day", "दिन", "दिवस"), "month": ("month", "महीन", "महिन"), "year": ("year", "साल", "वर्ष")}
_WORD_AMOUNT = re.compile(r"\b(?:lakhs?|lacs?|crores?)\b|लाख|करोड", re.I)
_DEV_DIGITS = re.compile(r"[०-९]")


def _unit_class(word: str) -> str:
    w = word.lower()
    for cls, stems in _UNIT_CLASS.items():
        if any(w.startswith(s) for s in stems):
            return cls
    return "?"


@dataclass
class Tokens:
    amounts: set[int] = field(default_factory=set)
    dates: set[date] = field(default_factory=set)
    percents: set[float] = field(default_factory=set)
    units: set[tuple[str, int]] = field(default_factory=set)       # ("day"|"month"|"year", n)
    format_errors: list[str] = field(default_factory=list)


def extract_tokens(text: str, lang: str) -> Tokens:
    t = Tokens()
    if "₹" in text:
        t.format_errors.append("uses the ₹ symbol; write amounts as 'Rs 5,00,000'")
    if _DEV_DIGITS.search(text):
        t.format_errors.append("uses Devanagari digits; use Western digits")
    if _WORD_AMOUNT.search(text):
        t.format_errors.append("writes an amount in words (lakh/crore); use digits like 'Rs 5,00,000'")

    for m in _AMOUNT.finditer(text):
        raw = m.group(0).rstrip(",").strip()
        num = int(m.group(1).rstrip(",").replace(",", ""))
        t.amounts.add(num)
        if raw != format_amount(num):
            t.format_errors.append(f"amount '{raw}' must be written '{format_amount(num)}'")

    for m in _DATE_OK.finditer(text):
        d_, mon, y = int(m.group(1)), m.group(2), int(m.group(3))
        try:
            d = date(y, _MON.index(mon) + 1, d_)
        except ValueError:
            t.format_errors.append(f"'{m.group(0)}' is not a real date")
            continue
        t.dates.add(d)
        if m.group(0) != format_date(d):
            t.format_errors.append(f"date '{m.group(0)}' must be written '{format_date(d)}'")
    for rx, why in ((_DATE_NUMERIC, "numeric date"), (_DATE_LONG_EN, "long-form date"),
                    (_DATE_NATIVE_MONTH, "translated month name")):
        for m in rx.finditer(text):
            t.format_errors.append(f"{why} '{m.group(0)}': write dates as 'DD Mon YYYY' (e.g. 01 Apr 2025)")

    t.percents = {float(m.group(1)) for m in _PERCENT.finditer(text)}
    for m in _UNIT[lang].finditer(text):
        t.units.add((_unit_class(m.group(2)), int(m.group(1))))
    return t


# ----------------------------------------------------------------- what the policy data allows
def _numbers_in(text: str) -> set[float]:
    return {float(x) for x in re.findall(r"\d+(?:\.\d+)?", re.sub(r"(?<=\d),(?=\d)", "", text))}


def allowed_numbers(p: PolicyExtraction) -> set[float]:
    """Numeric fields + numbers written inside the limit/benefit/exclusion/requirement TEXT. Not policy_no / dates / ids."""
    nums: set[float] = set()
    scalars = [p.sum_insured, p.premium, p.copay_percent, p.claim_requirements.intimation_deadline_hours,
               p.waiting_periods.initial_days, p.waiting_periods.pre_existing_months,
               p.waiting_periods.specific_diseases_months, p.room_rent_cap.value if p.room_rent_cap else None]
    nums |= {float(s) for s in scalars if s is not None}
    for sl in p.sub_limits:
        if sl.limit is not None:
            nums.add(float(sl.limit))
        nums |= _numbers_in(sl.item)
    texts = [c.text for c in p.covered] + [e.text for e in p.exclusions] + p.claim_requirements.cashless + p.claim_requirements.reimbursement
    for s in texts:
        nums |= _numbers_in(s)
    return nums


def _policy_dates(p: PolicyExtraction) -> set[date]:
    return {d for d in (p.start_date, p.end_date, p.renewal_date) if d}


# ----------------------------------------------------------------- result
@dataclass
class SummaryCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def retry_note(self, limit: int = 10) -> str:
        """Text to append to the summary prompt when regenerating (no document content, only the problems)."""
        lines = "\n".join(f"- {e}" for e in self.errors[:limit])
        return ("\n\nYour previous answer was REJECTED by the number checker:\n" + lines +
                "\nReturn corrected JSON only. Use the exact formats and ONLY numbers from the policy JSON.")


def _check_against_policy(label: str, tok: Tokens, p: PolicyExtraction, allowed: set[float], out: SummaryCheck) -> None:
    for e in tok.format_errors:
        out.errors.append(f"{label}: {e}")
    for a in sorted(tok.amounts):
        if float(a) not in allowed:
            out.errors.append(f"{label}: amount {format_amount(a)} is not in the policy data")
    for d in sorted(tok.dates):
        if d not in _policy_dates(p):
            out.errors.append(f"{label}: date {format_date(d)} is not in the policy data")
    for pc in sorted(tok.percents):
        if pc not in allowed:
            out.errors.append(f"{label}: percentage {pc:g}% is not in the policy data")
    wp = p.waiting_periods
    month_vals = {v for v in (wp.pre_existing_months, wp.specific_diseases_months) if v is not None}
    for cls, n in sorted(tok.units):
        if cls == "year":
            if n * 12 in month_vals:
                out.errors.append(f"{label}: {n} years is a conversion of {n * 12} months; give months as in the data")
            else:
                out.errors.append(f"{label}: '{n} years' is not in the policy data")
        elif float(n) not in allowed:
            out.errors.append(f"{label}: {n} {cls}s is not in the policy data")


def check_summary(policy: PolicyExtraction, summary: SummaryOutput, page_count: int | None = None) -> SummaryCheck:
    out = SummaryCheck()
    allowed = allowed_numbers(policy)
    per_lang: dict[str, Tokens] = {}

    for lang in LANGS:
        text = getattr(summary.plain_summary, lang)
        tok = per_lang[lang] = extract_tokens(text, lang)
        _check_against_policy(f"summary.{lang}", tok, policy, allowed, out)

        for name, d in (("start_date", policy.start_date), ("end_date", policy.end_date), ("renewal_date", policy.renewal_date)):
            if d and d not in tok.dates:
                out.errors.append(f"summary.{lang}: {name} {format_date(d)} is missing")
        if policy.sum_insured is not None and policy.sum_insured not in tok.amounts:
            out.errors.append(f"summary.{lang}: sum insured {format_amount(policy.sum_insured)} is missing")
        if policy.premium is not None and policy.premium not in tok.amounts:
            out.warnings.append(f"summary.{lang}: premium {format_amount(policy.premium)} is missing")
        if policy.copay_percent and float(policy.copay_percent) not in tok.percents:
            out.warnings.append(f"summary.{lang}: co-pay {policy.copay_percent:g}% is missing")
        if policy.room_rent_cap and policy.room_rent_cap.unit == "per_day" and int(policy.room_rent_cap.value) not in tok.amounts:
            out.warnings.append(f"summary.{lang}: room rent cap {format_amount(int(policy.room_rent_cap.value))} is missing")
        wp = policy.waiting_periods
        for cls, v in (("day", wp.initial_days), ("month", wp.pre_existing_months), ("month", wp.specific_diseases_months)):
            if v is not None and (cls, v) not in tok.units:
                out.warnings.append(f"summary.{lang}: waiting period of {v} {cls}s is missing")

    # same facts in every language
    base = per_lang["en"]
    for lang in ("hi", "mr"):
        other = per_lang[lang]
        for label, a, b in (("amounts", base.amounts, other.amounts), ("dates", base.dates, other.dates),
                            ("percentages", base.percents, other.percents), ("day/month counts", base.units, other.units)):
            if a != b:
                fmt = (lambda s: ", ".join(sorted(map(str, s)))) if label != "dates" else (lambda s: ", ".join(sorted(format_date(x) for x in s)))
                if label == "amounts":
                    fmt = lambda s: ", ".join(format_amount(x) for x in sorted(s))
                out.errors.append(f"summary.{lang} vs en: {label} differ (en: {fmt(a) or 'none'}; {lang}: {fmt(b) or 'none'})")

    # red flags: only values that exist in the policy data (summary_v1 rule 4)
    for i, rf in enumerate(summary.red_flags, start=1):
        tok = extract_tokens(f"{rf.title}. {rf.why_it_matters}", "en")
        _check_against_policy(f"red_flags[{i}]", tok, policy, allowed, out)
        if page_count is not None and not 1 <= rf.source.page <= page_count:
            out.errors.append(f"red_flags[{i}]: source page {rf.source.page} is outside the document (1-{page_count})")
    return out


def check_text(policy: PolicyExtraction, text: str, lang: str, label: str = "text") -> SummaryCheck:
    """Same number rules for any single piece of AI text (used by /ask): amounts, dates, percentages and
    day/month counts must exist in the policy data. Format problems are reported too; callers decide what to enforce."""
    out = SummaryCheck()
    _check_against_policy(label, extract_tokens(text, lang), policy, allowed_numbers(policy), out)
    return out
