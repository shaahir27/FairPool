"""Deterministic job queue fake (T01A02)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.fakes.clock import FakeClock


@dataclass
class FakeJob:
    id: UUID
    kind: str
    payload: dict[str, Any]
    run_at: datetime
    concurrency_key: str | None = None
    dedupe_key: str | None = None
    status: str = "PENDING"
    attempts: int = 0


@dataclass
class FakeJobQueue:
    clock: FakeClock = field(default_factory=FakeClock)
    jobs: list[FakeJob] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def enqueue(
        self,
        session: AsyncSession,
        kind: str,
        payload: dict[str, Any],
        *,
        run_at: datetime | None = None,
        concurrency_key: str | None = None,
        dedupe_key: str | None = None,
    ) -> UUID | None:
        self.calls.append(f"enqueue:{kind}")
        coalesced_key = dedupe_key
        if dedupe_key is not None:
            for existing in self.jobs:
                if existing.dedupe_key == dedupe_key and existing.status == "PENDING":
                    # Same rule as ``infra/jobs.py``: the coalesced event is not lost,
                    # the earlier run_at wins (domain-ports.md section 5).
                    moment = run_at or self.clock.now
                    existing.run_at = min(existing.run_at, moment)
                    return None
                if existing.dedupe_key == dedupe_key and existing.status == "RUNNING":
                    # A running handler may have read its counts already, so this event
                    # gets its own row with no dedupe key instead of being merged into
                    # it (``infra/jobs.py`` enqueue).
                    coalesced_key = None
        job = FakeJob(
            id=uuid4(),
            kind=kind,
            payload=dict(payload),
            run_at=run_at or self.clock.now,
            concurrency_key=concurrency_key,
            dedupe_key=coalesced_key,
        )
        self.jobs.append(job)
        return job.id

    def run_due(self, now: datetime | None = None) -> list[FakeJob]:
        moment = now or self.clock.now
        return [job for job in self.jobs if job.status == "PENDING" and job.run_at <= moment]

    def complete(self, job_id: UUID) -> None:
        for job in self.jobs:
            if job.id == job_id:
                job.status = "DONE"
                return
        raise KeyError(job_id)

    def fail(self, job_id: UUID) -> None:
        for job in self.jobs:
            if job.id == job_id:
                job.status = "FAILED"
                return
        raise KeyError(job_id)
