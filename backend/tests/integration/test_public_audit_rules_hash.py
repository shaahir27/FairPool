"""CR-11 / T04A06: what the audit route serves still hashes to what publish froze.

`rules_document(pool)` is rebuilt from the live row on every read, and the beacon
sub-dict comes from `pools.beacon`. So if seeding replaces that column instead of
merging onto it, the served document no longer hashes to the stored `rules_hash` and
every external verifier -- the audit page, and anyone who follows it -- disagrees with
the number publish committed to. This is the end-to-end version of that property: real
publish, real close, a beacon body shaped like drand's, then the HTTP payload.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain import hashing
from fairpool.domain.hashing import rules_hash
from fairpool.domain.pool_config import PoolInput
from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.beacon import DEFAULT_RANDOMNESS, FakeBeacon
from fairpool.fakes.clock import FakeClock
from fairpool.fakes.jobs import FakeJobQueue
from fairpool.infra.clock import DbClock
from fairpool.modules.pools.seed import PoolSeedService
from fairpool.modules.pools.service import PoolService, rules_document
from tests.integration.test_join_receipts import settings_for
from tests.integration.test_pipeline_fakes import move_timeline
from tests.integration.test_pools import payload
from tests.integration.test_triggers import add_user

pytestmark = pytest.mark.integration

ANNOUNCED = {"source": "drand", "chain_hash": "ab" * 32, "round": 41, "not_before": 1}
#: What drand's ``/pub/{round}`` actually returns: no source, no chain_hash.
DRAND_BODY = {"round": 41, "randomness": DEFAULT_RANDOMNESS, "signature": "cd" * 96}


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings_for())

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def publish_and_seed(db_session: AsyncSession) -> tuple[Any, str]:
    """Publish for a real frozen `rules_hash`, then seed through the real handler.

    The close is written directly instead of run through `pool.close`: what this file
    pins is that the seeded row still hashes to what publish froze, and the close
    pipeline is covered by its own suite.
    """
    admin = await add_user(db_session, role="admin")
    data = await payload(db_session)
    pools = PoolService(DbClock(), FakeAuditLog(), FakeJobQueue(), FakeBeacon(announced=ANNOUNCED))
    pool = await pools.create(db_session, actor_id=admin, payload=PoolInput.model_validate(data))
    await pools.publish(db_session, pool.id, actor_id=admin)
    frozen = str(pool.rules_hash)

    root = hashing.merkle_root([])
    await db_session.execute(
        text(
            "UPDATE pools SET status = CAST(:status AS pool_status), entries_root = :root, "
            "entries_count = 0 WHERE id = :pool"
        ),
        {"status": "CLOSED", "root": root, "pool": str(pool.id)},
    )
    # Lots must leave BIDDING and PLANNING before the seed is revealed (CR-11 gate).
    await db_session.execute(
        text("UPDATE lots SET status = 'BID_CLOSED'::lot_status WHERE pool_id = :pool"),
        {"pool": str(pool.id)},
    )
    await db_session.flush()
    # The identity map still holds the pre-update row, and the seed handler checks
    # `pool.status` off that object: refresh first or it returns as "not closed yet".
    await db_session.refresh(pool)

    now = await DbClock().db_now(db_session)
    seeder = PoolSeedService(
        FakeClock(now),
        FakeAuditLog(),
        FakeJobQueue(),
        FakeBeacon(announced=ANNOUNCED, fetched=DRAND_BODY),
    )
    await seeder.seed(db_session, {"pool_id": str(pool.id)})
    await db_session.refresh(pool)
    return pool, frozen


async def test_the_served_rules_document_hashes_to_the_frozen_hash(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # T04A06 acceptance (CR-11): a verifier that only ever sees this payload can
    # reproduce the number publish committed to.
    pool, frozen = await publish_and_seed(db_session)

    body = (await client.get(f"/api/v1/public/pools/{pool.id}/audit")).json()

    assert body["rules_hash"] == frozen
    assert rules_hash(body["rules_document"]) == body["rules_hash"]
    assert body["seed_hex"] == DEFAULT_RANDOMNESS


async def test_seeding_merges_the_beacon_body_onto_the_announcement(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    pool, _ = await publish_and_seed(db_session)

    body = (await client.get(f"/api/v1/public/pools/{pool.id}/audit")).json()
    beacon = body["beacon"]

    assert beacon["source"] == "drand"
    assert beacon["chain_hash"] == "ab" * 32
    assert beacon["round"] == 41
    assert beacon["not_before"] == 1
    assert beacon["randomness"] == DEFAULT_RANDOMNESS
    # fairness-and-hashing.md §4: only these three keys enter rules_document, so the
    # merged extra keys cannot change the frozen hash.
    assert set(body["rules_document"]["beacon"]) == {"source", "chain_hash", "round"}


async def test_the_demo_seed_path_keeps_the_document_reproducible(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """BEACON_MODE=demo is what the hosted app runs, so pin that branch too.

    The deployed pools are labelled DEMO SEED, and the audit page recomputes the rules
    document on every read. If publish and the read disagreed in demo mode, every
    hosted pool would show a red verdict, which is exactly what was seen on live data
    created by an older build.
    """
    admin = await add_user(db_session, role="admin")
    data = await payload(db_session)
    pools = PoolService(
        DbClock(), FakeAuditLog(), FakeJobQueue(), FakeBeacon(announced={"source": "demo"})
    )
    pool = await pools.create(db_session, actor_id=admin, payload=PoolInput.model_validate(data))
    await pools.publish(db_session, pool.id, actor_id=admin)
    frozen = str(pool.rules_hash)

    await db_session.execute(
        text(
            "UPDATE pools SET status = CAST(:status AS pool_status), entries_root = :root, "
            "entries_count = 0 WHERE id = :pool"
        ),
        {"status": "CLOSED", "root": hashing.merkle_root([]), "pool": str(pool.id)},
    )
    await db_session.execute(
        text("UPDATE lots SET status = 'BID_CLOSED'::lot_status WHERE pool_id = :pool"),
        {"pool": str(pool.id)},
    )
    await db_session.flush()
    await db_session.refresh(pool)

    now = await DbClock().db_now(db_session)
    seeder = PoolSeedService(
        FakeClock(now), FakeAuditLog(), FakeJobQueue(), FakeBeacon(announced={"source": "demo"})
    )
    await seeder.seed(db_session, {"pool_id": str(pool.id)})

    body = (await client.get(f"/api/v1/public/pools/{pool.id}/audit")).json()

    assert body["rules_hash"] == frozen
    assert rules_hash(body["rules_document"]) == body["rules_hash"]
    assert body["seed_is_demo"] is True
    assert body["seed_hex"] == hashing.demo_seed(str(pool.id))


async def test_shifting_a_window_keeps_the_document_reproducible(db_session: AsyncSession) -> None:
    """Q-2026-11-06-38: the demo seeder moves its own windows, and that broke the hash.

    `timeline` is an input to `rules_document`, so a pre-close shift must re-freeze
    `rules_hash`; the audit page recomputes the document on every read and would
    otherwise report a tampered pool.
    """
    admin = await add_user(db_session, role="admin")
    data = await payload(db_session)
    pools = PoolService(
        DbClock(), FakeAuditLog(), FakeJobQueue(), FakeBeacon(announced={"source": "demo"})
    )
    pool = await pools.create(db_session, actor_id=admin, payload=PoolInput.model_validate(data))
    await pools.publish(db_session, pool.id, actor_id=admin)

    await move_timeline(db_session, pool.id, key="open_at", seconds=-120)
    await move_timeline(db_session, pool.id, key="close_at", seconds=-60)
    await db_session.refresh(pool)

    assert rules_hash(rules_document(pool)) == pool.rules_hash


async def test_a_window_shift_is_refused_once_the_close_snapshot_exists(
    db_session: AsyncSession,
) -> None:
    """After the close the rules are the contract buyers committed under: not movable."""
    admin = await add_user(db_session, role="admin")
    data = await payload(db_session)
    pools = PoolService(
        DbClock(), FakeAuditLog(), FakeJobQueue(), FakeBeacon(announced={"source": "demo"})
    )
    pool = await pools.create(db_session, actor_id=admin, payload=PoolInput.model_validate(data))
    await pools.publish(db_session, pool.id, actor_id=admin)
    await db_session.execute(
        text("UPDATE pools SET entries_root = :root WHERE id = :pool"),
        {"root": hashing.merkle_root([]), "pool": str(pool.id)},
    )
    await db_session.flush()

    with pytest.raises(AssertionError, match="frozen once the close snapshot exists"):
        await move_timeline(db_session, pool.id, key="close_at", seconds=-60)
