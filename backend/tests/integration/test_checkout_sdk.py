"""T07A01: the JavaScript SDK v6 config, client token and approval channel.

``api.md`` section 4.1 fixes the public config object and the client-token
response; ``paypal-adapter.md`` section 12 adds the server obligations: only a
client-credentials token goes to the browser, cached to a minute before expiry,
and the SDK callback records ``approval_channel = sdk_popup`` while the redirect
return keeps the ``redirect`` value written at create time.

No test here calls PayPal: the gateway is the offline fake, and the token test
counts calls on an injected double (I1, I2). The one adapter test uses an
``httpx.MockTransport`` and asserts the request shape only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.adapters.paypal.gateway import RestPayPalGateway
from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain.payments import PaymentError
from fairpool.modules.checkout.sdk import SdkService
from tests.integration.test_checkout_routes import (
    SHIPPING,
    order_for,
    seated_world,
    sign_in,
)
from tests.integration.test_join_receipts import login, settings_for

pytestmark = pytest.mark.integration


def app_for(db_session: AsyncSession, **overrides: Any):
    app = create_app(settings_for(**overrides))

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    return app


def http_for(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.test")


class CountingTokenGateway:
    def __init__(self, token: str = "SDK-CLIENT-TOKEN") -> None:
        self.token = token
        self.calls: list[str] = []

    async def client_token(self, domain: str) -> tuple[str, int]:
        self.calls.append(domain)
        return self.token, 900


async def test_checkout_config_is_the_exact_public_object(
    db_session: AsyncSession,
) -> None:
    """T07A01 acceptance: the config endpoint matches api.md section 4.1 exactly."""
    app = app_for(db_session)
    async with http_for(app) as client:
        response = await client.get("/api/v1/checkout/config")

    assert response.status_code == 200, response.text
    assert response.json() == {
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


async def test_config_labels_surface_the_fallback_router(db_session: AsyncSession) -> None:
    """DEP-4: a deployment on the stand-in seller never presents it as neutral."""
    app = app_for(
        db_session,
        payment_router="single_seller",
        single_seller_email="seller@example.test",
    )
    async with http_for(app) as client:
        response = await client.get("/api/v1/checkout/config")

    assert response.status_code == 200, response.text
    assert response.json()["labels"] == ["SANDBOX", "FALLBACK: single stand-in seller"]


async def test_client_token_is_cached_across_requests(db_session: AsyncSession) -> None:
    """One gateway call serves repeated reads; only the token and remaining time go out."""
    gateway = CountingTokenGateway()
    app = app_for(db_session, paypal_sdk_auth="client_token")
    app.state.sdk_service = SdkService(
        gateway=gateway,
        client_id="dummy-sandbox-client-id",
        sdk_auth="client_token",
        approval_ui="sdk_popup",
        fallback=False,
        domain="checkout.example.test",
    )
    async with http_for(app) as client:
        await login(client, "client-token@example.test")
        first = await client.get("/api/v1/checkout/client-token")
        second = await client.get("/api/v1/checkout/client-token")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert gateway.calls == ["checkout.example.test"]
    assert first.json()["client_token"] == "SDK-CLIENT-TOKEN"
    assert 0 < first.json()["expires_in"] <= 900
    assert 0 < second.json()["expires_in"] <= first.json()["expires_in"]
    assert "secret" not in first.text.lower()


async def test_client_token_refuses_the_redirect_approval_ui(
    db_session: AsyncSession,
) -> None:
    """api.md: with the redirect UI there is no SDK token to hand out."""
    gateway = CountingTokenGateway()
    app = app_for(db_session, paypal_approval_ui="redirect", paypal_sdk_auth="client_token")
    app.state.sdk_service = SdkService(
        gateway=gateway,
        client_id="dummy-sandbox-client-id",
        sdk_auth="client_token",
        approval_ui="redirect",
        fallback=False,
        domain="checkout.example.test",
    )
    async with http_for(app) as client:
        await login(client, "redirect-token@example.test")
        response = await client.get("/api/v1/checkout/client-token")

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FEATURE_DISABLED"
    assert gateway.calls == []


async def test_client_token_requires_a_session(db_session: AsyncSession) -> None:
    app = app_for(db_session, paypal_sdk_auth="client_token")
    async with http_for(app) as client:
        response = await client.get("/api/v1/checkout/client-token")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_client_token_is_also_refused_when_client_id_is_the_sdk_auth(
    db_session: AsyncSession,
) -> None:
    gateway = CountingTokenGateway()
    app = app_for(db_session, paypal_sdk_auth="client_id")
    app.state.sdk_service = SdkService(
        gateway=gateway,
        client_id="dummy-sandbox-client-id",
        sdk_auth="client_id",
        approval_ui="sdk_popup",
        fallback=False,
        domain="checkout.example.test",
    )
    async with http_for(app) as client:
        await login(client, "client-id-token@example.test")
        response = await client.get("/api/v1/checkout/client-token")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FEATURE_DISABLED"
    assert gateway.calls == []


async def test_rest_gateway_client_token_posts_the_sandbox_form() -> None:
    """The adapter sends the form S13 verified: grant, response type and domain."""
    seen: dict[str, Any] = {}

    async def handle_async(request: httpx.Request) -> httpx.Response:
        return handle(request)

    def handle(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["basic"] = request.headers.get("authorization", "").startswith("Basic ")
        seen["form"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "SDK-TOKEN", "expires_in": 900})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle_async)) as client:
        gateway = RestPayPalGateway(settings_for(), client=client)
        token, expires_in = await gateway.client_token("checkout.example.test")

    assert token == "SDK-TOKEN" and expires_in == 900
    assert seen["path"] == "/v1/oauth2/token"
    assert seen["basic"] is True
    form = httpx.QueryParams(seen["form"])
    assert form["grant_type"] == "client_credentials"
    assert form["response_type"] == "client_token"
    assert form["domains[]"] == "checkout.example.test"


async def test_rest_gateway_client_token_reports_a_config_error_without_retrying() -> None:
    calls: list[str] = []

    async def handle_async(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(401, json={"error": "invalid_client"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle_async)) as client:
        gateway = RestPayPalGateway(settings_for(), client=client)
        with pytest.raises(PaymentError) as caught:
            await gateway.client_token("checkout.example.test")

    assert caught.value.category == "CONFIG"
    assert calls == ["/v1/oauth2/token"]


async def test_approved_stamps_sdk_popup_and_returns_no_amount(
    db_session: AsyncSession,
) -> None:
    """INT-7: the popup callback records its channel; the body carries no amount."""
    world = await seated_world(db_session)
    app = app_for(db_session)
    async with http_for(app) as client:
        csrf = await sign_in(client, db_session, world, index=0, email="sdk-approved@example.test")
        buyer_order_id = await order_for(db_session, world, index=0)
        created = await client.post(
            f"/api/v1/offers/{buyer_order_id}/continue",
            json={"shipping": SHIPPING},
            headers={"X-CSRF-Token": csrf},
        )
        approved = await client.post(
            f"/api/v1/offers/{buyer_order_id}/approved",
            json={"paypal_order_id": created.json()["paypal_order_id"]},
            headers={"X-CSRF-Token": csrf},
        )

        channel = await channel_for(db_session, buyer_order_id)
        assert approved.status_code == 200, approved.text
        assert channel == "sdk_popup"

        # The redirect return on a second seat keeps what ``continue`` wrote.
        csrf = await sign_in(client, db_session, world, index=1, email="sdk-redirect@example.test")
        other = await order_for(db_session, world, index=1)
        other_created = await client.post(
            f"/api/v1/offers/{other}/continue",
            json={"shipping": SHIPPING},
            headers={"X-CSRF-Token": csrf},
        )
        returned = await client.get(
            "/api/v1/checkout/return",
            params={"token": other_created.json()["paypal_order_id"], "PayerID": "FAKE-PAYER"},
        )

    assert approved.json()["buyer_order_id"] == str(buyer_order_id)
    assert set(approved.json()) == {"buyer_order_id", "status", "reason"}
    assert "amount" not in approved.text
    assert returned.status_code == 302
    assert await channel_for(db_session, other) == "redirect"


async def channel_for(session: AsyncSession, buyer_order_id: UUID) -> str | None:
    value = await session.scalar(
        text(
            "SELECT approval_channel FROM paypal_orders WHERE buyer_order_id = :id "
            "ORDER BY attempt DESC, created_at DESC LIMIT 1"
        ),
        {"id": buyer_order_id},
    )
    return None if value is None else str(value)
