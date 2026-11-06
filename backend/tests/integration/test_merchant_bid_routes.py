"""T05A04 and T05A06 route level: the merchant bid surface over HTTP.

What the contract puts at the edge, proved through the app rather than the service:

* a save returns its signed receipt and the bid stays unconfirmed until confirm;
* sealing holds at the route: another merchant's bid id answers ``404``;
* the state rules answer with the contracted codes (409), never a 500;
* ``GET /merchant/bids/{id}`` discloses the merchant's own ``reject_reason``.
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
from tests.integration.test_bid_sealing import (
    bidding_world,
    lot_with_deadline,
    set_bid_status,
    structured,
)
from tests.integration.test_join_receipts import PASSWORD, login, settings_for

pytestmark = pytest.mark.integration


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


async def merchant_csrf(client: httpx.AsyncClient, db_session: AsyncSession, email: str) -> str:
    """Register, promote to merchant, then log in again so the session carries the role."""
    await login(client, email)
    await db_session.execute(
        text("UPDATE users SET role = 'merchant' WHERE email = :email"), {"email": email}
    )
    await db_session.flush()
    result = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200
    return str(result.json()["csrf_token"])


async def open_bid(client: httpx.AsyncClient, db_session: AsyncSession, lot_id: Any) -> str:
    csrf = await merchant_csrf(client, db_session, "alpha@example.test")
    profile = await client.post(
        "/api/v1/merchant/profile",
        headers={"X-CSRF-Token": csrf},
        json={"display_name": "Demo Merchant Alpha", "attestations": {}},
    )
    assert profile.status_code == 200, profile.text
    saved = await client.put(
        f"/api/v1/merchant/lots/{lot_id}/bid",
        headers={"X-CSRF-Token": csrf},
        json={"structured": structured()},
    )
    assert saved.status_code == 200, saved.text
    return csrf


async def test_a_save_returns_a_receipt_and_stays_draft_until_confirm(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    csrf = await open_bid(client, db_session, lot_id)
    body = await client.put(
        f"/api/v1/merchant/lots/{lot_id}/bid",
        headers={"X-CSRF-Token": csrf},
        json={"structured": structured(capacity=20)},
    )
    assert body.status_code == 200, body.text
    saved = body.json()
    assert saved["status"] == "DRAFT"
    assert saved["revision"] == 2
    assert len(saved["receipt"]["hash"]) == 64
    assert saved["receipt"]["signature"]

    confirmed = await client.post(
        f"/api/v1/merchant/bids/{saved['bid_id']}/confirm",
        headers={"X-CSRF-Token": csrf},
        json={"revision": 2},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "CONFIRMED"

    view = await client.get(f"/api/v1/merchant/bids/{saved['bid_id']}")
    assert view.status_code == 200, view.text
    assert view.json()["status"] == "CONFIRMED"
    assert view.json()["reject_reason"] is None
    assert view.json()["structured"]["capacity"] == 20


async def test_another_merchants_bid_is_not_found_at_the_route(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    saved = await client.put(
        f"/api/v1/merchant/lots/{lot_id}/bid",
        headers={"X-CSRF-Token": await open_bid(client, db_session, lot_id)},
        json={"structured": structured()},
    )
    bid_id = saved.json()["bid_id"]
    other = await merchant_csrf(client, db_session, "beta@example.test")
    await client.post(
        "/api/v1/merchant/profile",
        headers={"X-CSRF-Token": other},
        json={"display_name": "Demo Merchant Beta", "attestations": {}},
    )

    read = await client.get(f"/api/v1/merchant/bids/{bid_id}")

    assert read.status_code == 404
    assert read.json()["error"]["code"] == "NOT_FOUND"


async def test_a_bid_after_the_deadline_answers_the_contracted_code(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    csrf = await open_bid(client, db_session, lot_id)
    await lot_with_deadline(db_session, world, offset_s=-1)

    late = await client.put(
        f"/api/v1/merchant/lots/{lot_id}/bid",
        headers={"X-CSRF-Token": csrf},
        json={"structured": structured()},
    )

    assert late.status_code == 409
    assert late.json()["error"]["code"] == "BID_WINDOW_CLOSED"


async def test_a_rejected_bid_reports_its_reason_to_its_owner(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    await open_bid(client, db_session, lot_id)
    bid = await db_session.scalar(
        text("SELECT id FROM bids WHERE lot_id = :lot"), {"lot": world.lot_id}
    )
    await set_bid_status(db_session, bid, "REJECTED")
    await db_session.execute(
        text("UPDATE bids SET reject_reason = 'R8_INFEASIBLE' WHERE id = :bid"), {"bid": bid}
    )
    await db_session.flush()

    view = await client.get(f"/api/v1/merchant/bids/{bid}")

    assert view.status_code == 200, view.text
    assert view.json()["status"] == "REJECTED"
    # CR-11: R8 is decided from the seated buyers' hidden caps, so the merchant is
    # told that the lot's feasibility or capacity rules were not met, not which of the
    # three feasibility codes fired. The exact code stays in the column for ops and the
    # auditor (config-and-errors.md fixes that code set).
    assert view.json()["reject_reason"] == "did not meet the lot's feasibility or capacity rules"
    stored = await db_session.scalar(
        text("SELECT reject_reason FROM bids WHERE id = :bid"), {"bid": bid}
    )
    assert stored == "R8_INFEASIBLE"
