"""Merchants, bids and awards (T01A01; db-schema.md "Merchants and auction")."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from fairpool.db.base import Base

from .enums import (
    BidStatus,
    FlagCode,
    FlagSeverity,
    MerchantOnboarding,
    pg_enum,
)


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    onboarding_status: Mapped[MerchantOnboarding] = mapped_column(
        pg_enum(MerchantOnboarding, "merchant_onboarding"),
        nullable=False,
        server_default=text("'NONE'::merchant_onboarding"),
    )
    payee_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    paypal_merchant_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    attestations: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Bid(Base):
    __tablename__ = "bids"
    __table_args__ = (UniqueConstraint("lot_id", "merchant_id", name="uq_bids_lot_merchant"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lots.id"), nullable=False
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    status: Mapped[BidStatus] = mapped_column(
        pg_enum(BidStatus, "bid_status"),
        nullable=False,
        server_default=text("'DRAFT'::bid_status"),
    )
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BidRevision(Base):
    __tablename__ = "bid_revisions"
    __table_args__ = (UniqueConstraint("bid_id", "revision", name="uq_bid_revisions_bid_revision"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    bid_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bids.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    structured: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    quote_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    receipt_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    receipt_signature: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BidFlag(Base):
    __tablename__ = "bid_flags"
    __table_args__ = (CheckConstraint("char_length(evidence) <= 200", name="evidence_len"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    bid_revision_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bid_revisions.id"), nullable=False
    )
    ai_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai_runs.id"), nullable=False
    )
    code: Mapped[FlagCode] = mapped_column(pg_enum(FlagCode, "flag_code"), nullable=False)
    severity: Mapped[FlagSeverity] = mapped_column(
        pg_enum(FlagSeverity, "flag_severity"), nullable=False
    )
    field: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Award(Base):
    __tablename__ = "awards"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lots.id"), unique=True, nullable=False
    )
    bid_revision_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bid_revisions.id"), nullable=False
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    tier_index: Mapped[int] = mapped_column(Integer, nullable=False)
    item_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    moq: Mapped[int] = mapped_column(Integer, nullable=False)
    totals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    award_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MerchantApiKey(Base):
    __tablename__ = "merchant_api_keys"
    __table_args__ = (CheckConstraint("char_length(key_prefix) = 8", name="key_prefix_len"),)

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
