"""F9: a capture that completes after the failure pass is refunded before close.

The scenario lives here because the fault run is where the gate proves it: money
that lands late must be refunded, not written off, before LS-10 may close the lot.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_failure_path import (
    drain,
    expire_the_deadline,
    failure_service,
    router_for_failure,
)
from tests.integration.test_funding import (
    authorized_orders,
    funding_service,
    lot_status,
    order_status,
)
from tests.integration.test_open_checkout import build_world

pytestmark = [pytest.mark.integration, pytest.mark.faults]


async def test_f09_a_capture_that_completes_late_is_refunded(
    db_session: AsyncSession,
) -> None:
    """F9: a PENDING capture blocks LS-10, then is refunded on the next pass."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0, moq=2)
    router = router_for_failure()
    orders = await authorized_orders(world, router=router, count=2)
    funding = funding_service(world, router=router)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await funding.capture(db_session, {"buyer_order_id": str(orders[0])})
    await expire_the_deadline(world, db_session)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})

    # The capture exists at PayPal but the seat still reads CAPTURE_PENDING: money is
    # in flight, so the lot must not close yet.
    await db_session.execute(
        text("UPDATE buyer_orders SET status = 'CAPTURE_PENDING' WHERE id = :id"), {"id": orders[0]}
    )
    await db_session.execute(
        text("UPDATE paypal_captures SET status = 'PENDING' WHERE buyer_order_id = :id"),
        {"id": orders[0]},
    )
    await db_session.flush()
    service = failure_service(world, router=router)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FAILING"

    # It completes now; the next pass refunds it before closing.
    await db_session.execute(
        text("UPDATE buyer_orders SET status = 'CAPTURED' WHERE id = :id"), {"id": orders[0]}
    )
    await db_session.execute(
        text("UPDATE paypal_captures SET status = 'COMPLETED' WHERE buyer_order_id = :id"),
        {"id": orders[0]},
    )
    await db_session.flush()
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})
    await drain(world, service, db_session)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})

    assert await order_status(db_session, orders[0]) == "REFUNDED"
    assert await lot_status(db_session, world.lot_id) == "FAILED_CLOSED"
    assert await world.ports.ledger.net_paid_cents(db_session, world.lot_id) == 0
