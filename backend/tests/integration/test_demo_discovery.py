"""T09A03 owner follow-up: a repeatable, joinable discovery demo without payments."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import ConfirmedRequest, EntryReceipt, Pool, PoolEntry
from fairpool.domain.hashing import rules_hash
from fairpool.fakes.beacon import FakeBeacon
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.pools.join import JoinService
from fairpool.modules.pools.service import PoolService, rules_document
from tests.integration import test_pipeline_fakes
from tests.integration.test_triggers import add_user

pytestmark = pytest.mark.integration


async def test_discovery_seed_is_joinable_signed_and_repeatable_without_changing_rules(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "tools"))
    demo = importlib.import_module("demo_seed")
    seed = getattr(demo, "seed_discovery", None)
    assert seed is not None, "the demo must leave an open discovery catalogue"

    class FastClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return datetime.now(tz or UTC) + timedelta(hours=2)

    monkeypatch.setattr(test_pipeline_fakes, "datetime", FastClock)
    admin = await add_user(db_session, role="admin")
    for email in demo.BUYER_EMAILS:
        await add_user(db_session, email=email)
    clock, audit = DbClock(), PostgresAuditLog()
    pools = PoolService(clock, audit, PostgresJobQueue(), FakeBeacon(announced={"source": "demo"}))
    joins = JoinService(
        clock, audit, PostgresIdempotencyStore(), signing_seed=b"d" * 32, dedupe_mode="two_keys"
    )

    first = await seed(db_session, pools=pools, joins=joins, admin_id=admin)
    rows = list((await db_session.scalars(select(Pool).where(Pool.id.in_(first)))).all())
    frozen = {pool.id: (dict(pool.timeline), pool.rules_hash) for pool in rows}
    assert len(first) == 6
    assert all(pool.status == "OPEN" for pool in rows)
    assert all(rules_hash(rules_document(pool)) == pool.rules_hash for pool in rows)
    assert len({pool.template["product_key"] for pool in rows}) == 6
    assert all(pool.template["variant"] and pool.template["bundle_contents"] for pool in rows)
    assert all(pool.timeline["close_at"] > pool.timeline["open_at"] for pool in rows)

    async def counts() -> tuple[int, int, int, int]:
        entries = int(
            await db_session.scalar(
                select(func.count()).select_from(PoolEntry).where(PoolEntry.pool_id.in_(first))
            )
            or 0
        )
        receipts = int(
            await db_session.scalar(
                select(func.count())
                .select_from(EntryReceipt)
                .join(PoolEntry)
                .where(PoolEntry.pool_id.in_(first))
            )
            or 0
        )
        requests = int(
            await db_session.scalar(
                select(func.count())
                .select_from(ConfirmedRequest)
                .where(ConfirmedRequest.pool_id.in_(first))
            )
            or 0
        )
        orders = int(
            await db_session.scalar(
                text(
                    "SELECT count(*) FROM buyer_orders bo "
                    "JOIN pool_entries pe ON pe.id=bo.entry_id "
                    "WHERE pe.pool_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": first},
            )
            or 0
        )
        return entries, receipts, requests, orders

    entries, receipts, requests, orders = await counts()
    assert entries == 15
    assert receipts == requests == entries
    assert orders == 0

    again = await seed(db_session, pools=pools, joins=joins, admin_id=admin)
    assert again == first
    assert await counts() == (entries, receipts, requests, orders)
    for pool in rows:
        await db_session.refresh(pool)
        assert (pool.timeline, pool.rules_hash) == frozen[pool.id]
