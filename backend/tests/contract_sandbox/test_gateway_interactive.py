"""C-08 and C-09: the interactive Sandbox runs that need a human approval.

The only human step is approving one USD 1 AUTHORIZE order in the Sandbox buyer
account; the assertions are made here. This module never runs in CI, and it does
not print an approval URL: ``AGENTS.md`` section 3 forbids printing or logging a
full approval URL, so the operator approves the printed **order id** from the
Sandbox account.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import pytest

from fairpool.adapters.paypal.gateway import RestPayPalGateway
from fairpool.config import Settings
from fairpool.domain.payments import CreateOrderRequest, Payee, PayPalOrder

pytestmark = pytest.mark.sandbox_interactive

APPROVAL_TIMEOUT_S = 300
POLL_EVERY_S = 5


@pytest.fixture
async def gateway() -> AsyncIterator[RestPayPalGateway]:
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


def one_dollar_request(suffix: str) -> CreateOrderRequest:
    return CreateOrderRequest(
        buyer_order_id=str(uuid4()),
        attempt=1,
        amount_cents=100,
        breakdown={"item_cents": 100},
        description=f"FairPool contract {suffix}",
        reference_id=f"contract-{suffix}",
        payee=Payee(os.environ["SINGLE_SELLER_EMAIL"], None),
        return_url="https://example.test/return",
        cancel_url="https://example.test/cancel",
        shipping=None,
        payload_level=0,
        extra_headers={},
    )


async def approved_order(
    gateway: RestPayPalGateway,
    read: Callable[[str], Awaitable[PayPalOrder]],
    suffix: str,
) -> str:
    created = await gateway.create_order(one_dollar_request(suffix))
    print(
        f"\nApprove order {created.id} in the Sandbox buyer account within "
        f"{APPROVAL_TIMEOUT_S // 60} minutes, then leave this test running.",
        flush=True,
    )
    deadline = time.monotonic() + APPROVAL_TIMEOUT_S
    while time.monotonic() < deadline:
        order = await read(created.id)
        if order.status == "APPROVED":
            return created.id
        await asyncio.sleep(POLL_EVERY_S)
    pytest.fail("the Sandbox order was not approved before the timeout")


async def test_c08_authorize_then_void_reads_voided(gateway: RestPayPalGateway) -> None:
    """C-08 (V8): authorize, void, and a fresh GET shows VOIDED; a repeat void is safe."""
    order_id = await approved_order(gateway, gateway.get_order, "c08")
    authorized = await gateway.authorize_order(order_id, request_key=f"c08:{order_id}")
    assert authorized.authorizations, "the authorize response carried no authorization"
    authorization = authorized.authorizations[0]
    assert authorization.status == "CREATED"
    assert authorization.amount_cents == 100

    await gateway.void_authorization(authorization.id)
    after = await gateway.get_authorization(authorization.id)
    assert after.status == "VOIDED"
    # Void does not replay (P2): the adapter GETs first and treats an already-voided
    # authorization as done rather than raising.
    await gateway.void_authorization(authorization.id)


async def test_c09_authorize_capture_then_refund(gateway: RestPayPalGateway) -> None:
    """C-09 (G3, S2): authorize, capture, refund; the refund completes for the amount."""
    order_id = await approved_order(gateway, gateway.get_order, "c09")
    authorized = await gateway.authorize_order(order_id, request_key=f"c09:{order_id}")
    assert authorized.authorizations, "the authorize response carried no authorization"
    authorization = authorized.authorizations[0]
    capture = await gateway.capture_authorization(
        authorization.id, amount_cents=100, request_key=f"cap:{authorization.id}"
    )
    assert capture.status in {"COMPLETED", "PENDING"}

    refund = await gateway.refund_capture(
        capture.id, amount_cents=100, request_key=f"refund:{capture.id}:1"
    )
    assert refund.amount_cents == 100
    read = await gateway.get_refund(refund.id)
    assert read.status == "COMPLETED"
    assert read.amount_cents == 100
