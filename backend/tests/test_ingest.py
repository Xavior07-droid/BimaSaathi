"""A12: POST /api/ingest + GET /api/policy/{id}/status, end to end through FastAPI (fake Gemini, in-memory store)."""
import asyncio
import io
from types import SimpleNamespace

import httpx
import pymupdf
import pytest
from fastapi import FastAPI
from fastapi.requests import Request
from PIL import Image

from app.config import Settings, get_settings
from app.routers import deps
from app.routers import ingest as I
from app.services import policy_cache as PC
from app.services.gemini import GeminiBusy, GeminiClient, GeminiRequestError
from app.services.ingest_jobs import JobTracker, get_tracker
from tests.test_policy_brain import CLEAN, GOOD, MANIFEST, FakeGemini, bad, pdf_bytes


class SlowGemini(FakeGemini):
    """Holds each call until `release` is set, so tests can observe the 'processing' states."""
    def __init__(self, script):
        super().__init__(script)
        self.release = asyncio.Event()

    async def generate_json(self, contents, **kw):
        await self.release.wait()
        return await super().generate_json(contents, **kw)


class Ctx:
    def __init__(self):
        self.store = PC.InMemoryPolicyStore()
        self.tracker = JobTracker()
        self.gemini = FakeGemini([GOOD])
        self.settings = Settings(_env_file=None, max_upload_mb=1)
        self.app = FastAPI()
        self.app.include_router(I.router)
        o = self.app.dependency_overrides
        o[deps.get_policy_store] = lambda: self.store
        o[get_tracker] = lambda: self.tracker
        o[deps.gemini_client] = lambda: self.gemini
        o[get_settings] = lambda: self.settings
        o[deps.current_uid] = self._uid

    @staticmethod
    async def _uid(request: Request) -> str:
        return request.headers.get("x-test-uid", "alice")

    def client(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")

    async def upload(self, c, data=CLEAN, uid="alice", name="policy.pdf", ctype="application/pdf"):
        return await c.post("/api/ingest", files={"file": (name, data, ctype)}, headers={"x-test-uid": uid})

    async def status(self, c, pid, uid="alice"):
        return await c.get(f"/api/policy/{pid}/status", headers={"x-test-uid": uid})

    async def finish_jobs(self):
        await asyncio.gather(*(j.task for j in self.tracker._jobs.values() if j.task), return_exceptions=True)


@pytest.fixture
def ctx():
    PC._inflight.clear()
    return Ctx()


# ------------------------------------------------------------------ happy path
async def test_upload_runs_in_background_then_status_done_and_saved(ctx):
    async with ctx.client() as c:
        r = await ctx.upload(c)
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "processing" and body["cached"] is False and body["poll_after_ms"] > 0
        pid = body["policy_id"]
        await ctx.finish_jobs()
        s = (await ctx.status(c, pid)).json()
    assert s["status"] == "done" and s["stage"] == "done" and s["progress"] == 100 and s["error"] is None
    stored = ctx.store.get_policy(pid)
    assert stored.owner_uid == "alice" and stored.data["policy_id"] == pid
    assert stored.data["extraction_meta"]["file_hash"] == PC.sha256_hex(CLEAN)
    rem = ctx.store.reminders[pid]
    assert rem["owner_uid"] == "alice" and rem["renewal_date"] == GOOD["renewal_date"] and rem["sent_flags"] == []
    assert len(ctx.gemini.calls) == 1


async def test_status_shows_understanding_while_gemini_runs(ctx):
    ctx.gemini = SlowGemini([GOOD])
    async with ctx.client() as c:
        pid = (await ctx.upload(c)).json()["policy_id"]
        await asyncio.sleep(0.05)
        s = (await ctx.status(c, pid)).json()
        assert s["status"] == "processing" and s["stage"] == "understanding" and s["progress"] == 65
        ctx.gemini.release.set()
        await ctx.finish_jobs()
        assert (await ctx.status(c, pid)).json()["status"] == "done"


async def test_jpg_photo_is_accepted(ctx):
    buf = io.BytesIO(); Image.new("RGB", (600, 800), "white").save(buf, "JPEG")
    ctx.gemini = FakeGemini([bad(sub_limits=[], covered=[], exclusions=[])])
    async with ctx.client() as c:
        r = await ctx.upload(c, buf.getvalue(), name="photo.jpg", ctype="image/jpeg")
        assert r.status_code == 202
        await ctx.finish_jobs()
        assert (await ctx.status(c, r.json()["policy_id"])).json()["status"] == "done"


# ------------------------------------------------------------------ cache
async def test_same_user_second_upload_is_instant_cache_hit(ctx):
    async with ctx.client() as c:
        pid = (await ctx.upload(c)).json()["policy_id"]
        await ctx.finish_jobs()
        r = await ctx.upload(c)
    b = r.json()
    assert r.status_code == 200 and b["status"] == "done" and b["cached"] and b["cache"] == "hit"
    assert b["policy_id"] == pid and b["policy"]["policy_id"] == pid and len(ctx.gemini.calls) == 1


async def test_other_user_same_file_gets_own_copy_without_gemini(ctx):
    async with ctx.client() as c:
        pid_a = (await ctx.upload(c, uid="alice")).json()["policy_id"]
        await ctx.finish_jobs()
        r = await ctx.upload(c, uid="bob")
        pid_b = r.json()["policy_id"]
        assert r.status_code == 200 and r.json()["cache"] == "hit_shared" and pid_b != pid_a
        assert ctx.store.get_policy(pid_b).owner_uid == "bob" and pid_b in ctx.store.reminders
        assert (await ctx.status(c, pid_b, uid="bob")).json()["status"] == "done"
        assert (await ctx.status(c, pid_b, uid="alice")).status_code == 404       # not alice's
    assert len(ctx.gemini.calls) == 1


async def test_double_upload_while_processing_follows_the_same_job(ctx):
    ctx.gemini = SlowGemini([GOOD])
    async with ctx.client() as c:
        r1, r2 = await ctx.upload(c), await ctx.upload(c)
        assert r1.status_code == r2.status_code == 202 and r1.json()["policy_id"] == r2.json()["policy_id"]
        ctx.gemini.release.set()
        await ctx.finish_jobs()
    assert len(ctx.gemini.calls) == 1 and len(ctx.store._docs) == 1


# ------------------------------------------------------------------ validation
async def test_too_large_file_is_413(ctx):
    async with ctx.client() as c:
        r = await ctx.upload(c, b"%PDF-" + b"0" * (1024 * 1024 + 10))
    assert r.status_code == 413 and r.json()["error_code"] == "file_too_large" and "1 MB" in r.json()["message"]


async def test_declared_content_length_is_checked_before_reading(ctx):
    async with ctx.client() as c:
        r = await c.post("/api/ingest", files={"file": ("a.pdf", b"%PDF-1", "application/pdf")},
                         headers={"content-length": str(10 ** 9)})
    assert r.status_code == 413 and r.json()["error_code"] == "file_too_large"


async def test_chunked_upload_without_length_is_411(ctx):
    async def gen():
        yield b"abc"
    async with ctx.client() as c:
        r = await c.post("/api/ingest", content=gen(), headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 411 and r.json()["error_code"] == "length_required"


@pytest.mark.parametrize("data,name,ctype", [
    (b"MZ\x90\x00 pretend exe", "policy.pdf", "application/pdf"),         # wrong bytes, right name + Content-Type
    (b"just some text", "policy.txt", "text/plain"),
    (b"GIF89a....", "policy.gif", "image/gif"),
])
async def test_unsupported_types_are_415_by_magic_bytes(ctx, data, name, ctype):
    async with ctx.client() as c:
        r = await ctx.upload(c, data, name=name, ctype=ctype)
    assert r.status_code == 415 and r.json()["error_code"] == "unsupported_type"
    assert ctx.gemini.calls == [] and ctx.store._docs == {}


async def test_empty_file_and_missing_field(ctx):
    async with ctx.client() as c:
        r1 = await ctx.upload(c, b"")
        r2 = await c.post("/api/ingest", files={"other": ("a.pdf", b"%PDF-1", "application/pdf")})
    assert (r1.status_code, r1.json()["error_code"]) == (400, "empty_file")
    assert (r2.status_code, r2.json()["error_code"]) == (400, "no_file")


async def test_corrupt_pdf_is_rejected_immediately_not_after_polling(ctx):
    async with ctx.client() as c:
        r = await ctx.upload(c, b"%PDF-1.4\nthis is not really a pdf")
    assert r.status_code == 422 and r.json()["error_code"] == "unreadable_file" and ctx.tracker._jobs == {}


async def test_password_protected_pdf_is_422(ctx):
    doc = pymupdf.open(); doc.new_page()
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    async with ctx.client() as c:
        r = await ctx.upload(c, locked)
    assert r.status_code == 422 and r.json()["error_code"] == "password_protected"


async def test_error_shape_is_error_code_and_message_only(ctx):
    async with ctx.client() as c:
        r = await ctx.upload(c, b"nope")
    assert set(r.json()) == {"error_code", "message"}


# ------------------------------------------------------------------ failures in the background job
async def _failed(ctx, gemini):
    ctx.gemini = gemini
    async with ctx.client() as c:
        pid = (await ctx.upload(c)).json()["policy_id"]
        await ctx.finish_jobs()
        r = await ctx.status(c, pid)
        assert r.status_code == 200                                   # failure is reported in the body, not as HTTP error
        return r.json(), pid


async def test_gemini_busy_becomes_friendly_failed_status(ctx):
    s, pid = await _failed(ctx, FakeGemini([GeminiBusy("Our AI service is busy right now. Please retry in a minute.")] * 3))
    assert s["status"] == "failed" and s["error"]["error_code"] == "ai_busy" and "retry in a minute" in s["error"]["message"]
    assert ctx.store.get_policy(pid) is None


async def test_unreadable_extraction_is_failed_status(ctx):
    s, _ = await _failed(ctx, FakeGemini([bad(copay_percent=150)] * 3))
    assert s["status"] == "failed" and s["error"]["error_code"] == "extraction_failed"


async def test_gemini_config_error_does_not_leak_details(ctx):
    s, _ = await _failed(ctx, FakeGemini([GeminiRequestError("key AIza-SECRET rejected")]))
    assert s["error"]["error_code"] == "ai_unavailable" and "SECRET" not in str(s) and "AIza" not in str(s)


async def test_unexpected_exception_is_internal_error_without_text(ctx):
    s, _ = await _failed(ctx, FakeGemini([RuntimeError("db password is hunter2")]))
    assert s["error"]["error_code"] == "internal_error" and "hunter2" not in str(s)


async def test_failed_job_does_not_block_a_retry(ctx):
    async with ctx.client() as c:
        ctx.gemini = FakeGemini([GeminiBusy("busy")] * 3)
        await ctx.upload(c); await ctx.finish_jobs()
        ctx.gemini = FakeGemini([GOOD])
        r = await ctx.upload(c)
        assert r.status_code == 202
        await ctx.finish_jobs()
        assert (await ctx.status(c, r.json()["policy_id"])).json()["status"] == "done"


async def test_store_write_failure_is_save_failed(ctx):
    ctx.store.save_policy = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("firestore quota"))
    s, _ = await _failed(ctx, FakeGemini([GOOD]))
    assert s["error"]["error_code"] == "save_failed" and "quota" not in str(s)


async def test_reminder_write_failure_does_not_lose_the_policy(ctx):
    ctx.store.save_reminder = lambda r: (_ for _ in ()).throw(RuntimeError("boom"))
    async with ctx.client() as c:
        pid = (await ctx.upload(c)).json()["policy_id"]
        await ctx.finish_jobs()
        assert (await ctx.status(c, pid)).json()["status"] == "done"
    assert ctx.store.get_policy(pid) is not None


# ------------------------------------------------------------------ limits, privacy
async def test_per_user_job_cap_is_429(ctx):
    ctx.gemini = SlowGemini([GOOD, GOOD, GOOD])
    files = [pdf_bytes(MANIFEST[i]["file"]) for i in range(3)]
    async with ctx.client() as c:
        rs = [await ctx.upload(c, f) for f in files]
        assert [r.status_code for r in rs] == [202, 202, 429]
        assert rs[2].json()["error_code"] == "too_many_uploads" and rs[2].headers["retry-after"]
        other = await ctx.upload(c, files[2], uid="bob")                 # another user is not blocked
        assert other.status_code == 202
        ctx.gemini.release.set()
        await ctx.finish_jobs()


async def test_global_job_cap_is_429(ctx):
    ctx.tracker = JobTracker(max_active=1)
    ctx.gemini = SlowGemini([GOOD, GOOD])
    async with ctx.client() as c:
        assert (await ctx.upload(c, uid="alice")).status_code == 202
        r = await ctx.upload(c, pdf_bytes(MANIFEST[1]["file"]), uid="bob")
        assert r.status_code == 429 and r.json()["error_code"] == "server_busy"
        ctx.gemini.release.set()
        await ctx.finish_jobs()


def test_uploads_stay_in_memory_not_in_temp_files():
    from starlette.formparsers import MultiPartParser
    assert MultiPartParser.spool_max_size > get_settings().max_upload_bytes


async def test_stored_document_contains_facts_only_never_the_file(ctx):
    async with ctx.client() as c:
        pid = (await ctx.upload(c)).json()["policy_id"]
        await ctx.finish_jobs()
    dumped = str(ctx.store.get_policy(pid).data) + str(ctx.store.reminders[pid])
    assert "%PDF" not in dumped and "stream" not in dumped.lower()


# ------------------------------------------------------------------ status endpoint
async def test_status_unknown_id_and_other_users_job_are_both_404(ctx):
    ctx.gemini = SlowGemini([GOOD])
    async with ctx.client() as c:
        assert (await ctx.status(c, "nope")).status_code == 404
        pid = (await ctx.upload(c, uid="alice")).json()["policy_id"]
        r = await ctx.status(c, pid, uid="mallory")
        assert r.status_code == 404 and r.json()["error_code"] == "not_found"
        assert r.headers["cache-control"] == "no-store"
        ctx.gemini.release.set()
        await ctx.finish_jobs()


async def test_status_of_policy_saved_before_a_restart_comes_from_the_store(ctx):
    ctx.store.save_policy({**GOOD, "policy_id": "old-1"}, "alice")
    ctx.tracker = JobTracker()                                           # fresh process, empty tracker
    async with ctx.client() as c:
        s = (await ctx.status(c, "old-1")).json()
        assert s["status"] == "done" and s["progress"] == 100
        assert (await ctx.status(c, "old-1", uid="bob")).status_code == 404


# ------------------------------------------------------------------ mock mode
async def test_mock_mode_returns_sample_under_fresh_id_and_still_validates_files(ctx):
    ctx.gemini = GeminiClient(Settings(_env_file=None, gemini_api_key=""), client=SimpleNamespace())
    async with ctx.client() as c:
        r1 = await ctx.upload(c)
        r2 = await ctx.upload(c)
        bad_r = await ctx.upload(c, b"%PDF-1.4 garbage")
    b1, b2 = r1.json(), r2.json()
    assert r1.status_code == 200 and b1["status"] == "done" and b1["cache"] == "mock"
    assert b1["policy_id"] != "sample-policy" and b1["policy_id"] != b2["policy_id"]
    assert ctx.store.get_policy(b1["policy_id"]).owner_uid == "alice" and b1["policy"]["insurer"]
    assert bad_r.status_code == 422


# ------------------------------------------------------------------ dev auth stub / tracker
@pytest.mark.skipif(not deps.USING_DEV_AUTH, reason="M's real auth is wired in")
async def test_dev_auth_stub_is_closed_unless_enabled(ctx, monkeypatch):
    del ctx.app.dependency_overrides[deps.current_uid]
    async with ctx.client() as c:
        r = await c.get("/api/policy/x/status")
        assert r.status_code == 503 and r.json()["detail"]["error_code"] == "auth_not_configured"
        monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(dev_auth=True))
        assert (await c.get("/api/policy/x/status", headers={"x-dev-uid": "u1"})).status_code == 404


def test_tracker_ttl_prunes_only_finished_jobs():
    t = [0.0]
    tr = JobTracker(ttl=10, clock=lambda: t[0])
    done, running = tr.start("u", "h1", "p1"), tr.start("u", "h2", "p2")
    tr.finish(done)
    t[0] = 11
    assert tr.get("p1", "u") is None and tr.get("p2", "u") is running
    assert tr.get("p2", "someone-else") is None


def test_tracker_stage_updates_stop_after_finish():
    tr = JobTracker()
    j = tr.start("u", "h", "p")
    tr.set_stage(j, "reading"); assert (j.stage, j.progress) == ("reading", 30)
    tr.finish(j); tr.set_stage(j, "understanding"); assert (j.stage, j.progress) == ("done", 100)
