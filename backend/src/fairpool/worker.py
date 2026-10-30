"""Worker entrypoint (T00A03): polling loop, JSON logs, graceful shutdown.

There is no job queue until T01A02; `run` accepts an empty handler registry and
waits on the stop event. Handlers will be registered by kind then.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Mapping
from types import FrameType

from fairpool.config import get_settings
from fairpool.logging import configure_logging

logger = logging.getLogger("fairpool.worker")

JobHandler = Callable[[], None]


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


def run(
    handlers: Mapping[str, JobHandler] | None = None,
    stop_event: threading.Event | None = None,
    *,
    poll_interval_s: float = 1.0,
) -> None:
    """Poll until stopped. The registry is empty until the job queue lands."""
    registry = dict(handlers or {})
    stop = stop_event if stop_event is not None else threading.Event()
    logger.info("worker.started handlers=%d", len(registry))
    try:
        while not stop.is_set():
            logger.debug("worker.poll handlers=%d", len(registry))
            stop.wait(poll_interval_s)
    except KeyboardInterrupt:
        stop.set()
    finally:
        logger.info("worker.stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop_event = threading.Event()
    install_signal_handlers(stop_event)
    run({}, stop_event)


if __name__ == "__main__":
    main()
