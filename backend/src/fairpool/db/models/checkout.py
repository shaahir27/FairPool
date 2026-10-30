"""Checkout, PayPal mirrors, ledger and webhooks (T01A01; db-schema.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from fairpool.db.base import Base

from .enums import (
    BuyerOrderStatus,
    LedgerKind,
    LedgerSource,
    WebhookStatus,
    pg_enum,
)

_ACTIVE_ORDER_STATUSES = (
    "'OFFERED','ORDER_CREATED','APPROVED','AUTHORIZING','AUTHORIZED',"
    "'CAPTURING','CAPTURE_PENDING','CAPTURED','REFUNDING'"
)


class BuyerOrder(Base):
    __tablename__ = "buyer_orders"
    __table_args__ = (
        Index(
            "idx_one_active_order_per_entry",
            "entry_id",
            unique=True,
            postgresql_where=text(f"status IN ({_ACTIVE_ORDER_STATUSES})"),
        ),
        Index("ix_buyer_orders_lot_status", "lot_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lots.id"), nullable=False
    )
    entry_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pool_entries.id"), nullable=False
    )
    status: Mapped[BuyerOrderStatus] = mapped_column(
        pg_enum(BuyerOrderStatus, "buyer_order_status"),
        nullable=False,
        server_default=text("'OFFERED'::buyer_order_status"),
    )
    current_attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    offer_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    shipping_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    seat_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    void_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PayPalOrder(Base):
    __tablename__ = "paypal_orders"
    __table_args__ = (
        UniqueConstraint("buyer_order_id", "attempt", name="uq_paypal_orders_order_attempt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    buyer_order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buyer_orders.id"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    paypal_order_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payee_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    payee_merchant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payer_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    payer_country: Mapped[str | None] = mapped_column(Text, nullable=True)
    approve_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_debug_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PayPalAuthorization(Base):
    __tablename__ = "paypal_authorizations"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    buyer_order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buyer_orders.id"), nullable=False
    )
    paypal_order_id: Mapped[str] = mapped_column(
        Text, ForeignKey("paypal_orders.paypal_order_id"), nullable=False
    )
    paypal_auth_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PayPalCapture(Base):
    __tablename__ = "paypal_captures"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    buyer_order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buyer_orders.id"), nullable=False
    )
    paypal_auth_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    paypal_capture_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    final_capture: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PayPalRefund(Base):
    __tablename__ = "paypal_refunds"
    __table_args__ = (
        UniqueConstraint("paypal_capture_id", "seq", name="uq_paypal_refunds_capture_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    buyer_order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buyer_orders.id"), nullable=False
    )
    paypal_capture_id: Mapped[str] = mapped_column(
        Text, ForeignKey("paypal_captures.paypal_capture_id"), nullable=False
    )
    paypal_refund_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lots.id"), nullable=False
    )
    buyer_order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buyer_orders.id"), nullable=False
    )
    kind: Mapped[LedgerKind] = mapped_column(pg_enum(LedgerKind, "ledger_kind"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paypal_ref: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    source: Mapped[LedgerSource] = mapped_column(
        pg_enum(LedgerSource, "ledger_source"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    paypal_event_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    raw_body: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    verification_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[WebhookStatus] = mapped_column(
        pg_enum(WebhookStatus, "webhook_status"),
        nullable=False,
        server_default=text("'RECEIVED'::webhook_status"),
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (Index("ix_shipments_lot_id", "lot_id"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lots.id"), nullable=False
    )
    buyer_order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("buyer_orders.id"), unique=True, nullable=False
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    carrier: Mapped[str] = mapped_column(Text, nullable=False)
    tracking_number: Mapped[str] = mapped_column(Text, nullable=False)
    shipped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paypal_tracker_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    paypal_debug_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
