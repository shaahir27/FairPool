"""Shared helpers for the Sandbox contract tests (C-01 to C-18, ``paypal-adapter.md`` §11).

Every helper here talks to the real Sandbox: ``AGENTS.md`` rule 18 forbids mocks in this
directory. Settings are built from explicitly exported variables and never from ``.env``,
so a run cannot silently pick up a different seller than the operator intended.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from uuid import uuid4

import pytest

from fairpool.adapters.paypal.gateway import RestPayPalGateway
from fairpool.config import Settings
from fairpool.domain.payments import CreateOrderRequest, Payee, PayPalCapture, PayPalOrder

#: A human needs this long to approve one order in the Sandbox buyer account.
APPROVAL_TIMEOUT_S = 300
POLL_EVERY_S = 5
#: A capture PayPal answers PENDING is polled this long before it is reported.
CAPTURE_TIMEOUT_S = 90

#: The three variables a provider run needs; values are never printed or logged (I14).
CREDENTIALS = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL")


def settings(*, payload_level: int = 0, mock_toggles_enabled: bool = False) -> Settings:
    """The exported credentials only, never ``.env``, and never a live host."""
    return Settings(
        _env_file=None,
        database_url="postgresql://unused@localhost/fairpool_test",
        secret_key="unused-contract-test",
        hmac_key="unused-contract-test",
        receipt_signing_key="unused-contract-test",
        address_encryption_key=base64.b64encode(b"A" * 32).decode(),
        paypal_client_id=os.environ["PAYPAL_CLIENT_ID"],
        paypal_client_secret=os.environ["PAYPAL_CLIENT_SECRET"],
        single_seller_email=os.environ["SINGLE_SELLER_EMAIL"],
        payment_mode="authorize_capture",
        ai_enabled=False,
        mock_toggles_enabled=mock_toggles_enabled,
        paypal_payload_level=payload_level,
    )


def requires_credentials() -> None:
    """Skip, never fail, when the operator has not exported the app-owning seller."""
    if os.environ.get("CI") or not all(os.environ.get(key) for key in CREDENTIALS):
        pytest.skip(
            "Explicit exported app-owning Sandbox seller credentials required; "
            "CI never calls PayPal"
        )


def one_dollar_request(suffix: str) -> CreateOrderRequest:
    """USD 1.00 at payload level 0, exactly the payload verified in V2 and V3."""
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


async def wait_for_approval(
    gateway: RestPayPalGateway, order_id: str, *, owner_step: str
) -> PayPalOrder:
    """Poll a GET until the buyer has approved, printing only the order ID.

    ``AGENTS.md`` section 3 forbids printing a full approval URL, so the operator acts
    on the printed order ID from the Sandbox account or the checkout page.
    """
    print(
        f"\n{owner_step} Order {order_id} must be approved within "
        f"{APPROVAL_TIMEOUT_S // 60} minutes; leave this test running.",
        flush=True,
    )
    deadline = time.monotonic() + APPROVAL_TIMEOUT_S
    while time.monotonic() < deadline:
        order = await gateway.get_order(order_id)
        if order.status == "APPROVED":
            return order
        await asyncio.sleep(POLL_EVERY_S)
    pytest.fail("the Sandbox order was not approved before the timeout")


async def approved_order(gateway: RestPayPalGateway, suffix: str) -> PayPalOrder:
    """Create a USD 1.00 AUTHORIZE order and return it once the buyer approved it."""
    created = await gateway.create_order(one_dollar_request(suffix))
    step = "Approve the order at its Sandbox checkout page (redirect approval path, V8)."
    return await wait_for_approval(gateway, created.id, owner_step=step)


async def completed_capture(gateway: RestPayPalGateway, capture: PayPalCapture) -> PayPalCapture:
    """A capture PayPal answered PENDING is polled; PENDING never counts as paid (I4)."""
    deadline = time.monotonic() + CAPTURE_TIMEOUT_S
    current = capture
    while current.status == "PENDING" and time.monotonic() < deadline:
        await asyncio.sleep(POLL_EVERY_S)
        current = await gateway.get_capture(capture.id)
    return current
