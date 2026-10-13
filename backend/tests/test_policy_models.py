import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import schema_export
from app.models.policy import (ExtractionMeta, PolicyBrain, PolicyExtraction, SummaryOutput)

SRC = {"page": 3, "clause": "4.2"}


def extraction_dict(**over):
    d = {
        "insurer": "Test Insurer", "policy_no": "P-1", "policy_type": "health",
        "holder_name": "Asha Patil", "start_date": "2025-04-01", "end_date": "2026-03-31",
        "renewal_date": "2026-04-01", "sum_insured": 500000, "premium": 12000,
        "waiting_periods": {"initial_days": 30, "pre_existing_months": 36, "specific_diseases_months": 24},
        "room_rent_cap": {"value": 5000, "unit": "per_day"}, "copay_percent": 10,
        "sub_limits": [{"item": "Cataract", "limit": 40000, "source": SRC}],
        "covered": [{"text": "Hospitalisation", "source": SRC}],
        "exclusions": [{"text": "Cosmetic surgery", "source": {"page": 9, "clause": "Excl 3"}}],
        "claim_requirements": {"cashless": ["ID"], "reimbursement": ["Bills"], "intimation_deadline_hours": 48},
    }
    d.update(over)
    return d


def meta():
    return ExtractionMeta(model="m", confidence=0.9, file_hash="ab" * 32,
                          created_at=datetime(2026, 10, 13, tzinfo=timezone.utc))


def test_valid_extraction_roundtrip():
    e = PolicyExtraction.model_validate(extraction_dict())
    assert e.sum_insured == 500000 and e.start_date.isoformat() == "2025-04-01"


def test_unknowns_are_null_not_guessed():
    e = PolicyExtraction.model_validate({})
    assert e.sum_insured is None and e.room_rent_cap is None and e.copay_percent is None
    assert e.waiting_periods.initial_days is None and e.covered == []


@pytest.mark.parametrize("bad", [
    {"covered": [{"text": "x", "source": {"page": 0, "clause": "1"}}]},   # page must be >= 1
    {"covered": [{"text": "x", "source": {"page": 1, "clause": "  "}}]},  # clause required
    {"covered": [{"text": "x"}]},                                          # source required
    {"exclusions": [{"text": "x"}]},
    {"sub_limits": [{"item": "x", "limit": 1}]},
    {"copay_percent": 150}, {"sum_insured": -5}, {"policy_type": "pet"},
    {"room_rent_cap": {"value": 1, "unit": "per_week"}},
    {"unexpected_field": 1},
    {"start_date": "2026-01-01", "end_date": "2025-01-01"},
    {"start_date": "01/04/2025"},
])
def test_invalid_rejected(bad):
    with pytest.raises(ValidationError):
        PolicyExtraction.model_validate(extraction_dict(**bad))


def test_red_flag_requires_source():
    with pytest.raises(ValidationError):
        SummaryOutput.model_validate({
            "plain_summary": {"en": "a", "hi": "b", "mr": "c"},
            "red_flags": [{"title": "t", "why_it_matters": "w"}]})


def test_summary_needs_all_three_languages():
    with pytest.raises(ValidationError):
        SummaryOutput.model_validate({"plain_summary": {"en": "a", "hi": "b"}})


def test_from_parts_and_to_store_is_json_safe():
    e = PolicyExtraction.model_validate(extraction_dict())
    s = SummaryOutput.model_validate({
        "plain_summary": {"en": "a", "hi": "ब", "mr": "क"},
        "red_flags": [{"title": "Co-pay", "why_it_matters": "You pay 10%", "source": SRC}]})
    pb = PolicyBrain.from_parts(policy_id="p1", extraction=e, meta=meta(), summary=s)
    doc = pb.to_store()
    json.dumps(doc)  # must not raise (no date objects left)
    assert doc["start_date"] == "2025-04-01"
    assert doc["extraction_meta"]["created_at"].startswith("2026-10-13")
    assert PolicyBrain.model_validate(doc) == pb  # stored doc re-validates


def test_brain_without_summary_is_allowed():
    pb = PolicyBrain.from_parts(policy_id="p1", extraction=PolicyExtraction(), meta=meta())
    assert pb.plain_summary is None and pb.red_flags == []


def test_empty_policy_id_rejected():
    with pytest.raises(ValidationError):
        PolicyBrain(policy_id="", extraction_meta=meta())


def test_committed_schema_files_are_current():
    """Fails if someone edits models/policy.py without re-running schema_export."""
    for name, model in schema_export.MODELS.items():
        committed = json.loads((schema_export.OUT_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert committed == json.loads(json.dumps(model.model_json_schema())), \
            f"{name}.schema.json is stale: run `python -m app.models.schema_export`"


@pytest.mark.parametrize("name", ["policy_extraction", "summary_output"])
def test_gemini_schema_is_flat_and_sdk_valid(name):
    from google.genai import types
    schema = schema_export.gemini_schema(schema_export.MODELS[name])
    text = json.dumps(schema)
    for banned in ("$ref", "$defs", "anyOf", "additionalProperties"):
        assert banned not in text
    types.Schema.model_validate(schema)
