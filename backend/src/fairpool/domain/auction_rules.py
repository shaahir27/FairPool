"""Tier resolution, feasibility, bid ranking and capacity (``ranking_v1``).

Contract: ``docs/contracts/fairness-and-hashing.md`` sections 10 and 11.

Each seated entry's total is computed at a tier's item price with that entry's
own shipping and tax, because regions differ. A tier applies when enough seated
entries can afford it; the chosen tier is the applicable tier with the lowest
item price; the bid is feasible only when the chosen tier reaches the MOQ.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from . import money
from .errors import AuctionError

R8_NO_FEASIBLE_TIER = "R8_NO_FEASIBLE_TIER"
R8_INFEASIBLE = "R8_INFEASIBLE"
R9_CAPACITY_EXHAUSTED = "R9_CAPACITY_EXHAUSTED"


def _require_int(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AuctionError(f"{field} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True)
class Tier:
    min_qty: int
    item_price_cents: int


@dataclass(frozen=True)
class SeatedBuyer:
    """A seated entry with the bid's shipping and tax for its zone and region."""

    entry_id: str
    cap_cents: int
    shipping_cents: int
    tax_rate_bps: int
    tax_included: bool = False


@dataclass(frozen=True)
class TierEntryTotal:
    entry_id: str
    item_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int
    within_cap: bool


@dataclass(frozen=True)
class TierEvaluation:
    tier_index: int
    min_qty: int
    item_price_cents: int
    n_tier: int
    applies: bool
    totals: tuple[TierEntryTotal, ...]
    accepting_totals: tuple[int, ...]
    mean_total_cents: int | None
    max_total_cents: int | None


@dataclass(frozen=True)
class TierResolution:
    evaluations: tuple[TierEvaluation, ...]
    chosen_tier_index: int | None
    feasible: bool
    rejection: str | None


@dataclass(frozen=True)
class BidCandidate:
    bid_id: str
    merchant_id: str
    mean_total_cents: int
    max_total_cents: int
    tiebreak_hash: str

    def key(self) -> tuple[int, int, str]:
        return (self.mean_total_cents, self.max_total_cents, self.tiebreak_hash)


@dataclass(frozen=True)
class AwardedLot:
    lot_order: int
    merchant_id: str
    seats: int


def evaluate_tiers(
    seated: Sequence[SeatedBuyer], tiers: Sequence[Tier]
) -> tuple[TierEvaluation, ...]:
    """Compute every tier's totals and the number of seated entries that can afford it."""
    seen: set[str] = set()
    for buyer in seated:
        if buyer.entry_id in seen:
            raise AuctionError(f"duplicate seated entry_id: {buyer.entry_id}")
        seen.add(buyer.entry_id)

    evaluations: list[TierEvaluation] = []
    for tier_index, tier in enumerate(tiers):
        min_qty = _require_int(tier.min_qty, "tier min_qty", minimum=1)
        item_price = _require_int(tier.item_price_cents, "tier item_price_cents")
        totals: list[TierEntryTotal] = []
        for buyer in seated:
            cap = _require_int(buyer.cap_cents, "cap_cents")
            shipping = _require_int(buyer.shipping_cents, "shipping_cents")
            rate = _require_int(buyer.tax_rate_bps, "tax_rate_bps")
            if not isinstance(buyer.tax_included, bool):
                raise AuctionError("tax_included must be a boolean")
            tax = 0 if buyer.tax_included else money.tax_cents(item_price, rate)
            total = money.total_cents(item_price, shipping, tax)
            totals.append(
                TierEntryTotal(
                    entry_id=buyer.entry_id,
                    item_cents=item_price,
                    shipping_cents=shipping,
                    tax_cents=tax,
                    total_cents=total,
                    within_cap=total <= cap,
                )
            )
        accepting = tuple(item.total_cents for item in totals if item.within_cap)
        n_tier = len(accepting)
        evaluations.append(
            TierEvaluation(
                tier_index=tier_index,
                min_qty=min_qty,
                item_price_cents=item_price,
                n_tier=n_tier,
                applies=n_tier >= min_qty,
                totals=tuple(totals),
                accepting_totals=accepting,
                mean_total_cents=money.mean_total_cents(accepting) if accepting else None,
                max_total_cents=max(accepting) if accepting else None,
            )
        )
    return tuple(evaluations)


def resolve_tiers(
    seated: Sequence[SeatedBuyer],
    tiers: Sequence[Tier],
    moq: int,
) -> TierResolution:
    """Pick the applicable tier with the lowest item price and test the MOQ (R8)."""
    minimum_order = _require_int(moq, "moq", minimum=1)
    evaluations = evaluate_tiers(seated, tiers)
    applicable = [evaluation for evaluation in evaluations if evaluation.applies]
    if not applicable:
        return TierResolution(
            evaluations=evaluations,
            chosen_tier_index=None,
            feasible=False,
            rejection=R8_NO_FEASIBLE_TIER,
        )
    chosen = min(applicable, key=lambda item: (item.item_price_cents, item.tier_index))
    if chosen.n_tier < minimum_order:
        return TierResolution(
            evaluations=evaluations,
            chosen_tier_index=chosen.tier_index,
            feasible=False,
            rejection=R8_INFEASIBLE,
        )
    return TierResolution(
        evaluations=evaluations,
        chosen_tier_index=chosen.tier_index,
        feasible=True,
        rejection=None,
    )


def bid_ranking_key(resolution: TierResolution, tiebreak_hash: str) -> tuple[int, int, str]:
    """Ascending key: mean total, max total over accepting entries, tie-break hash."""
    if not resolution.feasible or resolution.chosen_tier_index is None:
        raise AuctionError("ranking key needs a feasible tier")
    chosen = resolution.evaluations[resolution.chosen_tier_index]
    if chosen.mean_total_cents is None or chosen.max_total_cents is None:
        raise AuctionError("feasible tier has no accepting entries")
    return (chosen.mean_total_cents, chosen.max_total_cents, tiebreak_hash)


def rank_bids(candidates: Iterable[BidCandidate]) -> list[BidCandidate]:
    """Lowest ranking key wins; equal keys keep their input order (stable sort)."""
    return sorted(candidates, key=BidCandidate.key)


def remaining_capacity(
    total_capacity: int,
    merchant_id: str,
    awarded_lots: Iterable[AwardedLot],
) -> int:
    """Capacity left for a merchant after lots awarded earlier in ``lot_order`` (R9)."""
    total = _require_int(total_capacity, "total_capacity")
    used = 0
    for lot in sorted(awarded_lots, key=lambda item: item.lot_order):
        seats = _require_int(lot.seats, "awarded lot seats")
        _require_int(lot.lot_order, "lot_order", minimum=1)
        if lot.merchant_id == merchant_id:
            used += seats
    return total - used


def capacity_ok(
    total_capacity: int,
    merchant_id: str,
    bid_capacity: int,
    awarded_lots: Iterable[AwardedLot],
) -> bool:
    """A bid whose capacity exceeds the merchant's remaining seats fails R9."""
    capacity = _require_int(bid_capacity, "bid capacity")
    return capacity <= remaining_capacity(total_capacity, merchant_id, awarded_lots)
