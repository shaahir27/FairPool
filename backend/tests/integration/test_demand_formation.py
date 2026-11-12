"""CR-17 / FR-DM-01 to FR-DM-06: consented interest forms a pool at a published threshold.

The sweep proposes; a human publishes. One cluster yields one pool. Notifications go
to the people who asked, in the same transaction as the transition (I10), and the
public forming-demand view carries no buyer identity, cap or message.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fairpool.domain.demand import cluster_key
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.demand.service import DemandService
from fairpool.modules.notify.service import PostgresNotifier
from fairpool.wiring import pool_service
from tests.integration.test_join_receipts import settings_for

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
THRESHOLD = 3
FIELDS: dict[str, Any] = {
    "product_key": "monitor-27-4k",
    "condition": "NEW",
    "variant": "black",
    "bundle_contents": ["monitor", "stand", "power cable"],
}


def service(threshold: int = THRESHOLD) -> DemandService:
    return DemandService(
        clock=DbClock(),
        audit=PostgresAuditLog(),
        notifier=PostgresNotifier(),
        pools=pool_service(SETTINGS),
        jobs=PostgresJobQueue(),
        threshold=threshold,
        signal_ttl_days=30,
    )


async def buyer(session: AsyncSession, label: str) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', :name, 'buyer')"
        ),
        {"id": user_id, "email": f"{label}-{user_id}@example.test", "name": label},
    )
    return user_id


async def ask(session: AsyncSession, svc: DemandService, user_id: UUID, **overrides: Any) -> Any:
    fields = {**FIELDS, "region": "NY", "source": "intake", **overrides}
    return await svc.signal(session, user_id=user_id, **fields)


async def test_signals_from_different_buyers_share_one_cluster(db_session: AsyncSession) -> None:
    svc = service()
    first = await ask(db_session, svc, await buyer(db_session, "a"))
    second = await ask(db_session, svc, await buyer(db_session, "b"), product_key="Monitor 27 4K")
    assert first.cluster_key == second.cluster_key
    assert first.cluster_key == cluster_key(**FIELDS)
    forming = await svc.forming(db_session)
    assert len(forming) == 1
    assert forming[0]["interested"] == 2
    assert forming[0]["threshold"] == THRESHOLD


async def test_a_repeat_signal_from_the_same_buyer_is_idempotent(db_session: AsyncSession) -> None:
    svc = service()
    user_id = await buyer(db_session, "repeat")
    first = await ask(db_session, svc, user_id)
    again = await ask(db_session, svc, user_id)
    assert again.id == first.id
    assert (await svc.forming(db_session))[0]["interested"] == 1


async def test_forming_demand_carries_no_buyer_data(db_session: AsyncSession) -> None:
    svc = service()
    await ask(db_session, svc, await buyer(db_session, "private"))
    row = (await svc.forming(db_session))[0]
    assert set(row) == {
        "cluster_key",
        "title",
        "product_key",
        "condition",
        "variant",
        "bundle_contents",
        "regions",
        "interested",
        "threshold",
        "status",
    }
    assert "user_id" not in row and "cap" not in row and "message" not in row


async def test_below_the_threshold_the_sweep_creates_nothing(db_session: AsyncSession) -> None:
    svc = service()
    await ask(db_session, svc, await buyer(db_session, "one"))
    await ask(db_session, svc, await buyer(db_session, "two"))
    assert await svc.sweep(db_session) == 0
    pools = await db_session.scalar(
        text(
            "SELECT count(*) FROM pools WHERE id IN "
            "(SELECT pool_id FROM demand_clusters WHERE cluster_key = :key)"
        ),
        {"key": cluster_key(**FIELDS)},
    )
    assert pools == 0
    assert (await svc.forming(db_session))[0]["status"] == "COLLECTING"


async def test_at_the_threshold_one_draft_pool_is_proposed_and_holders_notified(
    db_session: AsyncSession,
) -> None:
    svc = service()
    users = [await buyer(db_session, label) for label in ("x", "y", "z")]
    for user_id in users:
        await ask(db_session, svc, user_id, region="NY" if user_id != users[-1] else "CA")
    assert await svc.sweep(db_session) == 1

    cluster = (await svc.forming(db_session))[0]
    assert cluster["status"] == "PROPOSED"
    assert sorted(cluster["regions"]) == ["CA", "NY"]
    pool_id = await db_session.scalar(
        text("SELECT pool_id FROM demand_clusters WHERE cluster_key = :key"),
        {"key": cluster["cluster_key"]},
    )
    assert pool_id is not None
    status = await db_session.scalar(
        text("SELECT status FROM pools WHERE id = :id"), {"id": pool_id}
    )
    assert str(status) == "DRAFT"

    kinds = await db_session.execute(
        text(
            "SELECT kind, payload FROM notifications "
            "WHERE payload->>'cluster_key' = :key ORDER BY created_at"
        ),
        {"key": cluster_key(**FIELDS)},
    )
    rows = kinds.mappings().all()
    assert len(rows) == 3
    assert {row["kind"] for row in rows} == {"demand.pool_proposed"}
    assert {row["payload"]["cluster_key"] for row in rows} == {cluster["cluster_key"]}


async def test_a_second_sweep_never_creates_a_second_pool(db_session: AsyncSession) -> None:
    svc = service()
    for label in ("x", "y", "z"):
        await ask(db_session, svc, await buyer(db_session, label))
    assert await svc.sweep(db_session) == 1
    assert await svc.sweep(db_session) == 0
    assert (
        await db_session.scalar(
            text(
                "SELECT count(*) FROM pools WHERE id IN "
                "(SELECT pool_id FROM demand_clusters WHERE cluster_key = :key)"
            ),
            {"key": cluster_key(**FIELDS)},
        )
        == 1
    )
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM notifications WHERE payload->>'cluster_key' = :key"),
            {"key": cluster_key(**FIELDS)},
        )
        == 3
    )


async def test_publishing_opens_the_pool_and_notifies_the_holders(db_session: AsyncSession) -> None:
    svc = service()
    admin = await buyer(db_session, "admin")
    for label in ("x", "y", "z"):
        await ask(db_session, svc, await buyer(db_session, label))
    await svc.sweep(db_session)
    key = (await svc.forming(db_session))[0]["cluster_key"]

    pool = await svc.publish(db_session, cluster_key=key, actor_id=admin)
    assert str(pool.status) == "PUBLISHED"
    assert pool.rules_hash and len(pool.rules_hash) == 64
    jobs = await db_session.execute(text("SELECT kind FROM jobs ORDER BY kind"))
    assert {row[0] for row in jobs} >= {"pool.open", "pool.close", "search.index"}

    cluster = (await svc.forming(db_session))[0]
    assert cluster["status"] == "POOLED"
    kinds = await db_session.execute(
        text("SELECT kind FROM notifications WHERE payload->>'cluster_key' = :key"),
        {"key": cluster_key(**FIELDS)},
    )
    assert {row[0] for row in kinds} == {"demand.pool_proposed", "demand.pool_open"}


async def test_rejecting_closes_the_cluster_without_a_pool(db_session: AsyncSession) -> None:
    svc = service()
    admin = await buyer(db_session, "admin")
    for label in ("x", "y", "z"):
        await ask(db_session, svc, await buyer(db_session, label))
    await svc.sweep(db_session)
    key = (await svc.forming(db_session))[0]["cluster_key"]

    cluster = await svc.reject(db_session, cluster_key=key, actor_id=admin)
    assert cluster.status == "REJECTED"
    assert (
        await db_session.scalar(
            text(
                "SELECT count(*) FROM pools WHERE id IN "
                "(SELECT pool_id FROM demand_clusters WHERE cluster_key = :key)"
            ),
            {"key": cluster_key(**FIELDS)},
        )
        == 1
    )
    assert await svc.sweep(db_session) == 0


async def test_a_cancelled_signal_stops_counting(db_session: AsyncSession) -> None:
    svc = service()
    users = [await buyer(db_session, label) for label in ("x", "y", "z")]
    signals = [await ask(db_session, svc, user_id) for user_id in users]
    await svc.cancel(db_session, user_id=users[0], signal_id=signals[0].id)
    assert (await svc.forming(db_session))[0]["interested"] == 2
    assert await svc.sweep(db_session) == 0


async def test_an_expired_signal_stops_counting(db_session: AsyncSession) -> None:
    svc = service()
    for label in ("x", "y", "z"):
        await ask(db_session, svc, await buyer(db_session, label))
    await db_session.execute(
        text("UPDATE demand_signals SET expires_at = now() - interval '1 day'")
    )
    assert (await svc.forming(db_session))[0]["interested"] == 0
    assert await svc.sweep(db_session) == 0


async def test_another_buyers_signal_cannot_be_cancelled(db_session: AsyncSession) -> None:
    from fairpool.domain.errors import ApplicationError

    svc = service()
    owner = await buyer(db_session, "owner")
    other = await buyer(db_session, "other")
    signal = await ask(db_session, svc, owner)
    with pytest.raises(ApplicationError):
        await svc.cancel(db_session, user_id=other, signal_id=signal.id)


async def test_interests_are_owner_scoped(db_session: AsyncSession) -> None:
    svc = service()
    owner = await buyer(db_session, "owner")
    await buyer(db_session, "other")
    await ask(db_session, svc, owner)
    mine = await svc.interests(db_session, user_id=owner)
    assert len(mine) == 1
    assert mine[0]["title"]
    assert mine[0]["status"] == "COLLECTING"


async def test_a_new_consent_renews_an_expired_signal(db_session: AsyncSession) -> None:
    svc = service()
    owner = await buyer(db_session, "renew")
    original = await ask(db_session, svc, owner)
    await db_session.execute(
        text("UPDATE demand_signals SET expires_at = now() - interval '1 day' WHERE id = :id"),
        {"id": original.id},
    )
    await db_session.refresh(original)
    assert await svc.interests(db_session, user_id=owner) == []
    renewed = await ask(db_session, svc, owner)
    assert renewed.id == original.id
    assert len(await svc.interests(db_session, user_id=owner)) == 1


async def test_an_empty_normalized_product_is_a_validation_error(db_session: AsyncSession) -> None:
    from fairpool.domain.errors import ApplicationError

    svc = service()
    with pytest.raises(ApplicationError) as refused:
        await ask(db_session, svc, await buyer(db_session, "invalid"), product_key="!!!")
    assert refused.value.code == "VALIDATION_ERROR"


async def test_simultaneous_first_signals_share_one_cluster(db_engine: AsyncEngine) -> None:
    svc = service()
    product = f"concurrent-product-{uuid4()}"
    key = cluster_key(**{**FIELDS, "product_key": product})
    async with AsyncSession(db_engine, expire_on_commit=False) as session:
        first_user = await buyer(session, "race-first")
        second_user = await buyer(session, "race-second")
        await session.commit()

    async def second_signal() -> str:
        async with AsyncSession(db_engine, expire_on_commit=False) as session:
            signal = await ask(session, svc, second_user, product_key=product)
            await session.commit()
            return str(signal.cluster_key)

    try:
        async with AsyncSession(db_engine, expire_on_commit=False) as first:
            signal = await ask(first, svc, first_user, product_key=product)
            second = asyncio.create_task(second_signal())
            # Keep the first cluster uncommitted while the second buyer asks for it.
            await asyncio.sleep(0.2)
            await first.commit()
            assert await asyncio.wait_for(second, timeout=5) == signal.cluster_key
        async with AsyncSession(db_engine) as session:
            assert (
                await session.scalar(
                    text("SELECT count(*) FROM demand_signals WHERE cluster_key = :key"),
                    {"key": key},
                )
                == 2
            )
    finally:
        async with db_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM demand_signals WHERE cluster_key = :key"), {"key": key}
            )
            await connection.execute(
                text("DELETE FROM demand_clusters WHERE cluster_key = :key"), {"key": key}
            )
            await connection.execute(
                text("DELETE FROM users WHERE id IN (:first, :second)"),
                {"first": first_user, "second": second_user},
            )
