"""CR-10: the one sliding-window limiter behind every rate limit in section 3.

The limiter is shared by the auth routes, the join and intake routes and the webhook
receiver, so its boundary is proved once here: the exact count, the ``Retry-After``,
the sliding window, per-key isolation, the key cap and thread safety (uvicorn runs
handlers on many threads, and a window that races is not a limit).
"""

from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

from fairpool.infra.limits import SlidingWindowLimiter


def test_the_limit_is_exact_and_the_refusal_carries_retry_after() -> None:
    limiter = SlidingWindowLimiter(limit=10, window_s=60.0)
    for index in range(10):
        limiter.check("buyer-1", 1000.0 + index)
    with pytest.raises(HTTPException) as refused:
        limiter.check("buyer-1", 1010.0)
    assert refused.value.status_code == 429
    assert refused.value.detail == "RATE_LIMITED"
    assert int(refused.value.headers["Retry-After"]) >= 1


def test_the_window_slides() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_s=60.0)
    limiter.check("buyer-1", 0.0)
    limiter.check("buyer-1", 1.0)
    with pytest.raises(HTTPException):
        limiter.check("buyer-1", 2.0)
    # The first hit has left the window at t=60, so exactly one slot is free again.
    limiter.check("buyer-1", 60.0)
    # The refused attempt was never counted, so the window is full again immediately.
    with pytest.raises(HTTPException):
        limiter.check("buyer-1", 60.5)


def test_keys_do_not_share_a_window() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_s=60.0)
    limiter.check("buyer-1", 100.0)
    limiter.check("buyer-2", 100.0)
    with pytest.raises(HTTPException):
        limiter.check("buyer-1", 100.5)


def test_the_oldest_key_is_evicted_past_the_cap() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_s=60.0, max_keys=2)
    for key in ("a", "b", "c"):
        limiter.check(key, 100.0)
    assert list(limiter._hits) == ["b", "c"]


def test_concurrent_callers_get_exactly_the_limit() -> None:
    limiter = SlidingWindowLimiter(limit=5, window_s=60.0)
    allowed: list[int] = []
    refused: list[int] = []
    start = threading.Barrier(20)

    def hit() -> None:
        start.wait()
        try:
            limiter.check("shared", 100.0)
        except HTTPException:
            refused.append(1)
        else:
            allowed.append(1)

    threads = [threading.Thread(target=hit) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(allowed) == 5
    assert len(refused) == 15
