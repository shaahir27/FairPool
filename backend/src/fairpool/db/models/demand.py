"""Consented demand signals and the clusters they form (CR-17, FR-DM-01 to FR-DM-06).

A signal is a buyer asking to be told when a pool forms for a product they could not
find. It stores the canonical product fields the buyer confirmed and a delivery region:
never a cap, a raw message, an address or payment data. The cluster key is derived
deterministically from those fields, so a similarity score never decides membership
(INT-1 stays retrieval-only) and one cluster can only ever yield one pool.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from fairpool.db.base import Base

CLUSTER_STATES = ("COLLECTING", "PROPOSED", "POOLED", "REJECTED", "EXPIRED")


class DemandCluster(Base):
    __tablename__ = "demand_clusters"
    __table_args__ = (
        CheckConstraint(
            "status IN ('COLLECTING','PROPOSED','POOLED','REJECTED','EXPIRED')",
            name="ck_demand_clusters_status",
        ),
    )

    cluster_key: Mapped[str] = mapped_column(Text, primary_key=True)
    product_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    regions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'COLLECTING'"))
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    pool_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pools.id"), nullable=True, unique=True
    )
    proposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pooled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DemandSignal(Base):
    __tablename__ = "demand_signals"
    __table_args__ = (
        Index("ix_demand_signals_cluster_key", "cluster_key"),
        Index(
            "uq_demand_signals_user_cluster_active",
            "user_id",
            "cluster_key",
            unique=True,
            postgresql_where=text("cancelled_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    cluster_key: Mapped[str] = mapped_column(
        Text, ForeignKey("demand_clusters.cluster_key"), nullable=False
    )
    region: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
