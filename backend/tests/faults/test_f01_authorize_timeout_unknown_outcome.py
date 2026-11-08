"""F1: an authorize call that times out leaves the seat held and is settled once (I7, I9).

The send reached PayPal and the answer was lost. Nothing may release the seat while
an authorization could exist (I7), and nothing may buy a second one: the reconciler
re-drives the same ``order.authorize`` job and the handler replays ``auth:{order}``,
so the provider sees one operation and the ledger gets one fact (I9).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.modules.checkout.expiry import OfferExpiry
from fairpool.modules.reconciler.resolve import Reconciler
from tests.integration.test_authorize_flow import authorize_handler, open_offers, order_status
from tests.integration.test_open_checkout import build_world, make_router

pytestmark = [pytest.mark.integration, pytest.mark.faults]


async def test_f01_authorize_timeout_unknown_outcome(db_session: AsyncSession) -> None:
    """F1: unknown outcome -> AUTHORIZING, no money, then the same key resolves it."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    # The approval's own job is consumed by the attempt below; only the reconciler's
    # re-drive may appear in the queue afterwards.
    world.ports.jobs.jobs.clear()
    router.gateway.outcome = "timeout_after_send"

    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTHORIZING"
    assert world.ports.ledger.entries == [], "an unknown outcome is not a payment (I4)"
    stored = int(
        await db_session.scalar(
            text("SELECT count(*) FROM paypal_authorizations WHERE buyer_order_id = :id"),
            {"id": order_id},
        )
        or 0
    )
    assert stored == 0, "no authorization row exists until the provider reports one"
    # I7: the seat is not released and no refill may be offered over it.
    expiry = OfferExpiry(engine=world.ports.engine, jobs=world.ports.jobs)
    assert await expiry.claimable_vacancies(db_session, world.lot_id) == 0
    assert "lot.refill" not in [job.kind for job in world.ports.jobs.jobs]

    # The provider was sent exactly one authorization under the contract's replay key.
    key = f"auth:{order_id}"
    assert key in router.gateway.replays
    auth_id = router.gateway.replays[key][1].authorizations[0].id  # type: ignore[union-attr]

    # The seat horizon passes, the reconciler re-drives the job, and the replay answers.
    world.ports.clock.advance(121)
    reconciler = Reconciler(clock=world.ports.clock, jobs=world.ports.jobs)
    await reconciler.sweep(db_session, {})
    resolves = [
        job
        for job in world.ports.jobs.jobs
        if job.kind == "order.resolve" and job.payload["buyer_order_id"] == str(order_id)
    ]
    assert len(resolves) == 1
    await reconciler.resolve(db_session, resolves[0].payload)
    assert [job.kind for job in world.ports.jobs.jobs].count("order.authorize") == 1

    router.gateway.outcome = "completed"
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTHORIZED"
    rows = (
        await db_session.execute(
            text(
                "SELECT paypal_auth_id, amount_cents FROM paypal_authorizations "
                "WHERE buyer_order_id = :id"
            ),
            {"id": order_id},
        )
    ).all()
    assert [str(row.paypal_auth_id) for row in rows] == [auth_id], "one authorization identity"
    assert [entry.kind for entry in world.ports.ledger.entries] == ["AUTH_CREATED"]
    assert len(router.gateway.authorizations) == 1, "no second authorization at the provider"
    # The seat was never given away while its money was unknown.
    assert await expiry.claimable_vacancies(db_session, world.lot_id) == 0
