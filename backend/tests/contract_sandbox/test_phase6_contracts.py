"""C-10, C-14 and C-15: the Phase 6 sandbox contracts, run against the real Sandbox.

Same discipline as ``test_gateway_contract.py`` and ``test_gateway_interactive.py``: no
mocks, no ``.env`` loading, and a skip when the credentials are not exported, so CI never
calls PayPal (AGENTS.md rule 18). These are the runs that carry IT-6's evidence, and two
of them need a human:

* **C-10** replays authorize, capture and refund against one approved order, so it needs
  the buyer approval at the Sandbox page (``sandbox_interactive``);
* **C-14** walks the payload ladder with real creates and GETs, which needs no approval;
* **C-15** verifies a signature over a delivery that actually arrived. S5 could only
  produce a *simulated* event, whose payload proves the plumbing and nothing else (P4),
  so this reads a captured delivery the operator saves to a file and skips with that
  instruction when it is absent.

S4 verified levels 1 and 2 and never level 3 (``docs/spike-results.md``), so C-14 stops at
the ceiling the switch is allowed to reach; level 3 stays unverified and unshipped.
"""

import base64
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from fairpool.adapters.paypal.gateway import RestPayPalGateway
from fairpool.config import Settings
from fairpool.domain.payments import CreateOrderRequest, Payee

pytestmark = pytest.mark.sandbox

#: Where the operator puts a captured delivery for C-15: the raw body bytes.
EVIDENCE_FILE = "FAIRPOOL_WEBHOOK_EVIDENCE_FILE"
SIG_EVIDENCE_FILE = "FAIRPOOL_WEBHOOK_HEADER_EVIDENCE_FILE"


def sandbox_settings(*, payload_level: int = 0) -> Settings:
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
        mock_toggles_enabled=False,
        paypal_payload_level=payload_level,
        paypal_webhook_id=os.environ.get("PAYPAL_WEBHOOK_ID", ""),
    )


def requires_credentials() -> None:
    if os.environ.get("CI") or not all(
        os.environ.get(key)
        for key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL")
    ):
        pytest.skip(
            "Explicit exported app-owning Sandbox seller credentials required; "
            "CI never calls PayPal"
        )


@pytest.fixture
async def gateway():
    requires_credentials()
    value = RestPayPalGateway(sandbox_settings())
    try:
        yield value
    finally:
        await value.close()


@pytest.fixture
async def ladder_gateway():
    """A gateway whose ceiling is the highest level S4 verified: 2."""
    requires_credentials()
    value = RestPayPalGateway(sandbox_settings(payload_level=2))
    try:
        yield value
    finally:
        await value.close()


def request_for(
    gateway: RestPayPalGateway, *, level: int, amount_cents: int = 100
) -> CreateOrderRequest:
    return CreateOrderRequest(
        buyer_order_id=str(uuid4()),
        attempt=1,
        amount_cents=amount_cents,
        breakdown={
            "item_cents": amount_cents - 25,
            "shipping_cents": 25,
            "tax_cents": 0,
        },
        description="Fictional Sandbox ladder item",
        reference_id="ladder",
        payee=Payee(gateway.settings.single_seller_email, None),
        return_url="https://example.test/return",
        cancel_url="https://example.test/cancel",
        shipping=None,
        payload_level=level,
        extra_headers={},
    )


async def test_c14_payload_ladder_levels(ladder_gateway) -> None:
    """C-14/S4: levels 0, 1 and 2 each create an order PayPal accepts, at the ceiling.

    The orders are left in place: S2's four old captures are already an owner action, and
    a created-but-unapproved order is not money.
    """
    assert ladder_gateway.settings.paypal_payload_level == 2

    for level in (0, 1, 2):
        created = await ladder_gateway.create_order(request_for(ladder_gateway, level=level))
        assert created.id
        read = await ladder_gateway.get_order(created.id)
        # V8: the order's own status is never a payment signal, only its identity is read.
        assert read.id == created.id

    # A level above the ceiling is refused before any call, so nothing unverified leaves.
    with pytest.raises(ValueError):
        ladder_gateway.order_payload(request_for(ladder_gateway, level=3))


async def test_c15_webhook_signature_over_a_captured_delivery(gateway) -> None:
    """C-15/S5: verify the signature over bytes that really arrived from PayPal.

    A simulated event (``POST /webhooks/{id}/event-types/{type}/simulate-event``) proves
    the listener is registered and is *mock* content (P4), so it is not accepted as
    evidence here. Save one delivered request's raw body and its headers from the
    listener, point the two environment variables at them, and re-run.
    """
    requires_credentials()
    body_path = os.environ.get(EVIDENCE_FILE)
    headers_path = os.environ.get(SIG_EVIDENCE_FILE)
    if not body_path or not headers_path:
        pytest.skip(
            "needs a real captured delivery: set "
            f"{EVIDENCE_FILE} (raw body bytes) and {SIG_EVIDENCE_FILE} (JSON of the "
            "paypal-transmission-* headers) from the listener log, then re-run"
        )
    if not gateway.settings.paypal_webhook_id:
        pytest.skip("PAYPAL_WEBHOOK_ID must be the registered listener id")
    raw = Path(body_path).read_bytes()
    headers = json.loads(Path(headers_path).read_text(encoding="utf-8"))

    assert await gateway.verify_webhook(headers, raw) is True
