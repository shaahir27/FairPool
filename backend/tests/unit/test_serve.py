"""The free-host entrypoint cannot leave a healthy API with a dead worker."""

from __future__ import annotations

import signal
import subprocess
from unittest.mock import MagicMock

import pytest

from fairpool import serve


@pytest.mark.parametrize("failed_child", [0, 1])
def test_child_exit_stops_its_sibling(monkeypatch: pytest.MonkeyPatch, failed_child: int) -> None:
    children = [MagicMock(), MagicMock()]
    for child in children:
        child.poll.return_value = None
    children[failed_child].poll.return_value = 7
    popen = MagicMock(side_effect=children)
    monkeypatch.setattr(serve.subprocess, "Popen", popen)
    monkeypatch.setattr(serve.signal, "signal", MagicMock())
    assert serve.main() == 7
    children[1 - failed_child].terminate.assert_called_once()
    commands = [call.args[0] for call in popen.call_args_list]
    assert commands[0][1:4] == ["-m", "uvicorn", "fairpool.main:app"]
    assert commands[1][1:] == ["-m", "fairpool.worker"]
    assert "--no-access-log" in commands[0]


def test_shutdown_signal_stops_both_children(monkeypatch: pytest.MonkeyPatch) -> None:
    children = [MagicMock(), MagicMock()]
    for child in children:
        child.poll.return_value = None
    monkeypatch.setattr(serve.subprocess, "Popen", MagicMock(side_effect=children))
    callbacks = {}
    monkeypatch.setattr(
        serve.signal, "signal", lambda sig, callback: callbacks.update({sig: callback})
    )
    monkeypatch.setattr(
        serve.threading.Event,
        "wait",
        lambda self, timeout: callbacks[signal.SIGTERM](signal.SIGTERM, None) or self.is_set(),
    )
    assert serve.main() == 0
    for child in children:
        child.terminate.assert_called_once()
        child.wait.assert_called_once()


def test_failed_worker_start_stops_api(monkeypatch: pytest.MonkeyPatch) -> None:
    api = MagicMock()
    api.poll.return_value = None
    monkeypatch.setattr(serve.subprocess, "Popen", MagicMock(side_effect=[api, OSError("failed")]))
    monkeypatch.setattr(serve.signal, "signal", MagicMock())
    with pytest.raises(OSError):
        serve.main()
    api.terminate.assert_called_once()


def test_unresponsive_child_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    api, worker = MagicMock(), MagicMock()
    api.poll.return_value = 1
    worker.poll.return_value = None
    worker.wait.side_effect = [subprocess.TimeoutExpired("worker", 10), None]
    monkeypatch.setattr(serve.subprocess, "Popen", MagicMock(side_effect=[api, worker]))
    monkeypatch.setattr(serve.signal, "signal", MagicMock())
    assert serve.main() == 1
    worker.kill.assert_called_once()
