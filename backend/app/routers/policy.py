"""GET /api/policy/{id} and GET /api/policies (A13). Later A steps add /ask and /suggestions to this router.

Ownership rules (same as the status endpoint): a policy that belongs to someone else, or does not exist, answers the
same 404, so ids cannot be probed. `owner_uid` is stripped from every response.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.models.policy import PolicyBrain
from app.routers.deps import current_uid, error, gemini_client, get_policy_store
from app.services import ask as ask_service
from app.services import suggestions as suggestions_service
from app.services.gemini import GeminiBusy, GeminiClient, GeminiError, GeminiRequestError
from app.services.ingest_jobs import JobTracker, get_tracker
from app.services.mock_policy import is_mock_policy, load_sample_policy
from app.services.policy_cache import PolicyStore, StoredPolicy

log = logging.getLogger("bimasaathi.policy")
router = APIRouter(prefix="/api", tags=["policy"])

MAX_LIST = 50
NO_STORE = {"Cache-Control": "private, no-store"}
# What we accept as an id before touching the database: our ids are 16 hex chars; Firestore also reserves "." / ".." / "__x__".
_VALID_ID = re.compile(r"^(?!__)[A-Za-z0-9_-]{1,64}$")


def _not_found() -> JSONResponse:
    return error(404, "not_found", "We could not find this policy.", headers=NO_STORE)


def _brain_from(stored: StoredPolicy) -> PolicyBrain | None:
    """Stored dict -> validated PolicyBrain without owner_uid; None if it no longer matches the schema."""
    data = {k: v for k, v in stored.data.items() if k != "owner_uid"}       # store contract says it is absent; be safe
    try:
        return PolicyBrain.model_validate(data)
    except ValidationError:
        log.warning("stored policy %s failed validation (schema drift?)", data.get("policy_id"))
        return None


def _list_item(brain: PolicyBrain) -> dict:
    """Light card for lists: headline facts only (full document = GET /api/policy/{id})."""
    return {
        "policy_id": brain.policy_id, "status": "done",
        "insurer": brain.insurer, "policy_no": brain.policy_no, "policy_type": brain.policy_type,
        "holder_name": brain.holder_name, "sum_insured": brain.sum_insured, "premium": brain.premium,
        "start_date": brain.start_date.isoformat() if brain.start_date else None,
        "end_date": brain.end_date.isoformat() if brain.end_date else None,
        "renewal_date": brain.renewal_date.isoformat() if brain.renewal_date else None,
        "red_flag_count": len(brain.red_flags), "has_summary": brain.plain_summary is not None,
        "created_at": brain.extraction_meta.created_at.isoformat(),
    }


# ------------------------------------------------------------------ GET /api/policy/{id}
@router.get("/policy/{policy_id}")
async def get_policy(policy_id: str,
                     uid: str = Depends(current_uid),
                     store: PolicyStore = Depends(get_policy_store),
                     tracker: JobTracker = Depends(get_tracker)):
    if is_mock_policy(policy_id):                       # the built-in demo policy ("try sample policy"): public, read-only
        return JSONResponse(load_sample_policy().to_store(), headers=NO_STORE)
    if not _VALID_ID.match(policy_id):
        return _not_found()

    try:
        stored = await asyncio.to_thread(store.get_policy, policy_id)
    except Exception:  # noqa: BLE001
        log.exception("store read failed policy_id=%s", policy_id)
        return error(503, "store_unavailable", "We could not load your policy right now. Please retry in a minute.", headers=NO_STORE)

    if stored is None or stored.owner_uid != uid:
        job = tracker.get(policy_id, uid)               # still being read? (UI opened the card before it was ready)
        if job is not None and job.status == "processing":
            return error(409, "still_processing", "We are still reading this policy. Please wait a moment.", headers=NO_STORE)
        return _not_found()

    brain = _brain_from(stored)
    if brain is None:
        return error(409, "policy_outdated", "This policy was saved by an older version of the app. Please upload it again.",
                     headers=NO_STORE)
    return JSONResponse(brain.to_store(), headers=NO_STORE)


# ------------------------------------------------------------------ GET /api/policies
@router.get("/policies")
async def list_policies(uid: str = Depends(current_uid),
                        store: PolicyStore = Depends(get_policy_store),
                        tracker: JobTracker = Depends(get_tracker)):
    try:
        stored = await asyncio.to_thread(store.list_policies, uid, MAX_LIST)
    except Exception:  # noqa: BLE001
        log.exception("store list failed")
        return error(503, "store_unavailable", "We could not load your policies right now. Please retry in a minute.", headers=NO_STORE)

    done = [it for it in (_brain_from(s) for s in stored if s.owner_uid == uid) if it is not None]
    done.sort(key=lambda b: b.extraction_meta.created_at, reverse=True)           # newest first; sorted here, not in Firestore
    items = [_list_item(b) for b in done]

    in_progress = sorted((j for j in tracker.active_for_owner(uid)), key=lambda j: j.created_at, reverse=True)
    pending = [{"policy_id": j.policy_id, "status": "processing", "stage": j.stage, "progress": j.progress}
               for j in in_progress if j.policy_id not in {i["policy_id"] for i in items}]
    return JSONResponse({"policies": pending + items}, headers=NO_STORE)


# ------------------------------------------------------------------ shared: "this user's policy, or the right error"
async def _load_brain(policy_id: str, uid: str, store: PolicyStore, tracker: JobTracker) -> tuple[PolicyBrain | None, JSONResponse | None]:
    """Used by the ask and suggestions routes. Same 404 for 'not yours' and 'does not exist'; sample policy is public."""
    if is_mock_policy(policy_id):
        return load_sample_policy(), None
    if not _VALID_ID.match(policy_id):
        return None, _not_found()
    try:
        stored = await asyncio.to_thread(store.get_policy, policy_id)
    except Exception:  # noqa: BLE001
        log.exception("store read failed policy_id=%s", policy_id)
        return None, error(503, "store_unavailable", "We could not load your policy right now. Please retry in a minute.", headers=NO_STORE)
    if stored is None or stored.owner_uid != uid:
        job = tracker.get(policy_id, uid)
        if job is not None and job.status == "processing":
            return None, error(409, "still_processing", "We are still reading this policy. Please wait a moment.", headers=NO_STORE)
        return None, _not_found()
    brain = _brain_from(stored)
    if brain is None:
        return None, error(409, "policy_outdated", "This policy was saved by an older version of the app. Please upload it again.", headers=NO_STORE)
    return brain, None


# ------------------------------------------------------------------ POST /api/policy/{id}/ask  (A19)
_limiter = ask_service.QuestionLimiter()


def question_limiter() -> ask_service.QuestionLimiter:
    return _limiter


MAX_BODY_BYTES = 8 * 1024


@router.post("/policy/{policy_id}/ask")
async def ask_policy(policy_id: str, request: Request,
                     uid: str = Depends(current_uid),
                     store: PolicyStore = Depends(get_policy_store),
                     tracker: JobTracker = Depends(get_tracker),
                     gemini: GeminiClient = Depends(gemini_client),
                     limiter: ask_service.QuestionLimiter = Depends(question_limiter)):
    """Body: {"question": str (<= 500 chars), "lang": "en"|"hi"|"mr"}.
    200 {answer, citations[{page, clause}], grounded, fallback, lang, disclaimer}. Not grounded -> fixed fallback text."""
    # 1) input (cheap checks first; nothing below runs for a malformed request)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return error(413, "question_too_long", "Please keep your question short.", headers=NO_STORE)
    try:
        body = json.loads(raw or b"null")
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return error(422, "invalid_request", 'Send JSON like {"question": "...", "lang": "en"}.', headers=NO_STORE)
    try:
        question, lang = ask_service.clean_question(body.get("question")), ask_service.check_lang(body.get("lang"))
    except ask_service.QuestionError as e:
        return error(422, e.code, e.message, headers=NO_STORE)

    # 2) policy + ownership (same 404 for "not yours" and "does not exist")
    brain, err = await _load_brain(policy_id, uid, store, tracker)
    if err is not None:
        return err

    # 3) per-user throttle, then the answer
    wait = limiter.check(uid)
    if wait:
        return error(429, "too_many_questions", f"Please wait {wait} seconds before asking again.",
                     headers={**NO_STORE, "Retry-After": str(wait)})
    try:
        result = await ask_service.answer_question(brain, question, lang, gemini)
    except GeminiBusy as e:
        return error(503, e.error_code, e.message, headers={**NO_STORE, "Retry-After": "30"})
    except GeminiRequestError:
        return error(503, "ai_unavailable", "Our AI service is not available right now. Please try again later.", headers=NO_STORE)
    except GeminiError as e:
        return error(503, e.error_code, e.message, headers=NO_STORE)
    log.info("ask policy_id=%s lang=%s grounded=%s reason=%s model=%s", policy_id, lang, result.grounded, result.reason, result.model)
    return JSONResponse(result.to_dict(), headers=NO_STORE)


# ------------------------------------------------------------------ GET /api/policy/{id}/suggestions  (A20)
@router.get("/policy/{policy_id}/suggestions")
async def policy_suggestions(policy_id: str, lang: str = "en",
                             uid: str = Depends(current_uid),
                             store: PolicyStore = Depends(get_policy_store),
                             tracker: JobTracker = Depends(get_tracker)):
    """`?lang=en|hi|mr` -> {policy_id, lang, suggestions: [{id, text}]}, at most 3, chosen by code (no Gemini call).
    Only questions this policy can answer with a citation are offered, so it can be fewer than 3 or empty."""
    try:
        lang = ask_service.check_lang(lang)
    except ask_service.QuestionError as e:
        return error(422, e.code, e.message, headers=NO_STORE)
    brain, err = await _load_brain(policy_id, uid, store, tracker)
    if err is not None:
        return err
    return JSONResponse({"policy_id": policy_id, "lang": lang, "suggestions": suggestions_service.suggest(brain, lang)},
                        headers={"Cache-Control": "private, max-age=300"})
