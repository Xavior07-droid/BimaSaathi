"""Shared Gemini test double (A26). Use this in NEW tests instead of copying a FakeGemini again.

    g = FakeGemini([{"answer": "..."}, GeminiBusy("b"), {"x": 1}])
    await some_service(..., g)
    g.calls[0]["temperature"]      # every keyword the service passed + "contents"
    g.models                       # ["fast", "fallback", ...] in call order

Script items are consumed one per generate_json call: dict -> returned as parsed JSON, Exception -> raised.
Running past the end of the script is a test bug and raises AssertionError (it never silently returns {}).
No network, no sleeping, no SDK: it only needs app.services.gemini.GeminiResult.
"""
from __future__ import annotations

import json
from typing import Any

from app.services.gemini import GeminiResult

FAST_ID, LITE_ID = "fast-m", "lite-m"


class FakeGemini:
    mock_mode = False

    def __init__(self, script: list[Any] | None = None):
        self.script = list(script or [])
        self.calls: list[dict[str, Any]] = []

    @property
    def models(self) -> list[str]:
        return [c["model"] for c in self.calls]

    async def generate_json(self, contents, **kw) -> GeminiResult:
        self.calls.append({"contents": contents, **kw})
        if not self.script:
            raise AssertionError(f"FakeGemini script exhausted: unexpected call #{len(self.calls)} (purpose={kw.get('purpose')})")
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        model = FAST_ID if kw.get("model", "fast") == "fast" else LITE_ID
        return GeminiResult(data=step, text=json.dumps(step), model=model, attempts=1, latency_ms=1, total_tokens=100,
                            used_fallback=(model == LITE_ID))


class MockModeGemini(FakeGemini):
    """What the app sees when GEMINI_API_KEY is empty. Any call is a bug."""
    mock_mode = True
