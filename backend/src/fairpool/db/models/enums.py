"""PostgreSQL enum types from docs/contracts/db-schema.md (T01A01).

The database types are created once by migration 0001; models set
``create_type=False`` so importing the metadata never emits DDL.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy.dialects.postgresql import ENUM


class PoolStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SEEDED = "SEEDED"
    ALLOCATED = "ALLOCATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LotStatus(StrEnum):
    PLANNED = "PLANNED"
    BIDDING = "BIDDING"
    BID_CLOSED = "BID_CLOSED"
    AWARDED = "AWARDED"
    CHECKOUT_OPEN = "CHECKOUT_OPEN"
    FUNDING = "FUNDING"
    FUNDED = "FUNDED"
    CLOSED = "CLOSED"
    FAILING = "FAILING"
    FAILED_CLOSED = "FAILED_CLOSED"
    CANCELLED = "CANCELLED"


class BuyerOrderStatus(StrEnum):
    OFFERED = "OFFERED"
    ORDER_CREATED = "ORDER_CREATED"
    APPROVED = "APPROVED"
    AUTHORIZING = "AUTHORIZING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURING = "CAPTURING"
    CAPTURE_PENDING = "CAPTURE_PENDING"
    CAPTURED = "CAPTURED"
    REFUNDING = "REFUNDING"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    AUTH_FAILED = "AUTH_FAILED"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"
    DECLINED = "DECLINED"


class BidStatus(StrEnum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"
    ELIGIBLE = "ELIGIBLE"
    AWARDED = "AWARDED"
    LOST = "LOST"


class EntryStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AllocationStatus(StrEnum):
    SEATED = "SEATED"
    WAITLISTED = "WAITLISTED"
    PRICED_OUT = "PRICED_OUT"


class UserRole(StrEnum):
    buyer = "buyer"
    merchant = "merchant"
    admin = "admin"


class PoolMode(StrEnum):
    LIVE_SANDBOX = "LIVE_SANDBOX"
    SIMULATION = "SIMULATION"


class SubmittedVia(StrEnum):
    human = "human"
    agent = "agent"


class ItemCondition(StrEnum):
    NEW = "NEW"
    REFURBISHED = "REFURBISHED"
    OPEN_BOX = "OPEN_BOX"


class PaymentRouter(StrEnum):
    fake = "fake"
    single_seller = "single_seller"
    payee_email = "payee_email"
    platform = "platform"


class PaymentMode(StrEnum):
    authorize_capture = "authorize_capture"
    capture_only = "capture_only"
    vault_charge = "vault_charge"


class VaultStatus(StrEnum):
    SETUP_PENDING = "SETUP_PENDING"
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"
    FAILED = "FAILED"


class MerchantOnboarding(StrEnum):
    NONE = "NONE"
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    DEMO = "DEMO"


class FlagSeverity(StrEnum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


class FlagCode(StrEnum):
    BUNDLE_MISMATCH = "BUNDLE_MISMATCH"
    CONDITION_MISMATCH = "CONDITION_MISMATCH"
    DELIVERY_CONFLICT = "DELIVERY_CONFLICT"
    HIDDEN_FEE = "HIDDEN_FEE"
    QUANTITY_CONFLICT = "QUANTITY_CONFLICT"
    RETURN_CONFLICT = "RETURN_CONFLICT"
    LOW_SIMILARITY = "LOW_SIMILARITY"
    OTHER = "OTHER"


class LedgerKind(StrEnum):
    AUTH_CREATED = "AUTH_CREATED"
    AUTH_VOIDED = "AUTH_VOIDED"
    CAPTURE_COMPLETED = "CAPTURE_COMPLETED"
    CAPTURE_PENDING = "CAPTURE_PENDING"
    CAPTURE_DECLINED = "CAPTURE_DECLINED"
    REFUND_COMPLETED = "REFUND_COMPLETED"
    REFUND_PENDING = "REFUND_PENDING"


class LedgerSource(StrEnum):
    api = "api"
    webhook = "webhook"
    reconciler = "reconciler"


class WebhookStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    DEAD_LETTER = "DEAD_LETTER"
    REJECTED = "REJECTED"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class AiTask(StrEnum):
    INTAKE = "INTAKE"
    QUOTE = "QUOTE"
    RECONCILE = "RECONCILE"
    SIM_TEXT = "SIM_TEXT"


def pg_enum(enum_cls: type[StrEnum], name: str) -> ENUM:
    """A metadata-only reference to an enum type created by migration 0001."""
    return ENUM(
        enum_cls,
        name=name,
        create_type=False,
        values_callable=lambda cls: [member.value for member in cls],
    )


ENUM_TYPES: dict[str, type[StrEnum]] = {
    "pool_status": PoolStatus,
    "lot_status": LotStatus,
    "buyer_order_status": BuyerOrderStatus,
    "bid_status": BidStatus,
    "entry_status": EntryStatus,
    "allocation_status": AllocationStatus,
    "user_role": UserRole,
    "pool_mode": PoolMode,
    "submitted_via": SubmittedVia,
    "item_condition": ItemCondition,
    "payment_router": PaymentRouter,
    "payment_mode": PaymentMode,
    "vault_status": VaultStatus,
    "merchant_onboarding": MerchantOnboarding,
    "flag_severity": FlagSeverity,
    "flag_code": FlagCode,
    "ledger_kind": LedgerKind,
    "ledger_source": LedgerSource,
    "webhook_status": WebhookStatus,
    "job_status": JobStatus,
    "ai_task": AiTask,
}
