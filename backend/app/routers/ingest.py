"""POST /api/ingest and GET /api/policy/{id}/status (A12).

Upload flow (all in memory; the original file is never written anywhere):
  1. size / type / readability checks  -> 4xx {error_code, message} immediately
  2. sha256 -> hash cache (A11)        -> 200 status=done right away (saves Gemini quota)
  3. otherwise a background job        -> 202 status=processing; the UI polls GET /api/policy/{id}/status
     stages: uploading -> reading -> understanding -> done   (or status=failed with {error_code, message})

Auth, store and Gemini are injected (see routers/deps.py) so M's real ones drop in without changes here.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.formparsers import MultiPartParser

from app.config import Settings, get_settings
from app.models.policy import PolicyBrain
from app.routers.deps import current_uid, error, gemini_client, get_policy_store
from app.services.gemini import GeminiBusy, GeminiClient, GeminiError, GeminiRequestError
from app.services.ingest_jobs import SAVING_PROGRESS, Job, JobLimit, JobTracker, get_tracker
from app.services.mock_policy import load_sample_policy
from app.services.pdf import ParsedDocument, PdfError, parse_document, sha256_hex, sniff_kind
from app.services.policy_brain import new_policy_id
from app.services.policy_cache import PolicyStore, ingest_cached, lookup_cached

log = logging.getLogger("bimasaathi.ingest")
router = APIRouter(prefix="/api", tags=["ingest"])

FORM_OVERHEAD_BYTES = 64 * 1024        # multipart boundaries + small fields on top of the file itself
POLL_AFTER_MS = 1500

# Memory-only uploads: Starlette spools multipart files larger than 1 MB to a temp file on DISK. Raise the spool
# threshold above the upload limit so a policy PDF never touches the filesystem (spec: "never persist the files").
MultiPartParser.spool_max_size = (get_settings().max_upload_mb * 1024 * 1024) + FORM_OVERHEAD_BYTES + 1


# ------------------------------------------------------------------ persistence
def _persist(store: PolicyStore, brain: PolicyBrain, owner_uid: str) -> None:
    """policies/{id} (must succeed) + reminders/{id} (best effort: a reminder problem must not lose the policy)."""
    store.save_policy(brain.to_store(), owner_uid)
    try:
        store.save_reminder({
            "policy_id": brain.policy_id, "owner_uid": owner_uid,
            "renewal_date": brain.renewal_date.isoformat() if brain.renewal_date else None,
            "insurer": brain.insurer, "policy_no": brain.policy_no, "premium": brain.premium,
            "sent_flags": [], "created_at": datetime.now(timezone.utc).isoformat()})
    except Exception:  # noqa: BLE001
        log.exception("reminder save failed policy_id=%s (policy itself was saved)", brain.policy_id)


# ------------------------------------------------------------------ response bodies
def _body(job: Job) -> dict:
    out = {"policy_id": job.policy_id, "status": job.status, "stage": job.stage, "progress": job.progress,
           "cached": False, "error": job.error}
    if job.status == "processing":
        out["poll_after_ms"] = POLL_AFTER_MS
    return out


def _done_body(policy_id: str, cache: str, policy: dict | None = None) -> dict:
    out = {"policy_id": policy_id, "status": "done", "stage": "done", "progress": 100,
           "cached": cache in ("hit", "hit_shared"), "cache": cache, "error": None}
    if policy is not None:
        out["policy"] = policy
    return out


# ------------------------------------------------------------------ background job
def _failure(exc: BaseException) -> tuple[str, str]:
    """Map an exception to a user-safe {error_code, message}. Raw exception text is never shown."""
    if isinstance(exc, PdfError):
        return exc.error_code, exc.message
    if isinstance(exc, GeminiBusy):
        return exc.error_code, exc.message
    if isinstance(exc, GeminiRequestError):               # our config problem (key / model id), not the user's
        return "ai_unavailable", "Our AI service is not available right now. Please try again later."
    if isinstance(exc, GeminiError):
        return exc.error_code, exc.message
    return "internal_error", "Something went wrong while reading your policy. Please try again."


async def _run_job(job: Job, data: bytes, parsed: ParsedDocument, store: PolicyStore, tracker: JobTracker,
                   gemini: GeminiClient) -> None:
    try:
        res = await ingest_cached(data, store=store, owner_uid=job.owner_uid, gemini=gemini, lookup=False,
                                  parsed=parsed, on_stage=lambda s: tracker.set_stage(job, s))
        brain = res.brain.model_copy(update={"policy_id": job.policy_id})
        tracker.set_stage(job, "understanding", SAVING_PROGRESS)
        try:
            await asyncio.to_thread(_persist, store, brain, job.owner_uid)
        except Exception:  # noqa: BLE001
            log.exception("policy save failed policy_id=%s", job.policy_id)
            tracker.fail(job, "save_failed", "We read your policy but could not save it. Please try again.")
            return
        tracker.finish(job)
        log.info("ingest done policy_id=%s model=%s", job.policy_id, brain.extraction_meta.model)
    except asyncio.CancelledError:
        tracker.fail(job, "interrupted", "The server restarted while reading your policy. Please upload it again.")
        raise
    except Exception as exc:  # noqa: BLE001 - everything becomes a failed status, never a hung spinner
        code, message = _failure(exc)
        if code in ("internal_error", "ai_unavailable"):
            log.exception("ingest failed policy_id=%s code=%s", job.policy_id, code)
        else:
            log.warning("ingest failed policy_id=%s code=%s", job.policy_id, code)
        tracker.fail(job, code, message)
    finally:
        del data                                           # drop our reference to the upload as early as possible


# ------------------------------------------------------------------ POST /api/ingest
@router.post("/ingest")
async def ingest(request: Request,
                 uid: str = Depends(current_uid),
                 store: PolicyStore = Depends(get_policy_store),
                 tracker: JobTracker = Depends(get_tracker),
                 gemini: GeminiClient = Depends(gemini_client),
                 settings: Settings = Depends(get_settings)):
    limit = settings.max_upload_bytes

    # 1. refuse oversized bodies BEFORE reading them (a declared length cannot be exceeded by a client)
    length = request.headers.get("content-length")
    if length is None:
        return error(411, "length_required", "Upload the file as a normal form upload.")
    if not length.isdigit():
        return error(400, "bad_request", "Invalid upload.")
    if int(length) > limit + FORM_OVERHEAD_BYTES:
        return error(413, "file_too_large", f"This file is larger than {settings.max_upload_mb} MB. Upload a smaller file.")

    # 2. read the single `file` field, in memory
    try:
        form = await request.form(max_files=1, max_fields=4)
    except Exception:  # noqa: BLE001 - malformed multipart
        return error(400, "bad_request", "We could not read the upload. Send the policy as the 'file' field.")
    try:
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            return error(400, "no_file", "Attach your policy as the 'file' field.")
        data = await upload.read()
    finally:
        await form.close()

    if not data:
        return error(400, "empty_file", "This file is empty.")
    if len(data) > limit:
        return error(413, "file_too_large", f"This file is larger than {settings.max_upload_mb} MB. Upload a smaller file.")
    if sniff_kind(data) is None:                                  # by magic bytes, never by name / Content-Type
        return error(415, "unsupported_type", "Upload a PDF, JPG or PNG file.")

    file_hash = sha256_hex(data)

    # 3. the same user already has this exact file being read -> follow that job
    running = tracker.active_for(uid, file_hash)
    if running is not None:
        return JSONResponse(_body(running), status_code=202)

    # 4. hash cache: answer immediately, no Gemini, no parsing
    if not gemini.mock_mode:
        found = await lookup_cached(store, file_hash, uid)
        if found is not None:
            brain, cache = found
            if cache == "hit_shared":                              # someone else's facts, new id for this user
                try:
                    await asyncio.to_thread(_persist, store, brain, uid)
                except Exception:  # noqa: BLE001
                    log.exception("save of shared cache hit failed")
                    return error(503, "save_failed", "We could not save your policy. Please try again.")
            return JSONResponse(_done_body(brain.policy_id, cache, brain.to_store()), status_code=200)

    # 5. is it a readable document? (corrupt / password-protected / too many pages are rejected now, not after a wait)
    try:
        parsed = await asyncio.to_thread(parse_document, data)
    except PdfError as e:
        return error(422, e.error_code, e.message)

    # 6. MOCK mode: no key -> sample policy under a fresh id, so the whole flow works offline
    if gemini.mock_mode:
        brain = load_sample_policy().model_copy(update={"policy_id": new_policy_id()})
        try:
            await asyncio.to_thread(_persist, store, brain, uid)
        except Exception:  # noqa: BLE001
            log.exception("mock save failed")
            return error(503, "save_failed", "We could not save your policy. Please try again.")
        return JSONResponse(_done_body(brain.policy_id, "mock", brain.to_store()), status_code=200)

    # 7. background job
    try:
        job = tracker.start(uid, file_hash, new_policy_id())
    except JobLimit as e:
        return error(429, e.error_code, e.message, headers={"Retry-After": "30"})
    job.task = asyncio.create_task(_run_job(job, data, parsed, store, tracker, gemini))
    return JSONResponse(_body(job), status_code=202)


# ------------------------------------------------------------------ GET /api/policy/{id}/status
@router.get("/policy/{policy_id}/status")
async def policy_status(policy_id: str,
                        uid: str = Depends(current_uid),
                        store: PolicyStore = Depends(get_policy_store),
                        tracker: JobTracker = Depends(get_tracker)):
    no_store = {"Cache-Control": "no-store"}
    job = tracker.get(policy_id, uid)
    if job is not None:
        return JSONResponse(_body(job), headers=no_store)
    stored = await asyncio.to_thread(store.get_policy, policy_id)
    if stored is not None and stored.owner_uid == uid:             # finished earlier / before a restart
        return JSONResponse(_done_body(policy_id, "stored"), headers=no_store)
    return error(404, "not_found", "We could not find this policy. Upload it again.", headers=no_store)
