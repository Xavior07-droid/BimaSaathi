import json
from pathlib import Path

import pymupdf
import pytest

from app.models.policy import PolicyExtraction

DIR = Path(__file__).resolve().parents[2] / "data" / "sample_policies"
MANIFEST = json.loads((DIR / "manifest.json").read_text(encoding="utf-8"))["policies"]


@pytest.mark.parametrize("p", MANIFEST, ids=lambda p: p["file"])
def test_pdf_pages_and_text_layer(p):
    doc = pymupdf.open(DIR / p["file"])
    assert len(doc) == p["pages"]
    chars = sum(len(pg.get_text().strip()) for pg in doc)
    if "SCANNED" in p["kind"]:
        assert chars == 0, "scanned sample must have no text layer"
    else:
        assert chars > 1000


@pytest.mark.parametrize("p", MANIFEST, ids=lambda p: p["file"])
def test_expected_values_fit_the_schema(p):
    e = p["expected"]
    PolicyExtraction.model_validate({k: e[k] for k in (
        "insurer", "policy_no", "holder_name", "start_date", "end_date", "renewal_date",
        "sum_insured", "premium", "waiting_periods", "room_rent_cap", "copay_percent")})


def test_one_scanned_and_one_bilingual():
    kinds = " ".join(p["kind"] for p in MANIFEST)
    assert "SCANNED" in kinds and "bilingual" in kinds and len(MANIFEST) == 4
