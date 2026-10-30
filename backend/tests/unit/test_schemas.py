"""T01B01: documented payload models exist and validate key shapes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from fairpool.api import schemas

MODEL_NAMES = [
    "ErrorEnvelope",
    "HealthResponse",
    "ReadyResponse",
    "RegisterRequest",
    "LoginRequest",
    "MeResponse",
    "DelegationCreateRequest",
    "DelegationCreated",
    "PayPalLoginStartResponse",
    "PoolSummary",
    "PoolDetail",
    "RulesDocument",
    "IntakeMessageRequest",
    "ConfirmationCard",
    "IntakeMessageResponse",
    "EntryCreateRequest",
    "EntryReceipt",
    "EntryCreateResponse",
    "EntryStatusResponse",
    "VaultStartRequest",
    "VaultStartResponse",
    "MeEntryList",
    "PublicAuditResponse",
    "PublicKeysResponse",
    "MerchantProfileRequest",
    "MerchantLotSummary",
    "QuoteRequest",
    "QuoteResponse",
    "BidRequest",
    "BidResponse",
    "BidConfirmRequest",
    "BidView",
    "ApiKeyCreateRequest",
    "ApiKeyCreated",
    "OfferResponse",
    "OfferTotals",
    "OfferNotices",
    "ContinueRequest",
    "ContinueResponse",
    "OrderStatusResponse",
    "CheckoutConfigResponse",
    "ClientTokenResponse",
    "ApprovedResponse",
    "MeOrderList",
    "PoolCreateRequest",
    "ForceAwardRequest",
    "MockToggleRequest",
    "SimRunRequest",
    "AdminLotView",
    "AgentPool",
    "AgentEntryCreateRequest",
    "AgentEntryResponse",
    "AgentEntryList",
    "AgentWithdrawRequest",
    "LotProgress",
    "FulfillmentRow",
    "ShipmentsRequest",
    "ShipmentsResponse",
    "VerificationManifest",
    "VerificationResponse",
    "MerchantApiBidRequest",
    "WebhookAck",
]


def test_every_documented_payload_has_a_model():
    missing = [name for name in MODEL_NAMES if not hasattr(schemas, name)]
    assert not missing, missing


def test_requests_reject_unknown_fields():
    with pytest.raises(ValidationError):
        schemas.RegisterRequest(
            email="buyer@example.test",
            password="long-enough",
            display_name="Buyer",
            unexpected=True,  # type: ignore[call-arg]
        )


def test_entry_receipt_matches_the_documented_example():
    entry_id = uuid4()
    pool_id = uuid4()
    response = schemas.EntryCreateResponse.model_validate(
        {
            "entry_id": str(entry_id),
            "already_entered": False,
            "pool_status": "OPEN",
            "receipt": {
                "payload": {
                    "commitment": "a" * 64,
                    "entry_id": str(entry_id),
                    "pool_id": str(pool_id),
                    "received_at": "2026-11-02T10:00:01.123456Z",
                    "v": 1,
                },
                "salt_hex": "b" * 64,
                "request_hash": "c" * 64,
                "signature": "base64url",
            },
        }
    )
    assert response.entry_id == entry_id
    assert response.receipt.payload.pool_id == pool_id


def test_offer_totals_and_notices():
    offer = schemas.OfferResponse(
        buyer_order_id=uuid4(),
        status="OFFERED",
        merchant=schemas.MerchantDisplay(display_name="Demo Merchant One"),
        product=schemas.ProductDisplay(
            title="27-inch 4K monitor",
            variant="black",
            condition="NEW",
            bundle_contents=["monitor", "stand", "power cable"],
        ),
        terms=schemas.OfferTerms(delivery_sla_days=5, returns_days=30),
        totals=schemas.OfferTotals(
            item_cents=47000,
            shipping_cents=1500,
            tax_cents=4113,
            total_cents=52613,
            cap_cents=55000,
        ),
        offer_expires_at="2026-11-02T11:00:00Z",
        notices=schemas.OfferNotices(
            hold="PayPal places a hold only after you approve.",
            lots_may_differ="Separate lots may differ.",
            fallback="Sandbox demo: one test seller stands in for the winning merchant.",
        ),
    )
    assert offer.totals.total_cents == 52613
    assert offer.notices.fallback is not None


def test_merchant_api_bid_must_be_confirmed():
    schemas.MerchantApiBidRequest(structured={"v": 1}, confirmed=True)
    with pytest.raises(ValidationError):
        schemas.MerchantApiBidRequest(structured={"v": 1}, confirmed=False)


def test_shipments_are_bounded_to_one_hundred_rows():
    row = {
        "buyer_order_id": str(uuid4()),
        "carrier": "UPS",
        "tracking_number": "1Z",
    }
    schemas.ShipmentsRequest(shipments=[row] * 100)
    with pytest.raises(ValidationError):
        schemas.ShipmentsRequest(shipments=[row] * 101)


def test_mock_toggle_kind_and_uuid_validation():
    with pytest.raises(ValidationError):
        schemas.MockToggleRequest(kind="not-a-toggle")
    with pytest.raises(ValidationError):
        schemas.EntryCreateRequest(confirmed_request_id="not-a-uuid")
