"""T07A06 plus the buyer entry read stubs: the lot and bid edges over HTTP.

Every acceptance bullet from the task rows is a named test here (PT-15 owns the
cross-merchant read):

* a missing or unknown key is the one ``401 API_KEY_INVALID`` answer, and a key that
  lacks the operation's scope is ``403 API_KEY_SCOPE``;
* ``PUT .../bid`` needs ``Idempotency-Key``, refuses ``confirmed`` other than true and a
  replay of the same key returns the same confirmed bid with its 64-hex receipt;
* a key lists and reads only its own merchant's bids, and a foreign bid is ``404``;
* ``GET /me/entries`` and ``GET /entries/{id}/status`` are owner-scoped reads of the
  allocation and the live offer.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.api.merchant_api.app import app as merchant_api_app
from tests.integration.test_bid_sealing import bidding_world, lot_with_deadline, structured
from tests.integration.test_join_receipts import login, settings_for
from tests.integration.test_merchant_api_keys import create_key, merchant
from tests.integration.test_open_checkout import build_world

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
API = "/merchant-api/v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS)

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    # The sub-app solves its own dependencies (mounted apps do not inherit overrides).
    merchant_api_app.dependency_overrides[database_session] = session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as http:
            yield http
    finally:
        merchant_api_app.dependency_overrides.clear()


async def key_for(
    client: httpx.AsyncClient, db_session: AsyncSession, email: str, scopes: list[str]
) -> str:
    """A merchant with its profile row, and one API key with exactly these scopes."""
    csrf, _merchant_id = await merchant(client, db_session, email)
    created = await create_key(client, csrf, scopes)
    return str(created["key"])


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def bid_body(*, confirmed: Any = True) -> dict[str, Any]:
    return {"structured": structured(), "notes": None, "confirmed": confirmed}


async def submit(
    client: httpx.AsyncClient,
    key: str,
    lot_id: UUID,
    *,
    idem: str = "merchant-bid-key",
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    return await client.put(
        f"{API}/lots/{lot_id}/bid",
        headers={**bearer(key), "Idempotency-Key": idem},
        json=bid_body() if body is None else body,
    )


async def test_no_key_or_an_unknown_key_answers_api_key_invalid(
    client: httpx.AsyncClient,
) -> None:
    missing = await client.get(f"{API}/lots")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "API_KEY_INVALID"

    unknown = await client.get(f"{API}/lots", headers=bearer(f"fpm_deadbeef_{'x' * 43}"))
    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "API_KEY_INVALID"


async def test_a_key_without_the_operation_scope_is_refused(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    lots_key = await key_for(client, db_session, "lotsonly@example.test", ["lots:read"])

    refused = await submit(client, lots_key, lot_id)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "API_KEY_SCOPE"

    bids_key = await key_for(client, db_session, "bidsonly@example.test", ["bids:write"])
    listed = await client.get(f"{API}/bids", headers=bearer(bids_key))
    assert listed.status_code == 403
    assert listed.json()["error"]["code"] == "API_KEY_SCOPE"


async def test_submit_bid_needs_the_header_and_a_true_confirmation(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    key = await key_for(client, db_session, "header@example.test", ["bids:write"])

    missing = await client.put(f"{API}/lots/{lot_id}/bid", headers=bearer(key), json=bid_body())
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    unconfirmed = await submit(client, key, lot_id, body=bid_body(confirmed=False))
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_the_same_key_replays_one_confirmed_bid_with_its_receipt(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    key = await key_for(client, db_session, "replay@example.test", ["bids:write", "bids:read"])

    first = await submit(client, key, lot_id, idem="same-key")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "CONFIRMED"
    assert body["revision"] == 1
    assert HEX64.match(body["receipt"]["hash"]), body["receipt"]
    assert body["receipt"]["signature"]

    replay = await submit(client, key, lot_id, idem="same-key")
    assert replay.status_code == 200, replay.text
    assert replay.json() == body

    revisions = await db_session.scalar(
        text("SELECT count(*) FROM bid_revisions WHERE bid_id = :bid"), {"bid": body["bid_id"]}
    )
    assert int(revisions or 0) == 1, "a replay never writes a second revision"
    status = await db_session.scalar(
        text("SELECT status FROM bids WHERE id = :bid"), {"bid": body["bid_id"]}
    )
    assert str(status) == "CONFIRMED"

    different = await submit(
        client,
        key,
        lot_id,
        idem="same-key",
        body={"structured": structured(capacity=20), "notes": None, "confirmed": True},
    )
    assert different.status_code == 409
    assert different.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_the_same_idempotency_header_belongs_to_one_merchant(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A key value is per merchant: the same header never replays another's bid."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    alpha = await key_for(
        client, db_session, "alpha-idem@example.test", ["bids:write", "bids:read"]
    )
    beta = await key_for(client, db_session, "beta-idem@example.test", ["bids:write", "bids:read"])

    first = await submit(client, alpha, lot_id, idem="shared-value")
    second = await submit(client, beta, lot_id, idem="shared-value")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["bid_id"] != second.json()["bid_id"]

    alpha_mine = await client.get(f"{API}/bids", headers=bearer(alpha))
    beta_mine = await client.get(f"{API}/bids", headers=bearer(beta))
    assert [item["bid_id"] for item in alpha_mine.json()["items"]] == [first.json()["bid_id"]]
    assert [item["bid_id"] for item in beta_mine.json()["items"]] == [second.json()["bid_id"]]


async def test_a_key_never_sees_another_merchants_bids(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """PT-15: the key resolves to one merchant, and every read is sealed to it."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    alpha = await key_for(client, db_session, "alpha16@example.test", ["bids:write", "bids:read"])
    submitted = await submit(client, alpha, lot_id)
    assert submitted.status_code == 200, submitted.text
    bid_id = submitted.json()["bid_id"]

    beta = await key_for(client, db_session, "beta16@example.test", ["bids:read"])
    listed = await client.get(f"{API}/bids", headers=bearer(beta))
    assert listed.status_code == 200
    assert listed.json()["items"] == []

    foreign = await client.get(f"{API}/bids/{bid_id}", headers=bearer(beta))
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "NOT_FOUND"

    own = await client.get(f"{API}/bids/{bid_id}", headers=bearer(alpha))
    assert own.status_code == 200, own.text
    assert own.json()["bid_id"] == bid_id
    assert own.json()["status"] == "CONFIRMED"
    assert own.json()["flags"] == []

    mine = await client.get(f"{API}/bids", headers=bearer(alpha))
    assert [item["bid_id"] for item in mine.json()["items"]] == [bid_id]


async def test_lots_open_for_bidding_are_listed_with_their_requirements(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    key = await key_for(client, db_session, "lotsread@example.test", ["lots:read"])

    listed = await client.get(f"{API}/lots", headers=bearer(key))
    assert listed.status_code == 200, listed.text
    assert str(lot_id) in [item["lot_id"] for item in listed.json()]

    one = await client.get(f"{API}/lots/{lot_id}", headers=bearer(key))
    assert one.status_code == 200, one.text
    summary = one.json()
    assert summary["product_key"] == "monitor-27-4k"
    assert summary["seats"] == 2
    assert summary["min_seats"] == 2
    assert summary["condition"] == "NEW"
    assert summary["delivery_sla_days"] == 7
    assert summary["min_return_days"] == 14

    unknown = await client.get(f"{API}/lots/{uuid4()}", headers=bearer(key))
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "NOT_FOUND"


async def test_my_entries_and_entry_status_are_owner_scoped(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await build_world(
        db_session, seats=2, seated=2, waitlisted=0, lot_status="BIDDING", with_award=False
    )
    entry_id = world.entry_ids[0]
    await login(client, "me-a@example.test")
    user_id = await db_session.scalar(
        text("SELECT id FROM users WHERE email = :email"), {"email": "me-a@example.test"}
    )
    await db_session.execute(
        text("UPDATE pool_entries SET user_id = :user WHERE id = :entry"),
        {"user": user_id, "entry": entry_id},
    )
    order_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO buyer_orders (id, lot_id, entry_id, status, offer_expires_at, "
            "total_cents, breakdown) VALUES (:id, :lot, :entry, 'OFFERED', :expires, "
            "50000, '{}'::jsonb)"
        ),
        {
            "id": order_id,
            "lot": world.lot_id,
            "entry": entry_id,
            "expires": world.now + timedelta(seconds=300),
        },
    )
    await db_session.flush()

    mine = await client.get("/api/v1/me/entries")
    assert mine.status_code == 200, mine.text
    items = mine.json()["items"]
    assert [item["entry_id"] for item in items] == [str(entry_id)]
    assert items[0]["pool_id"] == str(world.pool_id)
    assert items[0]["entry_status"] == "ELIGIBLE"
    assert items[0]["allocation"]["status"] == "SEATED"
    assert items[0]["offer"]["buyer_order_id"] == str(order_id)

    single = await client.get(f"/api/v1/entries/{entry_id}/status")
    assert single.status_code == 200, single.text
    status = single.json()
    assert status["entry_id"] == str(entry_id)
    assert status["entry_status"] == "ELIGIBLE"
    assert status["allocation"]["lot_id"] == str(world.lot_id)
    assert status["allocation"]["rank"] == 1
    assert status["allocation"]["waitlist_position"] is None
    assert status["offer"]["status"] == "OFFERED"

    await login(client, "me-b@example.test")
    foreign = await client.get(f"/api/v1/entries/{entry_id}/status")
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "NOT_FOUND"
    empty = await client.get("/api/v1/me/entries")
    assert empty.status_code == 200
    assert empty.json()["items"] == []
