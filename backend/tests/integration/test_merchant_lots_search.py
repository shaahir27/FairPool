"""T07B05: merchant-lane lot search, through the console and the Agent API alike.

The Demand Board and ``GET /merchant-api/v1/lots?q=`` are the same retrieval over
the same open lots (INT-1, ai-schemas.md section 7): ``q`` goes through the search
service and a lot that is no longer BIDDING never appears. Both edges must answer
the same ``MerchantLotSummary`` items (PT-15 parity for the reads).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.api.merchant_api.app import app as merchant_api_app
from fairpool.infra.clock import DbClock
from tests.integration.test_join_receipts import settings_for
from tests.integration.test_merchant_api_keys import create_key, merchant

pytestmark = pytest.mark.integration

SETTINGS = settings_for()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS)

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    merchant_api_app.dependency_overrides[database_session] = session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as http:
            yield http
    finally:
        merchant_api_app.dependency_overrides.clear()


async def add_lot(
    session: AsyncSession,
    *,
    title: str,
    product_key: str,
    status: str = "BIDDING",
    search_text: str,
    close_in: int = 3600,
) -> UUID:
    """One public pool with one lot; ``search_text`` is what publish would derive."""
    now = await DbClock().db_now(session)
    admin = uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, display_name) "
            "VALUES (:id, :email, 'hash', 'admin', 'Admin')"
        ),
        {"id": admin, "email": f"admin-{admin}@example.test"},
    )
    pool_id = uuid4()
    template = {
        "product_key": product_key,
        "variant": "black",
        "title": title,
        "condition": "NEW",
        "quantity": 1,
        "currency": "USD",
        "bundle_contents": [product_key, "cable"],
        "delivery_sla_days": 7,
        "fund_by": "2026-11-10",
        "min_return_days": 14,
        "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY"]}],
    }
    await session.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, created_by, search_text) "
            "VALUES (:id, 'LIVE_SANDBOX', 'OPEN', :title, CAST(:template AS jsonb), "
            "'[]'::jsonb, CAST(:timeline AS jsonb), false, 'allocation_v1', :admin, :search)"
        ),
        {
            "id": pool_id,
            "title": title,
            "template": json.dumps(template),
            "timeline": json.dumps(
                {
                    "open_at": (now - timedelta(minutes=1)).isoformat(),
                    "close_at": (now + timedelta(hours=2)).isoformat(),
                }
            ),
            "admin": admin,
            "search": search_text,
        },
    )
    lot_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
            "status, payment_router, payment_mode, bid_open_at, bid_close_at) "
            "VALUES (:id, :pool, 'US-EAST', 0, 1, 2, 2, CAST(:status AS lot_status), "
            "'single_seller', 'authorize_capture', :now, :close)"
        ),
        {
            "id": lot_id,
            "pool": pool_id,
            "status": status,
            "now": now,
            "close": now + timedelta(seconds=close_in),
        },
    )
    return lot_id


async def open_merchant(
    client: httpx.AsyncClient, db_session: AsyncSession, email: str
) -> tuple[str, str]:
    """A merchant console session and one lots:read key for the same merchant."""
    csrf, _merchant_id = await merchant(client, db_session, email)
    created = await create_key(client, csrf, ["lots:read"])
    return csrf, str(created["key"])


async def test_the_console_and_the_agent_api_search_the_same_open_lots(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    monitor = await add_lot(
        session=db_session,
        title="27-inch 4K monitor",
        product_key="monitor-27-4k",
        search_text="27-inch 4K monitor monitor-27-4k black NEW delivered NY",
    )
    lamp = await add_lot(
        session=db_session,
        title="Zephyr desk lamp",
        product_key="lamp-zephyr-7",
        search_text="Zephyr desk lamp lamp-zephyr-7 white NEW delivered NY",
        close_in=7200,
    )
    closed = await add_lot(
        session=db_session,
        title="Retired 27-inch monitor lot",
        product_key="monitor-27-4k",
        status="AWARDED",
        search_text="27-inch 4K monitor monitor-27-4k black NEW delivered NY",
    )
    csrf, key = await open_merchant(client, db_session, "search15@example.test")

    console = await client.get("/api/v1/merchant/lots", params={"q": "monitor-27-4k"})
    assert console.status_code == 200, console.text
    agent = await client.get(
        "/merchant-api/v1/lots",
        params={"q": "monitor-27-4k"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert agent.status_code == 200, agent.text

    assert str(monitor) in [item["lot_id"] for item in console.json()]
    assert str(closed) not in [item["lot_id"] for item in console.json()], "not BIDDING"
    assert agent.json() == console.json()

    only_lamp = await client.get("/api/v1/merchant/lots", params={"q": "zephyr"})
    assert only_lamp.status_code == 200, only_lamp.text
    assert str(lamp) in [item["lot_id"] for item in only_lamp.json()]

    everything = await client.get("/api/v1/merchant/lots", headers={"X-CSRF-Token": csrf})
    assert everything.status_code == 200, everything.text
    assert {item["lot_id"] for item in everything.json()} == {str(monitor), str(lamp)}

    none = await client.get("/api/v1/merchant/lots", params={"q": "nothing-matches-this"})
    assert none.status_code == 200
    assert none.json() == []


async def test_the_status_filter_only_accepts_open_lots(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    monitor = await add_lot(
        session=db_session,
        title="27-inch 4K monitor",
        product_key="monitor-27-4k",
        search_text="27-inch 4K monitor monitor-27-4k black NEW delivered NY",
    )
    _csrf, key = await open_merchant(client, db_session, "status15@example.test")

    bid_open = await client.get(
        "/merchant-api/v1/lots",
        params={"status": "BIDDING"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert bid_open.status_code == 200, bid_open.text
    assert [item["lot_id"] for item in bid_open.json()] == [str(monitor)]

    refused = await client.get(
        "/merchant-api/v1/lots",
        params={"status": "AWARDED"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "VALIDATION_ERROR"
