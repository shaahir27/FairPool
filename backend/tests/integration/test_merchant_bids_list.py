"""T08B02: the merchant console bids list (``GET /api/v1/merchant/bids``).

The console reads the same three queries the Merchant Agent API uses: the newest
100 bids, their current revisions and those revisions' flags. A ``status`` filter
is validated against the enum, an unknown value is ``422 VALIDATION_ERROR``, a
merchant sees only its own bids (PT-15), and flags travel with the row.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from tests.integration.test_bid_sealing import (
    bidding_world,
    lot_with_deadline,
    set_bid_status,
    structured,
)
from tests.integration.test_join_receipts import PASSWORD, login, settings_for

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
BIDS = "/api/v1/merchant/bids"


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS)

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def merchant_csrf(client: httpx.AsyncClient, db_session: AsyncSession, email: str) -> str:
    await login(client, email)
    await db_session.execute(
        text("UPDATE users SET role = 'merchant' WHERE email = :email"), {"email": email}
    )
    await db_session.flush()
    result = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200
    csrf = str(result.json()["csrf_token"])
    profile = await client.post(
        "/api/v1/merchant/profile",
        headers={"X-CSRF-Token": csrf},
        json={"display_name": f"Demo {email[:6]}", "attestations": {}},
    )
    assert profile.status_code == 200, profile.text
    return csrf


async def submit_bid(
    client: httpx.AsyncClient, csrf: str, lot_id: UUID, *, capacity: int = 12
) -> dict[str, Any]:
    saved = await client.put(
        f"/api/v1/merchant/lots/{lot_id}/bid",
        headers={"X-CSRF-Token": csrf},
        json={"structured": structured(capacity=capacity)},
    )
    assert saved.status_code == 200, saved.text
    return dict(saved.json())


async def add_flag(db_session: AsyncSession, bid_id: str, revision: int) -> None:
    run_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO ai_runs (id, task, model, prompt_version, input_hash, ok, latency_ms, "
            "tokens_in, tokens_out) VALUES (:id, 'RECONCILE', 'test-model', 'v1', :hash, true, "
            "1, 1, 1)"
        ),
        {"id": run_id, "hash": "d" * 64},
    )
    revision_id = await db_session.scalar(
        text("SELECT id FROM bid_revisions WHERE bid_id = :bid AND revision = :revision"),
        {"bid": bid_id, "revision": revision},
    )
    await db_session.execute(
        text(
            "INSERT INTO bid_flags (id, bid_revision_id, ai_run_id, code, severity, field, "
            "evidence) VALUES (:id, :revision, :run, 'DELIVERY_CONFLICT', 'WARNING', "
            "'delivery', 'ships in 30 days')"
        ),
        {"id": uuid4(), "revision": revision_id, "run": run_id},
    )
    await db_session.flush()


async def test_the_console_lists_bids_with_flags_and_filters_by_status(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await bidding_world(db_session)
    first_lot = await lot_with_deadline(db_session, world, offset_s=600)
    second_lot = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
            "status, bid_open_at, bid_close_at) VALUES (:id, :pool, 'US-EAST', 1, 2, 2, 2, "
            "'BIDDING', now(), now() + interval '1 hour')"
        ),
        {"id": second_lot, "pool": world.pool_id},
    )
    csrf = await merchant_csrf(client, db_session, "console-bids@example.test")
    first = await submit_bid(client, csrf, first_lot)
    second = await submit_bid(client, csrf, second_lot, capacity=20)
    await add_flag(db_session, first["bid_id"], first["revision"])

    listed = await client.get(BIDS)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    # Both saved bids are present; SQL keeps a deterministic order even when the
    # two created_at values tie inside one transaction.
    assert {item["bid_id"] for item in items} == {first["bid_id"], second["bid_id"]}
    assert {item["status"] for item in items} == {"DRAFT"}
    flagged = next(item for item in items if item["bid_id"] == first["bid_id"])
    assert flagged["flags"] == [
        {
            "code": "DELIVERY_CONFLICT",
            "severity": "WARNING",
            "field": "delivery",
            "evidence": "ships in 30 days",
        }
    ]
    other = next(item for item in items if item["bid_id"] == second["bid_id"])
    assert other["flags"] == []

    await set_bid_status(db_session, UUID(first["bid_id"]), "REJECTED")
    rejected = await client.get(BIDS, params={"status": "REJECTED"})
    assert rejected.status_code == 200
    assert [item["bid_id"] for item in rejected.json()["items"]] == [first["bid_id"]]
    draft = await client.get(BIDS, params={"status": "DRAFT"})
    assert {item["bid_id"] for item in draft.json()["items"]} == {second["bid_id"]}
    empty = await client.get(BIDS, params={"status": "AWARDED"})
    assert empty.json()["items"] == []
    for bad in ("NOT_A_STATUS", "draft", "  "):
        refused = await client.get(BIDS, params={"status": bad})
        assert refused.status_code == 422, (bad, refused.text)
        assert refused.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_another_merchants_bids_are_absent(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """PT-15: the console list is owner-scoped, not a global view."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    csrf = await merchant_csrf(client, db_session, "console-owner@example.test")
    saved = await submit_bid(client, csrf, lot_id)

    await merchant_csrf(client, db_session, "console-other@example.test")
    theirs = await client.get(BIDS)

    assert theirs.status_code == 200
    assert theirs.json()["items"] == []
    assert saved["bid_id"] not in theirs.text
