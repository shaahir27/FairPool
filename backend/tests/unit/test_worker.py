"""T00A03/T01A02: signal handling for the queue-backed worker."""

from __future__ import annotations

import signal
import threading
from collections.abc import Callable

import pytest

from fairpool import worker


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
