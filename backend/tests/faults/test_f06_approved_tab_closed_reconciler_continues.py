"""F6: a buyer approves and closes the tab; the reconciler still authorizes (I1).

The approval callback wrote APPROVED but its ``order.authorize`` job was lost with
the browser (or the worker). The sweep finds the APPROVED row and enqueues
``order.resolve``; the resolve re-enqueues the contract's own authorize trigger and
the handler settles the seat. Nothing is invented and no money moves before the
provider reports a CREATED authorization.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.modules.reconciler.resolve import Reconciler
from tests.integration.test_authorize_flow import authorize_handler, open_offers, order_status
from tests.integration.test_open_checkout import build_world, make_router

pytestmark = [pytest.mark.integration, pytest.mark.faults]


async def test_f06_approved_tab_closed_reconciler_continues(db_session: AsyncSession) -> None:
    """F6: an APPROVED seat whose job disappeared is healed by one sweep."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    assert await order_status(db_session, order_id) == "APPROVED"
    # The browser closed before the job could run, so no authorize is queued.
    world.ports.jobs.jobs.clear()

    reconciler = Reconciler(clock=world.ports.clock, jobs=world.ports.jobs)
    await reconciler.sweep(db_session, {})
    resolves = [
        job
        for job in world.ports.jobs.jobs
        if job.kind == "order.resolve" and job.payload["buyer_order_id"] == str(order_id)
    ]
    assert len(resolves) == 1

    await reconciler.resolve(db_session, resolves[0].payload)
    authorizes = [job for job in world.ports.jobs.jobs if job.kind == "order.authorize"]
    assert len(authorizes) == 1, "the resolve re-enqueues the existing trigger, once"

    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "AUTHORIZED"
    assert [entry.kind for entry in world.ports.ledger.entries] == ["AUTH_CREATED"]
    assert (
        int(
            await db_session.scalar(
                text("SELECT count(*) FROM paypal_authorizations WHERE buyer_order_id = :id"),
                {"id": order_id},
            )
            or 0
        )
        == 1
    )
    # The healed row is no longer stale: a second sweep has nothing to re-drive for it.
    before = len(world.ports.jobs.jobs)
    await reconciler.sweep(db_session, {})
    assert not [
        job
        for job in world.ports.jobs.jobs[before:]
        if job.kind == "order.resolve" and job.payload["buyer_order_id"] == str(order_id)
    ]
