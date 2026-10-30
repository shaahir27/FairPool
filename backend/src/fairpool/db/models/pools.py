"""Lots and allocations (T01A01; db-schema.md "Allocation and lots")."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from fairpool.db.base import Base

from .enums import AllocationStatus, LotStatus, PaymentMode, PaymentRouter, pg_enum


class Lot(Base):
    __tablename__ = "lots"
    __table_args__ = (
        UniqueConstraint("pool_id", "zone_id", "lot_index", name="uq_lots_pool_zone_index"),
        UniqueConstraint("pool_id", "lot_order", name="uq_lots_pool_order"),
        CheckConstraint("seats > 0", name="seats_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    pool_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pools.id"), nullable=False
    )
    zone_id: Mapped[str] = mapped_column(Text, nullable=False)
    lot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    lot_order: Mapped[int] = mapped_column(Integer, nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False)
    min_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[LotStatus] = mapped_column(
        pg_enum(LotStatus, "lot_status"),
        nullable=False,
        server_default=text("'PLANNED'::lot_status"),
    )
    payment_router: Mapped[PaymentRouter | None] = mapped_column(
        pg_enum(PaymentRouter, "payment_router"), nullable=True
    )
    payment_mode: Mapped[PaymentMode | None] = mapped_column(
        pg_enum(PaymentMode, "payment_mode"), nullable=True
    )
    award_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("awards.id", use_alter=True, name="fk_lots_award_id_awards"),
        nullable=True,
    )
    bid_open_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bid_close_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fund_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refill_cutoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    funded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Allocation(Base):
    __tablename__ = "allocations"
    __table_args__ = (
        UniqueConstraint("pool_id", "entry_id", name="uq_allocations_pool_entry"),
        UniqueConstraint("pool_id", "zone_id", "rank", name="uq_allocations_pool_zone_rank"),
        Index("ix_allocations_lot_status", "lot_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    pool_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pools.id"), nullable=False
    )
    entry_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pool_entries.id"), nullable=False
    )
    zone_id: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    rank_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lots.id"), nullable=True
    )
    status: Mapped[AllocationStatus] = mapped_column(
        pg_enum(AllocationStatus, "allocation_status"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
