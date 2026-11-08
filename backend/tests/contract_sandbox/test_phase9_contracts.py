"""C-11, C-12, C-13, C-17 and C-18: the interactive Sandbox contracts (T09A02).

Same discipline as the rest of this directory: real Sandbox calls, no mocks, no ``.env``
loading, USD 1.00. Each of these five needs a human to approve one order in the Sandbox
buyer account, so the whole module carries ``sandbox_interactive`` and skips unless the
operator exports ``FAIRPOOL_SANDBOX_APPROVAL=1`` (see ``conftest.py`` and ``README.md``).

The only thing the operator is ever shown is the order ID: ``AGENTS.md`` section 3
forbids printing a full approval URL or any token.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from fairpool.adapters.paypal.gateway import RestPayPalGateway, read_amount, resource_id
from fairpool.domain.payments import (
    PaymentError,
    PayPalCapture,
    TrackerItem,
)
from tests.contract_sandbox.support import (
    approved_order,
    completed_capture,
    one_dollar_request,
    wait_for_approval,
)

pytestmark = pytest.mark.sandbox_interactive


async def test_c11_void_replay_422_and_capture_after_void_rejected(
    gateway: RestPayPalGateway,
) -> None:
    """C-11 (S2): a void replays as 422, and a voided authorization can never be captured.

    The adapter's own void GETs before it acts, so a 422 is visible here only on the raw
    POST — which is exactly the path a lost response leaves behind (I9): the handler must
    GET and see VOIDED before it treats the 422 as already-done.
    """
    order_id = await approved_order(gateway, "c11")
    authorized = await gateway.authorize_order(order_id, request_key=f"c11:{order_id}")
    assert authorized.authorizations, "the authorize response carried no authorization"
    authorization = authorized.authorizations[0]

    await gateway.void_authorization(authorization.id)
    assert (await gateway.get_authorization(authorization.id)).status == "VOIDED"

    with pytest.raises(PaymentError) as replay:
        await gateway._request(
            "POST",
            f"/v2/payments/authorizations/{resource_id(authorization.id)}/void",
            body={},
        )
    # Two issues were recorded for this rejection (spike-results: UNPROCESSABLE_ENTITY,
    # O2 resolution: PREVIOUSLY_VOIDED); both are a terminal rejection, never a second void.
    assert replay.value.category == "TERMINAL"
    assert replay.value.code in {"PREVIOUSLY_VOIDED", "UNPROCESSABLE_ENTITY"}

    replayed = await gateway.get_authorization(authorization.id)
    assert replayed.status == "VOIDED" and replayed.amount_cents == 100

    with pytest.raises(PaymentError) as late_capture:
        await gateway.capture_authorization(
            authorization.id,
            amount_cents=100,
            request_key=f"cap-after-void:{authorization.id}",
        )
    assert late_capture.value.category == "TERMINAL"
    assert late_capture.value.code == "AUTHORIZATION_VOIDED"

    # The money is gone, so no capture exists to reconcile or refund.
    assert [c.id for c in (await gateway.get_order(order_id)).captures] == []


async def test_c12_payer_fields_and_payee_visible_on_get(
    gateway: RestPayPalGateway,
) -> None:
    """C-12 (V11, S2): GET carries the payer identity and the payee to check by email.

    V2: the payee is verified by email; ``payee.merchant_id`` is reported as PayPal sent
    it and is never required or inferred. The sanitized ``raw`` allowlist keeps payer
    identity out of anything FairPool persists.
    """
    order_id = await approved_order(gateway, "c12")
    order = await gateway.get_order(order_id)

    assert order.intent == "AUTHORIZE" and order.status == "APPROVED"
    assert order.currency == "USD" and order.amount_cents == 100
    assert order.payee_email is not None
    assert order.payee_email.lower() == gateway.settings.single_seller_email.lower()
    # V2: a missing merchant ID is reported as missing, not guessed at.
    assert order.payee_merchant_id is None or order.payee_merchant_id != ""
    print(f"\npayee email ok; merchant_id present={order.payee_merchant_id is not None}")

    # V11: payer fields are what make the FR-CK-05 country and payer-key checks possible.
    assert order.payer_id
    assert order.payer_country == "US"
    assert order.payer_country in gateway.settings.allowed_payer_countries

    # The allowlist in ``gateway.order`` persists no payer identity, source or URL.
    assert set(order.raw) <= {"id", "status", "intent", "debug_id", "captures"}


async def test_c13_india_or_inr_rejected(gateway: RestPayPalGateway) -> None:
    """C-13 (V12): the Sandbox rejects an INR order, and no INR can enter FairPool.

    V12 recorded ``UNSUPPORTED_PAYEE_CURRENCY`` for an India buyer and India seller and
    that INR is not in the Orders v2 currency list, so the currency leg is proven live
    here. The India-seller half needs an India seller account and stays the recorded
    fact; the app-side refusal of any non-US payer is ``ALLOWED_PAYER_COUNTRIES`` (FR-CK-05).
    """
    request = one_dollar_request("c13")
    body = gateway.order_payload(request)
    unit = body["purchase_units"][0]
    # No adapter path can express INR: the payload builder stamps USD every time (I3).
    assert unit["amount"]["currency_code"] == "USD"
    unit["amount"]["currency_code"] = "INR"

    with pytest.raises(PaymentError) as rejected:
        await gateway._request(
            "POST", "/v2/checkout/orders", body=body, key=f"c13:{request.buyer_order_id}"
        )
    assert rejected.value.category == "TERMINAL"
    assert "CURRENCY" in rejected.value.code.upper()

    # Reading an INR amount back is refused rather than rounded into USD cents (BD-14).
    with pytest.raises(PaymentError) as mismatch:
        read_amount({"currency_code": "INR", "value": "1.00"})
    assert mismatch.value.code == "CURRENCY_MISMATCH"
    assert gateway.settings.allowed_payer_countries == ("US",)


async def test_c17_sdk_popup_approval_then_server_authorize(
    gateway: RestPayPalGateway,
) -> None:
    """C-17 (S13, G17): the popup approves; the server authorizes and never captures.

    The popup itself cannot be driven from pytest — this repository adds no browser
    dependency for it (rule 20) — so the strongest preconditionable run is this one:
    the server creates the AUTHORIZE order, the owner approves it through the checkout
    page's SDK v6 popup, and every server obligation of ``paypal-adapter.md`` §12 is
    asserted from a fresh GET before and after the authorize. Owner step in ``README.md``.
    """
    created = await gateway.create_order(one_dollar_request("c17"))
    assert created.intent == "AUTHORIZE" and created.amount_cents == 100
    # FR-PP-06: the only approval URL the adapter may surface is the Sandbox checkout host.
    assert created.approve_url is not None
    assert created.approve_url.startswith(gateway.settings.paypal_checkout_base)
    order = await wait_for_approval(
        gateway,
        created.id,
        owner_step=(
            "Open the checkout page's SDK v6 popup (PAYPAL_APPROVAL_UI=sdk_popup) and "
            "approve it; the popup only posts the order ID to our server."
        ),
    )

    # FR-CK-05 from the server-side GET, which is the only evidence we accept: the
    # callback's fundingSource/payerId are hints (INT-7 obligation 6).
    assert order.intent == "AUTHORIZE" and order.status == "APPROVED"
    assert order.currency == "USD" and order.amount_cents == 100
    assert order.payee_email is not None
    assert order.payee_email.lower() == gateway.settings.single_seller_email.lower()
    assert order.payer_id
    assert order.payer_country in gateway.settings.allowed_payer_countries

    # INT-7 obligation 2: onApprove never authorizes and never captures.
    assert order.authorizations == [] and order.captures == []

    authorized = await gateway.authorize_order(order.id, request_key=f"c17:{order.id}")
    assert authorized.authorizations, "the server-side authorize returned no authorization"
    assert authorized.authorizations[0].status == "CREATED"
    assert authorized.captures == []
    # V8: the order's own status is never a payment signal, only the capture is (I4).
    assert (await gateway.get_order(order.id)).captures == []


async def test_c18_tracker_submitted_and_read_back(gateway: RestPayPalGateway) -> None:
    """C-18 (S12, G16): one tracker for a captured order, and a repeat stays one.

    ``add_trackers`` POSTs ``/track`` and then GETs the order, so each result is the
    read-back confirmation rather than the POST's own 201/200 (S12). The tracker id
    PayPal returns is ``<capture_id>-<tracking_number>``, which is what is matched.
    """
    order_id = await approved_order(gateway, "c18")
    authorized = await gateway.authorize_order(order_id, request_key=f"c18:{order_id}")
    authorization = authorized.authorizations[0]
    captured = await gateway.capture_authorization(
        authorization.id, amount_cents=100, request_key=f"cap:{authorization.id}"
    )
    capture: PayPalCapture = await completed_capture(gateway, captured)
    assert capture.status == "COMPLETED"  # PENDING is not paid (I4)

    tracking_number = f"FP{uuid4().hex[:12].upper()}"
    item = TrackerItem(order_id, capture.id, "USPS", tracking_number)

    first = await gateway.add_trackers([item])
    assert len(first) == 1
    assert (first[0].capture_id, first[0].ok, first[0].error) == (capture.id, True, None)

    # S12: resubmitting the same tracker returns 200 and the GET still shows exactly one.
    again = await gateway.add_trackers([item])
    assert again[0].ok and again[0].error is None, again
