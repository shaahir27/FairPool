"""Catalog, pools and entries (T01A01; db-schema.md "Catalog and pools")."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from fairpool.db.base import Base

from .enums import EntryStatus, PoolMode, PoolStatus, SubmittedVia, pg_enum

_USD_CHECK = "(template ? 'currency') AND template->>'currency' = 'USD'"
_ENTRY_USD_CHECK = "(canonical_request ? 'currency') AND canonical_request->>'currency' = 'USD'"


class CatalogProduct(Base):
    __tablename__ = "catalog_products"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    product_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    variant: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_price_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'seed'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Pool(Base):
    __tablename__ = "pools"
    __table_args__ = (
        CheckConstraint(_USD_CHECK, name="chk_usd_only"),
        Index(
            "ix_pools_search_text_trgm",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    mode: Mapped[PoolMode] = mapped_column(pg_enum(PoolMode, "pool_mode"), nullable=False)
    status: Mapped[PoolStatus] = mapped_column(
        pg_enum(PoolStatus, "pool_status"),
        nullable=False,
        server_default=text("'DRAFT'::pool_status"),
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    lot_plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    timeline: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    require_paypal_link: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    rules_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    beacon: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    seed_hex: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    seed_is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    entries_root: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    entries_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PoolEntry(Base):
    __tablename__ = "pool_entries"
    __table_args__ = (
        UniqueConstraint("pool_id", "user_id", name="uq_pool_entries_pool_user"),
        Index(
            "uq_pool_entries_pool_account",
            "pool_id",
            "paypal_account_key",
            unique=True,
            postgresql_where=text("paypal_account_key IS NOT NULL"),
        ),
        Index("ix_pool_entries_pool_status", "pool_id", "status"),
        CheckConstraint(_ENTRY_USD_CHECK, name="chk_usd_only"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    pool_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pools.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    paypal_account_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    request_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    cap_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    zone_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EntryStatus] = mapped_column(
        pg_enum(EntryStatus, "entry_status"),
        nullable=False,
        server_default=text("'SUBMITTED'::entry_status"),
    )
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_via: Mapped[SubmittedVia] = mapped_column(
        pg_enum(SubmittedVia, "submitted_via"), nullable=False
    )
    delegation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delegations.id"), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class EntryReceipt(Base):
    __tablename__ = "entry_receipts"

    entry_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pool_entries.id"), primary_key=True
    )
    commitment: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    salt: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
