"""Pydantic payloads for docs/contracts/api.md (T01B01).

Request models forbid unknown fields; response models mirror the documented
shapes. Money is integer cents and IDs are UUIDs. Handlers are stubs in PH1;
these models are the contract the later handlers and the frontend share.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from fairpool.domain.pool_config import PoolInput


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --- common -----------------------------------------------------------------
class ErrorBody(ResponseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorEnvelope(ResponseModel):
    error: ErrorBody


class HealthResponse(ResponseModel):
    status: str


class ReadyResponse(ResponseModel):
    status: str
    checks: dict[str, str]


# --- auth and delegations ---------------------------------------------------
class RegisterRequest(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)


class RegisterResponse(ResponseModel):
    user_id: UUID
    email: str


class LoginRequest(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(ResponseModel):
    user_id: UUID
    csrf_token: str


class MeResponse(ResponseModel):
    user_id: UUID
    email: str
    display_name: str
    role: str
    paypal_linked: bool
    unread_notifications: int


class DelegationScope(StrictModel):
    pool_ids: list[UUID] = Field(default_factory=list)
    category: str | None = None


class DelegationCreateRequest(StrictModel):
    scope: DelegationScope
    max_cap_cents: int = Field(ge=0)
    expires_at: datetime


class DelegationView(ResponseModel):
    id: UUID
    scope: dict[str, Any]
    max_cap_cents: int
    expires_at: datetime
    revoked_at: datetime | None = None


class DelegationCreated(DelegationView):
    token: str


class DelegationList(ResponseModel):
    items: list[DelegationView]


class PayPalLoginStartResponse(ResponseModel):
    authorize_url: str


class PayPalLoginCallbackResponse(ResponseModel):
    paypal_linked: bool


# --- catalog and pools ------------------------------------------------------
class PoolSummary(ResponseModel):
    pool_id: UUID
    title: str
    status: str
    mode: str
    product_key: str
    variant: str | None = None
    condition: str
    zone_ids: list[str]
    seats: int
    min_seats: int
    close_at: datetime | None = None


class PoolDetail(PoolSummary):
    template: dict[str, Any]
    lot_plan: list[dict[str, Any]]
    timeline: dict[str, Any]
    rules_hash: str | None = None


class RulesDocument(ResponseModel):
    v: int = 1
    pool_id: UUID
    rule_version: str
    template: dict[str, Any]
    lot_plan: list[dict[str, Any]]
    timeline: dict[str, Any]
    require_paypal_link: bool
    allocation: str
    bid_ranking: str
    refill: dict[str, Any]
    beacon: dict[str, Any]
    disclosures: dict[str, Any]


class RulesResponse(ResponseModel):
    rules_document: RulesDocument
    rules_hash: str


class PoolEvent(ResponseModel):
    event: str
    data: dict[str, Any]


# --- intake -----------------------------------------------------------------
class IntakeMessageRequest(StrictModel):
    session_id: UUID | None = None
    pool_id: UUID | None = None
    message: str = Field(min_length=1, max_length=2000)


class ConfirmationPool(ResponseModel):
    id: UUID
    title: str
    variant: str | None = None
    condition: str
    latest_delivery: str


class ConfirmationDelivery(ResponseModel):
    zone_id: str
    region: str


class ConfirmationNotices(ResponseModel):
    no_charge: str
    lots_may_differ: str


class ConfirmationCard(ResponseModel):
    proposal_id: UUID
    pool: ConfirmationPool
    delivery: ConfirmationDelivery
    required_by: str
    max_total_cents: int
    firm: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    notices: ConfirmationNotices


class IntakeMessageResponse(ResponseModel):
    session_id: UUID
    status: Literal["NEEDS_CLARIFICATION", "READY_TO_CONFIRM", "NO_MATCH"]
    clarifying_question: str | None = None
    confirmation_card: ConfirmationCard | None = None


class IntakeConfirmRequest(StrictModel):
    proposal_id: UUID


class IntakeConfirmResponse(ResponseModel):
    confirmed_request_id: UUID
    canonical_request: dict[str, Any]


class ManualIntakeRequest(StrictModel):
    pool_id: UUID
    delivery: dict[str, Any]
    required_by: str
    max_total_cents: int = Field(ge=0)
    firm: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


# --- entries ----------------------------------------------------------------
class EntryCreateRequest(StrictModel):
    confirmed_request_id: UUID


class ReceiptPayload(ResponseModel):
    commitment: str
    entry_id: UUID
    pool_id: UUID
    received_at: datetime
    v: Literal[1] = 1


class EntryReceipt(ResponseModel):
    payload: ReceiptPayload
    salt_hex: str
    request_hash: str
    signature: str


class EntryCreateResponse(ResponseModel):
    entry_id: UUID
    already_entered: bool
    pool_status: str
    receipt: EntryReceipt


class AllocationView(ResponseModel):
    status: str
    zone_id: str
    rank: int
    lot_id: UUID | None = None
    waitlist_position: int | None = None


class OfferRef(ResponseModel):
    buyer_order_id: UUID
    status: str
    offer_expires_at: datetime


class EntryStatusResponse(ResponseModel):
    entry_id: UUID
    entry_status: str
    allocation: AllocationView | None = None
    offer: OfferRef | None = None
    vault_status: str | None = None
    vault_label: str | None = None


class VaultStartRequest(StrictModel):
    consent_version: str
    cap_cents: int = Field(ge=0)


class VaultStartResponse(ResponseModel):
    approve_url: str
    consent_version: str


class MeEntry(ResponseModel):
    entry_id: UUID
    pool_id: UUID
    entry_status: str
    allocation: AllocationView | None = None
    offer: OfferRef | None = None


class MeEntryList(ResponseModel):
    items: list[MeEntry]


# --- public audit -----------------------------------------------------------
class AuditAward(ResponseModel):
    merchant_display_name: str
    item_cents: int
    tier_index: int
    award_hash: str
    valid_until: datetime


class AuditLot(ResponseModel):
    lot_id: UUID
    zone_id: str
    lot_order: int
    seats: int
    status: str
    rank_range: list[int]
    award: AuditAward | None = None


class AuditCheckpoint(ResponseModel):
    action: str
    hash: str


class PublicAuditResponse(ResponseModel):
    rules_hash: str
    rules_document: dict[str, Any]
    pool_status: str
    entries_root: str | None = None
    entries_count: int | None = None
    commitments: list[str] = Field(default_factory=list)
    beacon: dict[str, Any] | None = None
    seed_hex: str | None = None
    seed_is_demo: bool = False
    lots: list[AuditLot] = Field(default_factory=list)
    audit_checkpoints: list[AuditCheckpoint] = Field(default_factory=list)


class PublicKeysResponse(ResponseModel):
    algorithm: str = "ed25519"
    public_key: str


# --- merchant console -------------------------------------------------------
class MerchantProfileRequest(StrictModel):
    display_name: str = Field(min_length=1, max_length=120)
    payee_email: str | None = None
    paypal_merchant_id: str | None = None
    attestations: dict[str, Any] = Field(default_factory=dict)


class MerchantProfileResponse(ResponseModel):
    merchant_id: UUID
    display_name: str
    onboarding_status: str
    attestations: dict[str, Any]


class MerchantLotSummary(ResponseModel):
    lot_id: UUID
    pool_id: UUID
    zone_id: str
    seats: int
    min_seats: int
    status: str
    bid_close_at: datetime
    product_key: str
    variant: str | None = None
    condition: str
    delivery_sla_days: int
    min_return_days: int


class QuoteRequest(StrictModel):
    quote_text: str = Field(min_length=1, max_length=20000)


class QuoteAmbiguity(ResponseModel):
    field: str
    question: str


class QuoteResponse(ResponseModel):
    bid_id: UUID
    revision: int
    status: str
    proposed_fields: dict[str, Any]
    ambiguities: list[QuoteAmbiguity] = Field(default_factory=list)


class BidRequest(StrictModel):
    structured: dict[str, Any]
    quote_text: str | None = None
    notes: str | None = None


class BidReceipt(ResponseModel):
    hash: str
    signature: str


class BidResponse(ResponseModel):
    bid_id: UUID
    revision: int
    status: str
    receipt: BidReceipt


class BidConfirmRequest(StrictModel):
    revision: int = Field(ge=0)


class BidConfirmResponse(ResponseModel):
    bid_id: UUID
    revision: int
    status: str


class BidFlagView(ResponseModel):
    code: str
    severity: str
    field: str
    evidence: str


class BidView(ResponseModel):
    bid_id: UUID
    lot_id: UUID
    status: str
    current_revision: int
    structured: dict[str, Any] | None = None
    flags: list[BidFlagView] = Field(default_factory=list)
    reject_reason: str | None = None


class MerchantBidList(ResponseModel):
    items: list[BidView]


class MerchantEvent(ResponseModel):
    event: str
    data: dict[str, Any]


class ApiKeyCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1)


class ApiKeyCreated(ResponseModel):
    id: UUID
    name: str
    key: str
    scopes: list[str]


class ApiKeyView(ResponseModel):
    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyList(ResponseModel):
    items: list[ApiKeyView]


# --- offers and checkout ----------------------------------------------------
class MerchantDisplay(ResponseModel):
    display_name: str


class ProductDisplay(ResponseModel):
    title: str
    variant: str | None = None
    condition: str
    bundle_contents: list[str]


class OfferTerms(ResponseModel):
    delivery_sla_days: int
    returns_days: int


class OfferTotals(ResponseModel):
    item_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int
    cap_cents: int


class OfferNotices(ResponseModel):
    hold: str
    lots_may_differ: str
    fallback: str | None = None


class OfferResponse(ResponseModel):
    buyer_order_id: UUID
    status: str
    merchant: MerchantDisplay
    product: ProductDisplay
    terms: OfferTerms
    totals: OfferTotals
    offer_expires_at: datetime
    notices: OfferNotices


class ShippingAddress(StrictModel):
    name: str
    line1: str
    line2: str | None = None
    city: str
    region: str
    postal_code: str
    country_code: str


class ContinueRequest(StrictModel):
    shipping: ShippingAddress


class ContinueResponse(ResponseModel):
    paypal_order_id: str
    approve_url: str
    approval_ui: Literal["sdk_popup", "redirect"]


class OrderPayPalState(ResponseModel):
    authorization_status: str | None = None
    capture_status: str | None = None
    refund_status: str | None = None


class OrderHistoryItem(ResponseModel):
    status: str
    at: datetime


class OrderStatusResponse(ResponseModel):
    buyer_order_id: UUID
    status: str
    lot_status: str
    total_cents: int
    history: list[OrderHistoryItem] = Field(default_factory=list)
    paypal: OrderPayPalState
    labels: list[str] = Field(default_factory=list)


class CheckoutConfigResponse(ResponseModel):
    approval_ui: Literal["sdk_popup", "redirect"]
    sdk_auth: Literal["client_id", "client_token"]
    client_id: str
    sdk_url: str
    components: list[str]
    page_type: str
    currency: str
    labels: list[str]


class ClientTokenResponse(ResponseModel):
    client_token: str
    expires_in: int


class ApprovedRequest(StrictModel):
    paypal_order_id: str


class ApprovedResponse(ResponseModel):
    buyer_order_id: UUID
    status: Literal["APPROVED", "REJECTED", "EXPIRED"]
    reason: str | None = None


class CancelledRequest(StrictModel):
    paypal_order_id: str | None = None


class MeOrder(ResponseModel):
    buyer_order_id: UUID
    lot_id: UUID
    status: str
    total_cents: int
    receipt: dict[str, Any] | None = None


class MeOrderList(ResponseModel):
    items: list[MeOrder]


# --- admin ------------------------------------------------------------------
class PoolCreateRequest(PoolInput):
    pass


class AdminPoolResponse(ResponseModel):
    pool_id: UUID
    status: str


class ForceAwardRequest(StrictModel):
    merchant_id: UUID
    item_cents: int = Field(ge=0)
    tier_index: int = Field(ge=0)
    moq: int = Field(ge=1)
    valid_minutes: int = Field(ge=1)


class AdminForceAwardResponse(ResponseModel):
    lot_id: UUID
    award_id: UUID


class MockToggleRequest(StrictModel):
    kind: Literal["paypal_mock_response", "force_capture_failure", "delay_webhooks"]
    value: str | None = None
    ttl_s: int = Field(default=300, ge=1)


class SimRunRequest(StrictModel):
    entries: int = Field(ge=1)
    merchants: int = Field(ge=1)
    seed: int


class SimRunResponse(ResponseModel):
    sim_run_id: UUID
    pool_id: UUID


class AdminLotView(ResponseModel):
    lot_id: UUID
    pool_id: UUID
    status: str
    seats: int
    min_seats: int
    award_id: UUID | None = None
    payment_router: str | None = None
    payment_mode: str | None = None


class AuditExportResponse(ResponseModel):
    checkpoints: list[AuditCheckpoint]


# --- agent API --------------------------------------------------------------
class AgentPool(ResponseModel):
    pool_id: UUID
    title: str
    status: str
    template: dict[str, Any]
    timeline: dict[str, Any]
    rules_hash: str | None = None


class AgentRequest(StrictModel):
    delivery: dict[str, Any]
    required_by: str
    max_total_cents: int | None = Field(default=None, ge=0)
    max_total_usd: str | None = None
    firm: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


class AgentEntryCreateRequest(StrictModel):
    pool_id: UUID
    request: AgentRequest
    idempotency_key: str | None = None


class AgentEntryResponse(ResponseModel):
    entry_id: UUID
    pool_id: UUID
    entry_status: str
    allocation: AllocationView | None = None
    offer: OfferRef | None = None
    checkout_url: str | None = None
    checkout_hint: str = "A human approves payment on PayPal; this API cannot pay."


class AgentEntryList(ResponseModel):
    items: list[AgentEntryResponse]


class AgentWithdrawRequest(StrictModel):
    entry_id: UUID


class AgentWithdrawResponse(ResponseModel):
    entry_id: UUID
    entry_status: str


# --- fulfillment ------------------------------------------------------------
class LotProgress(ResponseModel):
    lot_id: UUID
    status: str
    seats: int
    moq: int
    holds_placed: int
    captures_completed: int
    refills_offered: int
    counts: dict[str, int]
    fund_deadline_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)


class FulfillmentRow(ResponseModel):
    buyer_order_id: UUID
    name: str
    line1: str
    line2: str | None = None
    city: str
    region: str
    postal_code: str
    country_code: str
    item_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int
    paypal_capture_id: str


class ShipmentInput(StrictModel):
    buyer_order_id: UUID
    carrier: str
    tracking_number: str


class ShipmentsRequest(StrictModel):
    shipments: list[ShipmentInput] = Field(min_length=1, max_length=100)


class ShipmentResult(ResponseModel):
    buyer_order_id: UUID
    status: Literal["RECORDED", "INVALID"]
    paypal_tracker_status: str | None = None


class ShipmentsResponse(ResponseModel):
    accepted: int
    rows: list[ShipmentResult]


class ManifestItem(ResponseModel):
    paypal_order_id: str
    paypal_capture_id: str
    amount_cents: int
    captured_at: datetime


class VerificationManifest(ResponseModel):
    lot_id: UUID
    currency: str = "USD"
    funded: bool
    expected_captured_total_cents: int
    items: list[ManifestItem]
    how_to_verify: str


class VerificationItem(ResponseModel):
    paypal_order_id: str
    paypal_capture_id: str
    expected_amount_cents: int
    paypal_capture_status: str
    paypal_amount_cents: int
    match: bool


class VerificationResponse(ResponseModel):
    lot_id: UUID
    checked_at: datetime
    matched: int
    total: int
    all_match: bool
    expected_captured_total_cents: int
    paypal_captured_total_cents: int
    items: list[VerificationItem]


# --- merchant agent API -----------------------------------------------------
class MerchantApiBidRequest(StrictModel):
    structured: dict[str, Any]
    notes: str | None = None
    confirmed: Literal[True]


class WebhookAck(ResponseModel):
    pass
