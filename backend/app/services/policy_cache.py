"""Hash cache (A11): same file bytes -> no second Gemini call (saves free-tier quota).

    bytes --sha256--> store.find_by_hash() --hit--> PolicyBrain (zero Gemini calls, zero PDF parsing)
                                           \\-miss--> ingest_document() (A9, 1-3 Gemini calls)

Lives in A's lane; the actual storage is M's `store.py` (Firestore, with an in-memory fallback). This module
only needs the tiny `PolicyStore` interface below, so it works today with `InMemoryPolicyStore` and later with
M's Firestore store unchanged. It does NOT save: A12's /api/ingest saves the returned brain with its owner.

Privacy rule (the spec's "return it immediately" is unsafe across users): a hit is classified by owner.
- hit        the same user uploaded these exact bytes before -> return their own policy as is.
- hit_shared ANOTHER user uploaded these exact bytes -> reuse the extracted FACTS under a NEW policy_id.
             Whoever holds identical bytes already holds the content, so nothing new is revealed; but the
             other user's policy_id / owner never leave the store.
Same-user duplicates in flight (double tap, retry) are collapsed into one extraction.

The cache is an optimisation, never a dependency: a store error or a stored document that no longer validates
(schema drift) is treated as a miss and the file is extracted normally.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from pydantic import ValidationError

from app.models.policy import SCHEMA_VERSION, PolicyBrain
from app.services.gemini import GeminiClient, get_gemini
from app.services.pdf import ParsedDocument, sha256_hex
from app.services.policy_brain import ingest_document, new_policy_id

log = logging.getLogger("bimasaathi.policy_cache")

CacheStatus = Literal["miss", "hit", "hit_shared", "mock"]


# ------------------------------------------------------------------ store interface (M implements for Firestore)
@dataclass(frozen=True)
class StoredPolicy:
    data: dict                    # PolicyBrain.to_store() output
    owner_uid: str | None


class PolicyStore(Protocol):
    """What A's code needs from M's store.py (Firestore). All methods are synchronous; callers use to_thread."""

    def find_by_hash(self, file_hash: str, owner_uid: str | None) -> StoredPolicy | None:
        """Policy whose extraction_meta.file_hash == file_hash. Prefer one owned by `owner_uid`; otherwise any."""
        ...

    def get_policy(self, policy_id: str) -> StoredPolicy | None:
        """policies/{policy_id}: PolicyBrain dict (WITHOUT owner_uid inside `data`) + its owner."""
        ...

    def list_policies(self, owner_uid: str, limit: int = 50) -> list[StoredPolicy]:
        """This user's policies, any order (callers sort; do NOT add an order_by: it would need a composite index)."""
        ...

    def save_policy(self, data: dict, owner_uid: str) -> None:
        """Write policies/{data['policy_id']} = data + owner_uid. Overwrites."""
        ...

    def save_reminder(self, reminder: dict) -> None:
        """Write reminders/{reminder['policy_id']} (see docs/api-ingest.md for the fields)."""
        ...


class InMemoryPolicyStore:
    """Dev/test store. Same behaviour contract as the Firestore one M will provide."""

    def __init__(self) -> None:
        self._docs: dict[str, StoredPolicy] = {}          # policy_id -> doc
        self.reminders: dict[str, dict] = {}              # policy_id -> reminder

    def save_policy(self, data: PolicyBrain | dict, owner_uid: str | None) -> None:
        data = data.to_store() if isinstance(data, PolicyBrain) else data
        self._docs[data["policy_id"]] = StoredPolicy(data=data, owner_uid=owner_uid)

    def get_policy(self, policy_id: str) -> StoredPolicy | None:
        return self._docs.get(policy_id)

    def list_policies(self, owner_uid: str, limit: int = 50) -> list[StoredPolicy]:
        return [d for d in self._docs.values() if d.owner_uid == owner_uid][:limit]

    def save_reminder(self, reminder: dict) -> None:
        self.reminders[reminder["policy_id"]] = reminder

    def find_by_hash(self, file_hash: str, owner_uid: str | None) -> StoredPolicy | None:
        matches = [d for d in self._docs.values() if d.data.get("extraction_meta", {}).get("file_hash") == file_hash]
        own = [d for d in matches if owner_uid is not None and d.owner_uid == owner_uid]
        return (own or matches or [None])[0]


# ------------------------------------------------------------------ result
@dataclass
class IngestResult:
    brain: PolicyBrain
    file_hash: str
    cache: CacheStatus

    @property
    def from_cache(self) -> bool:
        return self.cache in ("hit", "hit_shared")


# ------------------------------------------------------------------ lookup
def _usable(stored: StoredPolicy) -> PolicyBrain | None:
    """Stored dict -> PolicyBrain, or None if it is stale/corrupt (then we simply re-extract)."""
    try:
        brain = PolicyBrain.model_validate(stored.data)
    except ValidationError:
        log.warning("cached policy failed validation (schema drift?); treating as miss")
        return None
    if brain.extraction_meta.schema_version != SCHEMA_VERSION:
        log.info("cached policy has schema_version=%s (current %s); treating as miss",
                 brain.extraction_meta.schema_version, SCHEMA_VERSION)
        return None
    return brain


async def lookup_cached(store: PolicyStore, file_hash: str, owner_uid: str | None) -> tuple[PolicyBrain, CacheStatus] | None:
    try:
        stored = await asyncio.to_thread(store.find_by_hash, file_hash, owner_uid)
    except Exception:  # noqa: BLE001 - cache must never block an upload
        log.exception("cache lookup failed; continuing without cache")
        return None
    if stored is None:
        return None
    brain = _usable(stored)
    if brain is None:
        return None
    if owner_uid is not None and stored.owner_uid == owner_uid:
        return brain, "hit"
    return brain.model_copy(update={"policy_id": new_policy_id()}, deep=True), "hit_shared"


# ------------------------------------------------------------------ in-flight de-duplication
_inflight: dict[tuple[str | None, str], asyncio.Task[PolicyBrain]] = {}


def _forget(key: tuple[str | None, str]):
    def _cb(task: asyncio.Task) -> None:
        _inflight.pop(key, None)
        if not task.cancelled():
            task.exception()           # mark retrieved: avoids "never retrieved" noise if every waiter left
    return _cb


async def _extract_once(key: tuple[str | None, str], data: bytes, gemini: GeminiClient,
                        parsed: ParsedDocument | None = None) -> PolicyBrain:
    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(ingest_document(data, gemini=gemini, parsed=parsed))
        _inflight[key] = task
        task.add_done_callback(_forget(key))
    # shield: one waiter disconnecting must not cancel the extraction the others are waiting for
    brain = await asyncio.shield(task)
    return brain.model_copy(deep=True)


# ------------------------------------------------------------------ public entry
async def ingest_cached(data: bytes, *, store: PolicyStore, owner_uid: str | None,
                        gemini: GeminiClient | None = None, lookup: bool = True,
                        parsed: ParsedDocument | None = None,
                        on_stage: Callable[[str], None] | None = None) -> IngestResult:
    """bytes -> PolicyBrain, using the hash cache. Raises what ingest_document raises (PdfError, GeminiBusy,
    ExtractionFailed). The caller (A12) validates type/size first and saves the result with `owner_uid`.

    lookup=False: the caller already did `lookup_cached` (A12 does, to answer cache hits synchronously).
    parsed: an already-parsed document (skips a second PyMuPDF pass).
    on_stage("reading" | "understanding"): progress hook for the status endpoint."""
    gemini = gemini or get_gemini()
    file_hash = sha256_hex(data)
    stage = on_stage or (lambda _s: None)

    if gemini.mock_mode:                                   # offline dev: always the sample policy, never the store
        return IngestResult(await ingest_document(data, gemini=gemini), file_hash, "mock")

    stage("reading")
    if lookup:
        found = await lookup_cached(store, file_hash, owner_uid)
        if found is not None:
            brain, status = found
            log.info("cache %s file_hash=%s...", status, file_hash[:8])
            return IngestResult(brain, file_hash, status)

    stage("understanding")
    brain = await _extract_once((owner_uid, file_hash), data, gemini, parsed)
    return IngestResult(brain, file_hash, "miss")
