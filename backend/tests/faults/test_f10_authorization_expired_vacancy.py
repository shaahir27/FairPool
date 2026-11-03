"""F10: an authorization that expired at PayPal must give the seat back (I8).

The bug this replaces: a buyer approved, the authorize call timed out with the money
already in flight at PayPal, and the seat sat ``AUTHORIZING``. The reconciler re-drove
``order.authorize`` forever, and every drive returned early at BO-03's seat re-check once
the lot left ``CHECKOUT_OPEN`` -- the whitelist had no exit from ``AUTHORIZING`` that the
clock could satisfy. So the lot could neither fund nor close at net zero, because LS-08
and LS-10 refuse to move over a live authorization (Q-2026-11-01-18).

CR-8 note 1 settled the reading: an aged seat is resolved by what the provider says about
it, through edges that already exist. The two tests below are both halves of that rule --
the age guard is what unlocks it, and before the guard nothing moves.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.payments import Payee, PaymentError, PayPalOrder
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.modules.reconciler.resolve import Reconciler
from tests.integration.test_authorize_flow import authorize_handler, order_status
from tests.integration.test_open_checkout import (
    FakeRouter,
    World,
    build_world,
    open_handler,
)

pytestmark = pytest.mark.faults

#: Any span past the guard, which ``pool_config.py`` keeps below 72 hours.
AGED = timedelta(days=30)


class ExpiredAuthorizeGateway(FakePayPalGateway):
    """The authorization that exists at PayPal is ``EXPIRED``, and always was.

    A real authorize call can land at PayPal while ours times out; by the time anyone
    looks again the authorization has expired, and ``paypal-adapter.md`` section 4 says
    that means the order is not authorized. The expiry is written into everything a later
    read can reach -- the stored order, the authorization table and the replay -- before
    the lost response is raised, so the replay, the authorization GET and the order GET
    all say the same thing.
    """

    async def authorize_order(self, paypal_order_id: str, *, request_key: str) -> PayPalOrder:
        outcome, self.outcome = self.outcome, "completed"
        try:
            result = await super().authorize_order(paypal_order_id, request_key=request_key)
        finally:
            self.outcome = outcome
        expired = replace(result.authorizations[0], status="EXPIRED")
        stored = replace(result, authorizations=[expired])
        self.authorizations[expired.id] = expired
        self.orders[paypal_order_id] = stored
        self.replays[request_key] = (self.replays[request_key][0], stored)
        self._timeout(request_key)
        return stored


class NeverArrivedGateway(FakePayPalGateway):
    """The authorize send died before PayPal saw it, so no authorization exists anywhere.

    ``timeout_after_send`` above stores the authorization first and then raises, which is
    F1's shape. This is the other one: the replay that S2 proved safe is safe only
    because the provider already knows the key, so a write here would create a fresh
    authorization on a seat whose I7 re-check has already failed.
    """

    def __init__(self) -> None:
        super().__init__()
        self.authorize_calls = 0

    async def authorize_order(self, paypal_order_id: str, *, request_key: str) -> PayPalOrder:
        self.authorize_calls += 1
        raise PaymentError("RETRYABLE", "TIMEOUT")


def hung_router(*, reached: bool = True) -> FakeRouter:
    gateway: FakePayPalGateway = ExpiredAuthorizeGateway() if reached else NeverArrivedGateway()
    return FakeRouter(gateway=gateway, seller=Payee("seller@example.test", None))


async def hung_seat(
    session: AsyncSession, *, aged: bool, reached: bool = True
) -> tuple[World, UUID, FakeRouter]:
    """One seat hung in ``AUTHORIZING`` while its lot moved on to ``FUNDING``.

    A buyer approved, the authorize send was lost after it reached PayPal (the fake
    stores the authorization and then raises, which is F1), and the offer row is left
    ``AUTHORIZING``. ``aged`` then back-dates the row past the pool's age guard; the
    un-aged case keeps the seat honest, since I7 holds a seat that may still be paid.
    ``reached=False`` is the send that never arrived, so the provider holds nothing.
    """
    world = await build_world(session, seats=1, seated=1, waitlisted=0, mode="authorize_capture")
    await open_handler(world).open(world.session, {"lot_id": str(world.lot_id)})
    order_id = UUID(
        str(
            await world.session.scalar(
                text("SELECT id FROM buyer_orders WHERE lot_id = :lot ORDER BY created_at, id"),
                {"lot": world.lot_id},
            )
        )
    )
    # One gateway for the whole scene: the fake keeps orders in memory, so a create on
    # one instance cannot be read back from another.
    router = hung_router(reached=reached)
    handler = authorize_handler(world, router)
    await handler.continue_order(world.session, buyer_order_id=order_id)
    await handler.approved(world.session, buyer_order_id=order_id)
    if reached:
        router.gateway.outcome = "timeout_after_send"
    await handler.authorize(world.session, {"buyer_order_id": str(order_id)})
    assert await order_status(world.session, order_id) == "AUTHORIZING"

    await session.execute(
        text("UPDATE lots SET status = 'FUNDING'::lot_status WHERE id = :lot"),
        {"lot": world.lot_id},
    )
    if aged:
        # The row's own timestamp moves past the guard. The fake clock is frozen at
        # ``world.now``, so the arithmetic is exact rather than raced (I15).
        await session.execute(
            text("UPDATE buyer_orders SET updated_at = :stale WHERE id = :id"),
            {"stale": world.now - AGED, "id": order_id},
        )
    await session.flush()
    return world, order_id, router


async def test_f10_authorization_expired_vacancy(db_session: AsyncSession) -> None:
    """Past the age guard the expired authorization ends the seat and frees the vacancy."""
    world, order_id, router = await hung_seat(db_session, aged=True)

    await authorize_handler(world, router).authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTH_FAILED"
    # No money moved: an expired authorization funds nothing and writes no ledger fact,
    # so nothing here can be counted toward the lot's minimum (I4, I5).
    assert [str(getattr(entry, "kind", "")) for entry in world.ports.ledger.entries] == []
    # BO-05's effect is the refill, and I8 needs the seat back.
    assert "lot.refill" in [job.kind for job in world.ports.jobs.jobs]
    active = await db_session.scalar(
        text(
            "SELECT count(*) FROM buyer_orders WHERE lot_id = :lot AND status IN "
            "('OFFERED','ORDER_CREATED','APPROVED','AUTHORIZING','AUTHORIZED','CAPTURING',"
            "'CAPTURE_PENDING','CAPTURED','REFUNDING')"
        ),
        {"lot": world.lot_id},
    )
    assert int(active or 0) == 0, "an expired seat cannot keep a lot at its seat count"
    # The sweep the bug was: a settled row leaves the reconciler's own status filter, so
    # there is nothing left to re-drive (T06A03).
    before = len(world.ports.jobs.jobs)
    assert (
        await Reconciler(clock=world.ports.clock, jobs=world.ports.jobs).sweep(db_session, {}) == 0
    )
    assert len(world.ports.jobs.jobs) == before


async def test_an_aged_seat_the_provider_never_saw_is_settled_by_a_read_not_a_write(
    db_session: AsyncSession,
) -> None:
    """The replay S2 proved safe is safe only because the provider already knows the key.

    With the send lost before it arrived, ``auth:{buyer_order_id}`` is an id PayPal has
    never seen, so replaying it would create an authorization on a seat that the BO-03
    re-check has already refused (I7, I9). Only the order read settles what is there.
    """
    world, order_id, router = await hung_seat(db_session, aged=True, reached=False)

    await authorize_handler(world, router).authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTHORIZING"
    assert int(router.gateway.authorize_calls) == 1, "the aged path must not write"
    assert world.ports.ledger.entries == []


async def test_an_unaged_seat_still_waits_and_is_never_settled_by_the_clock(
    db_session: AsyncSession,
) -> None:
    """The guard is the discriminator: before it, nothing about the seat changes.

    Without this half the age guard would be a way to abandon a seat PayPal may still
    honour, which is exactly what I7 and I9 exist to prevent.
    """
    world, order_id, router = await hung_seat(db_session, aged=False)

    await authorize_handler(world, router).authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTHORIZING"
    assert [job.kind for job in world.ports.jobs.jobs if job.kind == "lot.refill"] == []
    assert world.ports.ledger.entries == []
