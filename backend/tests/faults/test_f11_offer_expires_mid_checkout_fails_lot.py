"""F11: the winning offer expires mid-checkout, so the lot fails and voids everything.

The buyer's offer window closes while the lot is CHECKOUT_OPEN. BO-15/BO-16/BO-17
move the lapsed order to EXPIRED and free one vacancy, but with no waitlisted entry
there is nothing to refill, so the lot can never reach its minimum. The contracted
way into FAILING is LS-08 on ``job:lot.try_fund`` (its guard names both the passed
deadline and an expired winning offer); the failure handler then voids the live
authorization and closes at net zero. The lapsed offer itself never authorizes, so no
amount outside the buyer's confirmed total is ever held (I3).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.modules.checkout.expiry import EXPIRED_STATE, OfferExpiry
from tests.integration.test_authorize_flow import authorize_handler, open_offers, order_status
from tests.integration.test_failure_path import drain, failure_service
from tests.integration.test_funding import funding_service, lot_status
from tests.integration.test_open_checkout import build_world, make_router, refill_handler

pytestmark = [pytest.mark.integration, pytest.mark.faults]


async def test_f11_offer_expires_mid_checkout_fails_lot(db_session: AsyncSession) -> None:
    """F11: the lapsed offer cannot fund, the lot fails LS-08, and the hold is voided."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0, moq=2)
    router = make_router()
    orders = await open_offers(world)
    handler = authorize_handler(world, router)
    # The first buyer is already holding money when the second offer lapses.
    await handler.continue_order(db_session, buyer_order_id=orders[0])
    await handler.approved(db_session, buyer_order_id=orders[0])
    await handler.authorize(db_session, {"buyer_order_id": str(orders[0])})
    assert await order_status(db_session, orders[0]) == "AUTHORIZED"

    # Both offer windows end mid-checkout (the timer would fire at the stored deadline).
    await db_session.execute(
        text("UPDATE buyer_orders SET offer_expires_at = :at WHERE lot_id = :lot"),
        {"at": world.now - timedelta(seconds=1), "lot": world.lot_id},
    )
    await db_session.flush()

    expiry = OfferExpiry(engine=world.ports.engine, jobs=world.ports.jobs)
    await expiry.expire(db_session, {"buyer_order_id": str(orders[1])})

    assert await order_status(db_session, orders[1]) == EXPIRED_STATE
    assert (
        int(
            await db_session.scalar(
                text("SELECT count(*) FROM paypal_authorizations WHERE buyer_order_id = :id"),
                {"id": orders[1]},
            )
            or 0
        )
        == 0
    ), "an expired offer never authorizes"
    refills = [job for job in world.ports.jobs.jobs if job.kind == "lot.refill"]
    assert len(refills) == 1
    # No waitlist exists, so the refill offers nothing and the vacancy stays open.
    await refill_handler(world).refill(db_session, {"lot_id": str(world.lot_id)})
    assert (await lot_status(db_session, world.lot_id)) == "CHECKOUT_OPEN"

    # A late approval of the lapsed offer is a no-op, not money.
    late = await handler.approved(db_session, buyer_order_id=orders[1])
    assert late["status"] == EXPIRED_STATE
    assert [entry.kind for entry in world.ports.ledger.entries] == ["AUTH_CREATED"], (
        "only the first buyer's authorization is a money fact"
    )

    # The funding timer evaluates the lot after the offer window: LS-08 fails it.
    await db_session.execute(
        text("UPDATE lots SET fund_deadline_at = :at WHERE id = :lot"),
        {"at": world.now - timedelta(seconds=1), "lot": world.lot_id},
    )
    await db_session.flush()
    funding = funding_service(world, router=router)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})

    assert await lot_status(db_session, world.lot_id) == "FAILING"
    failing = [row for row in world.ports.audit.rows if row["row"]["action"] == "lot.failing"]
    assert failing and failing[-1]["row"]["payload"]["transition_id"] == "LS-08"

    service = failure_service(world, router=router)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})
    await drain(world, service, db_session)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})

    assert await order_status(db_session, orders[0]) == "VOIDED"
    assert await lot_status(db_session, world.lot_id) == "FAILED_CLOSED"
    assert await world.ports.ledger.net_paid_cents(db_session, world.lot_id) == 0
    assert [entry.kind for entry in world.ports.ledger.entries] == [
        "AUTH_CREATED",
        "AUTH_VOIDED",
    ]
