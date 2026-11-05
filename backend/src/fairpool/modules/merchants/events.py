"""Merchant event feed over Server-Sent Events (api.md section 2, T08B02).

Four event names and nothing else: ``tick`` with the database time, ``lot_open``
when a lot becomes open for bidding, ``bid_status`` when one of *this merchant's*
bids changes status, and ``checkout_progress`` when one of the lots it won moves
through checkout. No buyer identity, address or amount rides the feed; a screen
that needs detail refetches the JSON endpoints.

Every poll opens a short read session and holds no transaction or lock for the
life of the stream. Concurrent streams per process are capped so an accidental
reconnect loop cannot exhaust the worker's connections.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DEFAULT_INTERVAL_S = 2.0
MAX_STREAMS = 32


class _Slots:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._active = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self._active >= self.limit:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)


_SLOTS = _Slots(MAX_STREAMS)


def has_capacity() -> bool:
    """True while a stream can still start without exceeding the process bound."""
    with _SLOTS._lock:
        return _SLOTS._active < _SLOTS.limit


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, sort_keys=True, separators=(',', ':'))}\n\n"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _tick_data(now: datetime) -> dict[str, str]:
    return {"server_time": _iso(now)}


async def _read_state(
    session: AsyncSession, merchant_id: UUID
) -> (
    tuple[
        list[tuple[str, str, str, datetime]],
        list[tuple[str, str, str]],
        list[tuple[str, str]],
        datetime,
    ]
    | None
):
    now = await session.scalar(text("SELECT clock_timestamp()"))
    if not isinstance(now, datetime):
        raise RuntimeError("database clock returned a non-datetime value")
    lots = (
        await session.execute(
            text(
                "SELECT l.id, l.pool_id, l.status, l.bid_close_at "
                "FROM lots l JOIN pools p ON p.id = l.pool_id "
                "WHERE l.status = 'BIDDING' AND p.status NOT IN ('DRAFT', 'CANCELLED') "
                "ORDER BY l.bid_close_at, l.id"
            )
        )
    ).all()
    bids = (
        await session.execute(
            text("SELECT id, lot_id, status FROM bids WHERE merchant_id = :merchant ORDER BY id"),
            {"merchant": merchant_id},
        )
    ).all()
    awarded = (
        await session.execute(
            text(
                "SELECT l.id, l.status FROM awards a JOIN lots l ON l.id = a.lot_id "
                "WHERE a.merchant_id = :merchant ORDER BY l.id"
            ),
            {"merchant": merchant_id},
        )
    ).all()
    return (
        [(str(row[0]), str(row[1]), str(row[2]), row[3]) for row in lots],
        [(str(row[0]), str(row[1]), str(row[2])) for row in bids],
        [(str(row[0]), str(row[1])) for row in awarded],
        now,
    )


async def stream_merchant_events(
    session_factory: async_sessionmaker[AsyncSession],
    merchant_id: UUID,
    *,
    interval_s: float = _DEFAULT_INTERVAL_S,
) -> AsyncIterator[str]:
    """Yield SSE frames until the client disconnects.

    The slot is taken when the stream actually starts and released when it ends,
    so a disconnect before the first frame cannot leak the process bound.
    """
    if not _SLOTS.acquire():
        return
    seen_lots: set[str] = set()
    last_bids: dict[str, tuple[str, str]] = {}
    last_awards: dict[str, str] = {}
    try:
        while True:
            async with session_factory() as session:
                state = await _read_state(session, merchant_id)
            if state is None:
                return
            lots, bids, awarded, now = state
            frame = ""
            for lot_id, pool_id, status, bid_close_at in lots:
                if lot_id in seen_lots:
                    continue
                seen_lots.add(lot_id)
                frame += _sse(
                    "lot_open",
                    {
                        "lot_id": lot_id,
                        "pool_id": pool_id,
                        "status": status,
                        "bid_close_at": _iso(bid_close_at),
                    },
                )
            current_bids = {bid_id: (lot_id, status) for bid_id, lot_id, status in bids}
            for bid_id, (lot_id, status) in current_bids.items():
                if last_bids.get(bid_id) != (lot_id, status):
                    frame += _sse(
                        "bid_status",
                        {"bid_id": bid_id, "lot_id": lot_id, "status": status},
                    )
            last_bids = current_bids
            current_awards = dict(awarded)
            for lot_id, status in current_awards.items():
                if last_awards.get(lot_id) != status:
                    frame += _sse("checkout_progress", {"lot_id": lot_id, "status": status})
            last_awards = current_awards
            frame += _sse("tick", _tick_data(now))
            yield frame
            try:
                await asyncio.sleep(interval_s)
            except asyncio.CancelledError:
                return
    finally:
        _SLOTS.release()


__all__ = ["MAX_STREAMS", "has_capacity", "stream_merchant_events"]
