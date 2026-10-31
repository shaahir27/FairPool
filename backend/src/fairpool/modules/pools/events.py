"""Public pool event feed over Server-Sent Events (api.md "Server-sent events").

Emits only ``pool_status``, ``lot_status`` and ``tick`` with server time: the
feed is public and carries no personal data, no salts, no caps and no entry
information (FR-IG-01, INT-1). Each poll opens a short read session, so no
transaction and no lock is held for the life of a stream, and the generator
stops cleanly when the client disconnects.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DEFAULT_INTERVAL_S = 2.0


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, sort_keys=True, separators=(',', ':'))}\n\n"


async def _read_state(
    session: AsyncSession, pool_id: UUID
) -> tuple[str, list[tuple[str, str]], datetime] | None:
    pool_status = await session.scalar(
        text("SELECT status FROM pools WHERE id = :id"), {"id": pool_id}
    )
    if pool_status is None:
        return None
    lots = (
        await session.execute(
            text("SELECT id, status FROM lots WHERE pool_id = :id ORDER BY lot_order, id"),
            {"id": pool_id},
        )
    ).all()
    # Server time only (I15): the database wall clock, never the process clock.
    now = await session.scalar(text("SELECT clock_timestamp()"))
    if not isinstance(now, datetime):
        raise RuntimeError("database clock returned a non-datetime value")
    return str(pool_status), [(str(lot_id), str(status)) for lot_id, status in lots], now


def _tick_data(now: datetime) -> dict[str, str]:
    return {"server_time": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}


async def stream_pool_events(
    session_factory: async_sessionmaker[AsyncSession],
    pool_id: UUID,
    *,
    interval_s: float = _DEFAULT_INTERVAL_S,
) -> AsyncIterator[str]:
    """Yield SSE frames until the pool disappears or the client disconnects.

    Cancellation on disconnect arrives while the generator is suspended at
    ``yield`` or in ``asyncio.sleep``; each poll session is opened and closed
    inside one iteration, so nothing is left holding a transaction.
    """
    last_pool_status: str | None = None
    last_lots: dict[str, str] = {}
    while True:
        async with session_factory() as session:
            state = await _read_state(session, pool_id)
        if state is None:
            return
        pool_status, lots, now = state
        frame = ""
        if pool_status != last_pool_status:
            frame += _sse("pool_status", {"pool_id": str(pool_id), "status": pool_status})
            last_pool_status = pool_status
        current = dict(lots)
        if current != last_lots:
            for lot_id, status in lots:
                if last_lots.get(lot_id) != status:
                    frame += _sse(
                        "lot_status", {"pool_id": str(pool_id), "lot_id": lot_id, "status": status}
                    )
            last_lots = current
        frame += _sse("tick", _tick_data(now))
        yield frame
        try:
            await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            return
