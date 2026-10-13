import pytest

from app.config import Settings


def make(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_mock_mode_when_key_empty():
    assert make(gemini_api_key="").mock_mode is True
    assert make(gemini_api_key="   ").mock_mode is True


def test_live_mode_when_key_set():
    assert make(gemini_api_key="k").mock_mode is False


def test_no_hardcoded_model_ids():
    s = make()
    assert s.gemini_model_fast == "" and s.gemini_model_fallback == ""


def test_models_read_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL_FAST", "fast-x")
    monkeypatch.setenv("GEMINI_MODEL_FALLBACK", "lite-y")
    s = Settings(_env_file=None)
    assert (s.gemini_model_fast, s.gemini_model_fallback) == ("fast-x", "lite-y")


def test_live_without_models_fails_loudly():
    with pytest.raises(RuntimeError, match="GEMINI_MODEL_FAST"):
        make(gemini_api_key="k").validate_for_live_gemini()


def test_mock_mode_needs_no_models():
    make().validate_for_live_gemini()  # must not raise


def test_limits_default_to_free_tier_safe_values():
    s = make()
    assert (s.gemini_max_concurrent, s.gemini_rpm, s.gemini_max_retries) == (2, 10, 3)
