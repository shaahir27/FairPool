"""C-01 to C-07: real USD1 Sandbox calls; no mocks and no .env loading."""

import os
from dataclasses import replace
from uuid import uuid4

import pytest

from fairpool.adapters.paypal.gateway import RestPayPalGateway
from fairpool.config import Settings
from fairpool.domain.payments import CreateOrderRequest, Payee, PaymentError

pytestmark = pytest.mark.sandbox


@pytest.fixture
async def gateway():
    if os.environ.get("CI") or not all(
        os.environ.get(k)
        for k in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL")
    ):
        pytest.skip(
            "Explicit exported app-owning Sandbox seller credentials required; "
            "CI never calls PayPal"
        )
    settings = Settings(
        _env_file=None,
        database_url="postgresql://unused@localhost/fairpool_test",
        secret_key="unused-contract-test",
        hmac_key="unused-contract-test",
        receipt_signing_key="unused-contract-test",
        address_encryption_key="unused-contract-test",
        paypal_client_id=os.environ["PAYPAL_CLIENT_ID"],
        paypal_client_secret=os.environ["PAYPAL_CLIENT_SECRET"],
        single_seller_email=os.environ["SINGLE_SELLER_EMAIL"],
        payment_mode="authorize_capture",
        ai_enabled=False,
        mock_toggles_enabled=True,
        paypal_payload_level=0,
    )
    value = RestPayPalGateway(settings)
    try:
        yield value
    finally:
        await value.close()


def order_request(gateway):
    return CreateOrderRequest(
        str(uuid4()),
        1,
        100,
        {"item_cents": 100, "shipping_cents": 0, "tax_cents": 0},
        "Fictional Sandbox contract item",
        "contract",
        Payee(gateway.settings.single_seller_email, None),
        "https://example.test/return",
        "https://example.test/cancel",
        None,
        0,
        {},
    )


async def test_c01_token(gateway):
    assert bool(await gateway._token())


async def test_c02_create_and_get(gateway):
    result = await gateway.create_order(order_request(gateway))
    assert result.id and result.status == "CREATED" and result.amount_cents == 100
    assert (await gateway.get_order(result.id)).id == result.id


async def test_c03_create_replay(gateway):
    req = order_request(gateway)
    assert (await gateway.create_order(req)).id == (await gateway.create_order(req)).id


async def test_c04_before_approval_waits(gateway):
    req = order_request(gateway)
    result = await gateway.create_order(req)
    with pytest.raises(PaymentError) as info:
        await gateway._request(
            "POST",
            f"/v2/checkout/orders/{result.id}/authorize",
            body={},
            key=f"contract:{req.buyer_order_id}:authorize",
        )
    assert info.value.category == "WAIT" and info.value.code == "ORDER_NOT_APPROVED"


async def test_c05_distinct_orders(gateway):
    assert (await gateway.create_order(order_request(gateway))).id != (
        await gateway.create_order(order_request(gateway))
    ).id


async def test_c06_verified_mock_duplicate_invoice(gateway):
    req = replace(
        order_request(gateway),
        extra_headers={"PayPal-Mock-Response": '{"mock_application_codes":"DUPLICATE_INVOICE_ID"}'},
    )
    with pytest.raises(PaymentError) as info:
        await gateway.create_order(req)
    assert info.value.category == "BUG" and info.value.code == "DUPLICATE_INVOICE_ID"


async def test_c07_event_types(gateway):
    events = await gateway.list_webhook_event_types()
    assert "PAYMENT.CAPTURE.COMPLETED" in {x["name"] for x in events}
