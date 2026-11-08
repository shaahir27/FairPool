"""F30: a denied funding source fails the seat and the vacancy is refilled (I8).

The provider returns an authorization with status DENIED. BO-05 applies AUTH_FAILED,
which creates one claimable vacancy and its ``lot.refill`` job; the waitlisted entry
takes the seat and can authorize normally. No money is recorded for the denial (I4),
and the refill never pushes offers in flight plus committed buyers past the seats.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_authorize_flow import authorize_handler, open_offers, order_status
from tests.integration.test_funding import distinct_router
from tests.integration.test_open_checkout import build_world, refill_handler

pytestmark = [pytest.mark.integration, pytest.mark.faults]


async def test_f30_funding_source_denied_vacancy(db_session: AsyncSession) -> None:
    """F30: DENIED -> AUTH_FAILED -> one vacancy -> the waitlist seat authorizes."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=1, moq=2)
    router = distinct_router(outcome="declined")
    orders = await open_offers(world)
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=orders[0])
    await handler.approved(db_session, buyer_order_id=orders[0])

    await handler.authorize(db_session, {"buyer_order_id": str(orders[0])})

    assert await order_status(db_session, orders[0]) == "AUTH_FAILED"
    assert world.ports.ledger.entries == [], "a denied authorization moves no money (I4)"
    assert "lot.refill" in [job.kind for job in world.ports.jobs.jobs]
    assert (
        int(
            await db_session.scalar(
                text(
                    "SELECT count(*) FROM paypal_authorizations "
                    "WHERE buyer_order_id = :id AND status = 'DENIED'"
                ),
                {"id": orders[0]},
            )
            or 0
        )
        == 1
    )

    # The waitlisted entry takes the freed seat; the other original seat keeps its offer.
    await refill_handler(world).refill(db_session, {"lot_id": str(world.lot_id)})
    rows = (
        await db_session.execute(
            text(
                "SELECT id, entry_id, status FROM buyer_orders WHERE lot_id = :lot "
                "ORDER BY created_at, id"
            ),
            {"lot": world.lot_id},
        )
    ).all()
    assert len(rows) == 3
    assert sum(1 for row in rows if str(row.status) == "OFFERED") == 2
    assert world.entry_ids[2] in {row.entry_id for row in rows}, "the waitlist was offered"
    active = sum(
        1
        for row in rows
        if str(row.status) in {"OFFERED", "ORDER_CREATED", "APPROVED", "AUTHORIZING", "AUTHORIZED"}
    )
    assert active == 2, "offers in flight plus committed buyers never exceed seats (I8)"

    # The replacement seat pays normally.
    router.gateway.outcome = "completed"
    replacement = next(row.id for row in rows if row.entry_id == world.entry_ids[2])
    other = orders[1]
    for order_id in (replacement, other):
        await handler.continue_order(db_session, buyer_order_id=order_id)
        await handler.approved(db_session, buyer_order_id=order_id)
        await handler.authorize(db_session, {"buyer_order_id": str(order_id)})
        assert await order_status(db_session, order_id) == "AUTHORIZED"
    assert [entry.kind for entry in world.ports.ledger.entries] == [
        "AUTH_CREATED",
        "AUTH_CREATED",
    ]
