"""T04A02: approval checks, the authorization flow and F1/F5/F6.

Every acceptance bullet of the task row is a named test: the FR-CK-05 checks
(payee, country and payer-key rules), BO-03 taking the lock, BO-04 reading the
authorization object, an unknown outcome staying AUTHORIZING, and a rejected
order never authorizing.

F1 (authorize times out), F5 (approval after the seat expired) and F6 (approved,
tab closed) are walked end to end against the offline gateway.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import ApplicationError
from fairpool.domain.payments import Payee, PayPalOrder
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.modules.allocation.read_service import PostgresAllocationRead
from fairpool.modules.checkout.authorize import CheckoutAuthorizeHandlers
from fairpool.modules.reconciler.resolve import Reconciler
from tests.integration.test_open_checkout import (
    FakeRouter,
    World,
    build_world,
    make_directory,
    make_router,
    open_handler,
)

pytestmark = pytest.mark.integration


def authorize_handler(world: World, router: FakeRouter | None = None) -> CheckoutAuthorizeHandlers:
    return CheckoutAuthorizeHandlers(
        engine=world.ports.engine,
        clock=world.ports.clock,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
        directory=make_directory(world.merchant_id),
        router=router or make_router(),
        hmac_key="test-hmac-key",
        allowed_payer_countries=("US",),
        dedupe_mode="two_keys",
        public_base_url="https://app.test",
    )


async def open_offers(world: World) -> list[UUID]:
    """Open checkout and return the created order ids in creation order."""
    await open_handler(world).open(world.session, {"lot_id": str(world.lot_id)})
    rows = (
        await world.session.execute(
            text("SELECT id FROM buyer_orders WHERE lot_id = :lot ORDER BY created_at, id"),
            {"lot": world.lot_id},
        )
    ).all()
    return [row.id for row in rows]


async def paypal_record(session: AsyncSession, buyer_order_id: UUID) -> Any:
    return (
        await session.execute(
            text(
                "SELECT paypal_order_id FROM paypal_orders WHERE buyer_order_id = :order "
                "ORDER BY attempt DESC LIMIT 1"
            ),
            {"order": buyer_order_id},
        )
    ).first()


async def order_status(session: AsyncSession, buyer_order_id: UUID) -> str:
    value = await session.scalar(
        text("SELECT status FROM buyer_orders WHERE id = :id"), {"id": buyer_order_id}
    )
    return str(value)


class MismatchAuthorizeGateway(FakePayPalGateway):
    """Returns a CREATED authorization for one cent less than the order."""

    async def authorize_order(self, paypal_order_id: str, *, request_key: str) -> PayPalOrder:
        result = await super().authorize_order(paypal_order_id, request_key=request_key)
        authorization = result.authorizations[0]
        wrong = replace(authorization, amount_cents=authorization.amount_cents - 1)
        updated = replace(result, authorizations=[wrong])
        self.orders[paypal_order_id] = updated
        return updated


# --------------------------------------------------------------- F1 and BO-01


async def test_f1_continue_creates_the_order_under_the_attempt_key(
    db_session: AsyncSession,
) -> None:
    """F1/T04A02: ``create:{buyer_order_id}:{attempt}`` is the create identity."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    handler = authorize_handler(world)

    result = await handler.continue_order(db_session, buyer_order_id=order_id)

    assert result["status"] == "ORDER_CREATED"
    record = await paypal_record(db_session, order_id)
    assert record is not None
    assert result["paypal_order_id"] == record.paypal_order_id
    assert await order_status(db_session, order_id) == "ORDER_CREATED"
    outcome = await db_session.scalar(
        text("SELECT idempotency_key FROM ledger_entries WHERE buyer_order_id = :id"),
        {"id": order_id},
    )
    assert outcome is None  # a create moves no money


async def test_f1_authorize_timeout_stays_authorizing_then_replays_same_key(
    db_session: AsyncSession,
) -> None:
    """F1: an unknown outcome leaves AUTHORIZING and the same key resolves it."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)

    router.gateway.outcome = "timeout_after_send"
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})
    assert await order_status(db_session, order_id) == "AUTHORIZING"
    assert world.ports.ledger.entries == []

    router.gateway.outcome = "completed"
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})
    assert await order_status(db_session, order_id) == "AUTHORIZED"
    # One authorization identity, so the replay could not have made a second one.
    auths = (
        await db_session.execute(
            text("SELECT paypal_auth_id FROM paypal_authorizations WHERE buyer_order_id = :id"),
            {"id": order_id},
        )
    ).all()
    assert len(auths) == 1
    assert [row.kind for row in world.ports.ledger.entries] == ["AUTH_CREATED"]


async def test_approving_after_the_offer_expired_answers_offer_expired(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M12: losing the approval/expiry race is a contract error, never a 500.

    The concurrent transaction in this test is the ``offer.expire`` timer: it commits
    EXPIRED between the handler's read and the locked apply, so the whitelist has no
    ORDER_CREATED to APPROVED edge left and ``IllegalTransition`` would have become a
    500 at the route without the mapping.
    """
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    handler = authorize_handler(world)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    engine = world.ports.engine
    original_apply = engine.apply

    async def racing_apply(session: Any, request: Any) -> Any:
        await session.execute(
            text("UPDATE buyer_orders SET status = 'EXPIRED' WHERE id = :id"), {"id": order_id}
        )
        session.expire_all()
        return await original_apply(session, request)

    monkeypatch.setattr(engine, "apply", racing_apply)

    with pytest.raises(ApplicationError) as raised:
        await handler.approved(db_session, buyer_order_id=order_id)

    assert raised.value.code == "OFFER_EXPIRED"
    assert await order_status(db_session, order_id) == "EXPIRED"


async def test_an_authorize_retry_rechecks_the_seat_under_the_row_lock(
    db_session: AsyncSession,
) -> None:
    """M9: an authorize retry re-proves BO-03, so a seat released in the gap is safe."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    # The first attempt times out, which leaves the row AUTHORIZING with the seat held.
    router.gateway.outcome = "timeout_after_send"
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})
    assert await order_status(db_session, order_id) == "AUTHORIZING"

    # The seat is released before the retry runs (the release is final, F5).
    await db_session.execute(
        text(
            "UPDATE allocations SET status = 'PRICED_OUT'::allocation_status, lot_id = NULL "
            "WHERE entry_id = (SELECT entry_id FROM buyer_orders WHERE id = :id)"
        ),
        {"id": order_id},
    )
    router.gateway.outcome = "completed"
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTHORIZING"
    auth = await db_session.scalar(
        text("SELECT count(*) FROM paypal_authorizations WHERE buyer_order_id = :id"),
        {"id": order_id},
    )
    assert auth == 0, "no authorization may exist for a seat that was released"
    assert world.ports.ledger.entries == []


# ---------------------------------------------------------------------- F5/F6


async def test_f5_approval_after_the_seat_was_released_never_authorizes(
    db_session: AsyncSession,
) -> None:
    """F5: BO-03 refuses a released seat, so the approval never authorizes."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    handler = authorize_handler(world)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    assert await order_status(db_session, order_id) == "APPROVED"

    # The seat is released before the authorize job runs (PRICED_OUT is final).
    await db_session.execute(
        text(
            "UPDATE allocations SET status = 'PRICED_OUT'::allocation_status, lot_id = NULL "
            "WHERE entry_id = (SELECT entry_id FROM buyer_orders WHERE id = :id)"
        ),
        {"id": order_id},
    )
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "APPROVED"
    auth = await db_session.scalar(
        text("SELECT count(*) FROM paypal_authorizations WHERE buyer_order_id = :id"),
        {"id": order_id},
    )
    assert auth == 0
    assert world.ports.ledger.entries == []


async def test_f6_approved_tab_closed_is_continued_by_the_reconciler(
    db_session: AsyncSession,
) -> None:
    """F6: an APPROVED seat with no running authorize job is picked up and healed."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    handler = authorize_handler(world)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    # The approval callback enqueued one job; drop it to model a lost worker.
    world.ports.jobs.jobs.clear()

    reconciler = Reconciler(clock=world.ports.clock, jobs=world.ports.jobs)
    swept = await reconciler.sweep(db_session, {})
    assert swept == 1
    resolves = [job for job in world.ports.jobs.jobs if job.kind == "order.resolve"]
    assert len(resolves) == 1

    await reconciler.resolve(db_session, {"buyer_order_id": resolves[0].payload["buyer_order_id"]})
    authorizes = [job for job in world.ports.jobs.jobs if job.kind == "order.authorize"]
    assert len(authorizes) == 1
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})
    assert await order_status(db_session, order_id) == "AUTHORIZED"


# ------------------------------------------------------------ FR-CK-05 checks


async def test_wrong_payer_country_is_rejected_and_never_authorizes(
    db_session: AsyncSession,
) -> None:
    """FR-CK-05 (V12): a payer outside ALLOWED_PAYER_COUNTRIES is REJECTED."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    record = await paypal_record(db_session, order_id)
    router.gateway.orders[record.paypal_order_id] = replace(
        router.gateway.orders[record.paypal_order_id], payer_country="IN"
    )

    result = await handler.approved(db_session, buyer_order_id=order_id)

    assert result["status"] == "REJECTED"
    assert await order_status(db_session, order_id) == "REJECTED"
    reason = await db_session.scalar(
        text("SELECT reject_reason FROM buyer_orders WHERE id = :id"), {"id": order_id}
    )
    assert reason == "WRONG_COUNTRY"
    assert not [job for job in world.ports.jobs.jobs if job.kind == "order.authorize"]


async def test_payee_mismatch_is_rejected(db_session: AsyncSession) -> None:
    """FR-CK-05: the order's payee must be the stamped router's payee."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    router = make_router(email="seller@example.test")
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    record = await paypal_record(db_session, order_id)
    router.gateway.orders[record.paypal_order_id] = replace(
        router.gateway.orders[record.paypal_order_id],
        payee_email="someone-else@example.test",
    )

    await handler.approved(db_session, buyer_order_id=order_id)

    reason = await db_session.scalar(
        text("SELECT reject_reason FROM buyer_orders WHERE id = :id"), {"id": order_id}
    )
    assert reason == "PAYEE_MISMATCH"


async def test_amount_mismatch_on_the_order_is_rejected(db_session: AsyncSession) -> None:
    """FR-CK-05: the approved order's amount must equal the expected cents."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    record = await paypal_record(db_session, order_id)
    router.gateway.orders[record.paypal_order_id] = replace(
        router.gateway.orders[record.paypal_order_id],
        amount_cents=router.gateway.orders[record.paypal_order_id].amount_cents - 1,
    )

    await handler.approved(db_session, buyer_order_id=order_id)

    reason = await db_session.scalar(
        text("SELECT reject_reason FROM buyer_orders WHERE id = :id"), {"id": order_id}
    )
    assert reason == "AMOUNT_MISMATCH"


async def test_duplicate_payer_key_on_another_active_seat_is_rejected(
    db_session: AsyncSession,
) -> None:
    """FR-ID-04 (two_keys): the checkout key is unique inside the pool on its own."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    first, second = await open_offers(world)
    handler = authorize_handler(world)
    await handler.continue_order(db_session, buyer_order_id=first)
    await handler.approved(db_session, buyer_order_id=first)
    await handler.continue_order(db_session, buyer_order_id=second)

    result = await handler.approved(db_session, buyer_order_id=second)

    assert result["status"] == "REJECTED"
    reason = await db_session.scalar(
        text("SELECT reject_reason FROM buyer_orders WHERE id = :id"), {"id": second}
    )
    assert reason == "DUPLICATE_PAYER"


async def test_a_missing_payer_id_is_rejected(db_session: AsyncSession) -> None:
    """FR-CK-05: without the provider payer id no uniqueness claim can be made."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    record = await paypal_record(db_session, order_id)
    router.gateway.orders[record.paypal_order_id] = replace(
        router.gateway.orders[record.paypal_order_id], payer_id=None
    )

    await handler.approved(db_session, buyer_order_id=order_id)

    reason = await db_session.scalar(
        text("SELECT reject_reason FROM buyer_orders WHERE id = :id"), {"id": order_id}
    )
    assert reason == "PAYER_MISMATCH"


# ------------------------------------------------------------ BO-04 and BO-20


async def test_a_policy_failure_found_before_authorizing_applies_bo19(
    db_session: AsyncSession,
) -> None:
    """BO-19: the checks are re-run from a GET before authorizing; a failure rejects."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    assert await order_status(db_session, order_id) == "APPROVED"
    record = await paypal_record(db_session, order_id)
    router.gateway.orders[record.paypal_order_id] = replace(
        router.gateway.orders[record.paypal_order_id], payer_country="IN"
    )

    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "REJECTED"
    reason = await db_session.scalar(
        text("SELECT reject_reason FROM buyer_orders WHERE id = :id"), {"id": order_id}
    )
    assert reason == "WRONG_COUNTRY"
    auths = await db_session.scalar(
        text("SELECT count(*) FROM paypal_authorizations WHERE buyer_order_id = :id"),
        {"id": order_id},
    )
    assert auths == 0
    assert world.ports.ledger.entries == []


async def test_authorize_reads_the_authorization_object(db_session: AsyncSession) -> None:
    """T04A02: BO-04 requires the authorization status CREATED and its amount."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    handler = authorize_handler(world)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)

    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTHORIZED"
    auth_status = await db_session.scalar(
        text("SELECT status FROM paypal_authorizations WHERE buyer_order_id = :id"),
        {"id": order_id},
    )
    assert str(auth_status) == "CREATED"
    assert [row.kind for row in world.ports.ledger.entries] == ["AUTH_CREATED"]
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.try_fund") >= 1


async def test_wrong_authorization_amount_is_voided_and_rejected(
    db_session: AsyncSession,
) -> None:
    """BO-20 (N5): a different authorized amount is voided at once and rejected."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    gateway = MismatchAuthorizeGateway()
    router = FakeRouter(
        gateway=gateway, seller=Payee(email="seller@example.test", merchant_id=None)
    )
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)

    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "REJECTED"
    reason = await db_session.scalar(
        text("SELECT reject_reason FROM buyer_orders WHERE id = :id"), {"id": order_id}
    )
    assert reason == "AMOUNT_MISMATCH"
    auth_ids = (
        (
            await db_session.execute(
                text("SELECT paypal_auth_id FROM paypal_authorizations WHERE buyer_order_id = :id"),
                {"id": order_id},
            )
        )
        .scalars()
        .all()
    )
    assert len(auth_ids) == 1
    assert gateway.authorizations[auth_ids[0]].status == "VOIDED"
    assert [row.kind for row in world.ports.ledger.entries] == ["AUTH_VOIDED"]


async def test_a_failed_checkout_return_token_authorises_nothing(
    db_session: AsyncSession,
) -> None:
    """FR-CK-05: the return URL's token only looks up our own order row."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    handler = authorize_handler(world)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    record = await paypal_record(db_session, order_id)

    with pytest.raises(ApplicationError) as unknown:
        await handler.checkout_return(db_session, token="NOT-OURS")
    assert unknown.value.code == "NOT_FOUND"

    with pytest.raises(ApplicationError) as foreign:
        await handler.checkout_return(db_session, token=record.paypal_order_id, user_id=UUID(int=1))
    assert foreign.value.code == "NOT_FOUND"

    owner = await db_session.scalar(
        text(
            "SELECT e.user_id FROM buyer_orders b JOIN pool_entries e ON e.id = b.entry_id "
            "WHERE b.id = :id"
        ),
        {"id": order_id},
    )
    result = await handler.checkout_return(db_session, token=record.paypal_order_id, user_id=owner)
    assert result["status"] == "APPROVED"
