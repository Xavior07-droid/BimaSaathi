"""Central env config. All model IDs come from env, never hardcoded.

Owner note: M owns this file; A1 creates the Gemini-related part.
M can add CORS/CRON/Firebase fields below without touching A's fields.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Gemini (A) ---
    gemini_api_key: str = ""
    gemini_model_fast: str = ""      # a Flash model, from env
    gemini_model_fallback: str = ""  # a Flash-Lite model, from env
    gemini_max_concurrent: int = Field(2, ge=1)
    gemini_rpm: int = Field(10, ge=1)
    gemini_max_retries: int = Field(3, ge=1)
    gemini_timeout_seconds: int = Field(60, ge=5)

    # --- Upload limits (A12 uses) ---
    max_upload_mb: int = Field(15, ge=1)

    # --- Optional ---
    use_gtts: bool = False

    # --- M's fields (placeholders so the app boots) ---
    allowed_origins: str = "http://localhost:3000"
    cron_key: str = ""
    firebase_service_account_json: str = ""
    # A12 dev stub: only used while M's auth.py has no `get_current_uid` yet. NEVER true in production.
    dev_auth: bool = False

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def mock_mode(self) -> bool:
        """No API key -> serve sample_policy.json instead of calling Gemini."""
        return not self.gemini_api_key.strip()

    def validate_for_live_gemini(self) -> None:
        """Call before the first real Gemini call. Fails loudly, not silently."""
        if self.mock_mode:
            return
        missing = [n for n, v in (("GEMINI_MODEL_FAST", self.gemini_model_fast),
                                  ("GEMINI_MODEL_FALLBACK", self.gemini_model_fallback)) if not v.strip()]
        if missing:
            raise RuntimeError(f"GEMINI_API_KEY is set but {', '.join(missing)} missing. "
                               "Set model IDs in .env (see .env.example).")


@lru_cache
def get_settings() -> Settings:
    return Settings()
