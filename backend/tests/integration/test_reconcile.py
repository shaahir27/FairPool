"""T06A03 / B2: unknown outcomes are settled by evidence, once, and scheduled.

``order.resolve`` is the only step that heals a row whose provider answer was lost,
and ``reconciler.sweep`` is what schedules it. This module drives that path end to
end over the real fakes and the Postgres rows, one test per acceptance bullet:

* an AUTHORIZING row is healed by the trigger that owns it, under the key the first
  attempt used, so the ledger gets exactly one ``AUTH_CREATED`` and the lot exactly
  one ``lot.try_fund``;
* the same path settles a DENIED answer as ``AUTH_FAILED`` (BO-05) and a CREATED
  answer for another amount as ``REJECTED`` (BO-20), each with the vacancy and refill
  the contract requires and no invented money fact;
* a CAPTURING vault row is read back by GET into ``CAPTURED`` with one
  ``CAPTURE_COMPLETED``, and a second sweep adds none (I9);
* a provider that holds nothing for the identity leaves the row where it is;
* the cron that ``domain-ports.md`` section 5 calls for enqueues exactly one
  coalescing ``reconciler.sweep`` per tick.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fairpool import worker
from fairpool.domain.payments import (
    ChargeResult,
    Payee,
    PaymentError,
    PayPalAuthorization,
    PayPalOrder,
)
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.modules.checkout.authorize import CheckoutAuthorizeHandlers
from fairpool.modules.checkout.vault_charge import VaultChargeHandler
from fairpool.modules.reconciler.resolve import Reconciler
from tests.integration.test_authorize_flow import authorize_handler, open_offers
from tests.integration.test_funding import capture_status
from tests.integration.test_open_checkout import FakeRouter, World, build_world
from tests.integration.test_vault_charge import (
    first_order,
    order_status,
    vault_handler,
    vault_world,
)

pytestmark = pytest.mark.integration


class RecordedAuthorizeAnswer(FakePayPalGateway):
    """The provider records an answer; the handler's first call loses the reply.

    ``status`` and ``amount_delta`` are what the provider stored, so the replay under
    ``auth:{buyer_order_id}`` reports them (S2 verified authorize replay, I9).
    """

    def __init__(self, *, status: str = "CREATED", amount_delta: int = 0) -> None:
        super().__init__(outcome="completed")
        self.recorded_status = status
        self.amount_delta = amount_delta
        self.auth_id = f"FAKE-AUTH-{uuid4().hex}"
        self.timed_out = False

    async def authorize_order(self, paypal_order_id: str, *, request_key: str) -> PayPalOrder:
        del request_key
        order = self.orders[paypal_order_id]
        authorization = PayPalAuthorization(
            self.auth_id, self.recorded_status, order.amount_cents + self.amount_delta, None
        )
        result = replace(order, authorizations=[authorization])
        self.authorizations[authorization.id] = authorization
        self.orders[paypal_order_id] = result
        if not self.timed_out:
            self.timed_out = True
            raise PaymentError("UNKNOWN", "OUTCOME_UNKNOWN")
        return result


class UnclassifiedAnswerGateway(FakePayPalGateway):
    """The provider recorded the capture; the first answer carried no usable status."""

    def __init__(self) -> None:
        super().__init__(outcome="completed")
        self.answered = False
        self.charge_calls = 0

    async def charge_vault(
        self, buyer_order_id: str, payment_token_id: str, total_cents: int, payee: Payee
    ) -> ChargeResult:
        self.charge_calls += 1
        result = await super().charge_vault(buyer_order_id, payment_token_id, total_cents, payee)
        if not self.answered:
            self.answered = True
            # The resource exists at the provider; only this answer was unreadable.
            return replace(result, capture_status="UNKNOWN")
        return result


class OrderWithoutCaptureGateway(FakePayPalGateway):
    """The provider answered with an order id and holds no capture for it yet."""

    def __init__(self) -> None:
        super().__init__(outcome="completed")
        self.charge_calls = 0

    async def charge_vault(
        self, buyer_order_id: str, payment_token_id: str, total_cents: int, payee: Payee
    ) -> ChargeResult:
        del payment_token_id
        self.charge_calls += 1
        provider_order_id = f"FAKE-ORDER-{buyer_order_id}"
        self.orders[provider_order_id] = PayPalOrder(
            provider_order_id,
            "COMPLETED",
            "CAPTURE",
            "USD",
            total_cents,
            payee.email,
            payee.merchant_id,
            "FAKE-PAYER",
            "US",
            None,
            [],
            [],
            None,
            {"simulated": True},
        )
        return ChargeResult(provider_order_id, None, None, None, total_cents, payee.email)


def router_with(gateway: FakePayPalGateway) -> FakeRouter:
    return FakeRouter(gateway=gateway, seller=Payee(email="seller@example.test", merchant_id=None))


async def sweep_and_resolve_authorize(world: World, order_id: UUID) -> None:
    """Let the AUTHORIZING seat horizon pass, sweep, and run the one resolve."""
    world.ports.clock.advance(121)  # capture_grace_s is 120 in the test timeline
    reconciler = Reconciler(clock=world.ports.clock, jobs=world.ports.jobs)
    assert await reconciler.sweep(world.session, {}) == 1
    await reconciler.resolve(world.session, {"buyer_order_id": str(order_id)})
    # ``order.resolve`` re-enqueues the trigger that owns the state, under its key.
    assert [job.kind for job in world.ports.jobs.jobs].count("order.authorize") == 1


def vault_reconciler(world: World, handler: VaultChargeHandler) -> Reconciler:
    """The production resolver shape: ``order.resolve`` hands CAPTURING to the handler."""

    async def resolve_charge(session: AsyncSession, buyer_order_id: UUID) -> None:
        await handler.reconcile(session, buyer_order_id)

    return Reconciler(clock=world.ports.clock, jobs=world.ports.jobs, resolve_charge=resolve_charge)


async def authorizing_order(
    db_session: AsyncSession, gateway: FakePayPalGateway
) -> tuple[World, UUID, CheckoutAuthorizeHandlers]:
    """Open one offer and leave it AUTHORIZING after an unknown authorize outcome."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    (order_id,) = await open_offers(world)
    handler = authorize_handler(world, router_with(gateway))
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})
    assert await order_status(db_session, order_id) == "AUTHORIZING"
    # Count only what the heal itself schedules, not the offer and deadline jobs.
    world.ports.jobs.jobs.clear()
    return world, order_id, handler


# ------------------------------------------------------- AUTHORIZING unknowns


async def test_an_authorizing_order_is_reconciled_to_authorized(
    db_session: AsyncSession,
) -> None:
    """T06A03 / B2 bullet (a): the replay's CREATED answer heals the row under its key.

    The sweep finds the stale AUTHORIZING row and ``order.resolve`` re-enqueues the
    trigger that owns it, so the provider sees ``auth:{buyer_order_id}`` again: one
    ``AUTH_CREATED`` fact and one ``lot.try_fund``, as the first attempt would have
    written them.
    """
    world, order_id, handler = await authorizing_order(db_session, RecordedAuthorizeAnswer())
    assert world.ports.ledger.entries == []

    await sweep_and_resolve_authorize(world, order_id)
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTHORIZED"
    assert [row.kind for row in world.ports.ledger.entries] == ["AUTH_CREATED"]
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.try_fund") == 1


async def test_an_authorizing_order_denied_is_reconciled_to_auth_failed(
    db_session: AsyncSession,
) -> None:
    """T06A03 / B2 bullet (b): a DENIED answer is definitive, so BO-05 frees the seat.

    A denial moves no money, so the ledger stays empty; BO-05's own effects are the
    vacancy and its one ``lot.refill`` job.
    """
    world, order_id, handler = await authorizing_order(
        db_session, RecordedAuthorizeAnswer(status="DENIED")
    )

    await sweep_and_resolve_authorize(world, order_id)
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTH_FAILED"
    assert world.ports.ledger.entries == []
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.refill") == 1


async def test_an_authorizing_order_for_another_amount_is_rejected_by_bo20(
    db_session: AsyncSession,
) -> None:
    """T06A03 / B2 bullet (b): CREATED for another amount is BO-20, never a pass.

    The replay reports one cent over the expected total, so the authorization is
    voided at once (N5) and the row goes REJECTED with its ``AUTH_VOIDED`` fact and
    one refill.
    """
    gateway = RecordedAuthorizeAnswer(amount_delta=1)
    world, order_id, handler = await authorizing_order(db_session, gateway)

    await sweep_and_resolve_authorize(world, order_id)
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "REJECTED"
    assert [row.kind for row in world.ports.ledger.entries] == ["AUTH_VOIDED"]
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.refill") == 1
    auth_id = await db_session.scalar(
        text("SELECT paypal_auth_id FROM paypal_authorizations WHERE buyer_order_id = :id"),
        {"id": order_id},
    )
    assert gateway.authorizations[str(auth_id)].status == "VOIDED", "N5: voided at once"


# ---------------------------------------------------------- CAPTURING unknowns


async def test_an_unknown_vault_capture_is_reconciled_to_captured_once(
    db_session: AsyncSession,
) -> None:
    """T06A03 / B2 bullet (c): the GET settles the row, and a second sweep pays nothing.

    The provider recorded the capture while our first answer was unreadable, so
    ``_read_back`` is the only path that can prove COMPLETED. A second sweep must add
    no second ledger fact: the row is no longer CAPTURING and the key is unchanged (I9).
    """
    world, _, _, _ = await vault_world(db_session, seats=1)
    gateway = UnclassifiedAnswerGateway()
    router = router_with(gateway)
    handler = vault_handler(world, router)
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})
    assert await order_status(db_session, order_id) == "CAPTURING"
    assert world.ports.ledger.entries == []

    reconciler = vault_reconciler(world, handler)
    world.ports.clock.advance(121)  # capture_grace_s is 120 in the test timeline
    assert await reconciler.sweep(db_session, {}) == 1
    await reconciler.resolve(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "CAPTURED"
    assert [row.kind for row in world.ports.ledger.entries] == ["CAPTURE_COMPLETED"]
    assert await capture_status(db_session, order_id) == "COMPLETED"

    world.ports.clock.advance(121)
    assert await reconciler.sweep(db_session, {}) == 0
    await handler.reconcile(db_session, order_id)

    assert [row.kind for row in world.ports.ledger.entries] == ["CAPTURE_COMPLETED"]
    assert len(gateway.captures) == 1, "one charge identity, so one capture at the provider"
    assert gateway.charge_calls == 1, "the settle came from the read-back, not a second charge"


async def test_a_provider_with_no_capture_leaves_the_row_capturing(
    db_session: AsyncSession,
) -> None:
    """T06A03 / B2 bullet (d): "nothing yet" is not an outcome, so nothing is invented.

    ``_read_back`` finds no capture resource for the stored order id. The row keeps
    CAPTURING for the next sweep, writes no ledger fact and frees no seat.
    """
    world, _, _, _ = await vault_world(db_session, seats=1)
    gateway = OrderWithoutCaptureGateway()
    handler = vault_handler(world, router_with(gateway))
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})
    assert await order_status(db_session, order_id) == "CAPTURING"
    world.ports.jobs.jobs.clear()

    await handler.reconcile(db_session, order_id)

    assert await order_status(db_session, order_id) == "CAPTURING"
    assert world.ports.ledger.entries == []
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM paypal_captures WHERE buyer_order_id = :id"),
            {"id": order_id},
        )
        == 0
    )
    kinds = [job.kind for job in world.ports.jobs.jobs]
    assert (kinds.count("lot.try_fund"), kinds.count("lot.refill")) == (0, 0)
    assert gateway.charge_calls == 1, "the row was read back, never charged a second time"


# ---------------------------------------------------------------- the cron


async def test_the_sweep_cron_enqueues_one_coalescing_job_per_tick(
    db_engine: AsyncEngine,
) -> None:
    """T06A03 / GAP 2: one job per tick, and the dedupe key prevents a pile-up.

    ``domain-ports.md`` section 5 gives ``reconciler.sweep`` the ``reconciler``
    concurrency key and the same dedupe key, so a tick that arrives while the
    previous sweep is still PENDING coalesces into it instead of queueing a second.
    The tick function is called directly: no sleeping and no thread in the test.
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def sweep_rows() -> list[Any]:
        async with factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT payload, concurrency_key, dedupe_key, status FROM jobs "
                        "WHERE kind = :kind"
                    ),
                    {"kind": worker.RECONCILER_KIND},
                )
            ).all()
        return [tuple(row) for row in rows]

    try:
        # This test is the only writer of the kind; start from a known empty set.
        async with factory.begin() as session:
            await session.execute(
                text("DELETE FROM jobs WHERE kind = :kind"), {"kind": worker.RECONCILER_KIND}
            )
        first = await worker.reconciler_tick(factory)
        second = await worker.reconciler_tick(factory)

        assert first is not None
        assert second is None, "the second tick coalesced into the pending sweep"
        rows = await sweep_rows()
        assert len(rows) == 1
        payload, concurrency_key, dedupe_key, status = rows[0]
        assert payload == {}
        assert (concurrency_key, dedupe_key, status) == (
            worker.RECONCILER_KEY,
            worker.RECONCILER_KEY,
            "PENDING",
        )
    finally:
        # Leave no row behind: the fixtures roll back, this test commits.
        async with factory.begin() as session:
            await session.execute(
                text("DELETE FROM jobs WHERE kind = :kind"), {"kind": worker.RECONCILER_KIND}
            )


# ------------------------------------------------------- the cron thread (FIX 4)


def cron_engine() -> Any:
    """The engine the cron thread creates for itself, built from the test database."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from fairpool.db.session import normalize_database_url
    from tests.conftest import database_url

    url, connect_args = normalize_database_url(database_url())
    return create_async_engine(url, connect_args=connect_args, poolclass=NullPool)


async def delete_cron_rows(engine: AsyncEngine) -> None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        await session.execute(
            text("DELETE FROM jobs WHERE kind = :kind"), {"kind": worker.RECONCILER_KIND}
        )


async def test_the_reconciler_thread_enqueues_one_coalesced_sweep(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIX 4: ``start_reconciler_thread`` makes one tick, and its stop event ends it.

    The thread owns its engine, so the test hands it the test database's URL and
    watches the queue: a single tick enqueues ``reconciler.sweep`` with the contract's
    one concurrency key and dedupe key, and setting the event stops the thread within
    its interval instead of waiting for it (``domain-ports.md`` section 5).
    """
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    await delete_cron_rows(db_engine)
    monkeypatch.setattr(worker, "create_engine", lambda *args, **kwargs: cron_engine())
    monkeypatch.setattr(worker, "get_settings", lambda: None)
    stop = threading.Event()
    thread = worker.start_reconciler_thread(stop, interval_s=60.0)
    try:
        rows: list[Any] = []
        for _ in range(250):
            async with factory() as session:
                rows = (
                    await session.execute(
                        text(
                            "SELECT status, concurrency_key, dedupe_key FROM jobs "
                            "WHERE kind = :kind"
                        ),
                        {"kind": worker.RECONCILER_KIND},
                    )
                ).all()
            if rows:
                break
            await asyncio.sleep(0.02)
        assert len(rows) == 1, "one tick, one job"
        assert tuple(rows[0]) == ("PENDING", worker.RECONCILER_KEY, worker.RECONCILER_KEY)
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive(), "the stop event ends the cron without its interval"
    await delete_cron_rows(db_engine)


def test_a_failing_tick_is_logged_and_never_kills_the_cron(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIX 4: a tick that cannot enqueue is named in the log, not raised out of the thread."""
    messages: list[str] = []

    async def broken(factory: Any) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(worker, "create_engine", lambda *args, **kwargs: cron_engine())
    monkeypatch.setattr(worker, "get_settings", lambda: None)
    monkeypatch.setattr(worker, "reconciler_tick", broken)
    monkeypatch.setattr(
        worker.logger,
        "error",
        lambda message, *args, **kwargs: messages.append(message % args),
    )
    stop = threading.Event()
    thread = worker.start_reconciler_thread(stop, interval_s=60.0)
    try:
        for _ in range(250):
            if messages:
                break
            time.sleep(0.02)
        assert messages == ["worker.reconciler_tick.failed type=RuntimeError"]
    finally:
        stop.set()
        thread.join(timeout=10)
    assert not thread.is_alive()
