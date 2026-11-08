"""F23: a worker killed mid-sweep is re-claimed, and re-running its steps changes nothing.

The claim statement re-queues RUNNING rows whose lease expired (``infra/jobs.py``),
so a job that died with its process is handed to the next worker instead of being
stranded. The steps themselves are idempotent: the sweep only enqueues, the resolve
only re-enqueues the contract's trigger, and the authorize handler replays its own
key (I9, I10). Re-running the whole healed path leaves one authorization and one
ledger fact.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.reconciler.resolve import Reconciler
from tests.integration.test_authorize_flow import authorize_handler, open_offers, order_status
from tests.integration.test_open_checkout import build_world, make_router

pytestmark = [pytest.mark.integration, pytest.mark.faults]


async def test_f23_worker_killed_mid_sweep(db_session: AsyncSession) -> None:
    """F23: an expired lease brings the sweep back; every step is safe to repeat."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    (order_id,) = await open_offers(world)
    router = make_router()
    handler = authorize_handler(world, router)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    # The approval's job is gone: the sweep is the only thing that can heal the row.
    jobs = PostgresJobQueue()
    reconciler = Reconciler(clock=world.ports.clock, jobs=jobs)

    sweep_id = await jobs.enqueue(
        db_session,
        "reconciler.sweep",
        {},
        concurrency_key="reconciler",
        dedupe_key="reconciler",
    )
    assert sweep_id is not None
    (killed,) = await jobs.claim(db_session, worker_id="worker-a", kinds=("reconciler.sweep",))
    assert killed.id == sweep_id
    # The process dies with the job RUNNING; its lease is all that is left of it.
    await db_session.execute(
        text("UPDATE jobs SET locked_until = now() - interval '1 second' WHERE id = :id"),
        {"id": sweep_id},
    )

    (reclaimed,) = await jobs.claim(db_session, worker_id="worker-b", kinds=("reconciler.sweep",))
    assert reclaimed.id == sweep_id, "the killed sweep is re-claimed, not replaced"
    assert reclaimed.attempts == 2

    await reconciler.sweep(db_session, reclaimed.payload)
    await jobs.complete(db_session, reclaimed.id, worker_id="worker-b", attempt=2)

    (resolve,) = await jobs.claim(db_session, worker_id="worker-b", kinds=("order.resolve",))
    assert resolve.payload["buyer_order_id"] == str(order_id)
    await reconciler.resolve(db_session, resolve.payload)
    await jobs.complete(db_session, resolve.id, worker_id="worker-b", attempt=1)
    (authorize,) = await jobs.claim(db_session, worker_id="worker-b", kinds=("order.authorize",))
    await handler.authorize(db_session, authorize.payload)
    await jobs.complete(db_session, authorize.id, worker_id="worker-b", attempt=1)

    assert await order_status(db_session, order_id) == "AUTHORIZED"
    assert [entry.kind for entry in world.ports.ledger.entries] == ["AUTH_CREATED"]
    assert len(router.gateway.authorizations) == 1

    # A duplicate delivery of the same steps (the crash before `complete`) is a replay.
    replay_id = await jobs.enqueue(
        db_session,
        "order.authorize",
        {"buyer_order_id": str(order_id)},
        concurrency_key=f"bo:{order_id}",
    )
    assert replay_id is not None
    (replay,) = await jobs.claim(db_session, worker_id="worker-b", kinds=("order.authorize",))
    await handler.authorize(db_session, replay.payload)
    await jobs.complete(db_session, replay.id, worker_id="worker-b", attempt=1)

    assert [entry.kind for entry in world.ports.ledger.entries] == ["AUTH_CREATED"]
    assert len(router.gateway.authorizations) == 1
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
    # Both jobs that died in flight are accounted for, none left RUNNING.
    running = int(
        await db_session.scalar(
            text(
                "SELECT count(*) FROM jobs WHERE status = 'RUNNING' AND kind IN "
                "('reconciler.sweep','order.resolve','order.authorize')"
            )
        )
        or 0
    )
    assert running == 0
