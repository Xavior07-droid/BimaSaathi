"""Shared FastAPI dependencies for A's routers (A12+).

Two things belong to M and may not exist yet. This module uses M's versions when present and falls back safely:

  auth   M7:  app/auth.py        must export `get_current_uid` (FastAPI dependency -> Firebase uid str, 401 on a bad token)
  store  M7:  app/services/store.py  must export `get_store()` returning an object that implements `PolicyStore`
              (app/services/policy_cache.py). In-memory fallback below is for local dev/tests only.

Fallback auth is a DEV STUB: it answers 503 unless DEV_AUTH=true, so a forgotten wiring can never become an open API.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.gemini import GeminiClient, get_gemini
from app.services.policy_cache import InMemoryPolicyStore, PolicyStore

log = logging.getLogger("bimasaathi.deps")

try:                                                    # M's real Firebase ID-token check
    from app.auth import get_current_uid as current_uid  # type: ignore[attr-defined]
    USING_DEV_AUTH = False
except ImportError:
    USING_DEV_AUTH = True

    async def current_uid(x_dev_uid: str | None = Header(default=None)) -> str:
        if not get_settings().dev_auth:
            raise HTTPException(status_code=503, detail={
                "error_code": "auth_not_configured",
                "message": "Sign-in is not set up on this server yet."})
        return (x_dev_uid or "dev-user").strip()[:128] or "dev-user"


def error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    """The API's one error shape: {error_code, message}."""
    return JSONResponse({"error_code": code, "message": message}, status_code=status, headers=headers)


@lru_cache
def _fallback_store() -> InMemoryPolicyStore:
    log.warning("services.store.get_store not found: using an IN-MEMORY policy store (data is lost on restart)")
    return InMemoryPolicyStore()


def get_policy_store() -> PolicyStore:
    try:
        from app.services.store import get_store         # type: ignore[attr-defined]
    except ImportError:
        return _fallback_store()
    return get_store()


def gemini_client() -> GeminiClient:
    return get_gemini()
