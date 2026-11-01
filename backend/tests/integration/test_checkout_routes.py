"""T04A02/T04X01 route level: offers, callbacks, return and order status over HTTP.

The handlers are tested against a real lot and award; these tests prove the HTTP
surface and the two rules the contract makes non-negotiable at the edge:

* every route is owner-scoped -- another buyer's id answers ``404``, like an unknown
  one;
* the return URL and the SDK callbacks are hints. The posted order id must be one
  this buyer order created, an unknown ``token`` never redirects, and the approval
  itself is decided by the FR-CK-05 checks behind the handler.

The app's checkout graph comes from ``wiring.checkout_services`` with
``PAYMENT_ROUTER=fake``, so the provider is ``FakePayPalGateway`` and no host is
reachable (I1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.api.routers.checkout import HOLD_NOTICE, VAULT_NOTICE
from fairpool.fakes.payments import FAKE_APPROVE_URL
from tests.integration.test_join_receipts import login, settings_for
from tests.integration.test_open_checkout import build_world, open_handler

pytestmark = pytest.mark.integration

SHIPPING = {
    "name": "Buyer One",
    "line1": "1 Market Street",
    "line2": None,
    "city": "New York",
    "region": "NY",
    "postal_code": "10001",
    "country_code": "US",
}


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


async def seated_world(db_session: AsyncSession, *, seated: int = 3) -> object:
    """A real lot with its award and one OFFERED order per seated entry."""
    world = await build_world(
        db_session, seats=seated, min_seats=2, seated=seated, waitlisted=0, moq=2
    )
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    return world


async def sign_in(
    client: httpx.AsyncClient, db_session: AsyncSession, world: object, *, index: int, email: str
) -> str:
    """Log in and make the test's entry ``index`` belong to that session's user."""
    csrf = await login(client, email)
    user_id = await db_session.scalar(
        text("SELECT id FROM users WHERE email = :email"), {"email": email}
    )
    await db_session.execute(
        text("UPDATE pool_entries SET user_id = :user WHERE id = :entry"),
        {"user": user_id, "entry": world.entry_ids[index]},  # type: ignore[attr-defined]
    )
    return csrf


async def order_for(db_session: AsyncSession, world: object, *, index: int) -> UUID:
    value = await db_session.scalar(
        text("SELECT id FROM buyer_orders WHERE entry_id = :entry"),
        {"entry": world.entry_ids[index]},  # type: ignore[attr-defined]
    )
    assert value is not None
    return UUID(str(value))


async def order_status(db_session: AsyncSession, buyer_order_id: UUID) -> str:
    value = await db_session.scalar(
        text("SELECT status FROM buyer_orders WHERE id = :id"), {"id": buyer_order_id}
    )
    return str(value)


async def test_the_offer_disclosure_shows_the_award_terms_and_is_owner_scoped(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await seated_world(db_session)
    csrf = await sign_in(client, db_session, world, index=0, email="offer@example.test")
    buyer_order_id = await order_for(db_session, world, index=0)

    response = await client.get(f"/api/v1/offers/{buyer_order_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "OFFERED"
    assert body["merchant"] == {"display_name": "Demo Merchant"}
    assert body["product"]["title"] == "27-inch 4K monitor"
    assert body["product"]["condition"] == "NEW"
    assert body["totals"] == {
        "item_cents": 47_000,
        "shipping_cents": 1_500,
        "tax_cents": 1_500,
        "total_cents": 50_000,
        "cap_cents": 60_000,
    }
    # The lot is stamped single_seller, so DEP-4 requires the fallback notice.
    assert body["notices"]["fallback"]
    assert body["notices"]["hold"] == HOLD_NOTICE
    assert body["notices"]["lots_may_differ"]
    assert body["offer_expires_at"]

    async with httpx.AsyncClient(transport=client._transport, base_url="https://api.test") as other:
        await login(other, "not-the-owner@example.test")
        refused = await other.get(f"/api/v1/offers/{buyer_order_id}")
    assert refused.status_code == 404 and refused.json()["error"]["code"] == "NOT_FOUND"
    assert csrf


async def test_continue_creates_the_provider_order_once_and_moves_the_seat(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await seated_world(db_session)
    csrf = await sign_in(client, db_session, world, index=0, email="continue@example.test")
    buyer_order_id = await order_for(db_session, world, index=0)

    first = await client.post(
        f"/api/v1/offers/{buyer_order_id}/continue",
        json={"shipping": SHIPPING},
        headers={"X-CSRF-Token": csrf},
    )

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["approve_url"].startswith(FAKE_APPROVE_URL)
    assert body["approval_ui"] == "sdk_popup"
    assert await order_status(db_session, buyer_order_id) == "ORDER_CREATED"

    replay = await client.post(
        f"/api/v1/offers/{buyer_order_id}/continue",
        json={"shipping": SHIPPING},
        headers={"X-CSRF-Token": csrf},
    )
    assert replay.status_code == 200
    assert replay.json()["paypal_order_id"] == body["paypal_order_id"]


async def test_continue_on_a_vault_lot_is_refused_before_any_provider_call(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """M8: the stamped mode is checked first, so the answer is a contract code, not a 500."""
    world = await build_world(
        db_session, seats=1, seated=1, waitlisted=0, mode="vault_charge", moq=1
    )
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    csrf = await sign_in(client, db_session, world, index=0, email="vault-continue@example.test")
    buyer_order_id = await order_for(db_session, world, index=0)

    response = await client.post(
        f"/api/v1/offers/{buyer_order_id}/continue",
        json={"shipping": SHIPPING},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "ORDER_STATE_INVALID"
    assert await order_status(db_session, buyer_order_id) == "OFFERED"
    # No provider order was created or recorded: the guard ran before the gateway.
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM paypal_orders WHERE buyer_order_id = :id"),
            {"id": buyer_order_id},
        )
        == 0
    )


async def test_a_vault_offer_says_nothing_is_held(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """M10: vault mode holds nothing, so the offer notice must not claim a hold."""
    world = await build_world(
        db_session, seats=1, seated=1, waitlisted=0, mode="vault_charge", moq=1
    )
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    await sign_in(client, db_session, world, index=0, email="vault-offer@example.test")
    buyer_order_id = await order_for(db_session, world, index=0)

    response = await client.get(f"/api/v1/offers/{buyer_order_id}")

    assert response.status_code == 200, response.text
    notices = response.json()["notices"]
    assert notices["hold"] == VAULT_NOTICE
    assert notices["hold"] != HOLD_NOTICE


async def test_approved_runs_the_checks_and_is_idempotent(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await seated_world(db_session)
    csrf = await sign_in(client, db_session, world, index=0, email="approved@example.test")
    buyer_order_id = await order_for(db_session, world, index=0)
    created = await client.post(
        f"/api/v1/offers/{buyer_order_id}/continue",
        json={"shipping": SHIPPING},
        headers={"X-CSRF-Token": csrf},
    )
    paypal_order_id = created.json()["paypal_order_id"]

    approved = await client.post(
        f"/api/v1/offers/{buyer_order_id}/approved",
        json={"paypal_order_id": paypal_order_id},
        headers={"X-CSRF-Token": csrf},
    )

    assert approved.status_code == 200, approved.text
    assert approved.json() == {
        "buyer_order_id": str(buyer_order_id),
        "status": "APPROVED",
        "reason": None,
    }
    assert await order_status(db_session, buyer_order_id) == "APPROVED"

    again = await client.post(
        f"/api/v1/offers/{buyer_order_id}/approved",
        json={"paypal_order_id": paypal_order_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert again.status_code == 200 and again.json()["status"] == "APPROVED"

    foreign = await client.post(
        f"/api/v1/offers/{buyer_order_id}/approved",
        json={"paypal_order_id": "NOT-OUR-ORDER"},
        headers={"X-CSRF-Token": csrf},
    )
    assert foreign.status_code == 422
    assert foreign.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_decline_and_the_cancel_hint_each_move_the_order_once(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await seated_world(db_session)
    csrf = await sign_in(client, db_session, world, index=0, email="decline@example.test")
    offered = await order_for(db_session, world, index=0)

    declined = await client.post(
        f"/api/v1/offers/{offered}/decline", headers={"X-CSRF-Token": csrf}
    )

    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "DECLINED"
    assert await order_status(db_session, offered) == "DECLINED"
    replay = await client.post(f"/api/v1/offers/{offered}/decline", headers={"X-CSRF-Token": csrf})
    assert replay.status_code == 200 and replay.json()["status"] == "DECLINED"

    # A second seat goes through ON_CANCEL instead: ORDER_CREATED then DECLINED.
    second = await order_for(db_session, world, index=1)
    csrf = await sign_in(client, db_session, world, index=1, email="cancel@example.test")
    await client.post(
        f"/api/v1/offers/{second}/continue",
        json={"shipping": SHIPPING},
        headers={"X-CSRF-Token": csrf},
    )
    cancelled = await client.post(
        f"/api/v1/offers/{second}/cancelled",
        json={"paypal_order_id": None},
        headers={"X-CSRF-Token": csrf},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "DECLINED"
    assert await order_status(db_session, second) == "DECLINED"
    repeated = await client.post(
        f"/api/v1/offers/{second}/cancelled",
        json={"paypal_order_id": None},
        headers={"X-CSRF-Token": csrf},
    )
    assert repeated.status_code == 200 and repeated.json()["status"] == "DECLINED"


async def test_checkout_return_never_trusts_the_token(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await seated_world(db_session)
    csrf = await sign_in(client, db_session, world, index=0, email="return@example.test")
    buyer_order_id = await order_for(db_session, world, index=0)
    created = await client.post(
        f"/api/v1/offers/{buyer_order_id}/continue",
        json={"shipping": SHIPPING},
        headers={"X-CSRF-Token": csrf},
    )
    token = created.json()["paypal_order_id"]

    unknown = await client.get("/api/v1/checkout/return", params={"token": "made-up"})
    assert unknown.status_code == 404

    returned = await client.get(
        "/api/v1/checkout/return", params={"token": token, "PayerID": "FAKE-PAYER"}
    )

    assert returned.status_code == 302
    assert returned.headers["location"] == f"http://localhost:5173/orders/{buyer_order_id}"
    assert await order_status(db_session, buyer_order_id) == "APPROVED"

    async with httpx.AsyncClient(transport=client._transport, base_url="https://api.test") as other:
        await login(other, "return-intruder@example.test")
        refused = await other.get("/api/v1/checkout/return", params={"token": token})
    assert refused.status_code == 404


async def test_checkout_cancel_declines_and_redirects(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await seated_world(db_session)
    csrf = await sign_in(client, db_session, world, index=0, email="cancel-route@example.test")
    buyer_order_id = await order_for(db_session, world, index=0)
    created = await client.post(
        f"/api/v1/offers/{buyer_order_id}/continue",
        json={"shipping": SHIPPING},
        headers={"X-CSRF-Token": csrf},
    )
    token = created.json()["paypal_order_id"]

    cancelled = await client.get("/api/v1/checkout/cancel", params={"token": token})

    assert cancelled.status_code == 302
    assert cancelled.headers["location"] == f"http://localhost:5173/orders/{buyer_order_id}"
    assert await order_status(db_session, buyer_order_id) == "DECLINED"
    missing = await client.get("/api/v1/checkout/cancel")
    assert missing.status_code == 404


async def test_the_order_page_lists_the_history_and_the_fallback_label(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await seated_world(db_session)
    csrf = await sign_in(client, db_session, world, index=0, email="status@example.test")
    buyer_order_id = await order_for(db_session, world, index=0)
    created = await client.post(
        f"/api/v1/offers/{buyer_order_id}/continue",
        json={"shipping": SHIPPING},
        headers={"X-CSRF-Token": csrf},
    )
    await client.post(
        f"/api/v1/offers/{buyer_order_id}/approved",
        json={"paypal_order_id": created.json()["paypal_order_id"]},
        headers={"X-CSRF-Token": csrf},
    )

    response = await client.get(f"/api/v1/orders/{buyer_order_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["lot_status"] == "CHECKOUT_OPEN"
    assert body["total_cents"] == 50_000
    assert [item["status"] for item in body["history"]] == ["ORDER_CREATED", "APPROVED"]
    assert body["paypal"] == {
        "authorization_status": None,
        "capture_status": None,
        "refund_status": None,
    }
    assert body["labels"] == ["SANDBOX", "FALLBACK: single stand-in seller"]


async def test_my_orders_lists_only_mine(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    world = await seated_world(db_session)
    await sign_in(client, db_session, world, index=0, email="mine@example.test")
    mine = await order_for(db_session, world, index=0)

    response = await client.get("/api/v1/me/orders")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["buyer_order_id"] for item in items] == [str(mine)]
    assert items[0]["status"] == "OFFERED" and items[0]["total_cents"] == 50_000


async def test_checkout_config_is_public_and_carries_no_secret(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/checkout/config")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "approval_ui": "sdk_popup",
        "sdk_auth": "client_id",
        "client_id": "dummy-sandbox-client-id",
        "sdk_url": "https://www.sandbox.paypal.com/web-sdk/v6/core",
        "components": ["paypal-payments"],
        "page_type": "checkout",
        "currency": "USD",
        "labels": ["SANDBOX"],
    }
    assert "secret" not in response.text.lower()
