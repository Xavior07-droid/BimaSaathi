"""MOCK mode (A6): with an empty GEMINI_API_KEY the backend serves app/data/sample_policy.json
instead of calling Gemini, so every teammate can develop offline.

The sample is a validated PolicyBrain built from data/sample_policies/01_*.pdf. It is language-complete
(en/hi/mr summaries, red flags, sources), so frontend work on the Policy Card needs no key.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models.policy import PolicyBrain

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "sample_policy.json"
MOCK_POLICY_ID = "sample-policy"


@lru_cache
def _load() -> PolicyBrain:
    return PolicyBrain.model_validate(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))


def load_sample_policy() -> PolicyBrain:
    """Fresh copy each call, so callers can mutate it without corrupting the cached one."""
    return _load().model_copy(deep=True)


def is_mock_policy(policy_id: str) -> bool:
    return policy_id == MOCK_POLICY_ID
