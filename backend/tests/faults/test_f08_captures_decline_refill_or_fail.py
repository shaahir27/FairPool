"""F8: declined seats open a vacancy and the lot refills or stays unsold (I5).

F8's case is the vacancy rule: one seat is released, one ``lot.refill`` runs and the
waitlist is offered the seat, while the lot never reaches FUNDED on a completed count
below the MOQ. The failure path itself (void and refund to zero) is T05A03 and is not
invented here.

The vacancy is proved where the contract can continue it: a decline while the lot is
CHECKOUT_OPEN (BO-21). A capture can only decline once the lot is FUNDING, and the
vacancy rule allows a FUNDING refill while BO-01/BO-03 require CHECKOUT_OPEN; the
handler therefore refuses that refill rather than creating an offer nobody could pay
for, which is recorded as Q-2026-11-01-16.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.payments import Payee
from fairpool.modules.allocation.read_service import PostgresAllocationRead
from fairpool.modules.checkout.engine import TransitionRequest
from fairpool.modules.checkout.refill import RefillService
from tests.integration.test_funding import (
    DistinctPayerGateway,
    authorized_orders,
    funding_service,
    lot_status,
    order_status,
)
from tests.integration.test_open_checkout import FakeRouter, World, build_world, open_handler

pytestmark = pytest.mark.integration


class DeclineCaptureGateway(DistinctPayerGateway):
    """Authorizations succeed; every capture reads DECLINED."""

    async def capture_authorization(
        self, auth_id: str, *, amount_cents: int, request_key: str
    ) -> Any:
        capture = await super().capture_authorization(
            auth_id, amount_cents=amount_cents, request_key=request_key
        )
        denied = replace(capture, status="DECLINED")
        self.captures[denied.id] = denied
        return denied


def declining_router() -> FakeRouter:
    return FakeRouter(
        gateway=DeclineCaptureGateway(),
        seller=Payee(email="seller@example.test", merchant_id=None),
    )


def refill_service(world: World) -> RefillService:
    return RefillService(
        clock=world.ports.clock,
        audit=world.ports.audit,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
    )


async def offered_entries(session: AsyncSession, lot_id: Any) -> list[Any]:
    rows = (
        await session.execute(
            text("SELECT entry_id FROM buyer_orders WHERE lot_id = :lot"), {"lot": lot_id}
        )
    ).all()
    return [row.entry_id for row in rows]


async def first_order_id(session: AsyncSession, lot_id: Any) -> Any:
    value = await session.scalar(
        text("SELECT id FROM buyer_orders WHERE lot_id = :lot ORDER BY created_at, id LIMIT 1"),
        {"lot": lot_id},
    )
    assert value is not None
    return value


async def waves(session: AsyncSession, lot_id: Any) -> int:
    value = await session.scalar(
        text("SELECT refill_waves FROM lots WHERE id = :lot"), {"lot": lot_id}
    )
    return int(value or 0)


async def test_f08_a_declined_offer_while_checkout_is_open_refills_the_seat(
    db_session: AsyncSession,
) -> None:
    """F8 (vacancy rule): a decline while CHECKOUT_OPEN frees a seat and refills it."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=1, moq=2)
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    assert len(await offered_entries(db_session, world.lot_id)) == 2

    # BO-21: the buyer declines the offer, which opens exactly one vacancy.
    await world.ports.engine.apply(
        db_session,
        TransitionRequest(
            buyer_order_id=await first_order_id(db_session, world.lot_id),
            to_state="DECLINED",
            trigger=None,
            actor="buyer",
        ),
    )
    await refill_service(world).refill(db_session, {"lot_id": str(world.lot_id)})

    offered = await offered_entries(db_session, world.lot_id)
    assert world.entry_ids[2] in offered, "the waitlisted entry took the vacancy"
    assert await waves(db_session, world.lot_id) == 1
    assert await lot_status(db_session, world.lot_id) == "CHECKOUT_OPEN"


async def test_f08_a_declined_capture_frees_the_seat_and_the_lot_stays_unfunded(
    db_session: AsyncSession,
) -> None:
    """F8: a declined capture frees the seat; the vacancy is not refillable in FUNDING."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=1, moq=2)
    router = declining_router()
    orders = await authorized_orders(world, router=router, count=2)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"

    await service.capture(db_session, {"buyer_order_id": str(orders[0])})

    assert await order_status(db_session, orders[0]) == "CAPTURE_FAILED"
    assert [row.kind for row in world.ports.ledger.entries].count("CAPTURE_DECLINED") == 1
    assert [row.kind for row in world.ports.ledger.entries].count("CAPTURE_COMPLETED") == 0
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.refill") == 1

    # Q-2026-11-01-16: FUNDING is past BO-01's CHECKOUT_OPEN, so the handler refuses and
    # no offer exists that the whitelist could never continue.
    await refill_service(world).refill(db_session, {"lot_id": str(world.lot_id)})
    assert await waves(db_session, world.lot_id) == 0
    assert world.entry_ids[2] not in await offered_entries(db_session, world.lot_id)

    # One completed capture is below moq = 2, so the lot is never FUNDED.
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"


async def test_f08_without_a_waitlist_the_lot_stays_unsold(
    db_session: AsyncSession,
) -> None:
    """F8: with no candidate the vacancy stays open and the lot does not fund."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0, moq=2)
    router = declining_router()
    orders = await authorized_orders(world, router=router, count=2)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})

    await refill_service(world).refill(db_session, {"lot_id": str(world.lot_id)})

    assert await waves(db_session, world.lot_id) == 0
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"
