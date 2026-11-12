"""Supervise the API and queue worker together on the free Render web instance."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from types import FrameType


def main() -> int:
    stop = threading.Event()

    def shutdown(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    children: list[subprocess.Popen[bytes]] = []
    try:
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "fairpool.main:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    os.environ.get("PORT", "10000"),
                    "--no-access-log",
                    "--forwarded-allow-ips",
                    os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
                ]
            )
        )
        children.append(subprocess.Popen([sys.executable, "-m", "fairpool.worker"]))
        while not stop.wait(0.25):
            for child in children:
                code = child.poll()
                if code is not None:
                    # An exited worker must not leave the API reporting healthy.
                    return code or 1
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
