"""Gemini wrapper (A5): structured JSON output, timeouts, exponential backoff, rate limiter,
token logging, Flash -> Flash-Lite fallback. Built against google-genai 2.29.0.

Free-tier rules enforced here:
- at most GEMINI_MAX_CONCURRENT calls in flight (default 2) and GEMINI_RPM per rolling minute (default 10)
- retries (429 / 5xx / timeouts) with exponential backoff, max GEMINI_MAX_RETRIES attempts (default 3)
- model IDs come only from settings (env); nothing hardcoded
- logs carry model, purpose, latency and token counts. NEVER prompt or response text (privacy).

MOCK mode (empty GEMINI_API_KEY) is handled by callers via `gemini.mock_mode` (A6 serves sample_policy.json);
calling generate_json in mock mode raises GeminiMockMode so it can never silently hit the network.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Awaitable, Callable, Literal

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.config import Settings, get_settings

log = logging.getLogger("bimasaathi.gemini")

RETRYABLE_HTTP = {429, 500, 502, 503, 504}
BUSY_MESSAGE = "Our AI service is busy right now. Please retry in a minute."


# ----------------------------------------------------------------- errors
class GeminiError(Exception):
    """Base. `error_code` + `message` match the API error shape {error_code, message}."""
    error_code = "gemini_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class GeminiBusy(GeminiError):
    """Quota / rate limit / overload after all retries. Show BUSY_MESSAGE to the user."""
    error_code = "ai_busy"


class GeminiRequestError(GeminiError):
    """Non-retryable (400/401/403/404 ...): bad key, bad model ID, bad request. Fix config/code, don't retry."""
    error_code = "ai_request_error"


class GeminiBadOutput(GeminiError):
    """Model answered but the text is empty / not JSON. Caller (A9) decides on retry/fallback."""
    error_code = "ai_bad_output"


class GeminiMockMode(GeminiError):
    error_code = "ai_mock_mode"


# ----------------------------------------------------------------- limiter
class RateLimiter:
    """Concurrency cap (semaphore) + rolling 60 s request cap. Waits up to `queue_timeout` s, then GeminiBusy.

    clock/sleep are injectable so tests don't need real time.
    """

    def __init__(self, max_concurrent: int, rpm: int, queue_timeout: float = 45.0,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._sem = asyncio.Semaphore(max_concurrent)
        self._rpm = rpm
        self._timeout = queue_timeout
        self._clock, self._sleep = clock, sleep
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def _reserve_rpm_slot(self, deadline: float) -> None:
        while True:
            async with self._lock:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= 60.0:
                    self._stamps.popleft()
                if len(self._stamps) < self._rpm:
                    self._stamps.append(now)
                    return
                wait = 60.0 - (now - self._stamps[0])
            if self._clock() + wait > deadline:
                raise GeminiBusy(BUSY_MESSAGE)
            await self._sleep(wait)

    @asynccontextmanager
    async def slot(self):
        deadline = self._clock() + self._timeout
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._timeout)
        except asyncio.TimeoutError:
            raise GeminiBusy(BUSY_MESSAGE) from None
        try:
            await self._reserve_rpm_slot(deadline)
            yield
        finally:
            self._sem.release()


# ----------------------------------------------------------------- result
@dataclass
class GeminiResult:
    data: Any                      # parsed JSON
    text: str                      # raw text (for A9 retry-with-error prompts)
    model: str
    attempts: int
    latency_ms: int
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    used_fallback: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------- helpers
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def parse_json_text(text: str | None) -> Any:
    if not text or not text.strip():
        raise GeminiBadOutput("Model returned an empty response.")
    m = _FENCE.match(text)
    body = m.group(1) if m else text.strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise GeminiBadOutput(f"Model output is not valid JSON: {e.msg} at char {e.pos}") from None


def pdf_part(data: bytes) -> types.Part:
    return types.Part.from_bytes(data=data, mime_type="application/pdf")


def image_part(data: bytes, mime_type: str = "image/jpeg") -> types.Part:
    return types.Part.from_bytes(data=data, mime_type=mime_type)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.APIError):
        return exc.code in RETRYABLE_HTTP
    return isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException, httpx.TransportError))


# ----------------------------------------------------------------- client
class GeminiClient:
    def __init__(self, settings: Settings | None = None, *, client: Any | None = None,
                 limiter: RateLimiter | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.settings = settings or get_settings()
        self._client = client            # lazily built so mock mode never needs the SDK client
        self._sleep = sleep
        self.limiter = limiter or RateLimiter(self.settings.gemini_max_concurrent, self.settings.gemini_rpm)

    @property
    def mock_mode(self) -> bool:
        return self.settings.mock_mode

    def _sdk(self):
        if self._client is None:
            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    def model_id(self, which: Literal["fast", "fallback"]) -> str:
        self.settings.validate_for_live_gemini()
        return self.settings.gemini_model_fast if which == "fast" else self.settings.gemini_model_fallback

    async def generate_json(
        self,
        contents: str | types.Part | list[str | types.Part],
        *,
        schema: dict[str, Any] | None = None,
        use_json_schema: bool = False,
        system: str | None = None,
        temperature: float = 0.0,
        model: Literal["fast", "fallback"] = "fast",
        purpose: str = "generic",
    ) -> GeminiResult:
        """One logical call: limiter -> request -> retry/backoff -> parse JSON.

        schema: flattened dict from app.models.schema_export.gemini_schema(...).
        use_json_schema=True sends it as response_json_schema (full JSON Schema) instead of response_schema;
        flip it if the live API rejects one form.
        """
        if self.mock_mode:
            raise GeminiMockMode("GEMINI_API_KEY is empty: running in MOCK mode, no Gemini calls are made.")
        model_id = self.model_id(model)

        cfg: dict[str, Any] = {
            "temperature": temperature,
            "response_mime_type": "application/json",
            "http_options": types.HttpOptions(timeout=self.settings.gemini_timeout_seconds * 1000),
        }
        if schema is not None:
            cfg["response_json_schema" if use_json_schema else "response_schema"] = schema
        if system:
            cfg["system_instruction"] = system
        config = types.GenerateContentConfig(**cfg)

        max_tries = self.settings.gemini_max_retries
        started = time.monotonic()
        last_exc: BaseException | None = None

        for attempt in range(1, max_tries + 1):
            try:
                async with self.limiter.slot():          # slot is released BEFORE we sleep for backoff
                    resp = await asyncio.wait_for(
                        self._sdk().aio.models.generate_content(model=model_id, contents=contents, config=config),
                        timeout=self.settings.gemini_timeout_seconds + 5)
            except GeminiError:
                raise
            except Exception as exc:  # noqa: BLE001 - classified below
                last_exc = exc
                if not _is_retryable(exc):
                    code = getattr(exc, "code", None)
                    log.error("gemini non-retryable error model=%s purpose=%s code=%s type=%s",
                              model_id, purpose, code, type(exc).__name__)
                    raise GeminiRequestError(
                        f"Gemini rejected the request (code {code}). Check GEMINI_API_KEY and model IDs.") from exc
                log.warning("gemini retryable error model=%s purpose=%s attempt=%d/%d code=%s type=%s",
                            model_id, purpose, attempt, max_tries, getattr(exc, "code", None), type(exc).__name__)
                if attempt < max_tries:
                    await self._sleep(min(2 ** attempt, 20) + random.uniform(0, 0.5))   # 2s, 4s, ...
                continue

            latency_ms = int((time.monotonic() - started) * 1000)
            usage = getattr(resp, "usage_metadata", None)
            result_kwargs = dict(
                model=model_id, attempts=attempt, latency_ms=latency_ms, used_fallback=(model == "fallback"),
                prompt_tokens=getattr(usage, "prompt_token_count", None),
                output_tokens=getattr(usage, "candidates_token_count", None),
                total_tokens=getattr(usage, "total_token_count", None))
            log.info("gemini ok model=%s purpose=%s attempts=%d latency_ms=%d prompt_tokens=%s output_tokens=%s total_tokens=%s",
                     model_id, purpose, attempt, latency_ms, result_kwargs["prompt_tokens"],
                     result_kwargs["output_tokens"], result_kwargs["total_tokens"])
            text = resp.text
            return GeminiResult(data=parse_json_text(text), text=text, **result_kwargs)

        log.error("gemini exhausted retries model=%s purpose=%s tries=%d", model_id, purpose, max_tries)
        raise GeminiBusy(BUSY_MESSAGE) from last_exc

    async def generate_json_with_fallback(self, contents, **kwargs) -> GeminiResult:
        """Try the Flash model; if it is overloaded/exhausted, try Flash-Lite once (own retry budget)."""
        kwargs.pop("model", None)
        try:
            return await self.generate_json(contents, model="fast", **kwargs)
        except GeminiBusy:
            log.warning("gemini falling back to fallback model purpose=%s", kwargs.get("purpose"))
            return await self.generate_json(contents, model="fallback", **kwargs)


@lru_cache
def get_gemini() -> GeminiClient:
    return GeminiClient()
