import csv
import importlib.util
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2] / "data"
spec = importlib.util.spec_from_file_location("make_gt", ROOT / "make_ground_truth.py")
make_gt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_gt)


def load():
    with (ROOT / "ground_truth.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_csv_is_up_to_date_with_manifest():
    assert load() == make_gt.build_rows(), "stale: run `python data/make_ground_truth.py`"


def test_shape_10_fields_x_4_policies():
    rows = load()
    assert len(rows) == 40
    assert set(Counter(r["policy_file"] for r in rows).values()) == {10}
    assert len({r["field"] for r in rows}) == 10


def test_null_rows_are_the_planted_traps():
    nulls = {(r["policy_file"][:2], r["field"]) for r in load() if r["is_null"] == "true"}
    assert nulls == {("02", "renewal_date"), ("03", "renewal_date"), ("04", "renewal_date"), ("04", "room_rent_cap")}


def test_expected_values_really_appear_in_the_pdfs():
    """Guards against ground truth that disagrees with the document itself (text-layer PDFs only)."""
    anchors = {
        "01_sanjivani_suraksha_clean.pdf": ["5,00,000", "14,250", "36 months", "24 months", "Rs. 5,000", "10%", "01 April 2026"],
        "02_bharat_arogya_floater_tables.pdf": ["10,00,000", "22,480", "Four (4) years", "Two (2) years", "1% of Sum Insured", "Nil"],
        "03_maharashtra_jeevan_raksha_bilingual_en_mr.pdf": ["3,00,000", "9,800", "15/06/2025", "14/06/2026", "24 months", "12 months", "Rs. 3,000", "5%"],
    }
    for name, needles in anchors.items():
        text = " ".join("".join(p.get_text() for p in pymupdf.open(ROOT / "sample_policies" / name)).split())  # collapse line wraps
        for n in needles:
            assert n in text, f"{n!r} not found in {name}"
