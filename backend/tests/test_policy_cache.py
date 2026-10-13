"""A11: hash cache. FakeGemini with an empty script raises IndexError if Gemini is called, so 'no call' is enforced."""
import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.models.policy import PolicyBrain
from app.services import policy_cache as PC
from app.services.gemini import GeminiClient, GeminiRequestError
from app.services.pdf import sha256_hex
from tests.test_policy_brain import CLEAN, GOOD, MANIFEST, FakeGemini, pdf_bytes


class SlowGemini(FakeGemini):
    async def generate_json(self, contents, **kw):
        await asyncio.sleep(0.02)
        return await super().generate_json(contents, **kw)


class BrokenStore:
    def find_by_hash(self, file_hash, owner_uid):
        raise RuntimeError("firestore down")


@pytest.fixture(autouse=True)
def _clean_inflight():
    PC._inflight.clear()
    yield
    PC._inflight.clear()


async def _first(store, owner="alice", data=CLEAN):
    g = FakeGemini([GOOD])
    res = await PC.ingest_cached(data, store=store, owner_uid=owner, gemini=g)
    store.save_policy(res.brain, owner)
    return res, g


async def test_miss_extracts_once_and_reports_hash():
    store = PC.InMemoryPolicyStore()
    res, g = await _first(store)
    assert res.cache == "miss" and not res.from_cache and len(g.calls) == 1
    assert res.file_hash == sha256_hex(CLEAN) == res.brain.extraction_meta.file_hash


async def test_same_user_same_file_is_a_hit_with_zero_gemini_calls():
    store = PC.InMemoryPolicyStore()
    first, _ = await _first(store)
    g = FakeGemini([])                                          # any call -> IndexError
    again = await PC.ingest_cached(CLEAN, store=store, owner_uid="alice", gemini=g)
    assert again.cache == "hit" and again.from_cache and g.calls == []
    assert again.brain.policy_id == first.brain.policy_id and again.brain == first.brain


async def test_other_user_same_file_gets_shared_hit_under_new_policy_id():
    store = PC.InMemoryPolicyStore()
    first, _ = await _first(store, owner="alice")
    g = FakeGemini([])
    res = await PC.ingest_cached(CLEAN, store=store, owner_uid="bob", gemini=g)
    assert res.cache == "hit_shared" and g.calls == []
    assert res.brain.policy_id != first.brain.policy_id
    assert res.brain.model_dump(exclude={"policy_id"}) == first.brain.model_dump(exclude={"policy_id"})
    assert store.find_by_hash(res.file_hash, "alice").data["policy_id"] == first.brain.policy_id   # original untouched


async def test_own_copy_is_preferred_over_someone_elses():
    store = PC.InMemoryPolicyStore()
    a, _ = await _first(store, owner="alice")
    store.save_policy(a.brain.model_copy(update={"policy_id": "bobs-copy"}), "bob")
    res = await PC.ingest_cached(CLEAN, store=store, owner_uid="bob", gemini=FakeGemini([]))
    assert res.cache == "hit" and res.brain.policy_id == "bobs-copy"


async def test_different_bytes_are_a_miss():
    store = PC.InMemoryPolicyStore()
    await _first(store)
    other = pdf_bytes(MANIFEST[1]["file"])
    g = FakeGemini([GOOD])
    res = await PC.ingest_cached(other, store=store, owner_uid="alice", gemini=g)
    assert res.cache == "miss" and len(g.calls) == 1


async def test_store_error_is_a_miss_not_a_failure():
    g = FakeGemini([GOOD])
    res = await PC.ingest_cached(CLEAN, store=BrokenStore(), owner_uid="alice", gemini=g)
    assert res.cache == "miss" and len(g.calls) == 1


@pytest.mark.parametrize("break_it", [
    lambda d: d["extraction_meta"].update(schema_version="0.1"),
    lambda d: d.update(sum_insured="not a number"),
    lambda d: d.update(surprise_field=1),
], ids=["old_schema_version", "invalid_value", "unknown_field"])
async def test_stale_or_corrupt_stored_doc_is_re_extracted(break_it):
    store = PC.InMemoryPolicyStore()
    first, _ = await _first(store)
    doc = first.brain.to_store()
    break_it(doc)
    store._docs.clear()
    store.save_policy(doc, "alice")
    g = FakeGemini([GOOD])
    res = await PC.ingest_cached(CLEAN, store=store, owner_uid="alice", gemini=g)
    assert res.cache == "miss" and len(g.calls) == 1


async def test_mock_mode_skips_the_store_entirely():
    g = GeminiClient(Settings(_env_file=None, gemini_api_key=""), client=SimpleNamespace())
    res = await PC.ingest_cached(b"not a pdf", store=BrokenStore(), owner_uid="alice", gemini=g)
    assert res.cache == "mock" and res.brain.policy_id == "sample-policy"


async def test_same_user_double_upload_in_flight_costs_one_extraction():
    g = SlowGemini([GOOD])
    store = PC.InMemoryPolicyStore()
    r1, r2 = await asyncio.gather(*(PC.ingest_cached(CLEAN, store=store, owner_uid="alice", gemini=g) for _ in range(2)))
    assert len(g.calls) == 1 and r1.cache == r2.cache == "miss"
    assert r1.brain.policy_id == r2.brain.policy_id and r1.brain is not r2.brain
    assert PC._inflight == {}


async def test_two_users_in_flight_are_not_merged():
    g = SlowGemini([GOOD, GOOD])
    store = PC.InMemoryPolicyStore()
    a, b = await asyncio.gather(PC.ingest_cached(CLEAN, store=store, owner_uid="alice", gemini=g),
                                PC.ingest_cached(CLEAN, store=store, owner_uid="bob", gemini=g))
    assert len(g.calls) == 2 and a.brain.policy_id != b.brain.policy_id


async def test_one_waiter_cancelling_does_not_kill_the_extraction():
    g = SlowGemini([GOOD])
    store = PC.InMemoryPolicyStore()
    t1 = asyncio.create_task(PC.ingest_cached(CLEAN, store=store, owner_uid="alice", gemini=g))
    t2 = asyncio.create_task(PC.ingest_cached(CLEAN, store=store, owner_uid="alice", gemini=g))
    await asyncio.sleep(0.005)
    t1.cancel()
    res = await t2
    assert res.cache == "miss" and len(g.calls) == 1 and t1.cancelled()


async def test_failure_reaches_every_waiter_and_is_not_cached():
    store = PC.InMemoryPolicyStore()
    g = SlowGemini([GeminiRequestError("bad key")])
    results = await asyncio.gather(*(PC.ingest_cached(CLEAN, store=store, owner_uid="alice", gemini=g) for _ in range(2)),
                                   return_exceptions=True)
    assert all(isinstance(r, GeminiRequestError) for r in results) and len(g.calls) == 1
    assert PC._inflight == {}
    retry = await PC.ingest_cached(CLEAN, store=store, owner_uid="alice", gemini=FakeGemini([GOOD]))
    assert retry.cache == "miss"


async def test_in_memory_store_contract():
    s = PC.InMemoryPolicyStore()
    assert s.find_by_hash("x", "alice") is None
    first, _ = await _first(s, owner="alice")
    h = first.file_hash
    assert s.find_by_hash(h, "alice").owner_uid == "alice"
    assert s.find_by_hash(h, "bob").owner_uid == "alice"          # no own copy -> any copy
    assert s.find_by_hash(h, None).owner_uid == "alice"
    assert s.find_by_hash("other", "alice") is None
