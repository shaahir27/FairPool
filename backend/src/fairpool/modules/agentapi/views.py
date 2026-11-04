"""Agent-facing entry views (T07A05, api.md section 4.4).

The agent list and single-entry read return the same body, so both go through
``entry_view``. The allocation comes from ``allocations``, the offer from the
active buyer order, and ``checkout_url`` is the human hand-off: an AI client can
point its buyer at that page but can never pay (I1, INT-5).

The dict is JSON-ready (ids and timestamps already serialised) because the
handlers return it through ``JSONResponse`` to keep the join's 201/200 status.
"""

from __future__ import annotations

from typing import Any

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


async def entry_view(
    session: AsyncSession, entry: PoolEntry, *, frontend_base_url: str
) -> dict[str, Any]:
    order = await session.scalar(
        select(BuyerOrder)
        .where(
            BuyerOrder.entry_id == entry.id,
            BuyerOrder.status.in_(ACTIVE_ORDER_STATUSES),
        )
        .order_by(BuyerOrder.created_at.desc(), BuyerOrder.id)
        .limit(1)
    )
    return {
        "entry_id": str(entry.id),
        "pool_id": str(entry.pool_id),
        "entry_status": str(entry.status),
        "allocation": await _allocation_view(session, entry),
        "offer": (
            {
                "buyer_order_id": str(order.id),
                "status": str(order.status),
                "offer_expires_at": order.offer_expires_at.isoformat(),
            }
            if order is not None
            else None
        ),
        "checkout_url": (
            f"{frontend_base_url.rstrip('/')}/offers/{order.id}" if order is not None else None
        ),
        "checkout_hint": "A human approves payment on PayPal; this API cannot pay.",
    }


async def _allocation_view(session: AsyncSession, entry: PoolEntry) -> dict[str, Any] | None:
    allocation = await session.scalar(
        select(Allocation).where(
            Allocation.pool_id == entry.pool_id, Allocation.entry_id == entry.id
        )
    )
    if allocation is None:
        return None
    waitlist_position: int | None = None
    if allocation.status == AllocationStatus.WAITLISTED:
        # rank is 1-based within the zone; the seats ahead of the waitlist are the
        # zone's lot seats, so the position is measured against what is actually
        # seated rather than against an invented constant.
        seats = await session.scalar(
            select(func.coalesce(func.sum(Lot.seats), 0)).where(
                Lot.pool_id == entry.pool_id, Lot.zone_id == allocation.zone_id
            )
        )
        waitlist_position = max(1, allocation.rank - int(seats or 0))
    return {
        "status": str(allocation.status),
        "zone_id": allocation.zone_id,
        "rank": allocation.rank,
        "lot_id": str(allocation.lot_id) if allocation.lot_id is not None else None,
        "waitlist_position": waitlist_position,
    }
