"""Sealed bids with signed receipts (T05A04; FR-AU-02, FR-AU-03, I11).

A bid is one row per merchant and lot; every submission is a new numbered
revision with a receipt the merchant can keep. Sealing is an access rule: a read
is scoped to the owning merchant in SQL and another merchant's bid is reported as
not found, never as forbidden (``api.md`` section 3: responses never contain
another merchant's bids).

Every status change here is a ``bid`` whitelist edge from ``state-machines.md``
with its audit row (I10), which is why a save cannot silently re-open a decided
bid and a revise always returns the bid to DRAFT until it is confirmed again.

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
from fairpool.domain.errors import ApplicationError, IllegalTransition
from fairpool.domain.states import assert_transition
from fairpool.modules.pools.receipts import format_received_at
from fairpool.ports import AuditLog, Clock

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


async def apply_bid_transition(
    session: AsyncSession,
    *,
    bid: Bid,
    to_status: str,
    trigger: str,
    audit: AuditLog,
    actor: str = "merchant",
    payload: dict[str, Any] | None = None,
) -> None:
    """Move a bid along the whitelist and write its audit row in this transaction (I10)."""
    transition = assert_transition("bid", str(bid.status), to_status, trigger=trigger)
    before = str(bid.status)
    bid.status = BidStatus(to_status)
    await session.flush()
    await audit.append(
        session,
        actor=actor,
        action=f"bid.{to_status.lower()}",
        subject_type="bid",
        subject_id=str(bid.id),
        payload={
            "lot_id": str(bid.lot_id),
            "merchant_id": str(bid.merchant_id),
            "from": before,
            "to": to_status,
            "trigger": trigger,
            "transition_id": transition.id,
            **(payload or {}),
        },
    )


class BidService:
    """One merchant's bids: revisions, receipts, confirmation and sealed reads."""

    def __init__(
        self, *, clock: Clock, audit: AuditLog, seed: bytes, flat_delivered: bool = True
    ) -> None:
        self.clock = clock
        self.audit = audit
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
        if str(lot.status) != "BIDDING":
            raise ApplicationError("LOT_NOT_BIDDING")
        now = await self.clock.db_now(session)
        # BS-12's own guard: past the deadline no revision is accepted, so a late
        # write can never replace a confirmed bid. Rejection of an unconfirmed bid
        # stays the award job's edge (R1, ``state-machines.md``).
        if lot.bid_close_at is not None and now >= lot.bid_close_at:
            raise ApplicationError("BID_WINDOW_CLOSED")
        capacity = structured.get("capacity")
        if isinstance(capacity, int) and capacity < int(lot.seats):
            raise ApplicationError("VALIDATION_ERROR")
        bid = await session.scalar(
            select(Bid).where(Bid.lot_id == lot_id, Bid.merchant_id == merchant_id)
        )
        if bid is None:
            # DRAFT is the machine's initial state, so creating the row is not a transition.
            bid = Bid(
                id=uuid4(),
                lot_id=lot_id,
                merchant_id=merchant_id,
                status=BidStatus.DRAFT,
                current_revision=0,
            )
            session.add(bid)
            await session.flush()
        revision = int(bid.current_revision) + 1
        if str(bid.status) != str(BidStatus.DRAFT):
            await self._move(
                session,
                bid=bid,
                to_status="DRAFT",
                trigger="merchant.revise",
                payload={"revision": revision},
            )
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
        await session.flush()
        return bid, row

    async def confirm(
        self, session: AsyncSession, *, merchant_id: UUID, bid_id: UUID, revision: int
    ) -> Bid:
        bid = await self._owned(session, merchant_id=merchant_id, bid_id=bid_id)
        if int(bid.current_revision) != int(revision):
            # A stale revision number is a body error, not a state error.
            raise ApplicationError("VALIDATION_ERROR")
        row = await session.scalar(
            select(BidRevision).where(
                BidRevision.bid_id == bid.id, BidRevision.revision == revision
            )
        )
        if row is None:
            raise ApplicationError("NOT_FOUND")
        now = await self.clock.db_now(session)
        await self._move(
            session,
            bid=bid,
            to_status="CONFIRMED",
            trigger="merchant.confirm",
            payload={"revision": revision},
        )
        row.confirmed_at = now
        await session.flush()
        return bid

    async def _move(
        self,
        session: AsyncSession,
        *,
        bid: Bid,
        to_status: str,
        trigger: str,
        payload: dict[str, Any],
    ) -> None:
        """Apply a whitelist edge, reporting a decided bid as the stale page it is."""
        try:
            await apply_bid_transition(
                session,
                bid=bid,
                to_status=to_status,
                trigger=trigger,
                audit=self.audit,
                payload=payload,
            )
        except IllegalTransition as error:
            # Only reachable once ``lot.award`` has decided the bid, and by then the
            # lot has left BIDDING; the merchant's tab is simply stale (I10 says no).
            raise ApplicationError("LOT_NOT_BIDDING") from error

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
