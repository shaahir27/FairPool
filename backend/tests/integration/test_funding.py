"""T04A03 and PT-09: funding trigger, capture sweep, polling and close.

PT-09 is "FUNDED only when completed captures from distinct buyers reach the MOQ".
The tests walk the authorize path for real (continue, approve, authorize against
the offline gateway), then exercise ``lot.try_fund``, ``order.capture``,
``capture.poll`` and ``lot.finalize_close`` against the Postgres rows and the fake
ledger.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import IllegalTransition
from fairpool.domain.payments import Payee, PaymentError, PayPalCapture, PayPalOrder
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.modules.allocation.read_service import PostgresAllocationRead
from fairpool.modules.checkout.authorize import CheckoutAuthorizeHandlers
from fairpool.modules.checkout.funding import FundingService
from tests.integration.test_authorize_flow import authorize_handler
from tests.integration.test_open_checkout import (
    FakeRouter,
    World,
    build_world,
    make_router,
    open_handler,
)

pytestmark = pytest.mark.integration


class DistinctPayerGateway(FakePayPalGateway):
    """One payer id per buyer order, so the pool-level dedupe can pass them all."""

    async def create_order(self, req: Any) -> PayPalOrder:
        result = await super().create_order(req)
        updated = replace(result, payer_id=f"PAYER-{req.buyer_order_id}")
        self.orders[result.id] = updated
        return updated


def distinct_router(*, outcome: str = "completed") -> FakeRouter:
    return FakeRouter(
        gateway=DistinctPayerGateway(outcome=outcome),
        seller=Payee(email="seller@example.test", merchant_id=None),
    )


class TimeoutOnFirstCaptureGateway(DistinctPayerGateway):
    """The provider took the capture; the first answer is lost (I9, B2).

    ``FundingService.reconcile`` replays ``cap:{paypal_auth_id}``, so the stored answer
    is what the second call returns: the same capture, never a second one.
    """

    def __init__(self, *, status: str = "COMPLETED", amount_delta: int = 0) -> None:
        super().__init__(outcome="completed")
        self.recorded_status = status
        self.amount_delta = amount_delta
        self.capture_calls = 0

    async def capture_authorization(
        self, auth_id: str, *, amount_cents: int, request_key: str
    ) -> PayPalCapture:
        result = await super().capture_authorization(
            auth_id, amount_cents=amount_cents, request_key=request_key
        )
        self.capture_calls += 1
        recorded = replace(
            result,
            status=self.recorded_status,
            amount_cents=result.amount_cents + self.amount_delta,
        )
        self.replays[request_key] = ((auth_id, amount_cents), recorded)
        self.captures[recorded.id] = recorded
        if self.capture_calls == 1:
            raise PaymentError("UNKNOWN", "OUTCOME_UNKNOWN")
        return recorded


class UnreadableCaptureGateway(DistinctPayerGateway):
    """The provider never answers a capture, so there is nothing to read back."""

    async def capture_authorization(
        self, auth_id: str, *, amount_cents: int, request_key: str
    ) -> PayPalCapture:
        raise PaymentError("UNKNOWN", "OUTCOME_UNKNOWN")


async def authorized_orders(world: World, *, router: FakeRouter, count: int) -> list[UUID]:
    """Open checkout, then approve and authorize the first ``count`` offers."""
    await open_handler(world).open(world.session, {"lot_id": str(world.lot_id)})
    rows = (
        await world.session.execute(
            text("SELECT id FROM buyer_orders WHERE lot_id = :lot ORDER BY created_at, id"),
            {"lot": world.lot_id},
        )
    ).all()
    handler: CheckoutAuthorizeHandlers = authorize_handler(world, router)
    chosen = [row.id for row in rows[:count]]
    for order_id in chosen:
        await handler.continue_order(world.session, buyer_order_id=order_id)
        await handler.approved(world.session, buyer_order_id=order_id)
        await handler.authorize(world.session, {"buyer_order_id": str(order_id)})
        assert (
            await world.session.scalar(
                text("SELECT status FROM buyer_orders WHERE id = :id"), {"id": order_id}
            )
        ).__str__() == "AUTHORIZED"
    return chosen


def funding_service(
    world: World,
    *,
    router: FakeRouter | None = None,
    capture_buffer: int = 0,
    capture_concurrency: int = 5,
) -> FundingService:
    return FundingService(
        engine=world.ports.engine,
        clock=world.ports.clock,
        audit=world.ports.audit,
        jobs=world.ports.jobs,
        notifier=world.ports.notifier,
        ledger=world.ports.ledger,
        allocations=PostgresAllocationRead(),
        gateway=(router or make_router()).gateway,
        capture_concurrency=capture_concurrency,
        capture_buffer=capture_buffer,
    )


async def order_status(session: AsyncSession, buyer_order_id: UUID) -> str:
    return str(
        await session.scalar(
            text("SELECT status FROM buyer_orders WHERE id = :id"), {"id": buyer_order_id}
        )
    )


async def lot_status(session: AsyncSession, lot_id: UUID) -> str:
    return str(
        await session.scalar(text("SELECT status FROM lots WHERE id = :lot"), {"lot": lot_id})
    )


# -------------------------------------------------------------------- LS-06


async def test_pt09_funding_waits_for_the_moq_of_completed_captures(
    db_session: AsyncSession,
) -> None:
    """PT-09: authorized seats fund the lot; only completed captures make it FUNDED."""
    world = await build_world(db_session, seats=3, seated=3, waitlisted=0, moq=2)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=3)
    service = funding_service(world, router=router)

    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"
    assert [job.kind for job in world.ports.jobs.jobs].count("order.capture") == 3

    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"

    await service.capture(db_session, {"buyer_order_id": str(orders[1])})
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDED"
    assert [row.kind for row in world.ports.ledger.entries].count("CAPTURE_COMPLETED") == 2
    assert [call.kind for call in world.ports.notifier.calls].count("lot.funded") == 1
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.finalize_close") == 1


async def test_the_capture_buffer_raises_the_trigger_threshold(
    db_session: AsyncSession,
) -> None:
    """T04A03 acceptance: ``authorized >= min(seats, moq + CAPTURE_BUFFER)``."""
    world = await build_world(db_session, seats=3, seated=3, waitlisted=0, moq=2)
    router = distinct_router()
    await authorized_orders(world, router=router, count=2)
    service = funding_service(world, router=router, capture_buffer=1)

    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})

    # min(3, 2 + 1) = 3 authorizations needed, only 2 exist.
    assert await lot_status(db_session, world.lot_id) == "CHECKOUT_OPEN"


async def test_the_deadline_funds_at_the_moq_without_the_buffer(
    db_session: AsyncSession,
) -> None:
    """T04A03 acceptance: past the deadline ``A >= moq`` is enough (LS-06)."""
    world = await build_world(
        db_session,
        seats=3,
        seated=3,
        waitlisted=0,
        moq=1,
        fund_deadline_at=None,
    )
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router, capture_buffer=1)

    # Before the deadline the buffer rule blocks it (threshold = min(3, 1 + 1) = 2).
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "CHECKOUT_OPEN"

    await db_session.execute(
        text("UPDATE lots SET fund_deadline_at = :at WHERE id = :lot"),
        {"at": world.now - timedelta(seconds=1), "lot": world.lot_id},
    )
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"
    assert orders


async def test_vault_mode_funds_on_completed_captures_from_the_ledger(
    db_session: AsyncSession,
) -> None:
    """LS-06/LS-07 (CR-4): vault mode has no authorization and counts the ledger."""
    world = await build_world(
        db_session, seats=2, seated=2, waitlisted=0, mode="vault_charge", moq=2
    )
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    created = (
        (
            await db_session.execute(
                text("SELECT id FROM buyer_orders WHERE lot_id = :lot"), {"lot": world.lot_id}
            )
        )
        .scalars()
        .all()
    )
    for order_id in created:
        await world.ports.ledger.record(
            db_session,
            lot_id=world.lot_id,
            buyer_order_id=order_id,
            kind="CAPTURE_COMPLETED",
            amount_cents=50_000,
            paypal_ref=f"CAP-{order_id}",
            idempotency_key=f"seed:{order_id}",
            source="api",
        )
    service = funding_service(world)

    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})

    assert await lot_status(db_session, world.lot_id) == "FUNDED"
    assert await world.ports.ledger.completed_capture_count(db_session, world.lot_id) == 2


# ---------------------------------------------------------------- capturing


async def test_a_pending_capture_is_polled_and_not_counted_as_paid(
    db_session: AsyncSession,
) -> None:
    """BO-08: PENDING records its ledger fact and schedules ``capture.poll``."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router(outcome="pending")
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"

    await service.capture(db_session, {"buyer_order_id": str(orders[0])})

    assert await order_status(db_session, orders[0]) == "CAPTURE_PENDING"
    assert [row.kind for row in world.ports.ledger.entries].count("CAPTURE_PENDING") == 1
    assert [job.kind for job in world.ports.jobs.jobs].count("capture.poll") == 1


async def test_capture_poll_completes_a_pending_capture(db_session: AsyncSession) -> None:
    """BO-09: a COMPLETED GET is the only thing that pays a pending capture."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router(outcome="pending")
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    assert await order_status(db_session, orders[0]) == "CAPTURE_PENDING"

    capture_id, capture = next(iter(router.gateway.captures.items()))
    router.gateway.captures[capture_id] = replace(capture, status="COMPLETED")
    await service.poll(db_session, {"buyer_order_id": str(orders[0])})

    assert await order_status(db_session, orders[0]) == "CAPTURED"
    assert [row.kind for row in world.ports.ledger.entries].count("CAPTURE_COMPLETED") == 1
    assert await capture_status(db_session, orders[0]) == "COMPLETED"


async def test_capture_poll_records_a_declined_outcome_on_the_capture_row(
    db_session: AsyncSession,
) -> None:
    """M6: the stored ``paypal_captures.status`` follows every poll, not only the order."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router(outcome="pending")
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    assert await capture_status(db_session, orders[0]) == "PENDING"

    capture_id, capture = next(iter(router.gateway.captures.items()))
    router.gateway.captures[capture_id] = replace(capture, status="DECLINED")
    await service.poll(db_session, {"buyer_order_id": str(orders[0])})

    assert await order_status(db_session, orders[0]) == "CAPTURE_FAILED"
    assert await capture_status(db_session, orders[0]) == "DECLINED"


async def capture_status(session: AsyncSession, buyer_order_id: UUID) -> str:
    """The stored ``paypal_captures.status`` for one buyer order (M6, I4)."""
    return str(
        await session.scalar(
            text("SELECT status FROM paypal_captures WHERE buyer_order_id = :id"),
            {"id": buyer_order_id},
        )
    )


async def test_no_capture_slot_requeues_instead_of_calling_paypal(
    db_session: AsyncSession, db_engine: Any
) -> None:
    """T04A03 acceptance: the sweep runs at most CAPTURE_CONCURRENCY at once."""
    from fairpool.modules.checkout.funding import CAPTURE_SLOT_NAMESPACE, _slot_key

    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router, capture_concurrency=1)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    async with db_engine.connect() as other:
        transaction = await other.begin()
        held = await other.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": _slot_key(CAPTURE_SLOT_NAMESPACE, 0)},
        )
        assert held
        try:
            await service.capture(db_session, {"buyer_order_id": str(orders[0])})
        finally:
            await transaction.rollback()

    assert await order_status(db_session, orders[0]) == "AUTHORIZED"
    assert router.gateway.captures == {}
    # One from LS-06, one from the busy-slot requeue.
    assert [job.kind for job in world.ports.jobs.jobs].count("order.capture") == 2


# -------------------------------------------------------------- LS-07 / LS-11


async def test_finalize_close_moves_funded_to_closed_and_notifies(
    db_session: AsyncSession,
) -> None:
    """LS-11: only a FUNDED lot closes, with audit and the merchant notification."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDED"

    await service.finalize_close(db_session, {"lot_id": str(world.lot_id)})

    assert await lot_status(db_session, world.lot_id) == "CLOSED"
    actions = [row["row"]["action"] for row in world.ports.audit.rows]
    assert "lot.closed" in actions
    assert [call.kind for call in world.ports.notifier.calls].count("lot.closed") == 1


async def test_finalize_close_ignores_a_lot_that_is_not_funded(
    db_session: AsyncSession,
) -> None:
    """LS-11 starts at FUNDED; anything else is left alone."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    service = funding_service(world)
    await service.finalize_close(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "AWARDED"
    assert world.ports.audit.rows == []


async def test_a_pending_capture_at_the_deadline_keeps_the_lot_funded(
    db_session: AsyncSession,
) -> None:
    """M5: LS-11 needs the capture window over, so a PENDING capture blocks the close."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0, moq=1)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=2)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})

    router.gateway.outcome = "pending"
    await service.capture(db_session, {"buyer_order_id": str(orders[1])})
    assert await order_status(db_session, orders[1]) == "CAPTURE_PENDING"
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDED"

    await service.finalize_close(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDED", "a capture is in flight"

    pending_capture_id = await db_session.scalar(
        text("SELECT paypal_capture_id FROM paypal_captures WHERE buyer_order_id = :id"),
        {"id": orders[1]},
    )
    capture = router.gateway.captures[str(pending_capture_id)]
    router.gateway.captures[str(pending_capture_id)] = replace(capture, status="COMPLETED")
    await service.poll(db_session, {"buyer_order_id": str(orders[1])})
    assert await order_status(db_session, orders[1]) == "CAPTURED"

    await service.finalize_close(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "CLOSED"


async def test_an_earlier_funding_event_is_not_swallowed_by_the_deadline_timer(
    db_session: AsyncSession,
) -> None:
    """M4: the deadline timer owns ``try_fund:{lot}``; a capture event still pulls it in.

    The lot's deadline is far in the future and its stored ``fund_deadline_at`` is
    never touched here: the completed capture's own ``lot.try_fund`` effect is what
    makes the funding decision run, because a coalesced enqueue keeps the earlier
    ``run_at`` (``infra/jobs.enqueue``).
    """
    from fairpool.infra.audit import PostgresAuditLog
    from fairpool.infra.clock import DbClock
    from fairpool.infra.idempotency import PostgresIdempotencyStore
    from fairpool.infra.jobs import PostgresJobQueue
    from fairpool.modules.checkout.engine import CheckoutEngine
    from fairpool.modules.checkout.open_checkout import OpenCheckoutHandler

    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    clock, jobs = DbClock(), PostgresJobQueue()
    await OpenCheckoutHandler(
        clock=clock,
        audit=world.ports.audit,
        jobs=jobs,
        notifier=world.ports.notifier,
        allocations=PostgresAllocationRead(),
    ).open(db_session, {"lot_id": str(world.lot_id)})
    (deadline,) = (
        await db_session.execute(
            text(
                "SELECT run_at FROM jobs WHERE kind = 'lot.try_fund' AND payload->>'lot_id' = :lot"
            ),
            {"lot": str(world.lot_id)},
        )
    ).one()
    stored_deadline = await db_session.scalar(
        text("SELECT fund_deadline_at FROM lots WHERE id = :lot"), {"lot": world.lot_id}
    )
    assert stored_deadline is not None

    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=1)
    service = FundingService(
        engine=CheckoutEngine(
            clock=clock,
            audit=PostgresAuditLog(),
            jobs=jobs,
            ledger=world.ports.ledger,
            notifier=world.ports.notifier,
            idempotency=PostgresIdempotencyStore(),
        ),
        clock=clock,
        audit=world.ports.audit,
        jobs=jobs,
        notifier=world.ports.notifier,
        ledger=world.ports.ledger,
        allocations=PostgresAllocationRead(),
        gateway=router.gateway,
        capture_concurrency=5,
        capture_buffer=0,
    )
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    assert await order_status(db_session, orders[0]) == "CAPTURED"

    rows = (
        await db_session.execute(
            text(
                "SELECT run_at FROM jobs WHERE kind = 'lot.try_fund' AND status = 'PENDING' "
                "AND payload->>'lot_id' = :lot"
            ),
            {"lot": str(world.lot_id)},
        )
    ).all()
    assert len(rows) == 1, "one coalesced funding job, not two"
    assert rows[0][0] < deadline, "the capture event pulled the deadline timer forward"
    # The deadline itself was never rewritten to make this happen.
    assert (
        await db_session.scalar(
            text("SELECT fund_deadline_at FROM lots WHERE id = :lot"), {"lot": world.lot_id}
        )
        == stored_deadline
    )
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDED"


# --------------------------------------------- the last funding event (FIX 1)


async def test_a_try_fund_enqueue_while_one_runs_gets_its_own_row(
    db_session: AsyncSession,
) -> None:
    """FIX 1: a RUNNING ``lot.try_fund`` never absorbs the next event (domain-ports.md 5).

    ``enqueue`` coalesces only into a PENDING row. A running handler may have read its
    counts already, so the event must get a row of its own with no dedupe key and be
    guaranteed to run; the running job's own concurrency key still serialises them.
    """
    from fairpool.infra.jobs import PostgresJobQueue

    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    jobs = PostgresJobQueue()
    # This test is the only writer of the kind: start from a known empty queue.
    await db_session.execute(text("DELETE FROM jobs WHERE kind = 'lot.try_fund'"))
    dedupe = f"try_fund:{world.lot_id}"

    async def enqueue_try_fund() -> UUID | None:
        return await jobs.enqueue(
            db_session,
            "lot.try_fund",
            {"lot_id": str(world.lot_id)},
            concurrency_key=f"lot:{world.lot_id}",
            dedupe_key=dedupe,
        )

    first = await enqueue_try_fund()
    assert first is not None
    (running,) = await jobs.claim(db_session, worker_id="w", kinds=("lot.try_fund",))
    assert running.id == first

    second = await enqueue_try_fund()

    assert second is not None and second != first
    rows = (
        await db_session.execute(
            text("SELECT id, status, dedupe_key FROM jobs WHERE kind = 'lot.try_fund'")
        )
    ).all()
    assert {row.id: (row.status, row.dedupe_key) for row in rows} == {
        first: ("RUNNING", dedupe),
        second: ("PENDING", None),
    }

    await jobs.complete(db_session, first, worker_id="w", attempt=running.attempts)
    (claimed,) = await jobs.claim(db_session, worker_id="w", kinds=("lot.try_fund",))
    assert claimed.id == second and claimed.attempts == 1, "the second job runs exactly once"
    await jobs.complete(db_session, second, worker_id="w", attempt=claimed.attempts)
    assert await jobs.claim(db_session, worker_id="w", kinds=("lot.try_fund",)) == []


async def test_a_capture_while_try_fund_runs_still_evaluates_the_lot(
    db_session: AsyncSession,
) -> None:
    """FIX 1: a capture that lands mid-run still gets the lot evaluated afterwards.

    The lot is FUNDING and the deadline ``lot.try_fund`` owns ``try_fund:{lot}`` in
    RUNNING when the last capture completes. The capture's ``job:lot.try_fund`` effect
    must not merge into that running row (which has already read its counts): it
    becomes an un-keyed job of its own, which is claimed and funds the lot (LS-07).
    """
    from fairpool.infra.audit import PostgresAuditLog
    from fairpool.infra.clock import DbClock
    from fairpool.infra.idempotency import PostgresIdempotencyStore
    from fairpool.infra.jobs import PostgresJobQueue
    from fairpool.modules.checkout.engine import CheckoutEngine
    from fairpool.modules.checkout.open_checkout import OpenCheckoutHandler

    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    clock, jobs = DbClock(), PostgresJobQueue()
    await db_session.execute(text("DELETE FROM jobs WHERE kind = 'lot.try_fund'"))
    await OpenCheckoutHandler(
        clock=clock,
        audit=world.ports.audit,
        jobs=jobs,
        notifier=world.ports.notifier,
        allocations=PostgresAllocationRead(),
    ).open(db_session, {"lot_id": str(world.lot_id)})
    router = distinct_router()
    service = FundingService(
        engine=CheckoutEngine(
            clock=clock,
            audit=PostgresAuditLog(),
            jobs=jobs,
            ledger=world.ports.ledger,
            notifier=world.ports.notifier,
            idempotency=PostgresIdempotencyStore(),
        ),
        clock=clock,
        audit=world.ports.audit,
        jobs=jobs,
        notifier=world.ports.notifier,
        ledger=world.ports.ledger,
        allocations=PostgresAllocationRead(),
        gateway=router.gateway,
        capture_concurrency=5,
        capture_buffer=0,
    )
    (order_id,) = (
        (
            await db_session.execute(
                text("SELECT id FROM buyer_orders WHERE lot_id = :lot"), {"lot": world.lot_id}
            )
        )
        .scalars()
        .all()
    )
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})
    assert await order_status(db_session, order_id) == "AUTHORIZED"
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"

    # The deadline timer's funding evaluation is in flight: it owns ``try_fund:{lot}``
    # and has read its counts, so nothing it does later can see the capture below.
    (deadline_job,) = (
        (
            await db_session.execute(
                text(
                    "SELECT id FROM jobs WHERE kind = 'lot.try_fund' AND status = 'PENDING' "
                    "AND payload->>'lot_id' = :lot"
                ),
                {"lot": str(world.lot_id)},
            )
        )
        .scalars()
        .all()
    )
    await db_session.execute(
        text("UPDATE jobs SET run_at = now() - interval '1 second' WHERE id = :id"),
        {"id": deadline_job},
    )
    (running,) = await jobs.claim(db_session, worker_id="w", kinds=("lot.try_fund",))
    assert running.id == deadline_job

    await service.capture(db_session, {"buyer_order_id": str(order_id)})
    assert await order_status(db_session, order_id) == "CAPTURED"
    assert await lot_status(db_session, world.lot_id) == "FUNDING", "the running job owns it"

    queued = (
        await db_session.execute(
            text(
                "SELECT id, payload, dedupe_key FROM jobs WHERE kind = 'lot.try_fund' "
                "AND status = 'PENDING'"
            )
        )
    ).all()
    assert len(queued) == 1, "the capture's event is its own job"
    assert queued[0].dedupe_key is None, "a RUNNING job cannot absorb it"

    await jobs.complete(db_session, deadline_job, worker_id="w", attempt=running.attempts)
    (next_job,) = await jobs.claim(db_session, worker_id="w", kinds=("lot.try_fund",))
    assert next_job.id == queued[0].id
    await service.try_fund(db_session, next_job.payload)
    assert await lot_status(db_session, world.lot_id) == "FUNDED"


# ---------------------------------------------- FundingService.reconcile (FIX 3)


async def capturing_order(world: World, *, router: FakeRouter) -> UUID:
    """Authorize one seat, fund the lot and lose the capture answer (still CAPTURING)."""
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(world.session, {"lot_id": str(world.lot_id)})
    await service.capture(world.session, {"buyer_order_id": str(orders[0])})
    assert await order_status(world.session, orders[0]) == "CAPTURING"
    return orders[0]


async def test_reconcile_replays_the_capture_key_and_pays_once(
    db_session: AsyncSession,
) -> None:
    """``order.resolve`` for a CAPTURING row: the replay pays once, a second call none.

    The unknown outcome is settled under ``cap:{paypal_auth_id}``, the key the first
    attempt used, so the provider replays instead of capturing twice (I9). The stored
    status follows the answer, the ledger gets its one fact, and the lot's funding
    event is scheduled; a second call finds the row CAPTURED and adds nothing.
    """
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    gateway = TimeoutOnFirstCaptureGateway()
    router = FakeRouter(
        gateway=gateway, seller=Payee(email="seller@example.test", merchant_id=None)
    )
    order_id = await capturing_order(world, router=router)
    assert [row.kind for row in world.ports.ledger.entries] == ["AUTH_CREATED"], "no money yet"
    service = funding_service(world, router=router)

    await service.reconcile(db_session, order_id)

    assert await order_status(db_session, order_id) == "CAPTURED"
    assert await capture_status(db_session, order_id) == "COMPLETED"
    assert [row.kind for row in world.ports.ledger.entries] == [
        "AUTH_CREATED",
        "CAPTURE_COMPLETED",
    ]
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.try_fund") >= 1
    assert gateway.capture_calls == 2, "the second call was a replay, not a new capture"

    await service.reconcile(db_session, order_id)

    assert [row.kind for row in world.ports.ledger.entries] == [
        "AUTH_CREATED",
        "CAPTURE_COMPLETED",
    ]
    assert len(gateway.captures) == 1, "one capture identity at the provider"


async def test_reconcile_settles_a_declined_replay_as_capture_failed(
    db_session: AsyncSession,
) -> None:
    """A replay that reports DECLINED moves no money: BO-11 fails the seat."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = FakeRouter(
        gateway=TimeoutOnFirstCaptureGateway(status="DECLINED"),
        seller=Payee(email="seller@example.test", merchant_id=None),
    )
    order_id = await capturing_order(world, router=router)
    service = funding_service(world, router=router)
    refills = [job for job in world.ports.jobs.jobs if job.kind == "lot.refill"]

    await service.reconcile(db_session, order_id)

    assert await order_status(db_session, order_id) == "CAPTURE_FAILED"
    assert await capture_status(db_session, order_id) == "DECLINED"
    kinds = [row.kind for row in world.ports.ledger.entries]
    assert "CAPTURE_COMPLETED" not in kinds, "a declined replay pays nothing"
    refills_after = [job for job in world.ports.jobs.jobs if job.kind == "lot.refill"]
    assert len(refills_after) == len(refills) + 1, "BO-11 opens one vacancy and refill"


async def test_reconcile_never_accepts_a_capture_for_another_amount(
    db_session: AsyncSession,
) -> None:
    """A replay paying a different amount is not this seat's payment (I3, BO-07).

    The authorize ladder has no whitelisted edge for a capture mismatch, so the engine
    refuses it instead of inventing one: the row stays CAPTURING with no ledger fact.
    The vault path settles the same contradiction on evidence instead of retrying it
    (``VaultChargeHandler._settle_evidence``).
    """
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = FakeRouter(
        gateway=TimeoutOnFirstCaptureGateway(amount_delta=1),
        seller=Payee(email="seller@example.test", merchant_id=None),
    )
    order_id = await capturing_order(world, router=router)
    service = funding_service(world, router=router)

    with pytest.raises(IllegalTransition):
        await service.reconcile(db_session, order_id)

    assert await order_status(db_session, order_id) == "CAPTURING"
    assert [row.kind for row in world.ports.ledger.entries] == ["AUTH_CREATED"]


async def test_reconcile_leaves_the_row_when_the_provider_answers_nothing(
    db_session: AsyncSession,
) -> None:
    """An unreachable provider proves nothing: no ledger fact, no transition, no refill."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = FakeRouter(
        gateway=UnreadableCaptureGateway(),
        seller=Payee(email="seller@example.test", merchant_id=None),
    )
    order_id = await capturing_order(world, router=router)
    service = funding_service(world, router=router)
    kinds_before = [job.kind for job in world.ports.jobs.jobs]

    await service.reconcile(db_session, order_id)

    assert await order_status(db_session, order_id) == "CAPTURING"
    assert [row.kind for row in world.ports.ledger.entries] == ["AUTH_CREATED"]
    assert [job.kind for job in world.ports.jobs.jobs] == kinds_before
