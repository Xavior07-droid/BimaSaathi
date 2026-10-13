import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors

from app.config import Settings
from app.services.gemini import (BUSY_MESSAGE, GeminiBadOutput, GeminiBusy, GeminiClient, GeminiMockMode,
                                 GeminiRequestError, RateLimiter, parse_json_text)

SECRET = "PATIENT-SECRET-TEXT-123"


def settings(**kw):
    base = dict(gemini_api_key="k", gemini_model_fast="fast-m", gemini_model_fallback="lite-m")
    base.update(kw)
    return Settings(_env_file=None, **base)


def api_error(code):
    return genai_errors.APIError(code, {"error": {"message": "x", "status": "S"}})


def ok(text='{"a": 1}', pt=11, ot=5):
    return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(
        prompt_token_count=pt, candidates_token_count=ot, total_token_count=pt + ot))


class FakeModels:
    def __init__(self, script):
        self.script, self.calls, self.models = list(script), 0, []
        self.in_flight = self.max_in_flight = 0

    async def generate_content(self, *, model, contents, config):
        self.calls += 1
        self.models.append(model)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            step = self.script.pop(0) if self.script else ok()
            if isinstance(step, BaseException):
                raise step
            return step
        finally:
            self.in_flight -= 1


def make(script, **skw):
    models = FakeModels(script)
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    client = GeminiClient(settings(**skw), client=SimpleNamespace(aio=SimpleNamespace(models=models)), sleep=fake_sleep)
    return client, models, sleeps


async def test_success_parses_json_and_reads_usage():
    c, m, _ = make([ok('{"x": 2}')])
    r = await c.generate_json("hi", purpose="t")
    assert r.data == {"x": 2} and r.model == "fast-m" and r.attempts == 1
    assert (r.prompt_tokens, r.output_tokens, r.total_tokens) == (11, 5, 16)


async def test_429_then_success_backs_off_exponentially():
    c, m, sleeps = make([api_error(429), api_error(503), ok()])
    r = await c.generate_json("hi")
    assert r.attempts == 3 and m.calls == 3
    assert 2 <= sleeps[0] < 3 and 4 <= sleeps[1] < 5


async def test_three_failures_raise_busy_with_friendly_message():
    c, m, _ = make([api_error(429)] * 3)
    with pytest.raises(GeminiBusy) as e:
        await c.generate_json("hi")
    assert e.value.message == BUSY_MESSAGE and e.value.error_code == "ai_busy" and m.calls == 3


@pytest.mark.parametrize("code", [400, 401, 403, 404])
async def test_non_retryable_fails_fast(code):
    c, m, sleeps = make([api_error(code)])
    with pytest.raises(GeminiRequestError):
        await c.generate_json("hi")
    assert m.calls == 1 and sleeps == []


async def test_timeouts_are_retried():
    c, m, _ = make([httpx.ReadTimeout("t"), asyncio.TimeoutError(), ok()])
    assert (await c.generate_json("hi")).attempts == 3


async def test_bad_json_and_empty_raise_bad_output_without_retry():
    for text in ("not json", "", None):
        c, m, _ = make([ok(text)])
        with pytest.raises(GeminiBadOutput):
            await c.generate_json("hi")
        assert m.calls == 1


def test_code_fences_are_stripped():
    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_text('```\n[1,2]\n```') == [1, 2]


async def test_fallback_model_after_fast_is_busy():
    c, m, _ = make([api_error(503)] * 3 + [ok()])
    r = await c.generate_json_with_fallback("hi")
    assert r.model == "lite-m" and r.used_fallback and m.models == ["fast-m"] * 3 + ["lite-m"]


async def test_no_fallback_on_non_retryable_error():
    c, m, _ = make([api_error(400)])
    with pytest.raises(GeminiRequestError):
        await c.generate_json_with_fallback("hi")
    assert m.models == ["fast-m"]


async def test_mock_mode_never_calls_network():
    c, m, _ = make([], gemini_api_key="")
    assert c.mock_mode
    with pytest.raises(GeminiMockMode):
        await c.generate_json("hi")
    assert m.calls == 0


async def test_live_without_model_ids_fails_loudly():
    c, _, _ = make([], gemini_model_fast="")
    with pytest.raises(RuntimeError, match="GEMINI_MODEL_FAST"):
        await c.generate_json("hi")


async def test_concurrency_never_exceeds_limit():
    c, m, _ = make([ok()] * 8, gemini_rpm=100)
    await asyncio.gather(*(c.generate_json("hi") for _ in range(8)))
    assert m.max_in_flight == 2 and m.calls == 8


async def test_rpm_window_delays_eleventh_request():
    now = [0.0]

    async def adv(s):
        now[0] += s

    lim = RateLimiter(max_concurrent=5, rpm=10, queue_timeout=120, clock=lambda: now[0], sleep=adv)
    for _ in range(10):
        async with lim.slot():
            pass
    assert now[0] == 0
    async with lim.slot():
        pass
    assert now[0] == pytest.approx(60.0)      # had to wait for the first stamp to age out


async def test_rpm_wait_beyond_queue_timeout_is_busy():
    now = [0.0]

    async def adv(s):
        now[0] += s

    lim = RateLimiter(max_concurrent=5, rpm=1, queue_timeout=10, clock=lambda: now[0], sleep=adv)
    async with lim.slot():
        pass
    with pytest.raises(GeminiBusy):
        async with lim.slot():
            pass


async def test_logs_contain_tokens_but_never_content(caplog):
    caplog.set_level(logging.INFO, logger="bimasaathi.gemini")
    c, _, _ = make([ok('{"secret": "%s"}' % SECRET)])
    await c.generate_json(f"policy text {SECRET}", purpose="extract")
    out = caplog.text
    assert "prompt_tokens=11" in out and "model=fast-m" in out and "purpose=extract" in out
    assert SECRET not in out


async def test_real_sdk_config_accepts_our_schema_both_modes():
    """Offline check that the kwargs we build are valid for the installed google-genai."""
    from google.genai import types

    from app.models.policy import PolicyExtraction
    from app.models.schema_export import gemini_schema

    seen = []

    class Spy:
        async def generate_content(self, *, model, contents, config):
            seen.append(config)
            return ok()

    c = GeminiClient(settings(), client=SimpleNamespace(aio=SimpleNamespace(models=Spy())))
    await c.generate_json("x", schema=gemini_schema(PolicyExtraction), system="s")
    await c.generate_json("x", schema=PolicyExtraction.model_json_schema(), use_json_schema=True)
    assert all(isinstance(s, types.GenerateContentConfig) for s in seen)
    assert seen[0].response_schema is not None and seen[0].response_json_schema is None
    assert seen[1].response_json_schema is not None and seen[1].response_schema is None
    assert seen[0].response_mime_type == "application/json" and seen[0].temperature == 0
    assert seen[0].http_options.timeout == 60_000
