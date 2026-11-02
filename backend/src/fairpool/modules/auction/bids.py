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

#: The keys ``db-schema.md`` gives ``bid_revisions.structured``. FR-AU-02 is the
#: product rule behind it: a bid that does not state every one of these is not a
#: bid, so BS-02's "structured form complete and valid" guard is refused here.
BID_KEYS: Final[tuple[str, ...]] = (
    "v",
    "product_key",
    "condition",
    "bundle_contents",
    "capacity",
    "target_quantity",
    "moq",
    "tiers",
    "tax",
    "delivery",
    "returns",
    "valid_until",
    "evidence",
)
BID_TEXT_KEYS: Final[tuple[str, ...]] = ("product_key", "condition", "valid_until")
BID_COUNT_KEYS: Final[tuple[str, ...]] = ("capacity", "moq", "target_quantity")


def _int_field(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApplicationError("VALIDATION_ERROR")
    return value


def _positive_int(value: object) -> int:
    number = _int_field(value)
    if number < 1:
        raise ApplicationError("VALIDATION_ERROR")
    return number


def _tiers(value: object) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_TIERS:
        raise ApplicationError("VALIDATION_ERROR")
    previous_min = 0
    previous_price: int | None = None
    for tier in value:
        if not isinstance(tier, Mapping):
            raise ApplicationError("VALIDATION_ERROR")
        minimum = _positive_int(tier.get("min_qty"))
        price = _int_field(tier.get("item_price_cents"))
        if minimum <= previous_min or (previous_price is not None and price > previous_price):
            raise ApplicationError("VALIDATION_ERROR")
        previous_min, previous_price = minimum, price


def _tax(structured: Mapping[str, Any]) -> str:
    tax = structured["tax"]
    if not isinstance(tax, Mapping):
        raise ApplicationError("VALIDATION_ERROR")
    mode = tax.get("mode")
    if mode == "INCLUDED":
        if "rate_bps_by_region" in tax:
            raise ApplicationError("VALIDATION_ERROR")
    elif mode == "RATE_TABLE":
        rates = tax.get("rate_bps_by_region")
        if not isinstance(rates, Mapping) or not rates:
            raise ApplicationError("VALIDATION_ERROR")
        for rate in rates.values():
            _int_field(rate)
    else:
        raise ApplicationError("VALIDATION_ERROR")
    return str(mode)


def _shipping_by_zone(structured: Mapping[str, Any]) -> dict[str, int]:
    shipping = structured.get("shipping_cents_by_zone") or {}
    if not isinstance(shipping, Mapping):
        raise ApplicationError("VALIDATION_ERROR")
    return {str(zone): _int_field(value) for zone, value in shipping.items()}


def validate_structured(structured: Mapping[str, Any], *, flat_delivered: bool) -> None:
    """Shape, tier rules and pricing mode. A ``VALIDATION_ERROR`` carries no message
    that could echo back anything the merchant did not send."""
    if not isinstance(structured, Mapping):
        raise ApplicationError("VALIDATION_ERROR")
    for key in BID_KEYS:
        if key not in structured:
            raise ApplicationError("VALIDATION_ERROR")
    if structured["v"] != 1:
        raise ApplicationError("VALIDATION_ERROR")
    for key in BID_TEXT_KEYS:
        value = structured[key]
        if not isinstance(value, str) or not value.strip():
            raise ApplicationError("VALIDATION_ERROR")
    bundle = structured["bundle_contents"]
    if not isinstance(bundle, list) or not all(
        isinstance(part, str) and part.strip() for part in bundle
    ):
        raise ApplicationError("VALIDATION_ERROR")
    if not isinstance(structured["evidence"], Mapping):
        raise ApplicationError("VALIDATION_ERROR")
    for key in BID_COUNT_KEYS:
        _positive_int(structured[key])
    if structured.get("total_capacity") is not None:
        _positive_int(structured["total_capacity"])
    _tiers(structured["tiers"])
    mode = _tax(structured)
    shipping = _shipping_by_zone(structured)
    delivery = structured["delivery"]
    returns = structured["returns"]
    if not isinstance(delivery, Mapping) or not isinstance(returns, Mapping):
        raise ApplicationError("VALIDATION_ERROR")
    if _positive_int(delivery.get("sla_days")) < 1 or _int_field(returns.get("days")) < 0:
        raise ApplicationError("VALIDATION_ERROR")
    if flat_delivered and (mode != "INCLUDED" or any(value != 0 for value in shipping.values())):
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
            # R4 at the write boundary: a bid that cannot supply its own lot never
            # reaches the award, so no buyer is left holding an unfillable offer.
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
        lot = await session.get(Lot, bid.lot_id)
        if lot is None:
            raise ApplicationError("NOT_FOUND")
        if str(lot.status) != "BIDDING":
            raise ApplicationError("LOT_NOT_BIDDING")
        now = await self.clock.db_now(session)
        # I15: a confirm is a write, so the stored deadline is re-read here too. A
        # merchant who leaves the tab open past the close cannot confirm a bid into
        # an auction that has already shut, and R1's ``submitted_at`` test would
        # otherwise never see it because the revision predates the deadline.
        if lot.bid_close_at is not None and now >= lot.bid_close_at:
            raise ApplicationError("BID_WINDOW_CLOSED")
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
            # Reachable when ``lot.award`` decided the bid while the merchant's tab
            # stayed open. The pair is off the whitelist, so it alerts (I10) and the
            # client is told the auction moved on rather than seeing a 500.
            logger.error(
                "auction.illegal_transition bid_id=%s lot_id=%s from=%s to=%s trigger=%s",
                bid.id,
                bid.lot_id,
                bid.status,
                to_status,
                trigger,
            )
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
