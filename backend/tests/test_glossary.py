"""A15: glossary.json shape and content checks."""
import json
import re
from pathlib import Path

GLOSSARY = Path(__file__).resolve().parents[1] / "app" / "data" / "glossary.json"
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
DEVANAGARI_DIGITS = re.compile(r"[०-९]")  # hard rule: Western digits only
REQUIRED_IDS = {
    "co_pay", "sub_limit", "waiting_period", "room_rent_cap",
    "cashless", "tpa", "pre_existing_disease",
}


def _load():
    return json.loads(GLOSSARY.read_text(encoding="utf-8"))


def test_term_count_in_range():
    assert 40 <= len(_load()["terms"]) <= 50


def test_required_terms_present_and_ids_unique():
    ids = [t["id"] for t in _load()["terms"]]
    assert len(ids) == len(set(ids))
    assert REQUIRED_IDS <= set(ids)


def test_every_term_has_all_languages():
    for t in _load()["terms"]:
        for field in ("term", "definition"):
            for lang in ("en", "hi", "mr"):
                assert t[field][lang].strip(), f"{t['id']}.{field}.{lang} empty"


def test_hi_mr_are_devanagari_and_en_is_not():
    for t in _load()["terms"]:
        for lang in ("hi", "mr"):
            assert DEVANAGARI.search(t["definition"][lang]), f"{t['id']} {lang}"
            assert DEVANAGARI.search(t["term"][lang]), f"{t['id']} {lang}"
        assert not DEVANAGARI.search(t["definition"]["en"]), t["id"]


def test_western_digits_only():
    raw = GLOSSARY.read_text(encoding="utf-8")
    assert not DEVANAGARI_DIGITS.search(raw)


def test_aliases_are_lowercase_and_unique_across_terms():
    seen: dict[str, str] = {}
    for t in _load()["terms"]:
        assert t["aliases"], t["id"]
        for a in t["aliases"]:
            assert a == a.lower() and a.strip(), (t["id"], a)
            assert a not in seen, f"alias {a!r} used by {seen[a]} and {t['id']}"
            seen[a] = t["id"]
