import csv
import json
import re
from pathlib import Path

from app.config import Settings
from app.models.policy import PolicyBrain
from app.services.mock_policy import MOCK_POLICY_ID, SAMPLE_PATH, is_mock_policy, load_sample_policy

DATA = Path(__file__).resolve().parents[2] / "data"


def test_sample_json_validates_against_schema():
    PolicyBrain.model_validate(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))


def test_sample_matches_ground_truth_for_policy_01():
    p = load_sample_policy().to_store()
    rows = [r for r in csv.DictReader((DATA / "ground_truth.csv").open(encoding="utf-8"))
            if r["policy_file"].startswith("01_")]
    assert len(rows) == 10
    for r in rows:
        cur = p
        for part in r["brain_path"].split("."):
            cur = cur[part]
        if r["match_type"] == "value|unit":
            got, want = f"{int(cur['value'])}|{cur['unit']}", r["expected"]
        elif r["match_type"] == "number":      # copay_percent is a float in the model: compare numerically
            got, want = float(cur), float(r["expected"])
        else:
            got, want = str(cur), r["expected"]
        assert got == want, r["field"]


def test_sample_hash_is_the_real_pdf_hash():
    import hashlib
    pdf = DATA / "sample_policies" / "01_sanjivani_suraksha_clean.pdf"
    assert load_sample_policy().extraction_meta.file_hash == hashlib.sha256(pdf.read_bytes()).hexdigest()


def test_every_claim_has_source_inside_the_document():
    p = load_sample_policy()
    items = [*p.covered, *p.exclusions, *p.sub_limits, *p.red_flags]
    assert len(items) >= 15
    assert all(1 <= i.source.page <= 5 for i in items)


def test_summaries_carry_identical_numbers_and_dates_in_all_languages():
    """Same rule A17 will enforce on live output: figures come from the data, identical in en/hi/mr."""
    p = load_sample_policy()
    must = ["5,00,000", "14,250", "01 Apr 2025", "31 Mar 2026", "5,000", "10%"]
    for lang in ("en", "hi", "mr"):
        text = getattr(p.plain_summary, lang)
        for m in must:
            assert m in text, f"{m} missing from {lang} summary"
    assert not re.search(r"[०-९]", p.plain_summary.hi + p.plain_summary.mr), "use Western digits"


def test_loader_returns_independent_copies():
    a = load_sample_policy()
    a.insurer = "CHANGED"
    assert load_sample_policy().insurer != "CHANGED"


def test_mock_mode_follows_empty_key():
    assert Settings(_env_file=None, gemini_api_key="").mock_mode
    assert is_mock_policy(MOCK_POLICY_ID) and not is_mock_policy("abc")
