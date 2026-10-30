"""Postgres job queue and async runner (T01A02; domain-ports.md section 5).

The claim statement takes a short global advisory lock: ``NOT EXISTS`` alone
races when two workers claim different rows that share a concurrency key.
Every claim also re-queues RUNNING rows whose lease expired, so a killed
worker never strands a job.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fairpool.ports import JobQueue

logger = logging.getLogger("fairpool.jobs")

CLAIM_LOCK = 0x46414952504F4F4D
MAX_BACKOFF_SECONDS = 256

JobHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


class PostgresJobQueue(JobQueue):
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
        job_id = uuid4()
        inserted = await session.scalar(
            text(
                "INSERT INTO jobs "
                "(id, kind, run_at, payload, concurrency_key, dedupe_key) "
                "VALUES (:id, :kind, COALESCE(CAST(:run_at AS timestamptz), now()), "
                "CAST(:payload AS jsonb), :concurrency_key, :dedupe_key) "
                "ON CONFLICT (dedupe_key) "
                "WHERE dedupe_key IS NOT NULL AND status IN ('PENDING','RUNNING') "
                "DO NOTHING RETURNING id"
            ),
            {
                "id": job_id,
                "kind": kind,
                "run_at": run_at,
                "payload": json.dumps(payload),
                "concurrency_key": concurrency_key,
                "dedupe_key": dedupe_key,
            },
        )
        return job_id if inserted is not None else None

    async def claim(
        self,
        session: AsyncSession,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 300,
    ) -> list[ClaimedJob]:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CLAIM_LOCK})
        await session.execute(
            text(
                "UPDATE jobs SET status = 'PENDING', locked_by = NULL, locked_until = NULL "
                "WHERE status = 'RUNNING' AND locked_until < now()"
            )
        )
        rows = (
            await session.execute(
                text(
                    "SELECT j.id, j.concurrency_key FROM jobs j "
                    "WHERE j.status = 'PENDING' AND j.run_at <= now() "
                    "AND (j.concurrency_key IS NULL OR NOT EXISTS ("
                    "  SELECT 1 FROM jobs r WHERE r.status = 'RUNNING' "
                    "  AND r.concurrency_key = j.concurrency_key)) "
                    "ORDER BY j.run_at, j.created_at "
                    "LIMIT :limit FOR UPDATE SKIP LOCKED"
                ),
                {"limit": limit},
            )
        ).all()
        seen_keys: set[str] = set()
        ids: list[UUID] = []
        for job_id, concurrency_key in rows:
            if concurrency_key is not None:
                if concurrency_key in seen_keys:
                    continue
                seen_keys.add(concurrency_key)
            ids.append(job_id)
        claimed: list[ClaimedJob] = []
        for job_id in ids:
            row = (
                await session.execute(
                    text(
                        "UPDATE jobs SET status = 'RUNNING', locked_by = :worker, "
                        "locked_until = now() + make_interval(secs => :lease), "
                        "attempts = attempts + 1 "
                        "WHERE id = :id "
                        "RETURNING id, kind, payload, attempts, max_attempts"
                    ),
                    {"worker": worker_id, "lease": lease_seconds, "id": job_id},
                )
            ).one()
            claimed.append(
                ClaimedJob(
                    id=row[0],
                    kind=row[1],
                    payload=row[2],
                    attempts=row[3],
                    max_attempts=row[4],
                )
            )
        return claimed

    async def complete(self, session: AsyncSession, job_id: UUID) -> None:
        await session.execute(
            text(
                "UPDATE jobs SET status = 'DONE', locked_by = NULL, locked_until = NULL "
                "WHERE id = :id AND status = 'RUNNING'"
            ),
            {"id": job_id},
        )

    async def fail(self, session: AsyncSession, job_id: UUID, error: str) -> None:
        await session.execute(
            text(
                "UPDATE jobs SET "
                "status = CASE WHEN attempts >= max_attempts THEN 'FAILED'::job_status "
                "ELSE 'PENDING'::job_status END, "
                "run_at = CASE WHEN attempts >= max_attempts THEN run_at "
                "ELSE now() + make_interval(secs => "
                "  LEAST(POWER(2, attempts), :cap)) END, "
                "locked_by = NULL, locked_until = NULL, last_error = :error "
                "WHERE id = :id"
            ),
            {"id": job_id, "error": error[:2000], "cap": MAX_BACKOFF_SECONDS},
        )


class JobRunner:
    def __init__(
        self,
        queue: PostgresJobQueue,
        session_factory: async_sessionmaker[AsyncSession],
        handlers: Mapping[str, JobHandler],
        *,
        worker_id: str,
        batch_size: int = 10,
        lease_seconds: int = 300,
        poll_interval_s: float = 1.0,
    ) -> None:
        self.queue = queue
        self.session_factory = session_factory
        self.handlers = dict(handlers)
        self.worker_id = worker_id
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.poll_interval_s = poll_interval_s

    async def run_once(self) -> int:
        async with self.session_factory() as session:
            async with session.begin():
                jobs = await self.queue.claim(
                    session,
                    worker_id=self.worker_id,
                    limit=self.batch_size,
                    lease_seconds=self.lease_seconds,
                )
        for job in jobs:
            handler = self.handlers.get(job.kind)
            async with self.session_factory() as session:
                async with session.begin():
                    if handler is None:
                        await self.queue.fail(session, job.id, f"no handler for {job.kind}")
                        continue
                    try:
                        await handler(session, job.payload)
                    except Exception as exc:
                        await self.queue.fail(session, job.id, type(exc).__name__)
                    else:
                        await self.queue.complete(session, job.id)
        return len(jobs)

    async def run_forever(self, stop_event: threading.Event) -> None:
        logger.info("job_runner.started worker=%s handlers=%d", self.worker_id, len(self.handlers))
        while not stop_event.is_set():
            try:
                claimed = await self.run_once()
            except Exception as exc:
                logger.error("job_runner.error type=%s", type(exc).__name__)
                claimed = 0
            if claimed == 0:
                await asyncio.sleep(self.poll_interval_s)
        logger.info("job_runner.stopped worker=%s", self.worker_id)
