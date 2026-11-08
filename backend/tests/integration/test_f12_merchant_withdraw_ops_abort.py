"""F12: a merchant withdraws, the operator aborts, and the lot closes at net zero.

There is no merchant self-service withdrawal in the contract: the response is the
ops abort (LS-09 on a FUNDING lot), which records why, hands the lot to
``lot.finalize_fail`` and lets it void the live authorization and refund the
completed capture before LS-10 closes it. The abort is an audited transition, not a
status write, and a lot with money still landing is refused rather than closed over.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.checkout import ops
from fairpool.modules.checkout.failure import FailureService
from tests.integration.test_funding import (
    authorized_orders,
    distinct_router,
    funding_service,
    lot_status,
    order_status,
)
from tests.integration.test_open_checkout import build_world

pytestmark = pytest.mark.integration


async def _run_money_jobs(session: AsyncSession, service: FailureService) -> None:
    """Run the void and refund handlers the abort's failure pass queued."""
    rows = (
        await session.execute(
            text(
                "SELECT kind, payload FROM jobs WHERE status = 'PENDING' "
                "AND kind IN ('void.run','refund.run') ORDER BY run_at, created_at"
            )
        )
    ).all()
    for row in rows:
        if str(row.kind) == "void.run":
            await service.run_void(session, row.payload)
        else:
            await service.run_refund(session, row.payload)


async def test_f12_merchant_withdraw_ops_abort(db_session: AsyncSession) -> None:
    """F12: an ops abort on a live lot is recorded and the money nets to zero."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0, moq=2)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=2)
    funding = funding_service(world, router=router)
    await funding.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await funding.capture(db_session, {"buyer_order_id": str(orders[0])})
    assert await lot_status(db_session, world.lot_id) == "FUNDING"

    result = await ops.abort(
        db_session,
        lot_id=world.lot_id,
        actor="ops:merchant_withdraw",
        notifier=world.ports.notifier,
    )

    assert result == {
        "lot_id": str(world.lot_id),
        "status": "FAILING",
        "transition_id": "LS-09",
    }
    assert await lot_status(db_session, world.lot_id) == "FAILING"
    payload = await db_session.scalar(
        text(
            "SELECT payload FROM audit_log WHERE subject_type = 'lot' AND subject_id = :lot "
            "AND action = 'lot.failing' ORDER BY seq DESC LIMIT 1"
        ),
        {"lot": str(world.lot_id)},
    )
    assert payload is not None
    assert payload["aborted"] is True
    assert payload["transition_id"] == "LS-09"
    assert payload["trigger"] == "job:lot.try_fund"

    service = FailureService(
        engine=world.ports.engine,
        clock=world.ports.clock,
        audit=PostgresAuditLog(),
        jobs=PostgresJobQueue(),
        ledger=world.ports.ledger,
        gateway=router.gateway,
    )
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})
    await _run_money_jobs(db_session, service)
    await service.finalize_fail(db_session, {"lot_id": str(world.lot_id)})

    assert [await order_status(db_session, order_id) for order_id in orders] == [
        "REFUNDED",
        "VOIDED",
    ]
    assert await lot_status(db_session, world.lot_id) == "FAILED_CLOSED"
    assert await world.ports.ledger.net_paid_cents(db_session, world.lot_id) == 0
    closed = await db_session.scalar(
        text(
            "SELECT payload FROM audit_log WHERE subject_type = 'lot' AND subject_id = :lot "
            "AND action = 'lot.failed_closed' ORDER BY seq DESC LIMIT 1"
        ),
        {"lot": str(world.lot_id)},
    )
    assert closed is not None and closed["transition_id"] == "LS-10"
