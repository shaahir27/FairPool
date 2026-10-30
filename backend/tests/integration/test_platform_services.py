"""T01A02: real Postgres clock, audit, idempotency and job queue."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fairpool.domain.hashing import audit_hash
from fairpool.infra.audit import ZERO_HASH, PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.infra.jobs import JobRunner, PostgresJobQueue
from fairpool.ports import (
    AuditLog,
    Clock,
    IdemConflict,
    IdemNew,
    IdempotencyStore,
    IdemReplay,
    JobQueue,
)


def test_real_implementations_satisfy_their_ports():
    assert isinstance(DbClock(), Clock)
    assert isinstance(PostgresJobQueue(), JobQueue)
    assert isinstance(PostgresAuditLog(), AuditLog)
    assert isinstance(PostgresIdempotencyStore(), IdempotencyStore)


def factory_for(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def verify_audit_chain(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT prev_hash, hash, actor, action, subject_type, subject_id, "
                    "payload, created_at FROM audit_log ORDER BY seq"
                )
            )
        ).all()
    previous = ZERO_HASH
    for row in rows:
        document = {
            "actor": row.actor,
            "action": row.action,
            "subject_type": row.subject_type,
            "subject_id": row.subject_id,
            "payload": row.payload,
            "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }
        assert row.prev_hash == previous
        assert row.hash == audit_hash(previous, document)
        previous = row.hash


async def clean_test_jobs(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        async with session.begin():
            await session.execute(text("DELETE FROM jobs WHERE kind LIKE 'test.%'"))


async def test_clock_reads_the_database_time(db_session: AsyncSession):
    now = await DbClock().db_now(db_session)
    assert now.tzinfo is not None
    delta = abs((datetime.now(UTC) - now).total_seconds())
    assert delta < 10


async def test_audit_rows_link_with_the_domain_hash(db_session: AsyncSession):
    audit = PostgresAuditLog()
    for index in range(3):
        await audit.append(
            db_session,
            actor="test.audit.sequence",
            action=f"step.{index}",
            subject_type="test",
            subject_id=str(index),
            payload={"index": index},
        )
    rows = (
        await db_session.execute(
            text(
                "SELECT prev_hash, hash, actor, action, subject_type, subject_id, "
                "payload, created_at FROM audit_log ORDER BY seq"
            )
        )
    ).all()
    previous = ZERO_HASH
    for row in rows:
        document = {
            "actor": row.actor,
            "action": row.action,
            "subject_type": row.subject_type,
            "subject_id": row.subject_id,
            "payload": row.payload,
            "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }
        assert row.prev_hash == previous
        assert row.hash == audit_hash(previous, document)
        previous = row.hash


async def test_audit_appends_serialise_across_connections(db_engine: AsyncEngine):
    factory = factory_for(db_engine)
    audit = PostgresAuditLog()

    async def append_actor(actor: str) -> None:
        async with factory() as session:
            async with session.begin():
                await audit.append(
                    session,
                    actor=actor,
                    action="concurrent",
                    subject_type="test",
                    subject_id=None,
                    payload={"actor": actor},
                )

    await asyncio.gather(
        append_actor(f"test.audit.concurrent.{uuid4()}"),
        append_actor(f"test.audit.concurrent.{uuid4()}"),
    )
    await verify_audit_chain(factory)


async def test_idempotency_store_new_replay_and_conflicts(db_session: AsyncSession):
    store = PostgresIdempotencyStore()
    key = f"test-idem-{uuid4()}"
    scope = "test.scope"
    request_hash = "a" * 64

    assert isinstance(
        await store.begin(db_session, key=key, scope=scope, request_hash=request_hash),
        IdemNew,
    )
    assert isinstance(
        await store.begin(db_session, key=key, scope=scope, request_hash=request_hash),
        IdemConflict,
    )
    await store.complete(db_session, key=key, response={"ok": True})
    replay = await store.begin(db_session, key=key, scope=scope, request_hash=request_hash)
    assert isinstance(replay, IdemReplay)
    assert replay.response == {"ok": True}
    assert isinstance(
        await store.begin(db_session, key=key, scope=scope, request_hash="b" * 64),
        IdemConflict,
    )
    assert isinstance(
        await store.begin(db_session, key=key, scope="other", request_hash=request_hash),
        IdemConflict,
    )


async def test_job_queue_dedupe_and_backoff(db_session: AsyncSession):
    queue = PostgresJobQueue()
    await db_session.execute(text("DELETE FROM jobs WHERE kind LIKE 'test.%'"))
    kind = f"test.jobs.{uuid4()}"
    dedupe = f"dedupe-{uuid4()}"
    first = await queue.enqueue(db_session, kind, {"n": 1}, dedupe_key=dedupe)
    assert first is not None
    assert await queue.enqueue(db_session, kind, {"n": 2}, dedupe_key=dedupe) is None

    claimed = await queue.claim(db_session, worker_id="test", limit=10)
    job = next(item for item in claimed if item.id == first)
    assert job.attempts == 1
    await queue.fail(db_session, first, "boom")
    row = (
        await db_session.execute(
            text("SELECT status, run_at, attempts FROM jobs WHERE id = :id"), {"id": first}
        )
    ).one()
    assert row.status == "PENDING"
    assert row.run_at > datetime.now(UTC)

    again = await queue.claim(db_session, worker_id="test", limit=10)
    assert all(item.id != first for item in again)

    await db_session.execute(
        text("UPDATE jobs SET run_at = now() - interval '1 second' WHERE id = :id"),
        {"id": first},
    )
    again = await queue.claim(db_session, worker_id="test", limit=10)
    retried = next(item for item in again if item.id == first)
    assert retried.attempts == 2

    await db_session.execute(text("UPDATE jobs SET max_attempts = 1 WHERE id = :id"), {"id": first})
    await queue.fail(db_session, first, "boom again")
    status = await db_session.scalar(text("SELECT status FROM jobs WHERE id = :id"), {"id": first})
    assert status == "FAILED"


async def test_job_queue_honours_concurrency_keys(db_engine: AsyncEngine):
    factory = factory_for(db_engine)
    queue = PostgresJobQueue()
    await clean_test_jobs(factory)
    key = f"ck-{uuid4()}"
    kind = f"test.concurrent.{uuid4()}"
    async with factory() as session:
        async with session.begin():
            assert await queue.enqueue(session, kind, {"n": 1}, concurrency_key=key)
            assert await queue.enqueue(session, kind, {"n": 2}, concurrency_key=key)

    async def claim(worker: str):
        async with factory() as session:
            async with session.begin():
                return await queue.claim(session, worker_id=worker, limit=10)

    first, second = await asyncio.gather(claim("w1"), claim("w2"))
    assert len(first) + len(second) == 1
    await clean_test_jobs(factory)


async def test_job_queue_reclaims_an_expired_lease(db_engine: AsyncEngine):
    factory = factory_for(db_engine)
    queue = PostgresJobQueue()
    await clean_test_jobs(factory)
    kind = f"test.lease.{uuid4()}"
    async with factory() as session:
        async with session.begin():
            job_id = await queue.enqueue(session, kind, {})
    assert job_id is not None
    async with factory() as session:
        async with session.begin():
            claimed = await queue.claim(session, worker_id="first", limit=50, lease_seconds=1)
    claimed_ids = [job.id for job in claimed]
    assert claimed_ids.count(job_id) == 1

    for _ in range(100):
        async with factory() as wait_session:
            expired = await wait_session.scalar(
                text(
                    "SELECT now() > locked_until + interval '100 milliseconds' "
                    "FROM jobs WHERE id = :id"
                ),
                {"id": job_id},
            )
        if expired:
            break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError("job lease did not expire")

    async with factory() as session:
        async with session.begin():
            reclaimed = await queue.claim(session, worker_id="second", limit=50)
    reclaimed_ids = [job.id for job in reclaimed]
    assert reclaimed_ids.count(job_id) == 1
    await clean_test_jobs(factory)


async def test_job_runner_completes_and_retries(db_engine: AsyncEngine):
    factory = factory_for(db_engine)
    queue = PostgresJobQueue()
    await clean_test_jobs(factory)
    ok_kind = f"test.runner.ok.{uuid4()}"
    fail_kind = f"test.runner.fail.{uuid4()}"
    async with factory() as session:
        async with session.begin():
            await queue.enqueue(session, ok_kind, {})
            await queue.enqueue(session, fail_kind, {})

    seen: list[str] = []

    async def ok_handler(session: AsyncSession, payload: dict[str, object]) -> None:
        seen.append("ok")

    async def fail_handler(session: AsyncSession, payload: dict[str, object]) -> None:
        raise RuntimeError("handler failed")

    runner = JobRunner(
        queue,
        factory,
        {ok_kind: ok_handler, fail_kind: fail_handler},
        worker_id="test-runner",
        batch_size=10,
    )
    assert await runner.run_once() == 2
    assert seen == ["ok"]

    async with factory() as session:
        rows = (
            await session.execute(
                text("SELECT kind, status, attempts FROM jobs WHERE kind IN (:ok, :fail)"),
                {"ok": ok_kind, "fail": fail_kind},
            )
        ).all()
    by_kind = {row.kind: row for row in rows}
    assert by_kind[ok_kind].status == "DONE"
    assert by_kind[fail_kind].status == "PENDING"
    assert by_kind[fail_kind].attempts == 1

    async with factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "UPDATE jobs SET run_at = now() - interval '1 second', "
                    "max_attempts = 1 WHERE kind = :kind"
                ),
                {"kind": fail_kind},
            )
    assert await runner.run_once() == 1
    async with factory() as session:
        status = await session.scalar(
            text("SELECT status FROM jobs WHERE kind = :kind"), {"kind": fail_kind}
        )
    assert status == "FAILED"
    await clean_test_jobs(factory)


async def test_worker_runner_stops_on_the_event(db_engine: AsyncEngine, monkeypatch):
    from fairpool import worker

    monkeypatch.setattr(worker, "get_engine", lambda: db_engine)
    stop = threading.Event()
    stop.set()
    await worker.run_worker({}, stop, poll_interval_s=0.01)
