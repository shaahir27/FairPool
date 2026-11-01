"""F8: declined captures open a vacancy and the lot refills or stays unsold (I5).

One capture declines after the sweep started. The seat becomes ``CAPTURE_FAILED``
with a ``CAPTURE_DECLINED`` ledger fact, one vacancy is offered to the waitlist,
and the lot never reaches FUNDED on a completed count below the MOQ. The failure
path itself (void and refund to zero) is T05A03 and is not invented here.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.payments import Payee
from fairpool.modules.allocation.read_service import PostgresAllocationRead
from fairpool.modules.checkout.refill import RefillService
from tests.integration.test_funding import (
    DistinctPayerGateway,
    authorized_orders,
    funding_service,
    lot_status,
    order_status,
)
from tests.integration.test_open_checkout import FakeRouter, build_world

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


async def test_f08_captures_decline_refill_or_fail(db_session: AsyncSession) -> None:
    """F8: a declined capture frees one seat, which refill offers to the waitlist."""
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
    refill_jobs = [job for job in world.ports.jobs.jobs if job.kind == "lot.refill"]
    assert len(refill_jobs) == 1

    refill = RefillService(
        clock=world.ports.clock,
        audit=world.ports.audit,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
    )
    await refill.refill(db_session, {"lot_id": str(world.lot_id)})

    waitlist_entry = world.entry_ids[2]
    offered = await db_session.scalar(
        text("SELECT status FROM buyer_orders WHERE lot_id = :lot AND entry_id = :entry"),
        {"lot": world.lot_id, "entry": waitlist_entry},
    )
    assert str(offered) == "OFFERED"
    waves = await db_session.scalar(
        text("SELECT refill_waves FROM lots WHERE id = :lot"), {"lot": world.lot_id}
    )
    assert waves == 1

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

    refill = RefillService(
        clock=world.ports.clock,
        audit=world.ports.audit,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
    )
    await refill.refill(db_session, {"lot_id": str(world.lot_id)})

    waves = await db_session.scalar(
        text("SELECT refill_waves FROM lots WHERE id = :lot"), {"lot": world.lot_id}
    )
    assert waves == 0
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"
