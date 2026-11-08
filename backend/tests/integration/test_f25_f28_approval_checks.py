"""F25/F28: a wrong currency, country or payee is rejected before any authorization.

FR-CK-05 runs on the order the provider returns, not on the browser's query string.
A byte of difference in the currency, a payer outside ``ALLOWED_PAYER_COUNTRIES``, or
a payee other than the stamped router's own all apply BO-18: the seat is REJECTED,
no authorization is attempted and no ledger fact exists (I1, I3).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_authorize_flow import (
    authorize_handler,
    open_offers,
    order_status,
    paypal_record,
)
from tests.integration.test_funding import distinct_router
from tests.integration.test_open_checkout import World, build_world

pytestmark = pytest.mark.integration


async def _reject_reason(session: AsyncSession, buyer_order_id: object) -> str | None:
    value = await session.scalar(
        text("SELECT reject_reason FROM buyer_orders WHERE id = :id"), {"id": buyer_order_id}
    )
    return None if value is None else str(value)


async def _no_money_and_no_authorize_job(world: World) -> None:
    assert world.ports.ledger.entries == []
    assert "order.authorize" not in [job.kind for job in world.ports.jobs.jobs]


async def test_f25_wrong_currency_or_country_rejected(db_session: AsyncSession) -> None:
    """F25 (I3): EUR and a non-allowed payer country are both refused by BO-18."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0, moq=1)
    first, second = await open_offers(world)
    router = distinct_router()
    handler = authorize_handler(world, router)

    # Wrong currency: the amount parses, but it is not the USD the buyer confirmed.
    await handler.continue_order(db_session, buyer_order_id=first)
    record = await paypal_record(db_session, first)
    router.gateway.orders[record.paypal_order_id] = replace(
        router.gateway.orders[record.paypal_order_id], currency="EUR"
    )
    currency_result = await handler.approved(db_session, buyer_order_id=first)

    assert currency_result["status"] == "REJECTED"
    assert await order_status(db_session, first) == "REJECTED"
    assert await _reject_reason(db_session, first) == "CURRENCY_MISMATCH"

    # Wrong payer country: V12 restricts payers to ALLOWED_PAYER_COUNTRIES (US).
    await handler.continue_order(db_session, buyer_order_id=second)
    record = await paypal_record(db_session, second)
    router.gateway.orders[record.paypal_order_id] = replace(
        router.gateway.orders[record.paypal_order_id], payer_country="IN"
    )
    country_result = await handler.approved(db_session, buyer_order_id=second)

    assert country_result["status"] == "REJECTED"
    assert await _reject_reason(db_session, second) == "WRONG_COUNTRY"

    for order_id in (first, second):
        count = await db_session.scalar(
            text("SELECT count(*) FROM paypal_authorizations WHERE buyer_order_id = :id"),
            {"id": order_id},
        )
        assert int(count or 0) == 0
    await _no_money_and_no_authorize_job(world)


async def test_f28_payee_mismatch_rejected(db_session: AsyncSession) -> None:
    """F28 (I1): the order's payee must be the stamped router's own payee."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    (order_id,) = await open_offers(world)
    router = distinct_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    record = await paypal_record(db_session, order_id)
    expected = router.gateway.orders[record.paypal_order_id].payee_email
    router.gateway.orders[record.paypal_order_id] = replace(
        router.gateway.orders[record.paypal_order_id],
        payee_email="someone-else@example.test",
    )

    result = await handler.approved(db_session, buyer_order_id=order_id)

    assert result["status"] == "REJECTED"
    assert await order_status(db_session, order_id) == "REJECTED"
    assert await _reject_reason(db_session, order_id) == "PAYEE_MISMATCH"
    assert expected and expected != "someone-else@example.test"
    count = await db_session.scalar(
        text("SELECT count(*) FROM paypal_authorizations WHERE buyer_order_id = :id"),
        {"id": order_id},
    )
    assert int(count or 0) == 0, "a mismatched payee is never authorized (I1)"
    await _no_money_and_no_authorize_job(world)
