"""T01A02: fake queue dedupe, due times and completion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fairpool.fakes.clock import FakeClock
from fairpool.fakes.jobs import FakeJobQueue


async def test_fake_queue_dedupes_pending_jobs_and_respects_run_at():
    start = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    clock = FakeClock(start)
    queue = FakeJobQueue(clock=clock)

    first = await queue.enqueue(
        None,
        "pool.open",
        {"pool_id": "p1"},
        concurrency_key="pool:p1",
        dedupe_key="pool:p1:open",
    )
    assert first is not None
    assert (
        await queue.enqueue(
            None,
            "pool.open",
            {"pool_id": "p1"},
            concurrency_key="pool:p1",
            dedupe_key="pool:p1:open",
        )
        is None
    )
    assert [job.kind for job in queue.run_due()] == ["pool.open"]

    queue.complete(first)
    assert queue.run_due() == []
    replacement = await queue.enqueue(
        None, "pool.open", {"pool_id": "p1"}, dedupe_key="pool:p1:open"
    )
    assert replacement is not None

    future = await queue.enqueue(
        None,
        "pool.close",
        {"pool_id": "p1"},
        run_at=start + timedelta(seconds=60),
    )
    assert future is not None
    assert [job.kind for job in queue.run_due()] == ["pool.open"]
    clock.advance(60)
    assert {job.kind for job in queue.run_due()} == {"pool.open", "pool.close"}
    assert queue.calls.count("enqueue:pool.open") == 3
