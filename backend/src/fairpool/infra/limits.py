"""Process-local sliding-window rate limits (config-and-errors.md section 3).

One class serves every limit in the contract: the auth attempt per address, the
login attempt per account, the intake turn per user, the join per user and the
webhook delivery per address. A window is a deque of the timestamps still inside
it plus a lock, because uvicorn runs handlers on many threads and a window that
races is not a limit.

The window is per process, which is the disclosed limit in section 3: an n-worker
deployment sees up to n times the listed rate until a shared store is scheduled.
"""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from typing import Final

from fastapi import HTTPException

#: Keys kept at once. Past it the oldest key is dropped, so a spoofed address
#: cannot grow the map without bound; the eviction is a limit, not a leak.
MAX_KEYS: Final[int] = 4096


class SlidingWindowLimiter:
    """``limit`` events per key per ``window_s`` seconds, counting the refused one."""

    def __init__(self, *, limit: int, window_s: float = 60.0, max_keys: int = MAX_KEYS) -> None:
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str, now: float) -> None:
        """Count this event, or raise the contract's 429 with a ``Retry-After``."""
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            self._hits.move_to_end(key)
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(1, int(self.window_s - (now - hits[0])) + 1)
                raise HTTPException(
                    429,
                    "RATE_LIMITED",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)
            while len(self._hits) > self.max_keys:
                # Expired buckets first: dropping a live one would hand a caller a fresh
                # budget while a bucket nobody can hit again still holds a slot.
                self._sweep(now)
                if len(self._hits) <= self.max_keys:
                    break
                self._hits.popitem(last=False)

    def _sweep(self, now: float) -> None:
        """Drop buckets whose newest hit has left the window; they hold no state."""
        expired = [
            key for key, hits in self._hits.items() if not hits or now - hits[-1] >= self.window_s
        ]
        for key in expired:
            del self._hits[key]


__all__ = ["MAX_KEYS", "SlidingWindowLimiter"]
