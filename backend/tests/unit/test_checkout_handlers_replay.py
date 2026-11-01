"""Every checkout handler returns silently on a legitimate retry (I15).

A job runner may deliver the same job twice (a lease expiry, a reconciler sweep,
an operator re-run). Each handler in this phase therefore starts by re-reading the
state it owns and, when the work is already done, writes no row, no audit record,
no notification and no next job. This module proves exactly that for every
handler, one test per handler.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.clock import FakeClock
from fairpool.modules.allocation.read_service import PostgresAllocationRead
from fairpool.modules.allocation.service import AllocationService
from fairpool.modules.checkout.funding import FundingService
from fairpool.modules.checkout.refill import RefillService
from fairpool.modules.checkout.vault_charge import VaultChargeHandler
from fairpool.modules.reconciler.resolve import Reconciler
from tests.integration.test_allocation_lots import add_eligible, insert_seeded_pool
from tests.integration.test_authorize_flow import authorize_handler, open_offers
from tests.integration.test_funding import (
    authorized_orders,
    distinct_router,
    funding_service,
)
from tests.integration.test_open_checkout import (
    build_world,
    make_directory,
    make_router,
    open_handler,
)
from tests.integration.test_seed_waits import insert_pool, seed_service
from tests.integration.test_vault_charge import add_token, cipher

pytestmark = pytest.mark.integration


async def counts(session: AsyncSession, table: str, where: str, params: dict[str, Any]) -> int:
    value = await session.scalar(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)
    return int(value or 0)


async def test_pool_seed_returns_silently_on_a_retry(db_session: AsyncSession) -> None:
    """T04A04: a second ``pool.seed`` writes no audit row and no job."""
    pool_id = await insert_pool(db_session, beacon={"source": "demo"})
    service, queue, audit, _ = seed_service(now=None)
    await service.seed(db_session, {"pool_id": str(pool_id)})
    jobs, rows = len(queue.jobs), len(audit.rows)

    await service.seed(db_session, {"pool_id": str(pool_id)})

    assert (len(queue.jobs), len(audit.rows)) == (jobs, rows)


async def test_pool_allocate_returns_silently_on_a_retry(db_session: AsyncSession) -> None:
    """T04A05: a second ``pool.allocate`` adds no allocation, lot or audit row."""
    pool_id = await insert_seeded_pool(db_session)
    await add_eligible(db_session, pool_id, count=3)
    audit_service, audit = await _allocate(db_session, pool_id)
    allocations = await counts(db_session, "allocations", "pool_id = :p", {"p": pool_id})
    lots = await counts(db_session, "lots", "pool_id = :p", {"p": pool_id})
    rows = len(audit.rows)

    await audit_service.allocate(db_session, {"pool_id": str(pool_id)})

    assert await counts(db_session, "allocations", "pool_id = :p", {"p": pool_id}) == allocations
    assert await counts(db_session, "lots", "pool_id = :p", {"p": pool_id}) == lots
    assert len(audit.rows) == rows


async def _allocate(session: AsyncSession, pool_id: UUID) -> tuple[Any, Any]:
    audit = FakeAuditLog()
    service = AllocationService(FakeClock(), audit)
    await service.allocate(session, {"pool_id": str(pool_id)})
    return service, audit


async def test_open_checkout_returns_silently_on_a_retry(db_session: AsyncSession) -> None:
    """T04A01: a second ``lot.open_checkout`` adds no order, job or audit row."""
    world = await build_world(db_session, seats=3, seated=2, waitlisted=1)
    handler = open_handler(world)
    await handler.open(db_session, {"lot_id": str(world.lot_id)})
    orders = await counts(db_session, "buyer_orders", "lot_id = :l", {"l": world.lot_id})
    jobs, rows = len(world.ports.jobs.jobs), len(world.ports.audit.rows)

    await handler.open(db_session, {"lot_id": str(world.lot_id)})

    assert await counts(db_session, "buyer_orders", "lot_id = :l", {"l": world.lot_id}) == orders
    assert (len(world.ports.jobs.jobs), len(world.ports.audit.rows)) == (jobs, rows)


async def test_order_authorize_returns_silently_on_a_retry(db_session: AsyncSession) -> None:
    """T04A02: ``order.authorize`` on an AUTHORIZED seat writes nothing."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    (order_id,) = await open_offers(world)
    handler = authorize_handler(world)
    await handler.continue_order(db_session, buyer_order_id=order_id)
    await handler.approved(db_session, buyer_order_id=order_id)
    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})
    audits = len(world.ports.audit.rows)
    ledger = len(world.ports.ledger.entries)

    await handler.authorize(db_session, {"buyer_order_id": str(order_id)})

    assert len(world.ports.audit.rows) == audits
    assert len(world.ports.ledger.entries) == ledger


async def test_order_capture_returns_silently_on_a_retry(db_session: AsyncSession) -> None:
    """T04A03: ``order.capture`` on a CAPTURED seat writes nothing."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    ledger = len(world.ports.ledger.entries)
    captures = await counts(db_session, "paypal_captures", "buyer_order_id = :o", {"o": orders[0]})

    await service.capture(db_session, {"buyer_order_id": str(orders[0])})

    assert len(world.ports.ledger.entries) == ledger
    assert (
        await counts(db_session, "paypal_captures", "buyer_order_id = :o", {"o": orders[0]})
        == captures
    )


async def test_capture_poll_returns_silently_on_a_retry(db_session: AsyncSession) -> None:
    """T04A03: ``capture.poll`` on a CAPTURED seat writes nothing."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    audits = len(world.ports.audit.rows)

    await service.poll(db_session, {"buyer_order_id": str(orders[0])})

    assert len(world.ports.audit.rows) == audits


async def test_vault_charge_returns_silently_on_a_retry(db_session: AsyncSession) -> None:
    """T04A02: ``order.vault_charge`` on a CAPTURED seat writes nothing."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, mode="vault_charge")
    await add_token(
        db_session,
        entry_id=world.entry_ids[0],
        user_id=world.user_ids[0],
        cap_cents=60_000,
    )
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    order_id = await db_session.scalar(
        text("SELECT id FROM buyer_orders WHERE lot_id = :lot"), {"lot": world.lot_id}
    )
    router = make_router()
    handler = VaultChargeHandler(
        engine=world.ports.engine,
        clock=world.ports.clock,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
        directory=make_directory(world.merchant_id),
        router=router,
        cipher=cipher(),
        concurrency=5,
    )
    await handler.charge(db_session, {"buyer_order_id": str(order_id)})
    ledger = len(world.ports.ledger.entries)
    audits = len(world.ports.audit.rows)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    assert len(world.ports.ledger.entries) == ledger
    assert len(world.ports.audit.rows) == audits


async def test_try_fund_returns_silently_on_a_retry(db_session: AsyncSession) -> None:
    """T04A03: ``lot.try_fund`` on a FUNDED lot adds no transition or job."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    jobs, audits = len(world.ports.jobs.jobs), len(world.ports.audit.rows)
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.finalize_close") == 1

    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})

    assert (len(world.ports.jobs.jobs), len(world.ports.audit.rows)) == (jobs, audits)


async def test_refill_returns_silently_when_no_vacancy_remains(db_session: AsyncSession) -> None:
    """T04A03: a second ``lot.refill`` offers nothing and spends no wave."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=1)
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    seated_order = await db_session.scalar(
        text("SELECT id FROM buyer_orders WHERE lot_id = :lot"), {"lot": world.lot_id}
    )
    await db_session.execute(
        text("UPDATE buyer_orders SET status = 'EXPIRED'::buyer_order_status WHERE id = :id"),
        {"id": seated_order},
    )
    service = RefillService(
        clock=world.ports.clock,
        audit=world.ports.audit,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
    )
    await service.refill(db_session, {"lot_id": str(world.lot_id)})
    waves = await db_session.scalar(
        text("SELECT refill_waves FROM lots WHERE id = :lot"), {"lot": world.lot_id}
    )
    jobs, audits = len(world.ports.jobs.jobs), len(world.ports.audit.rows)
    assert waves == 1

    await service.refill(db_session, {"lot_id": str(world.lot_id)})

    assert (
        await db_session.scalar(
            text("SELECT refill_waves FROM lots WHERE id = :lot"), {"lot": world.lot_id}
        )
        == waves
    )
    assert (len(world.ports.jobs.jobs), len(world.ports.audit.rows)) == (jobs, audits)


async def test_finalize_close_returns_silently_on_a_retry(db_session: AsyncSession) -> None:
    """LS-11: a second ``lot.finalize_close`` on a CLOSED lot writes nothing."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=1)
    service: FundingService = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.finalize_close(db_session, {"lot_id": str(world.lot_id)})
    audits, notified = len(world.ports.audit.rows), len(world.ports.notifier.calls)

    await service.finalize_close(db_session, {"lot_id": str(world.lot_id)})

    assert (len(world.ports.audit.rows), len(world.ports.notifier.calls)) == (audits, notified)


async def test_order_resolve_returns_silently_for_a_settled_order(
    db_session: AsyncSession,
) -> None:
    """T04A03: ``order.resolve`` on a CAPTURED order enqueues no trigger."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, moq=1)
    router = distinct_router()
    orders = await authorized_orders(world, router=router, count=1)
    service = funding_service(world, router=router)
    await service.try_fund(db_session, {"lot_id": str(world.lot_id)})
    await service.capture(db_session, {"buyer_order_id": str(orders[0])})
    jobs = len(world.ports.jobs.jobs)

    reconciler = Reconciler(clock=world.ports.clock, jobs=world.ports.jobs)
    await reconciler.resolve(db_session, {"buyer_order_id": str(orders[0])})

    assert len(world.ports.jobs.jobs) == jobs
