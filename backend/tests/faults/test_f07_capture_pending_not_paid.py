"""F7: a PENDING capture is not paid until a GET reads COMPLETED (I4).

The seat records a ``CAPTURE_PENDING`` ledger fact and a poll job, but the lot
never funds on it: "paid" means a capture resource reading ``COMPLETED``, read from
PayPal (P3). Only after the poll sees COMPLETED does the lot reach FUNDED.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_funding import (
    authorized_orders,
    distinct_router,
    funding_service,
    lot_status,
    order_status,
)
from tests.integration.test_open_checkout import build_world

pytestmark = pytest.mark.integration


async def test_f07_capture_pending_not_paid(db_session: AsyncSession) -> None:
    """F7: PENDING waits; the lot funds only once the GET reads COMPLETED."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router(outcome="pending")
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"

    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})

    assert await order_status(db_session, orders[0]) == "CAPTURE_PENDING"
    assert await lot_status(db_session, world.lot_id) == "FUNDING"
    kinds = [row.kind for row in world.ports.ledger.entries]
    assert kinds.count("CAPTURE_PENDING") == 1
    assert kinds.count("CAPTURE_COMPLETED") == 0

    # The provider settles: a GET now reads COMPLETED, so the poll records it.
    capture_id, capture = next(iter(router.gateway.captures.items()))
    router.gateway.captures[capture_id] = replace(capture, status="COMPLETED")
    await service.poll(db_session, {"buyer_order_id": str(orders[0])})
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})

    assert await order_status(db_session, orders[0]) == "CAPTURED"
    assert await lot_status(db_session, world.lot_id) == "FUNDED"
    assert [row.kind for row in world.ports.ledger.entries].count("CAPTURE_COMPLETED") == 1
    net_paid = await world.ports.ledger.net_paid_cents(db_session, world.lot_id)
    assert net_paid == world.totals[str(world.entry_ids[0])]["total_cents"]
