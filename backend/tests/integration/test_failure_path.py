"""T05A03 and PT-11: the failure path voids, refunds and closes at net zero.

PT-11 is "the failure path with the fake router ends at net zero". The walk is the
contract's: a shortfall at the deadline applies LS-08, ``lot.finalize_fail`` closes
the offers and enqueues one void or refund per order, and LS-10 opens only when the
ledger's net paid is zero with nothing pending.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.payments import Payee
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.modules.checkout.failure import FailureService
from tests.integration.test_funding import (
    authorized_orders,
    funding_service,
    lot_status,
    order_status,
)
from tests.integration.test_open_checkout import FakeRouter, World, build_world

pytestmark = [pytest.mark.integration, pytest.mark.faults]


class PerOrderPayerGateway(FakePayPalGateway):
    """One payer id per buyer order, so three authorizations are all accepted."""

    async def create_order(self, req):  # type: ignore[override]
        from dataclasses import replace

        from fairpool.domain.payments import PayPalOrder

        result = await super().create_order(req)
        updated: PayPalOrder = replace(result, payer_id=f"PAYER-{req.buyer_order_id}")
        self.orders[result.id] = updated
        return updated


def router_for_failure() -> FakeRouter:
    return FakeRouter(
        gateway=PerOrderPayerGateway(outcome="completed"),
        seller=Payee(email="seller@example.test", merchant_id=None),
    )


def failure_service(world: World, *, router: FakeRouter) -> FailureService:
    return FailureService(
        engine=world.ports.engine,
        clock=world.ports.clock,
        audit=world.ports.audit,
        jobs=world.ports.jobs,
        ledger=world.ports.ledger,
        gateway=router.gateway,
    )


async def expire_the_deadline(world: World, session: AsyncSession) -> None:
    await session.execute(
        text("UPDATE lots SET fund_deadline_at = :at WHERE id = :lot"),
        {"at": world.now - timedelta(seconds=1), "lot": world.lot_id},
    )
    await session.flush()


async def drain(world: World, service: FailureService, session: AsyncSession) -> None:
    """Run every queued void or refund handler once, in enqueue order."""
    for job in list(world.ports.jobs.jobs):
        if job.status != "PENDING":
            continue
        if job.kind == "void.run":
            await service.run_void(session, job.payload)
        elif job.kind == "refund.run":
            await service.run_refund(session, job.payload)


async def test_pt11_failure_path_ends_at_net_zero(db_session: AsyncSession) -> None:
    world = await build_world(db_session, seats=3, seated=3, waitlisted=0, moq=3)
    router = router_for_failure()
    orders = await authorized_orders(world, router=router, count=3)
    funding = funding_service(world, router=router)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"
    await funding.capture(db_session, {"buyer_order_id": str(orders[0])})
    assert await order_status(db_session, orders[0]) == "CAPTURED"

    await expire_the_deadline(world, db_session)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FAILING"

    service = failure_service(world, router=router)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FAILING"

    await drain(world, service, db_session)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})

    statuses = [await order_status(db_session, order_id) for order_id in orders]
    assert statuses == ["REFUNDED", "VOIDED", "VOIDED"]
    assert await lot_status(db_session, world.lot_id) == "FAILED_CLOSED"
    assert await world.ports.ledger.net_paid_cents(db_session, world.lot_id) == 0


async def test_a_declined_capture_lot_still_closes_at_zero(db_session: AsyncSession) -> None:
    """No capture ever completed: every authorization is voided, net stays zero."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0, moq=2)
    router = router_for_failure()
    orders = await authorized_orders(world, router=router, count=2)
    funding = funding_service(world, router=router)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await expire_the_deadline(world, db_session)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})

    service = failure_service(world, router=router)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})
    await drain(world, service, db_session)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})

    assert [await order_status(db_session, order_id) for order_id in orders] == [
        "VOIDED",
        "VOIDED",
    ]
    assert await lot_status(db_session, world.lot_id) == "FAILED_CLOSED"
    assert await world.ports.ledger.net_paid_cents(db_session, world.lot_id) == 0


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

    # The provider has the capture but the buyer-order is still CAPTURE_PENDING:
    # money is in flight, so the lot must not close yet.
    await db_session.execute(
        text("UPDATE buyer_orders SET status = 'CAPTURE_PENDING' WHERE id = :id"),
        {"id": orders[0]},
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


class RefundFailsGateway(PerOrderPayerGateway):
    async def refund_capture(self, capture_id, *, amount_cents, request_key):  # type: ignore[override]
        from fairpool.domain.payments import PaymentError

        raise PaymentError("TERMINAL", "REFUND_NOT_ALLOWED")


async def test_f24_a_failed_refund_keeps_the_lot_failing(db_session: AsyncSession) -> None:
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
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})

    assert await order_status(db_session, orders[0]) == "CAPTURED"
    assert await lot_status(db_session, world.lot_id) != "FAILED_CLOSED"
    assert await world.ports.ledger.net_paid_cents(db_session, world.lot_id) > 0
