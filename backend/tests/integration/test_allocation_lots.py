"""T04A05: ``pool.allocate``, lot formation, LS-12 and the real read service.

The ordering itself is property-tested in PT-01/PT-02; this module proves the
persisted result: one allocation per ELIGIBLE entry with its zone rank, lots in
plan order with the timeline's bid window, an undersized lot cancelled through
LS-12, PS-05 and PS-09 through the whitelist, and ``next_candidates`` applying N12
inside the caller's transaction.
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
from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.clock import FakeClock
from fairpool.fakes.jobs import FakeJobQueue
from fairpool.infra.clock import DbClock
from fairpool.modules.allocation.read_service import LotViewDetail, PostgresAllocationRead
from fairpool.modules.allocation.service import AllocationService
from tests.integration.test_open_checkout import build_world, timeline

pytestmark = pytest.mark.integration

ZONE = "US-EAST"


async def insert_seeded_pool(
    session: AsyncSession,
    *,
    status: str = "SEEDED",
    plan: list[dict[str, Any]] | None = None,
    close_in: int = -60,
) -> UUID:
    pool_id = uuid4()
    admin = uuid4()
    now = await DbClock().db_now(session)
    # Entries can only be inserted into an OPEN pool whose window is still live;
    # ``add_eligible`` closes the window once the rows exist.
    data = timeline(now)
    assert close_in == -60
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', 'Admin', 'admin')"
        ),
        {"id": admin, "email": f"alloc-{pool_id}@example.test"},
    )
    await session.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, rules_hash, seed_hex, seed_is_demo, created_by) "
            "VALUES (:id, 'LIVE_SANDBOX', CAST(:status AS pool_status), 'Allocation pool', "
            "CAST(:template AS jsonb), CAST(:plan AS jsonb), CAST(:timeline AS jsonb), false, "
            "'allocation_v1', :rules_hash, :seed, false, :admin)"
        ),
        {
            "id": pool_id,
            "status": "OPEN",
            "template": json.dumps(
                {
                    "product_key": "monitor-27-4k",
                    "title": "27-inch 4K monitor",
                    "condition": "NEW",
                    "currency": "USD",
                    "zones": [{"zone_id": ZONE, "label": "US East", "regions": ["NY"]}],
                }
            ),
            "plan": json.dumps(
                plan
                or [
                    {
                        "zone_id": ZONE,
                        "lots": [{"seats": 2, "min_seats": 2}, {"seats": 2, "min_seats": 2}],
                    }
                ]
            ),
            "timeline": json.dumps(data),
            "rules_hash": "a" * 64,
            "seed": "d" * 64,
            "admin": admin,
        },
    )
    return pool_id


async def add_eligible(
    session: AsyncSession,
    pool_id: UUID,
    *,
    count: int,
    zone: str = ZONE,
    status: str = "SEEDED",
) -> list[UUID]:
    """Add ELIGIBLE entries (the insert trigger needs an OPEN pool), then set status."""
    entry_ids: list[UUID] = []
    for _index in range(count):
        user_id = uuid4()
        entry_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) "
                "VALUES (:id, :email, 'hash', 'Buyer')"
            ),
            {"id": user_id, "email": f"alloc-buyer-{entry_id}@example.test"},
        )
        await session.execute(
            text(
                "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, request_hash, "
                "cap_cents, zone_id, status, submitted_via) VALUES (:id, :pool, :user, "
                "CAST(:request AS jsonb), :hash, 60000, :zone, 'ELIGIBLE', 'human')"
            ),
            {
                "id": entry_id,
                "pool": pool_id,
                "user": user_id,
                "request": json.dumps(
                    {
                        "v": 1,
                        "currency": "USD",
                        "max_total_cents": 60000,
                        "delivery": {"zone_id": zone, "region": "NY"},
                    }
                ),
                "hash": "b" * 64,
                "zone": zone,
            },
        )
        commitment = hashing.sha256_hex(f"commitment:{entry_id}")
        await session.execute(
            text(
                "INSERT INTO entry_receipts (entry_id, commitment, salt, signature, signed_at) "
                "VALUES (:entry, :commitment, :salt, 'sig', now())"
            ),
            {"entry": entry_id, "commitment": commitment, "salt": "e" * 64},
        )
        entry_ids.append(entry_id)
    await close_window(session, pool_id, status=status)
    return entry_ids


async def close_window(session: AsyncSession, pool_id: UUID, *, status: str = "SEEDED") -> None:
    """Set the lifecycle status and move ``close_at`` behind the wall clock."""
    now = await DbClock().db_now(session)
    closed = (now - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    await session.execute(
        text(
            "UPDATE pools SET status = CAST(:status AS pool_status), "
            "timeline = jsonb_set(timeline, '{close_at}', to_jsonb(CAST(:close AS text))) "
            "WHERE id = :id"
        ),
        {"status": status, "close": closed, "id": pool_id},
    )


async def run_allocate(
    session: AsyncSession, pool_id: UUID
) -> tuple[AllocationService, FakeAuditLog]:
    audit = FakeAuditLog()
    service = AllocationService(FakeClock(), audit, FakeJobQueue())
    await service.allocate(session, {"pool_id": str(pool_id)})
    return service, audit


async def test_pool_allocate_ranks_forms_lots_and_waitlists(db_session: AsyncSession) -> None:
    """T04A05 acceptance: ranks per zone, lots in plan order, the rest waitlisted."""
    pool_id = await insert_seeded_pool(db_session)
    entries = await add_eligible(db_session, pool_id, count=5)

    _, audit = await run_allocate(db_session, pool_id)

    status = await db_session.scalar(
        text("SELECT status FROM pools WHERE id = :id"), {"id": pool_id}
    )
    assert str(status) == "ALLOCATED"
    allocations = (
        await db_session.execute(
            text(
                "SELECT entry_id, rank, status, lot_id, rank_hash FROM allocations "
                "WHERE pool_id = :pool ORDER BY rank"
            ),
            {"pool": pool_id},
        )
    ).all()
    assert [row.rank for row in allocations] == [1, 2, 3, 4, 5]
    assert {row.entry_id for row in allocations} == set(entries)
    assert all(len(str(row.rank_hash)) == 64 for row in allocations)
    seated = [row for row in allocations if str(row.status) == "SEATED"]
    waitlisted = [row for row in allocations if str(row.status) == "WAITLISTED"]
    assert len(seated) == 4 and len(waitlisted) == 1
    assert all(row.lot_id is not None for row in seated)
    assert waitlisted[0].lot_id is None

    lots = (
        await db_session.execute(
            text(
                "SELECT lot_order, lot_index, seats, min_seats, status, bid_open_at, "
                "bid_close_at FROM lots WHERE pool_id = :pool ORDER BY lot_order"
            ),
            {"pool": pool_id},
        )
    ).all()
    assert [row.lot_order for row in lots] == [1, 2]
    assert [row.lot_index for row in lots] == [0, 1]
    assert all(str(row.status) == "PLANNED" for row in lots)
    assert [row.bid_open_at for row in lots][0] == [row.bid_open_at for row in lots][1]
    window = lots[0].bid_close_at - lots[0].bid_open_at
    assert window == timedelta(seconds=120)
    assert [row["row"]["action"] for row in audit.rows] == ["pool.allocated"]


async def test_an_undersized_lot_is_cancelled_through_ls12(db_session: AsyncSession) -> None:
    """LS-12 (N2): a lot below min_seats is CANCELLED and its entries waitlist."""
    pool_id = await insert_seeded_pool(
        db_session,
        plan=[
            {
                "zone_id": ZONE,
                "lots": [{"seats": 2, "min_seats": 2}, {"seats": 3, "min_seats": 3}],
            }
        ],
    )
    entries = await add_eligible(db_session, pool_id, count=3)

    _, audit = await run_allocate(db_session, pool_id)

    lots = (
        await db_session.execute(
            text("SELECT lot_order, status FROM lots WHERE pool_id = :pool ORDER BY lot_order"),
            {"pool": pool_id},
        )
    ).all()
    assert [str(row.status) for row in lots] == ["PLANNED", "CANCELLED"]
    actions = [row["row"]["action"] for row in audit.rows]
    assert actions == ["lot.cancelled", "pool.allocated"]
    assert audit.rows[0]["row"]["payload"]["transition_id"] == "LS-12"
    waitlisted = await db_session.scalar(
        text("SELECT entry_id FROM allocations WHERE pool_id = :pool AND status = 'WAITLISTED'"),
        {"pool": pool_id},
    )
    # The ranking is seeded, so which of the three entries is rank 3 varies.
    assert waitlisted in entries


async def test_pool_allocate_is_silent_on_a_replay(db_session: AsyncSession) -> None:
    """T04A05 acceptance: a second run writes no allocation, lot or audit row."""
    pool_id = await insert_seeded_pool(db_session)
    await add_eligible(db_session, pool_id, count=3)
    service, audit = await run_allocate(db_session, pool_id)
    allocations = await db_session.scalar(
        text("SELECT count(*) FROM allocations WHERE pool_id = :pool"), {"pool": pool_id}
    )
    rows = len(audit.rows)

    await service.allocate(db_session, {"pool_id": str(pool_id)})

    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM allocations WHERE pool_id = :pool"), {"pool": pool_id}
        )
        == allocations
    )
    assert len(audit.rows) == rows


async def test_a_pool_with_no_entries_completes_through_ps09(
    db_session: AsyncSession,
) -> None:
    """PS-09: every lot cancelled means no award can happen, so the pool completes."""
    pool_id = await insert_seeded_pool(db_session)
    await close_window(db_session, pool_id)

    _, audit = await run_allocate(db_session, pool_id)

    status = await db_session.scalar(
        text("SELECT status FROM pools WHERE id = :id"), {"id": pool_id}
    )
    assert str(status) == "COMPLETED"
    actions = [row["row"]["action"] for row in audit.rows]
    assert actions[-1] == "pool.completed"


async def test_next_candidates_skips_a_cap_below_the_total(db_session: AsyncSession) -> None:
    """N12: an unaffordable waitlist entry is skipped, not removed, and stays behind."""
    world = await build_world(db_session, seats=2, seated=1, waitlisted=2, priced_out=0)
    cheap_entry = world.entry_ids[1]
    affordable_entry = world.entry_ids[2]
    await db_session.execute(
        text("UPDATE pool_entries SET cap_cents = 40000 WHERE id = :entry"),
        {"entry": cheap_entry},
    )
    read = PostgresAllocationRead()

    seats = await read.next_candidates(db_session, world.lot_id, 2)

    assert [seat.entry_id for seat in seats] == [affordable_entry]
    statuses = dict(
        (
            await db_session.execute(
                text("SELECT entry_id, status FROM allocations WHERE pool_id = :pool"),
                {"pool": world.pool_id},
            )
        ).all()
    )
    assert str(statuses[affordable_entry]) == "SEATED"
    assert str(statuses[cheap_entry]) == "WAITLISTED"
    lot_of = await db_session.scalar(
        text("SELECT lot_id FROM allocations WHERE entry_id = :entry"),
        {"entry": affordable_entry},
    )
    assert lot_of == world.lot_id
    # Nothing left that can afford this lot's total.
    assert await read.next_candidates(db_session, world.lot_id, 1) == []


async def test_get_lot_exposes_the_cr4_timing_values(db_session: AsyncSession) -> None:
    """CR-4: ``get_lot`` carries refill_waves and the timeline's wait values."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    await db_session.execute(
        text("UPDATE lots SET refill_waves = 2 WHERE id = :lot"), {"lot": world.lot_id}
    )

    view = await PostgresAllocationRead().get_lot(db_session, world.lot_id)

    assert isinstance(view, LotViewDetail)
    assert view.refill_waves == 2
    assert view.pending_wait_s == 120
    assert view.capture_grace_s == 120
    assert view.max_refill_waves == 1
    assert view.pool_mode == "LIVE_SANDBOX"
