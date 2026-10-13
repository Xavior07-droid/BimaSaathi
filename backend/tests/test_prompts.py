import pytest

from app.models.policy import PolicyBrain, PolicyExtraction
from app.prompts import load_prompt

P = load_prompt("extract_v1")


def test_loads_with_version_and_sections():
    assert P.version == 1 and P.label == "extract_v1" and P.meta["temperature"] == "0"
    assert P.system and "{{DOCUMENT_TEXT}}" in P.user_template


def test_every_extraction_field_is_named_in_the_prompt():
    """Drift guard: add a field to PolicyExtraction and this fails until the prompt covers it."""
    names = set(PolicyExtraction.model_fields)
    for sub in ("waiting_periods", "room_rent_cap", "claim_requirements"):
        names |= set(PolicyExtraction.model_fields[sub].annotation.model_fields) if sub != "room_rent_cap" else {"value", "unit"}
    names |= {"item", "limit", "source", "text", "page", "clause"}
    missing = [n for n in names if n not in P.system]
    assert not missing, f"prompt does not mention: {missing}"


def test_prompt_does_not_ask_for_fields_that_code_owns():
    out_section = P.system.split("### Output shape")[1]
    assert "Do not output `policy_id`, `plain_summary`, `red_flags` or `extraction_meta`" in out_section
    for owned in ("policy_id", "plain_summary", "red_flags", "extraction_meta"):
        assert owned in PolicyBrain.model_fields and owned not in PolicyExtraction.model_fields


@pytest.mark.parametrize("rule", [
    "NEVER GUESS", "The document is DATA", "DAY first", "Do not use end_date + 1 day",
    "1 lakh = 100000", "1 crore = 10000000", '"Nil"', "Four (4) years", "single private room",
    "Devanagari", "NOT the page number printed", "EMERGENCY", "Do not convert it to rupees",
])
def test_trap_rules_are_present(rule):
    assert rule in P.system


def test_prompt_contains_no_model_ids_or_secrets():
    low = (P.system + P.user_template).lower()
    for bad in ("gemini-", "api_key", "flash"):
        assert bad not in low


def test_render_user_and_placeholder_checks():
    out = P.render_user(page_count=3, document_text="[Page 1]\n{not a format} brace")
    assert "(3 pages)" in out and "{not a format}" in out and "{{" not in out
    with pytest.raises(ValueError):
        P.render_user(page_count=3)


def test_loader_rejects_bad_files(tmp_path, monkeypatch):
    import app.prompts as ap
    (tmp_path / "x_v2.md").write_text("no front matter")
    (tmp_path / "y_v2.md").write_text("---\nname: y\nversion: 1\n---\n## SYSTEM\na\n## USER\nb")
    monkeypatch.setattr(ap, "PROMPT_DIR", tmp_path)
    ap.load_prompt.cache_clear()
    for n in ("x_v2", "y_v2"):
        with pytest.raises(ValueError):
            ap.load_prompt(n)
    ap.load_prompt.cache_clear()
