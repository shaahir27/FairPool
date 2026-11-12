"""Worker entrypoint (T00A03, async job runner T01A02, reconciler cron T06A03).

The queue-backed runner claims jobs from Postgres and runs registered handlers.

``main`` also starts the one scheduler this process owes the contract: the
``reconciler.sweep`` cron (``domain-ports.md`` section 5). It runs in its own daemon
thread so a slow sweep can never hold up the claim loop, and it shares the worker's
stop event so one SIGTERM ends both.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
from collections.abc import Mapping
from types import FrameType
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fairpool.config import get_settings
from fairpool.db.session import create_engine, get_engine
from fairpool.infra.jobs import JobHandler, JobRunner, PostgresJobQueue
from fairpool.logging import configure_logging

logger = logging.getLogger("fairpool.worker")

#: The sweep's contracted keys (``domain-ports.md`` section 5): one ``reconciler``
#: concurrency key and the same dedupe key, so ticks coalesce instead of piling up.
RECONCILER_KIND: Final[str] = "reconciler.sweep"
RECONCILER_KEY: Final[str] = "reconciler"
#: CR-17: demand formation rides the same cron, with its own keys so a pending sweep
#: coalesces independently of the payment reconciler.
DEMAND_KIND: Final[str] = "demand.sweep"
DEMAND_KEY: Final[str] = "demand"


def install_signal_handlers(stop_event: threading.Event) -> None:
    """SIGINT and SIGTERM set the stop event instead of killing mid-job."""

    def _request_stop(signum: int, frame: FrameType | None) -> None:
        logger.info("worker.signal name=%s", signal.Signals(signum).name)
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signum, _request_stop)
        except (ValueError, OSError):
            # Windows does not support every signal; the stop event still works.
            logger.debug("worker.signal_unsupported name=%s", signum)


async def reconciler_tick(session_factory: async_sessionmaker[AsyncSession]) -> UUID | None:
    """Enqueue one ``reconciler.sweep``; ``None`` when one is already waiting (I9).

    The dedupe key is the contract's own, so a sweep still pending from the previous
    interval absorbs this tick instead of queueing a second one behind the
    ``reconciler`` concurrency key.
    """
    async with session_factory.begin() as session:
        queue = PostgresJobQueue()
        job_id = await queue.enqueue(
            session,
            RECONCILER_KIND,
            {},
            concurrency_key=RECONCILER_KEY,
            dedupe_key=RECONCILER_KEY,
        )
        await queue.enqueue(
            session,
            DEMAND_KIND,
            {},
            concurrency_key=DEMAND_KEY,
            dedupe_key=DEMAND_KEY,
        )
    if job_id is not None:
        # Once per enqueue; ids only, because the sweep's payload is empty by contract.
        logger.info("worker.reconciler_tick.enqueued kind=%s job_id=%s", RECONCILER_KIND, job_id)
    return job_id


def run_reconciler_cron(stop_event: threading.Event, *, interval_s: float) -> None:
    """Tick :func:`reconciler_tick` every ``interval_s`` until ``stop_event`` is set.

    The cron owns its engine: an asyncpg connection belongs to the event loop that
    opened it, so this thread cannot borrow the runner's. A failed tick is logged as
    a type name only and retried on the next interval; nothing escapes the thread.
    """
    interval = max(1.0, float(interval_s))

    async def _loop() -> None:
        engine = create_engine(get_settings())
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            while not stop_event.is_set():
                try:
                    await reconciler_tick(factory)
                except Exception as exc:
                    logger.error("worker.reconciler_tick.failed type=%s", type(exc).__name__)
                await asyncio.to_thread(stop_event.wait, interval)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_loop())
    except Exception as exc:  # pragma: no cover - a broken loop must not kill the worker
        logger.error("worker.reconciler_cron.failed type=%s", type(exc).__name__)


def start_reconciler_thread(stop_event: threading.Event, *, interval_s: float) -> threading.Thread:
    """Start the sweep cron as a daemon thread bound to the worker's stop event."""
    thread = threading.Thread(
        target=run_reconciler_cron,
        args=(stop_event,),
        kwargs={"interval_s": interval_s},
        name="fairpool-reconciler",
        daemon=True,
    )
    thread.start()
    return thread


async def run_worker(
    handlers: Mapping[str, JobHandler] | None = None,
    stop_event: threading.Event | None = None,
    *,
    worker_id: str | None = None,
    poll_interval_s: float = 1.0,
) -> None:
    stop = stop_event if stop_event is not None else threading.Event()
    engine = get_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    runner = JobRunner(
        PostgresJobQueue(),
        factory,
        handlers or {},
        worker_id=worker_id or f"worker-{os.getpid()}",
        poll_interval_s=poll_interval_s,
    )
    try:
        await runner.run_forever(stop)
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop_event = threading.Event()
    install_signal_handlers(stop_event)
    from fairpool.wiring import worker_handlers

    start_reconciler_thread(stop_event, interval_s=float(settings.reconciler_interval_s))
    try:
        asyncio.run(run_worker(worker_handlers(settings), stop_event))
    finally:
        # The claim loop is gone, so the cron has nothing left to schedule.
        stop_event.set()


if __name__ == "__main__":
    main()
