"""Agent-facing entry views (T07A05, api.md section 4.4).

The agent list and single-entry read return the same body, so both go through
``entry_view``. The allocation comes from ``allocations``, the offer from the
active buyer order, and ``checkout_url`` is the human hand-off: an AI client can
point its buyer at that page but can never pay (I1, INT-5).

The dict is JSON-ready (ids and timestamps already serialised) because the
handlers return it through ``JSONResponse`` to keep the join's 201/200 status.

``entry_views`` reads the whole page in a fixed number of queries. The first
draft asked per entry, which is invisible with one row and a round-trip storm
with a real buyer list (the page must not get slower as the history grows).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import PoolEntry
from fairpool.db.models.checkout import BuyerOrder
from fairpool.db.models.enums import AllocationStatus, BuyerOrderStatus
from fairpool.db.models.pools import Allocation, Lot

#: The statuses under which a buyer order is still the entry's live offer.
ACTIVE_ORDER_STATUSES: tuple[BuyerOrderStatus, ...] = (
    BuyerOrderStatus.OFFERED,
    BuyerOrderStatus.ORDER_CREATED,
    BuyerOrderStatus.APPROVED,
    BuyerOrderStatus.AUTHORIZING,
    BuyerOrderStatus.AUTHORIZED,
    BuyerOrderStatus.CAPTURING,
    BuyerOrderStatus.CAPTURE_PENDING,
    BuyerOrderStatus.CAPTURED,
    BuyerOrderStatus.REFUNDING,
)

CHECKOUT_HINT = "A human approves payment on PayPal; this API cannot pay."


async def entry_views(
    session: AsyncSession, entries: Iterable[PoolEntry], *, frontend_base_url: str
) -> list[dict[str, Any]]:
    """Every entry's allocation and live offer in four queries, never two per entry."""
    rows = list(entries)
    if not rows:
        return []
    ids = [entry.id for entry in rows]
    allocations = {
        allocation.entry_id: allocation
        for allocation in await session.scalars(
            select(Allocation).where(Allocation.entry_id.in_(ids))
        )
    }
    # Oldest first, so the newest active order is the one left in the map.
    orders = {
        order.entry_id: order
        for order in await session.scalars(
            select(BuyerOrder)
            .where(BuyerOrder.entry_id.in_(ids), BuyerOrder.status.in_(ACTIVE_ORDER_STATUSES))
            .order_by(BuyerOrder.created_at, BuyerOrder.id)
        )
    }
    zone_seats = await _zone_seats(session, allocations.values())
    base = frontend_base_url.rstrip("/")
    views: list[dict[str, Any]] = []
    for entry in rows:
        allocation = allocations.get(entry.id)
        order = orders.get(entry.id)
        views.append(
            {
                "entry_id": str(entry.id),
                "pool_id": str(entry.pool_id),
                "entry_status": str(entry.status),
                "allocation": _allocation_dict(allocation, entry.pool_id, zone_seats),
                "offer": (
                    {
                        "buyer_order_id": str(order.id),
                        "status": str(order.status),
                        "offer_expires_at": order.offer_expires_at.isoformat(),
                    }
                    if order is not None
                    else None
                ),
                "checkout_url": f"{base}/offers/{order.id}" if order is not None else None,
                "checkout_hint": CHECKOUT_HINT,
            }
        )
    return views


async def entry_view(
    session: AsyncSession, entry: PoolEntry, *, frontend_base_url: str
) -> dict[str, Any]:
    return (await entry_views(session, [entry], frontend_base_url=frontend_base_url))[0]


async def _zone_seats(
    session: AsyncSession, allocations: Iterable[Allocation]
) -> dict[tuple[UUID, str], int]:
    """Seats per (pool, zone), read once for every waitlisted allocation on the page."""
    keys = {
        (allocation.pool_id, allocation.zone_id)
        for allocation in allocations
        if allocation.status == AllocationStatus.WAITLISTED
    }
    if not keys:
        return {}
    result = await session.execute(
        select(Lot.pool_id, Lot.zone_id, func.coalesce(func.sum(Lot.seats), 0))
        .where(Lot.pool_id.in_({pool_id for pool_id, _ in keys}))
        .group_by(Lot.pool_id, Lot.zone_id)
    )
    return {
        (pool_id, zone_id): int(seats)
        for pool_id, zone_id, seats in result
        if (pool_id, zone_id) in keys
    }


def _allocation_dict(
    allocation: Allocation | None, pool_id: UUID, zone_seats: dict[tuple[UUID, str], int]
) -> dict[str, Any] | None:
    if allocation is None:
        return None
    waitlist_position: int | None = None
    if allocation.status == AllocationStatus.WAITLISTED:
        # rank is 1-based within the zone; the seats ahead of the waitlist are the
        # zone's lot seats, so the position is measured against what is actually
        # seated rather than against an invented constant.
        waitlist_position = max(
            1, allocation.rank - zone_seats.get((pool_id, allocation.zone_id), 0)
        )
    return {
        "status": str(allocation.status),
        "zone_id": allocation.zone_id,
        "rank": allocation.rank,
        "lot_id": str(allocation.lot_id) if allocation.lot_id is not None else None,
        "waitlist_position": waitlist_position,
    }
