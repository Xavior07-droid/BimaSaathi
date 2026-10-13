"""Policy Brain schema (A2). Language-neutral facts live in PolicyExtraction;
summaries/red flags are added by the second Gemini call; policy_id and
extraction_meta are set by CODE, never by the LLM.

Rules enforced here:
- unknown = None (never guess)
- every covered / exclusion / sub-limit / red-flag item carries Source(page, clause)
- numbers are INR integers, dates are ISO dates
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = "1.0"

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Rupees = Annotated[int, Field(ge=0)]


class _Strict(BaseModel):
    # forbid extras so schema drift from the LLM fails validation (triggers A9's retry)
    model_config = ConfigDict(extra="forbid")


class Source(_Strict):
    page: int = Field(ge=1, description="1-based page number from the [Page N] marker")
    clause: NonEmpty = Field(description="Clause / section number or heading, e.g. '4.2' or 'Exclusions'")


class WaitingPeriods(_Strict):
    initial_days: int | None = Field(None, ge=0)
    pre_existing_months: int | None = Field(None, ge=0)
    specific_diseases_months: int | None = Field(None, ge=0)


class RoomRentCap(_Strict):
    value: float = Field(ge=0)
    unit: Literal["per_day", "percent_of_sum_insured"]


class SubLimit(_Strict):
    item: NonEmpty
    limit: Rupees | None = None
    source: Source


class CoveredItem(_Strict):
    text: NonEmpty
    source: Source


class ExclusionItem(_Strict):
    text: NonEmpty
    source: Source


class ClaimRequirements(_Strict):
    cashless: list[NonEmpty] = Field(default_factory=list)
    reimbursement: list[NonEmpty] = Field(default_factory=list)
    intimation_deadline_hours: int | None = Field(None, ge=0)


class RedFlag(_Strict):
    title: NonEmpty
    why_it_matters: NonEmpty
    source: Source


class PlainSummary(_Strict):
    en: NonEmpty
    hi: NonEmpty
    mr: NonEmpty


class ExtractionMeta(_Strict):
    model: NonEmpty
    confidence: float | None = Field(None, ge=0, le=1)
    file_hash: NonEmpty = Field(description="sha256 hex of the uploaded bytes")
    created_at: datetime
    schema_version: str = SCHEMA_VERSION


class PolicyExtraction(_Strict):
    """What the FIRST Gemini call returns (facts only, no translations)."""

    insurer: str | None = None
    policy_no: str | None = None
    policy_type: Literal["health", "motor", "life"] | None = None
    holder_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    renewal_date: date | None = None
    sum_insured: Rupees | None = None
    premium: Rupees | None = None
    waiting_periods: WaitingPeriods = Field(default_factory=WaitingPeriods)
    room_rent_cap: RoomRentCap | None = None
    copay_percent: float | None = Field(None, ge=0, le=100)
    sub_limits: list[SubLimit] = Field(default_factory=list)
    covered: list[CoveredItem] = Field(default_factory=list)
    exclusions: list[ExclusionItem] = Field(default_factory=list)
    claim_requirements: ClaimRequirements = Field(default_factory=ClaimRequirements)

    @model_validator(mode="after")
    def _dates_make_sense(self) -> "PolicyExtraction":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        return self


class SummaryOutput(_Strict):
    """What the SECOND Gemini call returns."""

    plain_summary: PlainSummary
    red_flags: list[RedFlag] = Field(default_factory=list)


class PolicyBrain(PolicyExtraction):
    """Full stored document (Firestore policies/{policy_id})."""

    policy_id: NonEmpty
    plain_summary: PlainSummary | None = None  # None until the summary call succeeds
    red_flags: list[RedFlag] = Field(default_factory=list)
    extraction_meta: ExtractionMeta

    def to_store(self) -> dict[str, Any]:
        """JSON-safe dict (ISO dates/datetimes) for Firestore / API responses."""
        return self.model_dump(mode="json")

    @classmethod
    def from_parts(cls, *, policy_id: str, extraction: PolicyExtraction,
                   meta: ExtractionMeta, summary: SummaryOutput | None = None) -> "PolicyBrain":
        data = extraction.model_dump()
        if summary is not None:
            data["plain_summary"] = summary.plain_summary.model_dump()
            data["red_flags"] = [r.model_dump() for r in summary.red_flags]
        return cls(policy_id=policy_id, extraction_meta=meta, **data)


class AskOutput(_Strict):
    """What the Ask call returns (A18/A19). Code, not the model, decides what the user finally sees:
    grounded=False or no (valid) citation -> the fixed 'policy is not clear' fallback in the chosen language."""

    answer: str = Field(description="Plain-language answer in the requested language; empty string when grounded is false")
    citations: list[Source] = Field(default_factory=list,
                                    description="page + clause copied from source objects in the policy JSON; empty when grounded is false")
    grounded: bool = Field(description="true only if the policy JSON states the answer AND at least one source is cited")


class ExclusionMatchOutput(_Strict):
    """What the exclusion-match call returns (A22). Code validates the indexes and builds the citations."""

    verdict: Literal["match", "possible", "no_match"] = Field(
        description="match = clearly inside an exclusion; possible = might apply, depends on facts not given; "
                    "no_match = no listed exclusion applies (this does NOT mean covered)")
    matched: list[int] = Field(default_factory=list,
                               description="0-based indexes from the numbered exclusion list, most specific first, at most 3; empty for no_match")
    reason: str = Field(description="One short English sentence naming the exclusion by its wording and why it applies; empty string for no_match")


DocType = Literal["claim_form", "discharge_summary", "hospital_bill", "pharmacy_bill", "investigation_report", "prescription",
                  "doctor_note", "id_proof", "insurance_card", "cancelled_cheque", "police_report", "other", "unreadable"]
DocQuality = Literal["good", "fair", "poor"]
DocIssue = Literal["blurry", "too_dark", "glare", "cut_off", "rotated", "handwriting_hard_to_read", "partial_page",
                   "low_resolution", "unreadable"]
DateLabel = Literal["admission", "discharge", "bill", "report", "prescription", "other"]


class DocDate(_Strict):
    label: DateLabel
    date: date


class DocumentClassification(_Strict):
    """What the document-classify call returns (A23): facts read off ONE claim-document image. R's checker compares them in code."""

    doc_type: DocType = Field(description="what kind of document this is; unreadable if you cannot tell")
    patient_name: str | None = Field(None, description="the patient's name in English letters, or null if not shown")
    dates: list[DocDate] = Field(default_factory=list, description="dates printed on the document, ISO format, each with a label")
    has_stamp: bool = Field(description="true only if a hospital/doctor/pharmacy stamp or seal is visible")
    has_signature: bool = Field(description="true only if a handwritten signature is visible")
    quality: DocQuality = Field(description="good = all text readable; fair = key fields readable; poor = key fields hard to read")
    issues: list[DocIssue] = Field(default_factory=list, description="problems that make this image hard to use")


class RecommendationOutput(_Strict):
    """What the compare-recommendation call returns (A24): the same 3-4 sentences in three languages. Numbers come from the input facts."""

    en: NonEmpty
    hi: NonEmpty
    mr: NonEmpty


class ReasonItem(_Strict):
    id: NonEmpty = Field(description="the id of the input reason this text rewords, copied exactly")
    text: NonEmpty = Field(description="the reworded reason: same facts, simple neutral words, 1-2 short sentences")


class FraudReasonOutput(_Strict):
    """What the review-reason rewording call returns (A25). Reasons are produced by rules in code; this only rewords them."""

    reasons: list[ReasonItem]

