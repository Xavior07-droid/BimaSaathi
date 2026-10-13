"""In-memory ingest job tracker (A12). Powers GET /api/policy/{id}/status while extraction runs in the background.

Why in memory and not Firestore: status flips 3-4 times per upload; keeping it in RAM costs 0 Firestore writes
(free tier = 20k writes/day) and the finished policy is in Firestore anyway. Trade-off: if Render restarts or
sleeps mid-job the status is lost and the client sees 404, which the UI treats as "upload again".

Also the guard rail for the free tier: a cap on active jobs per user and overall, because each job holds up to
15 MB of upload in RAM (Render free = 512 MB) and costs 1-3 Gemini calls.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Literal

STAGES = ("uploading", "reading", "understanding", "done")        # the 4 progress states the UI shows
DEFAULT_PROGRESS = {"uploading": 10, "reading": 30, "understanding": 65, "done": 100}
SAVING_PROGRESS = 90                                               # shown inside "understanding"

MAX_ACTIVE_JOBS = 6
MAX_JOBS_PER_USER = 2
FINISHED_TTL_SECONDS = 15 * 60

Status = Literal["processing", "done", "failed"]


class JobLimit(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code, self.message = error_code, message


@dataclass
class Job:
    policy_id: str
    owner_uid: str
    file_hash: str
    status: Status = "processing"
    stage: str = "uploading"
    progress: int = DEFAULT_PROGRESS["uploading"]
    error: dict | None = None                       # {error_code, message} when failed
    created_at: float = 0.0
    finished_at: float | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


class JobTracker:
    def __init__(self, *, max_active: int = MAX_ACTIVE_JOBS, max_per_user: int = MAX_JOBS_PER_USER,
                 ttl: float = FINISHED_TTL_SECONDS, clock: Callable[[], float] = time.monotonic):
        self.max_active, self.max_per_user, self.ttl, self._clock = max_active, max_per_user, ttl, clock
        self._jobs: dict[str, Job] = {}

    # -- queries
    def _prune(self) -> None:
        now = self._clock()
        for pid in [p for p, j in self._jobs.items() if j.finished_at is not None and now - j.finished_at > self.ttl]:
            del self._jobs[pid]

    def _active(self) -> list[Job]:
        return [j for j in self._jobs.values() if j.status == "processing"]

    def active_for(self, owner_uid: str, file_hash: str) -> Job | None:
        """Same user + same bytes already being processed -> reuse it (no duplicate policy, no extra Gemini call)."""
        self._prune()
        return next((j for j in self._active() if j.owner_uid == owner_uid and j.file_hash == file_hash), None)

    def active_for_owner(self, owner_uid: str) -> list[Job]:
        self._prune()
        return [j for j in self._active() if j.owner_uid == owner_uid]

    def get(self, policy_id: str, owner_uid: str) -> Job | None:
        """Owner-only: another user's job looks exactly like a job that does not exist."""
        self._prune()
        job = self._jobs.get(policy_id)
        return job if job is not None and job.owner_uid == owner_uid else None

    # -- lifecycle
    def start(self, owner_uid: str, file_hash: str, policy_id: str) -> Job:
        self._prune()
        active = self._active()
        if sum(j.owner_uid == owner_uid for j in active) >= self.max_per_user:
            raise JobLimit("too_many_uploads", "You already have policies being read. Wait for them to finish, then try again.")
        if len(active) >= self.max_active:
            raise JobLimit("server_busy", "Many people are uploading right now. Please retry in a minute.")
        job = Job(policy_id=policy_id, owner_uid=owner_uid, file_hash=file_hash, created_at=self._clock())
        self._jobs[policy_id] = job
        return job

    def set_stage(self, job: Job, stage: str, progress: int | None = None) -> None:
        if job.status != "processing":
            return
        job.stage = stage
        job.progress = progress if progress is not None else DEFAULT_PROGRESS[stage]

    def finish(self, job: Job) -> None:
        job.status, job.stage, job.progress, job.finished_at = "done", "done", 100, self._clock()

    def fail(self, job: Job, error_code: str, message: str) -> None:
        job.status, job.error, job.finished_at = "failed", {"error_code": error_code, "message": message}, self._clock()


@lru_cache
def get_tracker() -> JobTracker:
    return JobTracker()
