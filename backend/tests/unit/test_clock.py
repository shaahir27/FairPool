"""T01A02: the deterministic clock fake."""

from __future__ import annotations

from datetime import UTC, datetime

from fairpool.fakes.clock import FakeClock


async def test_fake_clock_is_settable_and_advances():
    start = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    clock = FakeClock(start)
    assert await clock.db_now(None) == start  # type: ignore[arg-type]
    clock.advance(90)
    assert await clock.db_now(None) == datetime(2026, 10, 30, 12, 1, 30, tzinfo=UTC)
    later = datetime(2026, 11, 1, tzinfo=UTC)
    clock.set(later)
    assert clock.now == later
