"""T04A04 and F27: ``pool.seed`` fetches the announced round or waits.

F27 is the property that a beacon outage never invents a seed: the handler
re-enqueues the same job ten seconds later and stores nothing. Demo mode stores
the derived demo seed with ``seed_is_demo = true``; a live round stores its
randomness together with the full beacon response.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain import hashing
from fairpool.domain.errors import ApplicationError
from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.beacon import DEFAULT_RANDOMNESS, DEFAULT_SIGNATURE, FakeBeacon
from fairpool.fakes.clock import FakeClock
from fairpool.fakes.jobs import FakeJobQueue
from fairpool.infra.clock import DbClock
from fairpool.modules.pools.seed import SEED_RETRY_DELAY_S, PoolSeedService

pytestmark = pytest.mark.integration


async def insert_pool(
    session: AsyncSession,
    *,
    status: str = "CLOSED",
    beacon: dict[str, Any] | None = None,
    seed_hex: str | None = None,
) -> UUID:
    pool_id = uuid4()
    admin = uuid4()
    now = await DbClock().db_now(session)
    timeline = {
        "open_at": (now - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "close_at": (now - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "beacon_delay_s": 10,
        "bid_window_s": 120,
        "offer_window_s": 180,
        "fund_deadline_s": 600,
        "capture_grace_s": 120,
        "pending_wait_s": 120,
        "max_refill_waves": 1,
        "authorization_age_guard_s": 216000,
    }
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', 'Admin', 'admin')"
        ),
        {"id": admin, "email": f"seed-{pool_id}@example.test"},
    )
    await session.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, rules_hash, beacon, seed_hex, created_by) "
            "VALUES (:id, 'LIVE_SANDBOX', CAST(:status AS pool_status), 'Seed pool', "
            "CAST(:template AS jsonb), '[]'::jsonb, CAST(:timeline AS jsonb), false, "
            "'allocation_v1', :rules_hash, CAST(:beacon AS jsonb), :seed_hex, :admin)"
        ),
        {
            "id": pool_id,
            "status": status,
            "template": json.dumps(
                {
                    "product_key": "monitor-27-4k",
                    "title": "27-inch 4K monitor",
                    "condition": "NEW",
                    "currency": "USD",
                }
            ),
            "timeline": json.dumps(timeline),
            "rules_hash": "a" * 64,
            "beacon": None if beacon is None else json.dumps(beacon),
            "seed_hex": seed_hex,
            "admin": admin,
        },
    )
    return pool_id


def seed_service(
    *,
    beacon: FakeBeacon | None = None,
    now: Any = None,
) -> tuple[PoolSeedService, FakeJobQueue, FakeAuditLog, FakeBeacon]:
    clock = FakeClock(now)
    queue = FakeJobQueue(clock=clock)
    audit = FakeAuditLog(clock=lambda: clock.now)
    client = beacon or FakeBeacon()
    return PoolSeedService(clock, audit, queue, client), queue, audit, client


async def state(session: AsyncSession, pool_id: UUID) -> tuple[Any, ...]:
    row = (
        await session.execute(
            text("SELECT status, seed_hex, seed_is_demo, beacon FROM pools WHERE id = :id"),
            {"id": pool_id},
        )
    ).one()
    return (str(row[0]), None if row[1] is None else str(row[1]), row[2], row[3])


async def test_f27_beacon_down_waits_and_never_falls_back(db_session: AsyncSession) -> None:
    """F27: an unavailable round re-enqueues the same job and stores no seed."""
    pool_id = await insert_pool(
        db_session, beacon={"source": "drand", "chain_hash": "ab" * 32, "round": 7}
    )
    now = await DbClock().db_now(db_session)
    service, queue, audit, beacon = seed_service(beacon=FakeBeacon(available=False), now=now)

    await service.seed(db_session, {"pool_id": str(pool_id)})

    status, seed_hex, seed_is_demo, stored_beacon = await state(db_session, pool_id)
    assert status == "CLOSED"
    assert seed_hex is None and seed_is_demo is False
    assert stored_beacon == {"source": "drand", "chain_hash": "ab" * 32, "round": 7}
    assert audit.rows == []
    assert len(queue.jobs) == 1
    retry = queue.jobs[0]
    assert retry.kind == "pool.seed"
    assert retry.run_at == now + timedelta(seconds=SEED_RETRY_DELAY_S)
    assert beacon.fetch_calls and beacon.fetch_calls[0].announced["round"] == 7


async def test_a_later_available_round_stores_the_live_seed(db_session: AsyncSession) -> None:
    """T04A04 acceptance: the seed is stored with the full beacon response."""
    pool_id = await insert_pool(
        db_session, beacon={"source": "drand", "chain_hash": "ab" * 32, "round": 7}
    )
    now = await DbClock().db_now(db_session)
    service, queue, audit, _ = seed_service(now=now)

    await service.seed(db_session, {"pool_id": str(pool_id)})

    status, seed_hex, seed_is_demo, stored_beacon = await state(db_session, pool_id)
    assert status == "SEEDED"
    assert seed_hex == DEFAULT_RANDOMNESS
    assert seed_is_demo is False
    assert stored_beacon["randomness"] == DEFAULT_RANDOMNESS
    assert stored_beacon["signature"] == DEFAULT_SIGNATURE
    actions = [row["row"]["action"] for row in audit.rows]
    assert actions == ["pool.seeded"]
    assert [job.kind for job in queue.jobs] == ["pool.allocate"]


async def test_demo_mode_uses_the_demo_seed_and_labels_it(db_session: AsyncSession) -> None:
    """fairness section 4: ``BEACON_MODE=demo`` sets ``seed_is_demo``."""
    pool_id = await insert_pool(db_session, beacon={"source": "demo"})
    now = await DbClock().db_now(db_session)
    service, queue, _, beacon = seed_service(now=now)

    await service.seed(db_session, {"pool_id": str(pool_id)})

    status, seed_hex, seed_is_demo, _ = await state(db_session, pool_id)
    assert status == "SEEDED"
    assert seed_hex == hashing.demo_seed(str(pool_id))
    assert seed_is_demo is True
    assert beacon.fetch_calls == []
    assert [job.kind for job in queue.jobs] == ["pool.allocate"]


async def test_seed_is_silent_on_a_replay(db_session: AsyncSession) -> None:
    """T04A04 acceptance: a second run writes no row, audit record or job."""
    pool_id = await insert_pool(db_session, beacon={"source": "demo"})
    now = await DbClock().db_now(db_session)
    service, queue, audit, _ = seed_service(now=now)
    await service.seed(db_session, {"pool_id": str(pool_id)})
    jobs, rows = len(queue.jobs), len(audit.rows)

    await service.seed(db_session, {"pool_id": str(pool_id)})

    assert len(queue.jobs) == jobs
    assert len(audit.rows) == rows


async def test_a_pool_that_never_closed_is_left_alone(db_session: AsyncSession) -> None:
    """PS-04 starts at CLOSED; other states have no edge for this trigger."""
    pool_id = await insert_pool(db_session, status="OPEN", beacon={"source": "demo"})
    now = await DbClock().db_now(db_session)
    service, queue, audit, beacon = seed_service(now=now)

    await service.seed(db_session, {"pool_id": str(pool_id)})

    status, seed_hex, _, _ = await state(db_session, pool_id)
    assert status == "OPEN" and seed_hex is None
    assert queue.jobs == [] and audit.rows == [] and beacon.fetch_calls == []


async def test_a_malformed_beacon_value_is_not_a_seed(db_session: AsyncSession) -> None:
    """Never an invented seed: a round without 64 hex characters fails closed."""
    pool_id = await insert_pool(
        db_session, beacon={"source": "drand", "chain_hash": "ab" * 32, "round": 7}
    )
    now = await DbClock().db_now(db_session)
    beacon = FakeBeacon(fetched={"source": "drand", "round": 7, "randomness": "not-hex"})
    service, queue, _, _ = seed_service(beacon=beacon, now=now)

    with pytest.raises(ApplicationError) as raised:
        await service.seed(db_session, {"pool_id": str(pool_id)})
    assert raised.value.code == "INTERNAL_ERROR"
    status, seed_hex, _, _ = await state(db_session, pool_id)
    assert status == "CLOSED" and seed_hex is None
    assert queue.jobs == []


async def test_seed_keeps_the_announcement_alongside_the_fetched_value(
    db_session: AsyncSession,
) -> None:
    """CR-11 acceptance: the beacon dict is merged, never replaced (db-schema.md).

    The fetched body is what drand's ``/pub/{round}`` actually returns: round,
    randomness and signature, with no ``source`` and no ``chain_hash``. Replacing
    the announcement with it dropped those keys, and because
    ``rules_document(pool)`` rebuilds its ``beacon`` sub-dict from the stored value
    at read time, the served document then hashed to something other than the
    stored ``rules_hash`` -- breaking the one property the audit page depends on.
    """
    announced = {"source": "drand", "chain_hash": "ab" * 32, "round": 7, "not_before": 1}
    pool_id = await insert_pool(db_session, beacon=announced)
    now = await DbClock().db_now(db_session)
    beacon = FakeBeacon(
        announced=announced,
        fetched={"round": 7, "randomness": DEFAULT_RANDOMNESS, "signature": DEFAULT_SIGNATURE},
    )
    service, _, _, _ = seed_service(beacon=beacon, now=now)

    await service.seed(db_session, {"pool_id": str(pool_id)})

    _, seed_hex, _, stored = await state(db_session, pool_id)
    assert seed_hex == DEFAULT_RANDOMNESS
    assert stored["source"] == "drand"
    assert stored["chain_hash"] == "ab" * 32
    assert stored["not_before"] == 1
    assert stored["round"] == 7
    assert stored["randomness"] == DEFAULT_RANDOMNESS
    assert stored["signature"] == DEFAULT_SIGNATURE
