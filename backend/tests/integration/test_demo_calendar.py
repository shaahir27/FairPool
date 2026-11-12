"""The two-month demo calendar preserves published rules and signed entry history."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import EntryReceipt, PoolEntry
from fairpool.domain.hashing import rules_hash
from fairpool.fakes.beacon import FakeBeacon
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.pools.join import JoinService
from fairpool.modules.pools.service import PoolService, rules_document
from tests.integration.test_triggers import add_user


def calendar_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "tools"))
    return importlib.import_module("demo_seed")


def test_calendar_has_complete_terms_through_two_calendar_months(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo = calendar_module(monkeypatch)
    build = getattr(demo, "calendar_plans", None)
    assert build is not None, "the seeder needs a validated two-month calendar"
    plans = build(datetime(2026, 11, 12, 4, tzinfo=UTC))
    assert len(plans) == 28
    regular = plans[:24]
    assert len({p.payload.template.product_key for p in regular}) == 12
    assert max(p.payload.timeline.close_at.date().isoformat() for p in regular) == "2027-01-12"
    assert len({p.payload.title for p in plans}) == 28
    for plan in plans:
        payload = plan.payload
        assert payload.template.bundle_contents and payload.template.variant
        assert payload.template.fund_by >= payload.timeline.close_at.date().isoformat()
        assert payload.template.zones[0].regions == ["NY", "NJ", "PA"]
        assert payload.template.currency == "USD"
        assert payload.timeline.open_at < payload.timeline.close_at
        assert 0 < plan.cap_cents and isinstance(plan.cap_cents, int)
    assert all(5 not in p.buyer_indexes for p in regular)


@pytest.mark.parametrize(
    ("start", "last"),
    [("2026-12-31", "2027-02-28"), ("2027-01-31", "2027-03-31")],
)
def test_calendar_rolls_over_month_and_year_boundaries(
    monkeypatch: pytest.MonkeyPatch, start: str, last: str
) -> None:
    demo = calendar_module(monkeypatch)
    plans = demo.calendar_plans(datetime.fromisoformat(start).replace(tzinfo=UTC))
    assert max(p.payload.timeline.close_at.date().isoformat() for p in plans[:24]) == last


@pytest.mark.integration
@pytest.mark.parametrize(("plan_index", "age_days"), [(0, 0), (-1, 1)])
async def test_calendar_seed_reuses_entries_and_never_creates_a_payment(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, plan_index: int, age_days: int
) -> None:
    demo = calendar_module(monkeypatch)
    seed = getattr(demo, "seed_calendar_pool", None)
    assert seed is not None, "calendar writes must use the normal publishing and join services"
    admin = await add_user(db_session, role="admin")
    buyers = [await add_user(db_session) for _ in range(6)]
    clock, audit = DbClock(), PostgresAuditLog()
    pools = PoolService(clock, audit, PostgresJobQueue(), FakeBeacon(announced={"source": "demo"}))
    joins = JoinService(
        clock, audit, PostgresIdempotencyStore(), signing_seed=b"d" * 32, dedupe_mode="two_keys"
    )
    plan = demo.calendar_plans(await clock.db_now(db_session) - timedelta(days=age_days))[
        plan_index
    ]
    pool = await seed(
        db_session, plan=plan, pools=pools, joins=joins, admin_id=admin, buyers=buyers
    )
    frozen = (dict(pool.timeline), pool.rules_hash)
    assert pool.status == "OPEN"
    assert pool.rules_hash == rules_hash(rules_document(pool))
    again = await seed(
        db_session, plan=plan, pools=pools, joins=joins, admin_id=admin, buyers=buyers
    )
    assert again.id == pool.id
    assert (again.timeline, again.rules_hash) == frozen
    entries = await db_session.scalar(
        select(func.count()).select_from(PoolEntry).where(PoolEntry.pool_id == pool.id)
    )
    receipts = await db_session.scalar(
        select(func.count())
        .select_from(EntryReceipt)
        .join(PoolEntry)
        .where(PoolEntry.pool_id == pool.id)
    )
    assert entries == receipts == len(plan.buyer_indexes)
    assert await audit.verify_chain(db_session)
    assert (
        await db_session.scalar(
            text(
                "SELECT count(*) FROM buyer_orders o JOIN pool_entries e ON e.id=o.entry_id "
                "WHERE e.pool_id=:pool"
            ),
            {"pool": pool.id},
        )
        == 0
    )
