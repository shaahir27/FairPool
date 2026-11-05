"""CR-10: a buyer route is for buyers, and a merchant cannot bid in its own pool.

Two separations, and both used to be missing:

* the buyer surface (entries, intake, offers, orders) was session-wide, so a merchant
  or an admin session could read and write it. The refusal is ``FORBIDDEN`` at 403 and
  it happens before the owner lookup, which is why a random id answers 403, not 404;
* a merchant whose own user holds an entry in the pool could bid in it: it could see
  the pool's demand while it priced and, if it won, sell to itself.

``GET /api/v1/me`` stays session-wide on purpose: it is how any signed-in client learns
its own role.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain.errors import ApplicationError
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import IdentityService
from tests.integration.test_bid_sealing import lot_with_deadline, service, structured
from tests.integration.test_join_receipts import login, settings_for
from tests.integration.test_open_checkout import build_world

pytestmark = pytest.mark.integration

PASSWORD = "a-secure-password"


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


async def role_session(client: httpx.AsyncClient, db_session: AsyncSession, role: str) -> str:
    """Sign in a session whose user carries ``role`` (the password check stays real)."""
    email = f"{role}-{uuid4().hex[:8]}@example.test"
    await IdentityService("test-signing-key", DbClock()).register(
        db_session, email=email, password=PASSWORD, display_name=role.title()
    )
    await db_session.execute(
        text("UPDATE users SET role = :role WHERE email = :email"), {"role": role, "email": email}
    )
    sign_in = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert sign_in.status_code == 200, sign_in.text
    return str(sign_in.json()["csrf_token"])


def buyer_routes() -> list[tuple[str, str, dict[str, Any] | None]]:
    """Every buyer-only route, with a body where the route has one."""
    pool, entry, order = uuid4(), uuid4(), uuid4()
    return [
        ("POST", f"/api/v1/pools/{pool}/entries", {"confirmed_request_id": str(uuid4())}),
        ("GET", f"/api/v1/pools/{pool}/entries/me", None),
        ("DELETE", f"/api/v1/pools/{pool}/entries/me", None),
        ("POST", f"/api/v1/entries/{entry}/vault", {"consent_version": "v1", "cap_cents": 1}),
        ("DELETE", f"/api/v1/entries/{entry}/vault", None),
        ("GET", "/api/v1/me/entries", None),
        ("GET", f"/api/v1/entries/{entry}/status", None),
        ("POST", "/api/v1/intake/messages", {"message": "a 27 inch monitor"}),
        ("POST", "/api/v1/intake/confirm", {"proposal_id": str(uuid4())}),
        ("POST", f"/api/v1/offers/{order}/continue", {"shipping": {}}),
        ("POST", f"/api/v1/offers/{order}/decline", None),
        ("POST", f"/api/v1/offers/{order}/approved", {"paypal_order_id": "PP-1"}),
        ("POST", f"/api/v1/offers/{order}/cancelled", {"paypal_order_id": "PP-1"}),
        ("GET", f"/api/v1/orders/{order}", None),
        ("GET", "/api/v1/me/orders", None),
    ]


@pytest.mark.parametrize("role", ["merchant", "admin"])
async def test_a_non_buyer_session_is_refused_on_every_buyer_route(
    client: httpx.AsyncClient, db_session: AsyncSession, role: str
) -> None:
    csrf = await role_session(client, db_session, role)
    for method, path, body in buyer_routes():
        response = await client.request(
            method,
            path,
            json=body,
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "role-1"},
        )
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["error"]["code"] == "FORBIDDEN", (method, path)


async def test_me_stays_session_wide_for_every_role(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await role_session(client, db_session, "merchant")
    response = await client.get("/api/v1/me")
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "merchant"


async def test_a_buyer_session_still_reaches_the_buyer_routes(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await login(client, "still-a-buyer@example.test")
    response = await client.get("/api/v1/me/entries")
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}


async def test_the_buyers_own_404_is_unchanged_for_a_real_buyer(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # The 403 above must not have turned every unknown id into a role answer.
    await login(client, "buyer-404@example.test")
    response = await client.get(f"/api/v1/orders/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_a_merchant_with_an_entry_in_the_pool_cannot_bid_in_it(
    db_session: AsyncSession,
) -> None:
    world = await build_world(
        db_session, seats=2, seated=2, waitlisted=0, lot_status="BIDDING", with_award=False
    )
    await lot_with_deadline(db_session, world, offset_s=600)
    # The merchant's own user is also a buyer here, which is the self-dealing case.
    await db_session.execute(
        text("UPDATE pool_entries SET user_id = :user WHERE id = :entry"),
        {"user": world.merchant_user_id, "entry": world.entry_ids[0]},
    )

    with pytest.raises(ApplicationError) as refused:
        await service().save(
            db_session, merchant_id=world.merchant_id, lot_id=world.lot_id, structured=structured()
        )
    assert refused.value.code == "FORBIDDEN"
    # Nothing was written: the guard runs before the first revision.
    stored = await db_session.scalar(
        text("SELECT count(*) FROM bids WHERE merchant_id = :merchant"),
        {"merchant": world.merchant_id},
    )
    assert int(stored or 0) == 0


async def test_a_merchant_without_an_entry_bids_as_usual(db_session: AsyncSession) -> None:
    """The guard is about the same person on both sides, not about merchants at all."""
    world = await build_world(
        db_session, seats=2, seated=2, waitlisted=0, lot_status="BIDDING", with_award=False
    )
    await lot_with_deadline(db_session, world, offset_s=600)
    bid, revision = await service().save(
        db_session, merchant_id=world.merchant_id, lot_id=world.lot_id, structured=structured()
    )
    assert str(bid.status) == "DRAFT"
    assert revision.revision == 1


async def test_the_guard_covers_a_merchant_who_joins_after_bidding(
    db_session: AsyncSession,
) -> None:
    world = await build_world(
        db_session, seats=2, seated=2, waitlisted=0, lot_status="BIDDING", with_award=False
    )
    await lot_with_deadline(db_session, world, offset_s=600)
    await service().save(
        db_session, merchant_id=world.merchant_id, lot_id=world.lot_id, structured=structured()
    )
    # The same person now holds an entry in the pool, so every later save must ask the
    # question again: a joined buyer cannot revise the bid it is bidding against.
    await db_session.execute(
        text("UPDATE pool_entries SET user_id = :user WHERE id = :entry"),
        {"user": world.merchant_user_id, "entry": world.entry_ids[1]},
    )
    with pytest.raises(ApplicationError) as refused:
        await service().save(
            db_session,
            merchant_id=world.merchant_id,
            lot_id=world.lot_id,
            structured=structured(capacity=12),
        )
    assert refused.value.code == "FORBIDDEN"
