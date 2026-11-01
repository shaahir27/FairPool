"""T04A06: the public audit payload shows lots, awards and the seed, and no PII.

``api.md`` "Public audit" fixes the fields; ``fairness-and-hashing.md`` fixes the
gate. The payload may carry the lot's public facts and the merchant's display name,
and it may never carry a buyer (user id, entry id, e-mail), a cap or a salt. The
close-time gate covers the new fields too: before the published snapshot exists the
lots, beacon and seed are withheld, because a seed or an allocation that predates the
commitment list would describe a pool buyers are still entering.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain import hashing
from tests.integration.test_join_receipts import settings_for
from tests.integration.test_open_checkout import build_world


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


async def close_pool(db_session: AsyncSession, pool_id: UUID) -> str:
    """Publish the close-time snapshot the close transaction would have written."""
    seed = hashing.demo_seed(str(pool_id))
    root = hashing.merkle_root([])
    await db_session.execute(
        text(
            "UPDATE pools SET status = 'CLOSED', entries_root = :root, entries_count = 0, "
            "seed_hex = :seed, seed_is_demo = true, beacon = CAST(:beacon AS jsonb) "
            "WHERE id = :id"
        ),
        {"root": root, "seed": seed, "beacon": json.dumps({"source": "demo"}), "id": pool_id},
    )
    return seed


async def audit(client: httpx.AsyncClient, pool_id: UUID) -> dict[str, Any]:
    response = await client.get(f"/api/v1/public/pools/{pool_id}/audit")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_the_audit_withholds_lots_and_the_seed_until_the_pool_closes(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A pool that is still open publishes the close-time fields only, and empty."""
    world = await build_world(db_session, lot_status="AWARDED", pool_status="OPEN")

    payload = await audit(client, world.pool_id)

    assert payload["lots"] == []
    assert payload["beacon"] is None
    assert payload["seed_hex"] is None
    assert payload["seed_is_demo"] is False
    assert payload["entries_root"] is None
    assert payload["commitments"] == []
    assert payload["audit_checkpoints"] == []


async def test_the_audit_publishes_lots_their_awards_and_the_seed(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """T04A06 acceptance: ``lots`` with ``award``, plus ``beacon``/``seed_hex``."""
    world = await build_world(
        db_session, seats=3, min_seats=2, seated=2, waitlisted=1, lot_status="AWARDED"
    )
    seed = await close_pool(db_session, world.pool_id)

    payload = await audit(client, world.pool_id)

    assert payload["seed_hex"] == seed
    assert payload["seed_is_demo"] is True
    assert payload["beacon"] == {"source": "demo"}
    assert len(payload["lots"]) == 1
    lot = payload["lots"][0]
    assert sorted(lot) == [
        "award",
        "lot_id",
        "lot_order",
        "rank_range",
        "seats",
        "status",
        "zone_id",
    ]
    assert lot["lot_id"] == str(world.lot_id)
    assert lot["zone_id"] == "US-EAST" and lot["seats"] == 3 and lot["status"] == "AWARDED"
    # Ranks 1 and 2 are the seated allocations; the waitlisted entry holds none.
    assert lot["rank_range"] == [1, 2]
    award = lot["award"]
    assert award["merchant_display_name"] == "Demo Merchant"
    assert award["item_cents"] == 47_000 and award["tier_index"] == 0
    assert award["award_hash"] == "0" * 64
    assert award["valid_until"]


async def test_a_lot_without_an_award_publishes_no_award(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await build_world(db_session, lot_status="CANCELLED", with_award=False, seated=0)
    await db_session.execute(
        text("UPDATE lots SET status = 'CANCELLED' WHERE id = :lot"), {"lot": world.lot_id}
    )
    await close_pool(db_session, world.pool_id)

    payload = await audit(client, world.pool_id)

    assert payload["lots"][0]["award"] is None
    assert payload["lots"][0]["rank_range"] == []


async def test_the_audit_payload_carries_no_personal_data(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """FR-SL-06/I13: no user, entry, cap, salt or address ever crosses this route."""
    world = await build_world(db_session, seats=3, seated=2, waitlisted=1, lot_status="AWARDED")
    await close_pool(db_session, world.pool_id)
    emails = (
        (
            await db_session.execute(
                text("SELECT email FROM users WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": [str(user_id) for user_id in world.user_ids]},
            )
        )
        .scalars()
        .all()
    )

    raw = json.dumps(await audit(client, world.pool_id))
    forbidden = [
        *[str(entry_id) for entry_id in world.entry_ids],
        *[str(user_id) for user_id in world.user_ids],
        *[str(email) for email in emails],
        "60000",  # the buyer caps
        "c" * 64,  # the allocation rank hashes (salted per entry)
    ]
    for value in forbidden:
        assert value not in raw, value


async def test_an_unknown_or_draft_pool_is_not_found(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    unknown = await client.get(f"/api/v1/public/pools/{uuid4()}/audit")
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "NOT_FOUND"

    draft = await build_world(db_session, pool_status="OPEN")
    await db_session.execute(
        text("UPDATE pools SET status = 'DRAFT', rules_hash = NULL WHERE id = :id"),
        {"id": draft.pool_id},
    )
    withheld = await client.get(f"/api/v1/public/pools/{draft.pool_id}/audit")
    assert withheld.status_code == 404
