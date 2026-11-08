"""F21/F22: the adapter's token and retry contract (paypal-adapter.md section 4).

Both tests inject faults at the HTTP boundary with ``httpx.MockTransport``. They are
adapter plumbing tests, not evidence of PayPal behaviour: no Sandbox host is called
and the request bodies never leave the process. The contract they pin is the table's
two rows -- a 401 refreshes the token once and retries with the *same*
``PayPal-Request-Id`` (F21), and a 429 or 5xx backs off and retries with that same
key (F22), at most five tries, then a typed UNKNOWN for the reconciler.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from fairpool.adapters.paypal.gateway import RestPayPalGateway
from fairpool.domain.payments import CreateOrderRequest, Payee, PaymentError
from tests.unit.test_settings import make_settings

pytestmark = pytest.mark.faults

ORDER_BODY: dict[str, Any] = {
    "id": "ORDER-FAULT",
    "status": "CREATED",
    "intent": "AUTHORIZE",
    "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}],
}


def request() -> CreateOrderRequest:
    return CreateOrderRequest(
        buyer_order_id="11111111-1111-4111-8111-111111111111",
        attempt=1,
        amount_cents=100,
        breakdown={"item_cents": 100, "shipping_cents": 0, "tax_cents": 0},
        description="Fictional item",
        reference_id="lot",
        payee=Payee("seller@example.test", None),
        return_url="https://example.test/return",
        cancel_url="https://example.test/cancel",
        shipping=None,
        payload_level=0,
        extra_headers={},
    )


async def no_wait(*args: Any) -> None:
    return None


async def test_f21_token_expiry_refresh_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """F21: one 401 refreshes once and retries; a second 401 is terminal, not a loop."""
    monkeypatch.setattr("fairpool.adapters.paypal.gateway.asyncio.sleep", no_wait)
    tokens: list[str] = []
    posts: list[str] = []

    async def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/oauth2/token":
            tokens.append(f"TOKEN{len(tokens) + 1}")
            return httpx.Response(200, json={"access_token": tokens[-1], "expires_in": 32400})
        posts.append(req.headers["PayPal-Request-Id"])
        if len(posts) == 1:
            return httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"})
        return httpx.Response(201, json=ORDER_BODY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await RestPayPalGateway(make_settings(), client=client).create_order(request())

    assert result.id == "ORDER-FAULT"
    assert len(tokens) == 2, "exactly one refresh after the 401"
    assert len(posts) == 2, "the call is retried once, with the refreshed token"
    assert len(set(posts)) == 1, "the retry reuses the operation's PayPal-Request-Id (I9)"

    # The provider keeps refusing: the adapter must refresh once and then stop, not loop.
    refusing_posts: list[str] = []
    refusing_tokens: list[str] = []

    async def refusing(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/oauth2/token":
            refusing_tokens.append("token")
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": 32400})
        refusing_posts.append(req.headers["PayPal-Request-Id"])
        return httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(refusing)) as client:
        with pytest.raises(PaymentError) as raised:
            await RestPayPalGateway(make_settings(), client=client).create_order(request())

    assert len(refusing_tokens) == 2, "one cached token plus one refresh"
    assert len(refusing_posts) == 2, "one retry after the single allowed refresh"
    assert len(set(refusing_posts)) == 1
    assert raised.value.category in {"TERMINAL", "CONFIG"}


async def test_f22_paypal_429_5xx_backoff_same_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """F22: 429 and 5xx are retried with backoff under one key; exhaustion is UNKNOWN."""
    monkeypatch.setattr("fairpool.adapters.paypal.gateway.asyncio.sleep", no_wait)
    posts: list[str] = []
    statuses = iter((429, 503, 201))

    async def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": 32400})
        posts.append(req.headers["PayPal-Request-Id"])
        status = next(statuses)
        if status == 201:
            return httpx.Response(201, json=ORDER_BODY)
        return httpx.Response(status, json={"name": "TEMPORARY"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await RestPayPalGateway(make_settings(), client=client).create_order(request())

    assert result.id == "ORDER-FAULT"
    assert len(posts) == 3, "429 and 5xx each got one retry"
    assert len(set(posts)) == 1, "every try carried the same idempotency key (I9)"

    # Five failed tries is the table's bound; the sixth attempt does not happen.
    exhausted: list[str] = []

    async def always_500(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": 32400})
        exhausted.append(req.headers["PayPal-Request-Id"])
        return httpx.Response(500, json={"name": "INTERNAL_SERVER_ERROR"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(always_500)) as client:
        with pytest.raises(PaymentError) as raised:
            await RestPayPalGateway(make_settings(), client=client).create_order(request())

    assert raised.value.category == "UNKNOWN"
    assert len(exhausted) == 5, "the backoff table stops at five tries"
    assert len(set(exhausted)) == 1, "the same key survived every retry"
