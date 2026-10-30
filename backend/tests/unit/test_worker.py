"""T00A03: the worker starts, logs JSON and stops promptly on a signal event."""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from collections.abc import Callable

import pytest
from _pytest.logging import LogCaptureFixture

from fairpool import worker
from fairpool.logging import JsonFormatter

LOGGER_NAME = "fairpool.worker"


def wait_until(predicate: Callable[[], bool], timeout_s: float = 0.9) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_worker_starts_logs_and_stops_within_one_second(caplog: LogCaptureFixture) -> None:
    stop_event = threading.Event()
    started_at = time.monotonic()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        thread = threading.Thread(
            target=worker.run,
            args=({},),
            kwargs={"stop_event": stop_event, "poll_interval_s": 60.0},
            daemon=True,
        )
        thread.start()
        assert wait_until(
            lambda: any(
                record.getMessage() == "worker.started handlers=0" for record in caplog.records
            )
        ), "worker never logged its start"
        stop_requested_at = time.monotonic()
        stop_event.set()
        thread.join(1.0)
        stopped_at = time.monotonic()

    assert not thread.is_alive(), "worker ignored the stop event"
    assert stopped_at - started_at < 1.0
    assert stopped_at - stop_requested_at < 1.0

    messages = [record.getMessage() for record in caplog.records]
    assert "worker.started handlers=0" in messages
    assert "worker.stopped" in messages
    for record in caplog.records:
        payload = json.loads(JsonFormatter().format(record))
        assert payload["level"] == "INFO"
        assert payload["logger"] == LOGGER_NAME
        assert isinstance(payload["message"], str)


def test_signal_handlers_set_the_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: dict[int, Callable[[int, object], None]] = {}

    def fake_signal(signum: int, handler: Callable[[int, object], None]) -> None:
        registered[signum] = handler

    monkeypatch.setattr(worker.signal, "signal", fake_signal)
    stop_event = threading.Event()
    worker.install_signal_handlers(stop_event)

    assert set(registered) == {signal.SIGINT, signal.SIGTERM}
    registered[signal.SIGINT](signal.SIGINT, None)
    assert stop_event.is_set()

    stop_event.clear()
    registered[signal.SIGTERM](signal.SIGTERM, None)
    assert stop_event.is_set()


def test_run_accepts_no_arguments_and_returns_after_stop() -> None:
    stop_event = threading.Event()
    thread = threading.Thread(target=worker.run, kwargs={"stop_event": stop_event}, daemon=True)
    thread.start()
    stop_event.set()
    thread.join(1.0)
    assert not thread.is_alive()
