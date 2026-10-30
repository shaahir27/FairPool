"""Deterministic award fixtures shared by port fakes and tests.

The fixture models the handoff point between award and checkout: three seated
entries (one priced out), two waitlisted entries and the immutable award
snapshot. Every UUID and timestamp is fixed so tests can compare values across
runs and processes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from fairpool.domain import hashing, money
from fairpool.domain.fairness import ENTRY_ELIGIBLE
from fairpool.ports import AwardView, LotView, SeatView, Totals

_NAMESPACE = UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

POOL_ID = uuid5(_NAMESPACE, "fairpool/fixture/v1/pool")
LOT_ID = uuid5(_NAMESPACE, "fairpool/fixture/v1/lot")
MERCHANT_ID = uuid5(_NAMESPACE, "fairpool/fixture/v1/merchant")
BID_REVISION_ID = uuid5(_NAMESPACE, "fairpool/fixture/v1/bid-revision")

ZONE_ID = "US-EAST"
REGION = "NY"
ITEM_CENTS = 47_000
MOQ = 2
TIER_INDEX = 1
TAX_RATE_BPS = 875
SHIPPING_CENTS_BY_ZONE = {ZONE_ID: 1_500}

VALID_UNTIL = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
FUND_DEADLINE_AT = datetime(2026, 11, 2, 11, 10, tzinfo=UTC)
REFILL_CUTOFF_AT = datetime(2026, 11, 2, 11, 5, tzinfo=UTC)

SEATED = "SEATED"
WAITLISTED = "WAITLISTED"
PRICED_OUT = "PRICED_OUT"


@dataclass(frozen=True)
class FixtureEntry:
    """One entry and its allocation state at the award snapshot."""

    entry_id: UUID
    user_id: UUID
    cap_cents: int
    zone_id: str
    region: str
    rank: int
    status: str
    allocation_status: str
    lot_id: UUID | None
    paypal_account_key: str | None

    def to_seat(self) -> SeatView:
        return SeatView(
            entry_id=self.entry_id,
            user_id=self.user_id,
            cap_cents=self.cap_cents,
            zone_id=self.zone_id,
            region=self.region,
            rank=self.rank,
            paypal_account_key=self.paypal_account_key,
        )


@dataclass(frozen=True)
class AwardFixture:
    """The fake allocation service's read model plus its immutable award."""

    lot: LotView
    min_seats: int
    seats: tuple[SeatView, ...]
    award: AwardView
    award_document: dict[str, Any]
    waitlist: tuple[SeatView, ...]
    priced_out: UUID
    entries: tuple[FixtureEntry, ...]


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _entry(
    index: int,
    *,
    cap_cents: int,
    rank: int,
    allocation_status: str,
    lot_id: UUID | None,
) -> FixtureEntry:
    return FixtureEntry(
        entry_id=uuid5(_NAMESPACE, f"fairpool/fixture/v1/entry/{index}"),
        user_id=uuid5(_NAMESPACE, f"fairpool/fixture/v1/user/{index}"),
        cap_cents=cap_cents,
        zone_id=ZONE_ID,
        region=REGION,
        rank=rank,
        status=ENTRY_ELIGIBLE,
        allocation_status=allocation_status,
        lot_id=lot_id,
        paypal_account_key=f"PAYPAL-ACCOUNT-{index}",
    )


def make_award_fixture() -> AwardFixture:
    """Build the deterministic three-seat lot, award and five-entry fixture."""
    entries = (
        _entry(1, cap_cents=60_000, rank=1, allocation_status=SEATED, lot_id=LOT_ID),
        _entry(2, cap_cents=55_000, rank=2, allocation_status=SEATED, lot_id=LOT_ID),
        _entry(3, cap_cents=50_000, rank=3, allocation_status=PRICED_OUT, lot_id=LOT_ID),
        _entry(4, cap_cents=50_000, rank=4, allocation_status=WAITLISTED, lot_id=None),
        _entry(5, cap_cents=55_000, rank=5, allocation_status=WAITLISTED, lot_id=None),
    )
    shipping_cents = SHIPPING_CENTS_BY_ZONE[ZONE_ID]
    tax = money.tax_cents(ITEM_CENTS, TAX_RATE_BPS)
    total = money.total_cents(ITEM_CENTS, shipping_cents, tax)
    totals = Totals(
        item_cents=ITEM_CENTS,
        shipping_cents=shipping_cents,
        tax_cents=tax,
        total_cents=total,
    )
    award_totals = {entry.entry_id: totals for entry in entries}

    lot = LotView(
        id=LOT_ID,
        pool_id=POOL_ID,
        zone_id=ZONE_ID,
        lot_order=0,
        seats=3,
        status="AWARDED",
        payment_router="single_seller",
        payment_mode="vault_charge",
        fund_deadline_at=FUND_DEADLINE_AT,
        refill_cutoff_at=REFILL_CUTOFF_AT,
        offer_window_s=180,
        fund_deadline_s=600,
        max_refill_waves=1,
        pool_mode="LIVE_SANDBOX",
    )
    award_document: dict[str, Any] = {
        "v": 1,
        "lot_id": str(LOT_ID),
        "bid_revision_id": str(BID_REVISION_ID),
        "merchant_id": str(MERCHANT_ID),
        "tier_index": TIER_INDEX,
        "item_cents": ITEM_CENTS,
        "moq": MOQ,
        "totals": {
            str(entry_id): {
                "item_cents": entry_totals.item_cents,
                "shipping_cents": entry_totals.shipping_cents,
                "tax_cents": entry_totals.tax_cents,
                "total_cents": entry_totals.total_cents,
            }
            for entry_id, entry_totals in award_totals.items()
        },
        "valid_until": _format_timestamp(VALID_UNTIL),
        "rule_version": "ranking_v1",
    }
    award = AwardView(
        lot_id=LOT_ID,
        merchant_id=MERCHANT_ID,
        item_cents=ITEM_CENTS,
        moq=MOQ,
        tier_index=TIER_INDEX,
        totals=award_totals,
        valid_until=VALID_UNTIL,
        award_hash=hashing.award_hash(award_document),
    )
    return AwardFixture(
        lot=lot,
        min_seats=2,
        seats=tuple(entry.to_seat() for entry in entries[:3]),
        award=award,
        award_document=award_document,
        waitlist=tuple(entry.to_seat() for entry in entries[3:]),
        priced_out=entries[2].entry_id,
        entries=entries,
    )
