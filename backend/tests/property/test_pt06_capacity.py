"""PT-06: capacity is shared across lots awarded in published ``lot_order`` (R9).

The properties are stated against the rule, not the implementation: no merchant
is awarded more seats than it declared, a better-ranked bid is only skipped when
capacity blocks it, the outcome does not depend on the input list order, and a
lot with feasible bids but no winner reports ``R9_CAPACITY_EXHAUSTED``.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from fairpool.domain import auction_rules
from fairpool.domain.auction_rules import (
    AwardedLot,
    BidOffer,
    LotFacts,
    SeatedBuyer,
    Tier,
)


@st.composite
def scenarios(draw: st.DrawFn) -> dict[str, Any]:
    merchant_count = draw(st.integers(min_value=1, max_value=2))
    merchants = [f"m-{index}" for index in range(merchant_count)]
    capacity = {merchant: draw(st.integers(min_value=1, max_value=10)) for merchant in merchants}
    lot_count = draw(st.integers(min_value=1, max_value=3))
    lots: list[LotFacts] = []
    seated: dict[str, list[SeatedBuyer]] = {}
    offers: dict[str, list[BidOffer]] = {}
    for index in range(lot_count):
        lot_id = f"lot-{index + 1}"
        seats = draw(st.integers(min_value=1, max_value=6))
        lots.append(
            LotFacts(
                lot_id=lot_id,
                lot_order=index + 1,
                moq=1,
                seats=seats,
                product_key="monitor",
                condition="new",
                bundle_key=None,
                max_delivery_days=14,
                min_returns_days=7,
            )
        )
        seated[lot_id] = [
            SeatedBuyer(
                entry_id=f"{lot_id}-entry-{seat}",
                cap_cents=100_000,
                shipping_cents=0,
                tax_rate_bps=0,
                tax_included=True,
            )
            for seat in range(seats)
        ]
        offers[lot_id] = [
            BidOffer(
                bid_id=f"{lot_id}-bid-{merchant}",
                merchant_id=merchant,
                tiers=(Tier(min_qty=1, item_price_cents=draw(st.integers(1_000, 5_000))),),
                capacity=draw(st.integers(min_value=1, max_value=8)),
                tiebreak_hash=f"{lot_id}-{merchant}",
            )
            for merchant in merchants
        ]
    return {"lots": lots, "seated": seated, "offers": offers, "capacity": capacity}


@given(scenarios())
def test_no_merchant_exceeds_its_declared_capacity(scenario: dict[str, Any]) -> None:
    assignments = auction_rules.select_across_lots(
        scenario["lots"], scenario["seated"], scenario["offers"], scenario["capacity"]
    )
    used: dict[str, int] = {}
    for lot in scenario["lots"]:
        assignment = assignments[lot.lot_id]
        if assignment.bid_id is not None and assignment.merchant_id is not None:
            used[assignment.merchant_id] = used.get(assignment.merchant_id, 0) + lot.seats
    for merchant, seats in used.items():
        assert seats <= scenario["capacity"][merchant]


@given(scenarios())
def test_a_better_ranked_bid_is_only_skipped_for_capacity(
    scenario: dict[str, Any],
) -> None:
    assignments = auction_rules.select_across_lots(
        scenario["lots"], scenario["seated"], scenario["offers"], scenario["capacity"]
    )
    awarded: list[AwardedLot] = []
    for lot in sorted(scenario["lots"], key=lambda item: item.lot_order):
        ranked = sorted(
            (offer for offer in scenario["offers"][lot.lot_id]),
            key=lambda offer: (offer.tiers[0].item_price_cents, offer.tiebreak_hash),
        )
        winner = assignments[lot.lot_id]
        for offer in ranked:
            if offer.bid_id == winner.bid_id:
                break
            remaining = auction_rules.remaining_capacity(
                scenario["capacity"][offer.merchant_id], offer.merchant_id, awarded
            )
            blocked = offer.capacity > remaining or lot.seats > remaining
            assert blocked, f"{offer.bid_id} outranked {winner.bid_id} and was not blocked"
        if winner.bid_id is None and ranked:
            assert all(
                offer.capacity
                > auction_rules.remaining_capacity(
                    scenario["capacity"][offer.merchant_id], offer.merchant_id, awarded
                )
                or lot.seats
                > auction_rules.remaining_capacity(
                    scenario["capacity"][offer.merchant_id], offer.merchant_id, awarded
                )
                for offer in ranked
            )
        if winner.merchant_id is not None:
            awarded.append(
                AwardedLot(lot_order=lot.lot_order, merchant_id=winner.merchant_id, seats=lot.seats)
            )


@given(scenarios())
def test_input_order_does_not_change_the_outcome(scenario: dict[str, Any]) -> None:
    forward = auction_rules.select_across_lots(
        scenario["lots"], scenario["seated"], scenario["offers"], scenario["capacity"]
    )
    backward = auction_rules.select_across_lots(
        list(reversed(scenario["lots"])),
        scenario["seated"],
        scenario["offers"],
        scenario["capacity"],
    )
    assert {key: (item.bid_id, item.merchant_id) for key, item in forward.items()} == {
        key: (item.bid_id, item.merchant_id) for key, item in backward.items()
    }


@given(scenarios())
def test_an_empty_award_reports_capacity_exhaustion(scenario: dict[str, Any]) -> None:
    assignments = auction_rules.select_across_lots(
        scenario["lots"], scenario["seated"], scenario["offers"], scenario["capacity"]
    )
    for lot in scenario["lots"]:
        if assignments[lot.lot_id].bid_id is None:
            assert assignments[lot.lot_id].reject == auction_rules.R9_CAPACITY_EXHAUSTED
