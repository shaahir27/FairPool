"""Sealed bids with signed receipts (T05A04; FR-AU-01, FR-AU-02, I11).

A bid is one row per merchant and lot; every submission is a new numbered
revision with a receipt the merchant can keep. Sealing is an access rule: a read
is scoped to the owning merchant in SQL and another merchant's bid is reported as
not found, never as forbidden (``api.md`` section 3: responses never contain
another merchant's bids).

``BID_PRICING_MODE=flat_delivered`` is enforced here, at the write boundary, with
the contracted message from ``flat-delivered-bids.md``; the pure rules engine
stays mode-agnostic.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Bid, BidFlag, BidRevision
from fairpool.db.models.enums import BidStatus
from fairpool.db.models.pools import Lot
from fairpool.domain import hashing
from fairpool.domain.errors import ApplicationError
from fairpool.modules.pools.receipts import format_received_at
from fairpool.ports import Clock

logger: Final[logging.Logger] = logging.getLogger("fairpool.auction.bids")

FLAT_DELIVERED_MESSAGE: Final[str] = (
    "Bids must be one delivered price per lot, shipping and tax included."
)

MAX_TIERS: Final[int] = 3


def _int_field(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApplicationError("VALIDATION_ERROR")
    if value < 0:
        raise ApplicationError("VALIDATION_ERROR")
    return value


def validate_structured(structured: Mapping[str, Any], *, flat_delivered: bool) -> None:
    """Shape, tiers and pricing mode. Raises ``VALIDATION_ERROR`` without a message
    that could leak anything the merchant did not send."""
    if not isinstance(structured, Mapping):
        raise ApplicationError("VALIDATION_ERROR")
    tiers = structured.get("tiers")
    if not isinstance(tiers, list) or not 1 <= len(tiers) <= MAX_TIERS:
        raise ApplicationError("VALIDATION_ERROR")
    previous_min = 0
    previous_price: int | None = None
    for tier in tiers:
        if not isinstance(tier, Mapping):
            raise ApplicationError("VALIDATION_ERROR")
        minimum = _int_field(tier.get("min_qty"), "min_qty")
        price = _int_field(tier.get("item_price_cents"), "item_price_cents")
        if minimum <= previous_min:
            raise ApplicationError("VALIDATION_ERROR")
        if previous_price is not None and price > previous_price:
            raise ApplicationError("VALIDATION_ERROR")
        previous_min, previous_price = minimum, price
    if structured.get("capacity") is not None:
        _int_field(structured.get("capacity"), "capacity")
    if flat_delivered:
        tax = structured.get("tax") or {}
        mode = tax.get("mode") if isinstance(tax, Mapping) else None
        shipping = structured.get("shipping_cents_by_zone") or {}
        if mode != "INCLUDED" or (
            isinstance(shipping, Mapping) and any(int(v) != 0 for v in shipping.values())
        ):
            raise ApplicationError("VALIDATION_ERROR", FLAT_DELIVERED_MESSAGE)


class BidService:
    """One merchant's bids: revisions, receipts, confirmation and sealed reads."""

    def __init__(self, *, clock: Clock, seed: bytes, flat_delivered: bool = True) -> None:
        self.clock = clock
        self.seed = seed
        self.flat_delivered = flat_delivered

    async def save(
        self,
        session: AsyncSession,
        *,
        merchant_id: UUID,
        lot_id: UUID,
        structured: Mapping[str, Any],
        quote_text: str | None = None,
        notes: str | None = None,
    ) -> tuple[Bid, BidRevision]:
        validate_structured(structured, flat_delivered=self.flat_delivered)
        lot = await session.get(Lot, lot_id)
        if lot is None:
            raise ApplicationError("NOT_FOUND")
        capacity = structured.get("capacity")
        if isinstance(capacity, int) and capacity < int(lot.seats):
            raise ApplicationError("VALIDATION_ERROR")
        now = await self.clock.db_now(session)
        bid = await session.scalar(
            select(Bid).where(Bid.lot_id == lot_id, Bid.merchant_id == merchant_id)
        )
        if bid is None:
            bid = Bid(
                id=uuid4(),
                lot_id=lot_id,
                merchant_id=merchant_id,
                status=BidStatus.PROPOSED,
                current_revision=0,
            )
            session.add(bid)
            await session.flush()
        revision = int(bid.current_revision) + 1
        late = lot.bid_close_at is not None and now > lot.bid_close_at
        receipt_hash = hashing.bid_receipt_hash(
            str(bid.id), revision, structured, format_received_at(now)
        )
        signature = hashing.sign_ed25519(
            hashing.bid_receipt_payload(str(bid.id), revision, receipt_hash), self.seed
        )
        row = BidRevision(
            id=uuid4(),
            bid_id=bid.id,
            revision=revision,
            structured=dict(structured),
            quote_text=quote_text,
            notes=notes,
            receipt_hash=receipt_hash,
            receipt_signature=signature,
        )
        session.add(row)
        bid.current_revision = revision
        if late:
            # The revision is kept as evidence, but it can never be ranked.
            bid.status = BidStatus.REJECTED
            bid.reject_reason = "R1_LATE"
        elif bid.status in (BidStatus.DRAFT, BidStatus.REJECTED):
            bid.status = BidStatus.PROPOSED
            bid.reject_reason = None
        await session.flush()
        return bid, row

    async def confirm(
        self, session: AsyncSession, *, merchant_id: UUID, bid_id: UUID, revision: int
    ) -> Bid:
        bid = await self._owned(session, merchant_id=merchant_id, bid_id=bid_id)
        if int(bid.current_revision) != int(revision):
            raise ApplicationError("VALIDATION_ERROR")
        if str(bid.status) == str(BidStatus.REJECTED):
            raise ApplicationError("VALIDATION_ERROR")
        row = await session.scalar(
            select(BidRevision).where(
                BidRevision.bid_id == bid.id, BidRevision.revision == revision
            )
        )
        if row is None:
            raise ApplicationError("NOT_FOUND")
        now = await self.clock.db_now(session)
        row.confirmed_at = now
        bid.status = BidStatus.CONFIRMED
        await session.flush()
        return bid

    async def get(
        self, session: AsyncSession, *, merchant_id: UUID, bid_id: UUID
    ) -> tuple[Bid, BidRevision, list[BidFlag]]:
        bid = await self._owned(session, merchant_id=merchant_id, bid_id=bid_id)
        revision = await session.scalar(
            select(BidRevision).where(
                BidRevision.bid_id == bid.id, BidRevision.revision == bid.current_revision
            )
        )
        if revision is None:
            raise ApplicationError("INTEGRITY_ERROR")
        flags = list(
            await session.scalars(select(BidFlag).where(BidFlag.bid_revision_id == revision.id))
        )
        return bid, revision, flags

    async def _owned(self, session: AsyncSession, *, merchant_id: UUID, bid_id: UUID) -> Bid:
        bid = await session.scalar(
            select(Bid).where(Bid.id == bid_id, Bid.merchant_id == merchant_id)
        )
        if bid is None:
            # Another merchant's bid must not confirm its existence.
            raise ApplicationError("NOT_FOUND")
        return bid
