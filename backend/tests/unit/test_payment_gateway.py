from dataclasses import replace

import httpx
import pytest

from fairpool.adapters.paypal.gateway import RestPayPalGateway, request_id
from fairpool.domain.payments import CreateOrderRequest, Payee, PaymentError
from fairpool.wiring import payment_router
from tests.unit.test_settings import make_settings


def request():
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


async def test_token_cache_retries_and_sanitized_order():
    calls = []

    async def handle(req):
        calls.append(req)
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "PRIVATE", "expires_in": 32400})
        return httpx.Response(
            201,
            json={
                "id": "ORDER",
                "status": "CREATED",
                "intent": "AUTHORIZE",
                "purchase_units": [
                    {
                        "amount": {"currency_code": "USD", "value": "1.00"},
                        "payee": {"email_address": "seller@example.test"},
                    }
                ],
                "links": [
                    {
                        "rel": "approve",
                        "href": "https://www.sandbox.paypal.com/checkoutnow?token=PRIVATE",
                    }
                ],
                "payment_source": {"paypal": {"vault_id": "SECRET"}},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        gateway = RestPayPalGateway(make_settings(), client=client)
        first = await gateway.create_order(request())
        await gateway.create_order(request())
    assert len([c for c in calls if c.url.path == "/v1/oauth2/token"]) == 1
    assert first.amount_cents == 100
    assert "PRIVATE" not in str(first.raw) and "SECRET" not in str(first.raw)
    assert calls[1].headers["PayPal-Request-Id"] == calls[2].headers["PayPal-Request-Id"]


async def test_the_first_create_is_attempt_zero() -> None:
    """N9 starts the counter at 0, so the gateway must not demand a positive attempt."""

    async def handle(req):
        raise AssertionError("the payload is built locally, no request is expected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        gateway = RestPayPalGateway(make_settings(), client=client)
        gateway.order_payload(replace(request(), attempt=0))
        with pytest.raises(ValueError):
            gateway.order_payload(replace(request(), attempt=-1))


def test_idempotency_vectors_and_vault_operation_separation():
    assert (
        request_id("create:11111111-1111-4111-8111-111111111111:1")
        == "af91b897-da70-5be9-acc5-1603b4fbdd08"
    )
    assert request_id("vc:buyer:create") != request_id("vc:buyer:capture")


async def test_simulation_router_never_constructs_live_gateway(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("network-capable dependency constructed")

    monkeypatch.setattr("fairpool.wiring.RestPayPalGateway", fail)
    router = payment_router(make_settings(), simulated=True)
    assert router.name == "fake"
    assert router.label() == "SIMULATED"


async def test_void_get_guard_and_unknown_outcome_identity():
    calls = []

    async def handle(req):
        calls.append(req.url.path)
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "x", "expires_in": 32400})
        return httpx.Response(
            200,
            json={
                "id": "A",
                "status": "VOIDED",
                "amount": {"currency_code": "USD", "value": "1.00"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        gateway = RestPayPalGateway(make_settings(), client=client)
        await gateway.void_authorization("A")
    assert not any(p.endswith("/void") for p in calls)


async def test_breakdown_validation_and_fake_denial():
    from fairpool.fakes.payments import FakePayPalGateway

    fake = FakePayPalGateway(outcome="declined")
    result = await fake.charge_vault("buyer", "fake-token", 100, request().payee)
    assert result.capture_status == "DECLINED"
    assert await fake.charge_vault("buyer", "fake-token", 100, request().payee) == result
    with pytest.raises(PaymentError):
        await fake.charge_vault("buyer", "fake-token", 200, request().payee)
    gateway = RestPayPalGateway(make_settings(paypal_payload_level=2))
    with pytest.raises(ValueError):
        gateway.order_payload(replace(request(), payload_level=2, amount_cents=200))
    await gateway.close()


async def no_wait(*args):
    return None


async def test_401_refresh_and_transient_retries_preserve_operation_key(monkeypatch):
    monkeypatch.setattr("fairpool.adapters.paypal.gateway.asyncio.sleep", no_wait)
    tokens, posts, keys = [], [], []

    async def handle(req):
        if req.url.path == "/v1/oauth2/token":
            tokens.append(1)
            return httpx.Response(
                200, json={"access_token": f"TOKEN{len(tokens)}", "expires_in": 32400}
            )
        posts.append(1)
        keys.append(req.headers["PayPal-Request-Id"])
        if len(posts) == 1:
            return httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"})
        if len(posts) == 2:
            return httpx.Response(503, json={"name": "TEMPORARY"})
        return httpx.Response(
            201,
            json={
                "id": "O",
                "status": "CREATED",
                "intent": "AUTHORIZE",
                "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert (
            await RestPayPalGateway(make_settings(), client=client).create_order(request())
        ).id == "O"
    assert len(tokens) == 2 and len(posts) == 3 and len(set(keys)) == 1


async def test_retry_exhaustion_is_typed_unknown_and_bounded(monkeypatch):
    monkeypatch.setattr("fairpool.adapters.paypal.gateway.asyncio.sleep", no_wait)
    keys = []

    async def handle(req):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": 32400})
        keys.append(req.headers["PayPal-Request-Id"])
        raise httpx.ReadTimeout("unknown after send")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(PaymentError) as info:
            await RestPayPalGateway(make_settings(), client=client).create_order(request())
    assert info.value.category == "UNKNOWN" and len(keys) == 5 and len(set(keys)) == 1


async def test_vault_capture_unknown_preserves_known_order_identity(monkeypatch):
    monkeypatch.setattr("fairpool.adapters.paypal.gateway.asyncio.sleep", no_wait)
    keys = []

    async def handle(req):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": 32400})
        keys.append(req.headers["PayPal-Request-Id"])
        if req.url.path.endswith("/capture"):
            raise httpx.ReadTimeout("after send")
        return httpx.Response(
            201,
            json={
                "id": "KNOWN",
                "status": "APPROVED",
                "intent": "CAPTURE",
                "purchase_units": [{"amount": {"currency_code": "USD", "value": "1.00"}}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await RestPayPalGateway(
            make_settings(single_seller_email="seller@example.test"), client=client
        ).charge_vault("buyer", "fictional-token", 100, request().payee)
    assert result.order_id == "KNOWN" and result.error == "OUTCOME_UNKNOWN"
    assert keys[0] != keys[1] and len(set(keys[1:])) == 1


async def test_fake_drops_webhooks_and_lists_none():
    from fairpool.fakes.payments import FakePayPalGateway

    fake = FakePayPalGateway()
    assert await fake.verify_webhook({}, b"{}") is False
    assert await fake.list_webhooks() == []


async def test_fake_timeout_after_send_is_retrievable():
    from fairpool.fakes.payments import FakePayPalGateway

    fake = FakePayPalGateway(outcome="timeout_after_send")
    with pytest.raises(PaymentError):
        await fake.charge_vault("buyer", "fake-token", 100, request().payee)
    result = await fake.charge_vault("buyer", "fake-token", 100, request().payee)
    assert (await fake.get_order(result.order_id)).captures[0].id == result.capture_id
    assert (await fake.get_capture(result.capture_id)).status == "COMPLETED"


async def test_tracker_requires_exact_single_match():
    from fairpool.domain.payments import TrackerItem

    async def handle(req):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": 32400})
        if req.method == "POST":
            return httpx.Response(201, json={})
        return httpx.Response(
            200,
            json={
                "purchase_units": [
                    {
                        "shipping": {
                            "trackers": [
                                # The real read-back shape (C-18): an id built from the
                                # capture and the tracking number, and no other fields.
                                {"id": "C-T", "status": "SHIPPED", "notify_payer": False}
                            ]
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        results = await RestPayPalGateway(make_settings(), client=client).add_trackers(
            [TrackerItem("O", "C", "UPS", "T"), TrackerItem("O", "OTHER", "UPS", "T")]
        )
    assert [r.ok for r in results] == [True, False]


async def test_vault_charge_returns_the_provider_captured_amount_and_payee(monkeypatch):
    """T04A02/BO-24: the real adapter must hand BO-24 the provider's own values.

    The fake supplied them from the start, which is why the earlier suite passed while
    every real capture would have been rejected: BO-24 compares these against the award
    total and the stamped seller, and unset values fail that compare (I3).
    """
    monkeypatch.setattr("fairpool.adapters.paypal.gateway.asyncio.sleep", no_wait)

    async def handle(req):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "TOKEN", "expires_in": 32400})
        # The vault order completes itself, so this single payload carries both the
        # order and the capture the guard reads.
        return httpx.Response(
            201,
            json={
                "id": "ORDER-1",
                "status": "COMPLETED",
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "amount": {"currency_code": "USD", "value": "1.00"},
                        "payee": {"email_address": "seller@example.test"},
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAP-1",
                                    "status": "COMPLETED",
                                    "amount": {"currency_code": "USD", "value": "1.00"},
                                }
                            ]
                        },
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await RestPayPalGateway(
            make_settings(single_seller_email="seller@example.test"), client=client
        ).charge_vault("buyer", "fictional-token", 100, request().payee)

    assert result.capture_status == "COMPLETED"
    assert result.amount_cents == 100, "BO-24 needs the captured amount, not None"
    assert result.payee_email == "seller@example.test", "BO-24 needs the payee"
