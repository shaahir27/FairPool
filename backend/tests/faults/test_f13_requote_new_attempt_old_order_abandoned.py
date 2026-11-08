"""F13: a changed price is a new attempt; the old provider order is abandoned (I3, I9).

The re-quote counter (N9) moves ``buyer_orders.current_attempt`` and the seat returns
to OFFERED. The next create uses ``create:{order}:{attempt}``, so it cannot reuse the
first order's key over a different payload; the approval and authorization read the
latest attempt only, and the superseded provider order never carries an authorization
or a ledger fact. The new amount is the one the buyer approves and the one the ledger
records, so I3's "equals the authorization amount" holds across the re-quote.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_authorize_flow import authorize_handler, open_offers, order_status
from tests.integration.test_open_checkout import build_world, make_router

pytestmark = [pytest.mark.integration, pytest.mark.faults]

NEW_TOTAL_CENTS = 52_000
OLD_TOTAL_CENTS = 50_000


async def test_f13_requote_new_attempt_old_order_abandoned(db_session: AsyncSession) -> None:
    """F13: a re-quote creates attempt 1, and only attempt 1 can move money."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)

    first = await handler.continue_order(db_session, buyer_order_id=order_id)
    first_order_id = str(first["paypal_order_id"])

    # The merchant's price changed, so the order is re-offered as attempt 1 (N9).
    await db_session.execute(
        text(
            "UPDATE buyer_orders SET status = 'OFFERED', current_attempt = 1, "
            "total_cents = :total, breakdown = CAST(:breakdown AS jsonb) WHERE id = :id"
        ),
        {
            "total": NEW_TOTAL_CENTS,
            "breakdown": ('{"item_cents": 49000, "shipping_cents": 1500, "tax_cents": 1500}'),
            "id": order_id,
        },
    )
    await db_session.flush()

    second = await handler.continue_order(db_session, buyer_order_id=order_id)
    second_order_id = str(second["paypal_order_id"])

    assert second_order_id != first_order_id
    assert f"create:{order_id}:0" in router.gateway.replays
    assert f"create:{order_id}:1" in router.gateway.replays
    rows = (
        await db_session.execute(
            text(
                "SELECT attempt, paypal_order_id FROM paypal_orders "
                "WHERE buyer_order_id = :id ORDER BY attempt"
            ),
            {"id": order_id},
        )
    ).all()
    assert [(int(row.attempt), str(row.paypal_order_id)) for row in rows] == [
        (0, first_order_id),
        (1, second_order_id),
    ]

    await handler.approved(db_session, buyer_order_id=order_id)
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTHORIZED"
    (authorization,) = (
        await db_session.execute(
            text(
                "SELECT paypal_auth_id, amount_cents FROM paypal_authorizations "
                "WHERE buyer_order_id = :id"
            ),
            {"id": order_id},
        )
    ).all()
    assert int(authorization.amount_cents) == NEW_TOTAL_CENTS, "the new price is what was approved"
    assert len(router.gateway.authorizations) == 1, "the superseded provider order never authorized"
    (ledger,) = world.ports.ledger.entries
    assert ledger.kind == "AUTH_CREATED"
    assert int(ledger.amount_cents) == NEW_TOTAL_CENTS
    assert int(ledger.amount_cents) != OLD_TOTAL_CENTS
