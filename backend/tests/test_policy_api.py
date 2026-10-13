"""A13: GET /api/policy/{id} and GET /api/policies."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models.policy import PolicyBrain
from app.routers import policy as P
from app.services import policy_cache as PC
from app.services.mock_policy import load_sample_policy
from tests.test_ingest import CLEAN, GOOD, Ctx, FakeGemini, SlowGemini

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


class Ctx2(Ctx):
    def __init__(self):
        super().__init__()
        self.app.include_router(P.router)

    def put(self, owner, pid, minutes=0, **over):
        """Save a valid policy (sample brain, which has summaries + red flags) for `owner`."""
        b = load_sample_policy()
        b = b.model_copy(update={"policy_id": pid, **over,
                                 "extraction_meta": b.extraction_meta.model_copy(update={"created_at": T0 + timedelta(minutes=minutes), "file_hash": f"hash-{pid}"})})
        self.store.save_policy(b.to_store(), owner)
        return b

    async def get(self, c, path, uid="alice"):
        return await c.get(path, headers={"x-test-uid": uid})


@pytest.fixture
def ctx():
    PC._inflight.clear()
    return Ctx2()


# ------------------------------------------------------------------ GET /api/policy/{id}
async def test_owner_gets_full_policy_without_owner_uid(ctx):
    b = ctx.put("alice", "p1")
    async with ctx.client() as c:
        r = await ctx.get(c, "/api/policy/p1")
    assert r.status_code == 200 and r.json() == json.loads(b.model_dump_json())
    assert "owner_uid" not in r.json() and r.headers["cache-control"] == "private, no-store"
    PolicyBrain.model_validate(r.json())                                    # the response is a valid Policy Brain


async def test_owner_uid_is_stripped_even_if_the_store_leaks_it(ctx):
    ctx.put("alice", "p1")
    ctx.store._docs["p1"].data["owner_uid"] = "alice"
    async with ctx.client() as c:
        r = await ctx.get(c, "/api/policy/p1")
    assert r.status_code == 200 and "owner_uid" not in r.json()


async def test_other_users_policy_and_unknown_id_look_identical(ctx):
    ctx.put("alice", "p1")
    async with ctx.client() as c:
        theirs = await ctx.get(c, "/api/policy/p1", uid="mallory")
        unknown = await ctx.get(c, "/api/policy/zzz", uid="mallory")
    assert theirs.status_code == unknown.status_code == 404
    assert theirs.json() == unknown.json() == {"error_code": "not_found", "message": "We could not find this policy."}


@pytest.mark.parametrize("bad_id", ["..", "__secret__", "a" * 65, "a.b", "a%20b", "a$b"])
async def test_malformed_ids_are_404_without_touching_the_store(ctx, bad_id):
    calls = []
    ctx.store.get_policy = lambda pid: calls.append(pid)
    async with ctx.client() as c:
        r = await ctx.get(c, f"/api/policy/{bad_id}")
    assert r.status_code == 404 and calls == []


async def test_sample_policy_is_readable_by_anyone_and_never_hits_the_store(ctx):
    ctx.store.get_policy = lambda pid: (_ for _ in ()).throw(AssertionError("store must not be read"))
    async with ctx.client() as c:
        a, b = await ctx.get(c, "/api/policy/sample-policy", "alice"), await ctx.get(c, "/api/policy/sample-policy", "bob")
    assert a.status_code == b.status_code == 200 and a.json()["policy_id"] == "sample-policy"
    assert a.json()["plain_summary"]["hi"] and a.json()["red_flags"]


async def test_policy_still_being_read_is_409_then_200_when_done(ctx):
    ctx.gemini = SlowGemini([GOOD])
    async with ctx.client() as c:
        pid = (await ctx.upload(c)).json()["policy_id"]
        early = await ctx.get(c, f"/api/policy/{pid}")
        assert early.status_code == 409 and early.json()["error_code"] == "still_processing"
        other = await ctx.get(c, f"/api/policy/{pid}", uid="mallory")
        assert other.status_code == 404                                          # someone else's job is invisible
        ctx.gemini.release.set()
        await ctx.finish_jobs()
        done = await ctx.get(c, f"/api/policy/{pid}")
    assert done.status_code == 200 and done.json()["policy_id"] == pid and done.json()["insurer"] == GOOD["insurer"]


async def test_failed_upload_has_no_policy(ctx):
    from app.services.gemini import GeminiBusy
    ctx.gemini = FakeGemini([GeminiBusy("busy")] * 3)
    async with ctx.client() as c:
        pid = (await ctx.upload(c)).json()["policy_id"]
        await ctx.finish_jobs()
        r = await ctx.get(c, f"/api/policy/{pid}")
    assert r.status_code == 404


async def test_schema_drifted_document_is_409_outdated(ctx):
    ctx.put("alice", "p1")
    ctx.store._docs["p1"].data["sum_insured"] = "not a number"
    async with ctx.client() as c:
        r = await ctx.get(c, "/api/policy/p1")
    assert r.status_code == 409 and r.json()["error_code"] == "policy_outdated"


async def test_store_failure_is_503_without_details(ctx):
    ctx.store.get_policy = lambda pid: (_ for _ in ()).throw(RuntimeError("firestore password hunter2"))
    async with ctx.client() as c:
        r = await ctx.get(c, "/api/policy/p1")
    assert r.status_code == 503 and r.json()["error_code"] == "store_unavailable" and "hunter2" not in r.text


# ------------------------------------------------------------------ GET /api/policies
async def test_list_is_empty_for_new_user(ctx):
    async with ctx.client() as c:
        r = await ctx.get(c, "/api/policies")
    assert r.status_code == 200 and r.json() == {"policies": []}


async def test_list_has_only_my_policies_newest_first_as_light_cards(ctx):
    ctx.put("alice", "old", minutes=1); ctx.put("alice", "new", minutes=30); ctx.put("bob", "bobs", minutes=99)
    async with ctx.client() as c:
        r = await ctx.get(c, "/api/policies")
    items = r.json()["policies"]
    assert [i["policy_id"] for i in items] == ["new", "old"]
    it = items[0]
    assert it["status"] == "done" and it["insurer"] and it["renewal_date"] and it["has_summary"] is True
    assert it["red_flag_count"] == len(load_sample_policy().red_flags)
    assert not {"covered", "exclusions", "sub_limits", "plain_summary", "owner_uid"} & set(it)     # light card only
    assert r.headers["cache-control"] == "private, no-store"


async def test_list_puts_policies_being_read_first_and_hides_failed_ones(ctx):
    from app.services.gemini import GeminiBusy
    ctx.put("alice", "done1")
    ctx.gemini = SlowGemini([GOOD])
    async with ctx.client() as c:
        pid = (await ctx.upload(c)).json()["policy_id"]
        await asyncio.sleep(0.05)
        items = (await ctx.get(c, "/api/policies")).json()["policies"]
        assert [i["policy_id"] for i in items] == [pid, "done1"]
        assert items[0] == {"policy_id": pid, "status": "processing", "stage": "understanding", "progress": 65}
        assert (await ctx.get(c, "/api/policies", uid="bob")).json() == {"policies": []}
        ctx.gemini.release.set()
        await ctx.finish_jobs()
        after = (await ctx.get(c, "/api/policies")).json()["policies"]
        assert sorted(i["policy_id"] for i in after) == sorted([pid, "done1"]) and all(i["status"] == "done" for i in after)

        ctx.gemini = FakeGemini([GeminiBusy("busy")] * 3)
        from tests.test_policy_brain import pdf_bytes, MANIFEST
        await ctx.upload(c, pdf_bytes(MANIFEST[1]["file"])); await ctx.finish_jobs()
        assert len((await ctx.get(c, "/api/policies")).json()["policies"]) == 2        # failed upload is not listed


async def test_one_corrupt_document_does_not_break_the_list(ctx):
    ctx.put("alice", "good", minutes=5); ctx.put("alice", "broken", minutes=9)
    ctx.store._docs["broken"].data["premium"] = "oops"
    async with ctx.client() as c:
        r = await ctx.get(c, "/api/policies")
    assert [i["policy_id"] for i in r.json()["policies"]] == ["good"]


async def test_list_is_capped_and_ignores_foreign_docs_returned_by_a_sloppy_store(ctx):
    for n in range(P.MAX_LIST + 5):
        ctx.put("alice", f"p{n:03d}", minutes=n)
    ctx.put("bob", "bobs")
    ctx.store.list_policies = lambda owner, limit=50: list(ctx.store._docs.values())[:limit] + [ctx.store._docs["bobs"]]
    async with ctx.client() as c:
        ids = [i["policy_id"] for i in (await ctx.get(c, "/api/policies")).json()["policies"]]
    assert "bobs" not in ids and len(ids) <= P.MAX_LIST


async def test_list_store_failure_is_503(ctx):
    ctx.store.list_policies = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    async with ctx.client() as c:
        r = await ctx.get(c, "/api/policies")
    assert r.status_code == 503 and r.json()["error_code"] == "store_unavailable"


async def test_uploaded_policy_appears_in_list_and_opens(ctx):
    async with ctx.client() as c:
        pid = (await ctx.upload(c)).json()["policy_id"]
        await ctx.finish_jobs()
        lst = (await ctx.get(c, "/api/policies")).json()["policies"]
        doc = (await ctx.get(c, f"/api/policy/{pid}")).json()
    assert [i["policy_id"] for i in lst] == [pid] and doc["policy_id"] == pid
    assert lst[0]["has_summary"] is False and lst[0]["sum_insured"] == GOOD["sum_insured"]       # A16 adds summaries later
