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
from datetime import UTC, datetime, timedelta

from . import money
from .errors import AuctionError

R8_NO_FEASIBLE_TIER = "R8_NO_FEASIBLE_TIER"
R8_INFEASIBLE = "R8_INFEASIBLE"
R9_CAPACITY_EXHAUSTED = "R9_CAPACITY_EXHAUSTED"

#: R1..R7, in the deterministic order the evaluator applies them
#: (``docs/contracts/config-and-errors.md`` section 5).
R1_SCHEMA = "R1_SCHEMA"
R1_LATE = "R1_LATE"
R1_UNCONFIRMED = "R1_UNCONFIRMED"
R2_MERCHANT_INELIGIBLE = "R2_MERCHANT_INELIGIBLE"
R3_PRODUCT_MISMATCH = "R3_PRODUCT_MISMATCH"
R3_CONDITION_MISMATCH = "R3_CONDITION_MISMATCH"
R3_BUNDLE_MISMATCH = "R3_BUNDLE_MISMATCH"
R4_CAPACITY = "R4_CAPACITY"
R5_DELIVERY = "R5_DELIVERY"
R5_RETURNS = "R5_RETURNS"
R5_TAX_COVERAGE = "R5_TAX_COVERAGE"
R6_VALIDITY = "R6_VALIDITY"
R7_AI_BLOCKING = "R7_AI_BLOCKING"

BID_REJECTION_CODES = (
    R1_SCHEMA,
    R1_LATE,
    R1_UNCONFIRMED,
    R2_MERCHANT_INELIGIBLE,
    R3_PRODUCT_MISMATCH,
    R3_CONDITION_MISMATCH,
    R3_BUNDLE_MISMATCH,
    R4_CAPACITY,
    R5_DELIVERY,
    R5_RETURNS,
    R5_TAX_COVERAGE,
    R6_VALIDITY,
    R7_AI_BLOCKING,
    R8_NO_FEASIBLE_TIER,
    R8_INFEASIBLE,
    R9_CAPACITY_EXHAUSTED,
)


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


@dataclass(frozen=True)
class LotFacts:
    """The lot requirements R3 to R6 compare a bid against.

    ``fund_deadline_at`` and ``capture_grace_s`` give R6's horizon: registry R6
    measures a bid's validity against the deadline the money has to reach, not
    against the bid window.
    """

    lot_id: str
    lot_order: int
    moq: int
    seats: int
    product_key: str
    condition: str
    bundle_key: str | None
    max_delivery_days: int
    min_returns_days: int
    fund_deadline_at: str
    capture_grace_s: int


@dataclass(frozen=True)
class BidFacts:
    """One submitted revision, normalised for deterministic validation.

    ``tiers`` is empty when the bid carries no usable tier list; ``tax_mode`` is
    ``"INCLUDED"`` for ``BID_PRICING_MODE=flat_delivered``; ``blocking_flags``
    are AI flag codes that may only withhold a bid, never qualify one.
    """

    bid_id: str
    merchant_id: str
    schema_ok: bool
    confirmed: bool
    submitted_at: str
    bid_close_at: str
    product_key: str
    condition: str
    bundle_key: str | None
    tiers: tuple[Tier, ...]
    capacity: int | None
    tax_mode: str
    shipping_cents_by_zone: dict[str, int]
    delivery_days: int
    returns_days: int
    validity_end: str
    blocking_flags: tuple[str, ...]


def _parse_iso(value: str, field: str) -> datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise AuctionError(f"{field} is not an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise AuctionError(f"{field} must carry a timezone")
    return parsed.astimezone(UTC)


def bid_rejection(
    facts: BidFacts,
    lot: LotFacts,
    *,
    merchant_eligible: bool,
    flat_delivered: bool = True,
) -> str | None:
    """First failing rule in contract order, or ``None`` when the bid may rank.

    R1 shape/late/confirmation, R2 eligibility, R3 product identity, R4 seat
    coverage, R5 delivery/returns/tax, R6 validity, R7 AI blocking. R8 and R9
    need the seated entries and the awarded lots, so :func:`resolve_tiers` and
    :func:`select_across_lots` decide those.
    """
    if not facts.schema_ok or not facts.tiers:
        return R1_SCHEMA
    if facts.delivery_days <= 0 or facts.returns_days < 0:
        # R1 is listed first, so a revision that does not even state a delivery or
        # returns term fails here rather than as R5 or after R2.
        return R1_SCHEMA
    submitted = _parse_iso(facts.submitted_at, "submitted_at")
    closed = _parse_iso(facts.bid_close_at, "bid_close_at")
    if submitted >= closed:
        # ``state-machines.md`` clarification 1: admission is strictly before close.
        return R1_LATE
    if not facts.confirmed:
        return R1_UNCONFIRMED
    if not merchant_eligible:
        return R2_MERCHANT_INELIGIBLE
    if facts.product_key != lot.product_key:
        return R3_PRODUCT_MISMATCH
    if facts.condition != lot.condition:
        return R3_CONDITION_MISMATCH
    if lot.bundle_key is not None and facts.bundle_key != lot.bundle_key:
        return R3_BUNDLE_MISMATCH
    if facts.capacity is None or facts.capacity < lot.seats:
        # R4 in ``docs/registry.md``: the capacity covers the lot's seats. The
        # merchant's total capacity across lots is R9's, decided in section 11.
        return R4_CAPACITY
    if facts.delivery_days > lot.max_delivery_days:
        return R5_DELIVERY
    if facts.returns_days < lot.min_returns_days:
        return R5_RETURNS
    if flat_delivered and (
        facts.tax_mode != "INCLUDED"
        or any(value != 0 for value in facts.shipping_cents_by_zone.values())
    ):
        return R5_TAX_COVERAGE
    horizon = _parse_iso(lot.fund_deadline_at, "fund_deadline_at") + timedelta(
        seconds=lot.capture_grace_s
    )
    if _parse_iso(facts.validity_end, "validity_end") < horizon:
        # R6 in ``docs/registry.md``: valid at least until the fund deadline plus
        # the capture grace, because that is when the money must still be honourable.
        return R6_VALIDITY
    if facts.blocking_flags:
        return R7_AI_BLOCKING
    return None


@dataclass(frozen=True)
class BidOffer:
    """A validated bid competing for one lot, with the inputs the key needs."""

    bid_id: str
    merchant_id: str
    tiers: tuple[Tier, ...]
    capacity: int
    tiebreak_hash: str


@dataclass(frozen=True)
class Assignment:
    """Outcome for one lot: a winning bid, or no bid and why."""

    lot_id: str
    bid_id: str | None
    merchant_id: str | None
    reject: str | None


def select_across_lots(
    lots: Sequence[LotFacts],
    seated_by_lot: dict[str, Sequence[SeatedBuyer]],
    offers_by_lot: dict[str, Sequence[BidOffer]],
    total_capacity_by_merchant: dict[str, int],
) -> dict[str, Assignment]:
    """Award each lot in ascending ``lot_order`` within each merchant's capacity.

    Pure: returns assignments only. Creating ``awards`` rows, ``lot.award``
    transitions and checkout jobs belongs to the lot handlers (T06A06).
    """
    ordered = sorted(lots, key=lambda item: item.lot_order)
    awarded: list[AwardedLot] = []
    assignments: dict[str, Assignment] = {}
    for lot in ordered:
        seated = seated_by_lot.get(lot.lot_id, ())
        ranked: list[tuple[tuple[int, int, str], BidOffer]] = []
        for offer in offers_by_lot.get(lot.lot_id, ()):
            resolution = resolve_tiers(seated, offer.tiers, lot.moq)
            if not resolution.feasible:
                continue
            ranked.append((bid_ranking_key(resolution, offer.tiebreak_hash), offer))
        ranked.sort(key=lambda item: item[0])
        assignment: Assignment | None = None
        reject: str | None = R8_NO_FEASIBLE_TIER if not ranked else None
        for _key, offer in ranked:
            total_capacity = total_capacity_by_merchant.get(offer.merchant_id)
            if total_capacity is None:
                reject = reject or R9_CAPACITY_EXHAUSTED
                continue
            remaining = remaining_capacity(total_capacity, offer.merchant_id, awarded)
            # Contract section 11 compares the bid's capacity only; a bid that
            # cannot supply the lot's seats is a submission-time rule (R4/R9 note
            # in T06A04), not an award-time one.
            if offer.capacity > remaining:
                reject = R9_CAPACITY_EXHAUSTED
                continue
            assignment = Assignment(
                lot_id=lot.lot_id,
                bid_id=offer.bid_id,
                merchant_id=offer.merchant_id,
                reject=None,
            )
            awarded.append(
                AwardedLot(
                    lot_order=lot.lot_order,
                    merchant_id=offer.merchant_id,
                    seats=lot.seats,
                )
            )
            break
        assignments[lot.lot_id] = assignment or Assignment(
            lot_id=lot.lot_id, bid_id=None, merchant_id=None, reject=reject
        )
    return assignments
