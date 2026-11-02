"""F24: a refund that cannot complete leaves the lot FAILING, never closed.

A lot the ledger cannot balance must stay visible. Closing it as if it were settled
would report money back to the buyer that PayPal never moved.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.payments import Payee
from fairpool.modules.checkout.failure import STUCK_AFTER_PASSES
from tests.integration.test_failure_path import (
    RefundFailsGateway,
    drain,
    expire_the_deadline,
    failure_service,
    run_queued_passes,
)
from tests.integration.test_funding import (
    authorized_orders,
    funding_service,
    lot_status,
    order_status,
)
from tests.integration.test_open_checkout import FakeRouter, build_world

pytestmark = [pytest.mark.integration, pytest.mark.faults]


async def test_f24_a_failed_refund_keeps_the_lot_failing(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """F24: a lot that cannot be balanced never closes as if it were."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0, moq=2)
    router = FakeRouter(
        gateway=RefundFailsGateway(outcome="completed"),
        seller=Payee(email="seller@example.test", merchant_id=None),
    )
    orders = await authorized_orders(world, router=router, count=2)
    funding = funding_service(world, router=router)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await funding.capture(db_session, {"buyer_order_id": str(orders[0])})
    await expire_the_deadline(world, db_session)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})

    service = failure_service(world, router=router)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})
    await drain(world, service, db_session)
    # The worker keeps coming back for this lot. Each pass re-reads the ledger, finds
    # the refund still outstanding and schedules the next one (F24 stays visible).
    for _ in range(STUCK_AFTER_PASSES):
        await run_queued_passes(world, service, db_session)

    assert await order_status(db_session, orders[0]) == "CAPTURED"
    assert await lot_status(db_session, world.lot_id) != "FAILED_CLOSED"
    assert await world.ports.ledger.net_paid_cents(db_session, world.lot_id) > 0
    # Staying visible also means saying so: the retry escalates to one ERROR alert.
    assert caplog.text.count("finalize_fail_stuck") == 1
