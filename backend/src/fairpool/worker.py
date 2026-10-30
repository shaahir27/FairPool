"""Worker entrypoint (T00A03, async job runner T01A02).

The queue-backed runner claims jobs from Postgres and runs registered
handlers; the registry is empty until the engine phases add handlers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
from collections.abc import Mapping
from types import FrameType

from sqlalchemy.ext.asyncio import async_sessionmaker

from fairpool.config import get_settings
from fairpool.db.session import get_engine
from fairpool.infra.jobs import JobHandler, JobRunner, PostgresJobQueue
from fairpool.logging import configure_logging

logger = logging.getLogger("fairpool.worker")


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
    asyncio.run(run_worker({}, stop_event))


if __name__ == "__main__":
    main()
