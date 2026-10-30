"""PT-05: tier resolution, feasibility, bid ranking and tie-break determinism.

Checks the ``ranking_v1`` rules against the vectors' shape: each seated entry is
priced with its own shipping and tax, ``n_tier`` counts caps that cover the
total, the chosen tier is the applicable tier with the lowest item price, and a
bid is feasible only at the MOQ. Ranking keys are ordered ascending.
"""

from __future__ import annotations

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fairpool.domain import auction_rules, hashing, money
from fairpool.domain.errors import AuctionError

pytestmark = pytest.mark.property

HEX64 = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)

SEATED = st.lists(
    st.builds(
        auction_rules.SeatedBuyer,
        entry_id=st.uuids().map(str),
        cap_cents=st.integers(min_value=0, max_value=200_000),
        shipping_cents=st.integers(min_value=0, max_value=5_000),
        tax_rate_bps=st.integers(min_value=0, max_value=2_000),
        tax_included=st.booleans(),
    ),
    max_size=8,
    unique_by=lambda buyer: buyer.entry_id,
)
TIERS = st.lists(
    st.builds(
        auction_rules.Tier,
        min_qty=st.integers(min_value=1, max_value=8),
        item_price_cents=st.integers(min_value=0, max_value=100_000),
    ),
    min_size=1,
    max_size=3,
)


@given(SEATED, TIERS, st.integers(min_value=1, max_value=8))
def test_tier_resolution_follows_ranking_v1(
    seated: list[auction_rules.SeatedBuyer],
    tiers: list[auction_rules.Tier],
    moq: int,
) -> None:
    evaluations = auction_rules.evaluate_tiers(seated, tiers)
    assert [item.tier_index for item in evaluations] == list(range(len(tiers)))
    for evaluation, tier in zip(evaluations, tiers, strict=True):
        assert evaluation.min_qty == tier.min_qty
        assert evaluation.item_price_cents == tier.item_price_cents
        assert [item.entry_id for item in evaluation.totals] == [buyer.entry_id for buyer in seated]
        assert evaluation.n_tier == sum(item.within_cap for item in evaluation.totals)
        assert evaluation.applies == (evaluation.n_tier >= tier.min_qty)
        for total, buyer in zip(evaluation.totals, seated, strict=True):
            expected_tax = (
                0
                if buyer.tax_included
                else money.tax_cents(tier.item_price_cents, buyer.tax_rate_bps)
            )
            assert total.item_cents == tier.item_price_cents
            assert total.shipping_cents == buyer.shipping_cents
            assert total.tax_cents == expected_tax
            expected_total = tier.item_price_cents + buyer.shipping_cents + expected_tax
            assert total.total_cents == expected_total
            assert total.within_cap == (expected_total <= buyer.cap_cents)
        accepting = [item.total_cents for item in evaluation.totals if item.within_cap]
        assert evaluation.accepting_totals == tuple(accepting)
        assert evaluation.mean_total_cents == (
            money.mean_total_cents(accepting) if accepting else None
        )
        assert evaluation.max_total_cents == (max(accepting) if accepting else None)

    resolution = auction_rules.resolve_tiers(seated, tiers, moq)
    applicable = [item for item in evaluations if item.applies]
    if not applicable:
        assert resolution.chosen_tier_index is None
        assert resolution.rejection == auction_rules.R8_NO_FEASIBLE_TIER
        assert not resolution.feasible
        with pytest.raises(AuctionError):
            auction_rules.bid_ranking_key(resolution, "00" * 32)
        return
    chosen = min(applicable, key=lambda item: (item.item_price_cents, item.tier_index))
    assert resolution.chosen_tier_index == chosen.tier_index
    assert resolution.feasible == (chosen.n_tier >= moq)
    if resolution.feasible:
        assert resolution.rejection is None
        key = auction_rules.bid_ranking_key(resolution, "ab" * 32)
        assert key == (chosen.mean_total_cents, chosen.max_total_cents, "ab" * 32)
    else:
        assert resolution.rejection == auction_rules.R8_INFEASIBLE


def test_tier_totals_use_each_entries_shipping_and_tax() -> None:
    seated = [
        auction_rules.SeatedBuyer("a", cap_cents=100_000, shipping_cents=0, tax_rate_bps=0),
        auction_rules.SeatedBuyer("b", cap_cents=100_000, shipping_cents=2_000, tax_rate_bps=1_000),
        auction_rules.SeatedBuyer(
            "c", cap_cents=100_000, shipping_cents=500, tax_rate_bps=1_000, tax_included=True
        ),
    ]
    (evaluation,) = auction_rules.evaluate_tiers(seated, [auction_rules.Tier(1, 10_000)])
    totals = {item.entry_id: item for item in evaluation.totals}
    assert totals["a"].total_cents == 10_000
    assert totals["b"].tax_cents == 1_000
    assert totals["b"].total_cents == 13_000
    assert totals["c"].tax_cents == 0
    assert totals["c"].total_cents == 10_500


def test_tier_resolution_rejects_invalid_inputs() -> None:
    buyer = auction_rules.SeatedBuyer("a", cap_cents=1, shipping_cents=0, tax_rate_bps=0)
    with pytest.raises(AuctionError):
        auction_rules.evaluate_tiers([buyer, buyer], [auction_rules.Tier(1, 1)])
    with pytest.raises(AuctionError):
        auction_rules.evaluate_tiers([buyer], [auction_rules.Tier(0, 1)])
    with pytest.raises(AuctionError):
        auction_rules.resolve_tiers([buyer], [auction_rules.Tier(1, 1)], moq=0)


BID_CANDIDATES = st.lists(
    st.builds(
        auction_rules.BidCandidate,
        bid_id=st.uuids().map(str),
        merchant_id=st.uuids().map(str),
        mean_total_cents=st.integers(min_value=0, max_value=200_000),
        max_total_cents=st.integers(min_value=0, max_value=200_000),
        tiebreak_hash=HEX64,
    ),
    max_size=10,
    unique_by=lambda candidate: candidate.bid_id,
)


@given(BID_CANDIDATES)
def test_rank_bids_sorts_by_key_and_is_a_permutation(
    candidates: list[auction_rules.BidCandidate],
) -> None:
    ranked = auction_rules.rank_bids(candidates)
    keys = [candidate.key() for candidate in ranked]
    assert keys == sorted(keys)
    assert sorted(candidate.bid_id for candidate in ranked) == sorted(
        candidate.bid_id for candidate in candidates
    )


@given(HEX64, st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=10))
def test_tiebreak_is_deterministic_and_merchant_specific(lot_seed: str, merchant: str) -> None:
    other = merchant + "x"
    first = hashing.tiebreak_hash(lot_seed, merchant)
    assert first == hashing.tiebreak_hash(lot_seed, merchant)
    assert first != hashing.tiebreak_hash(lot_seed, other)


@given(
    st.integers(min_value=0, max_value=100),
    st.lists(st.tuples(st.integers(min_value=1, max_value=5), st.booleans()), max_size=6),
    st.integers(min_value=0, max_value=100),
)
def test_capacity_never_exceeds_merchant_total(
    total_capacity: int,
    lots: list[tuple[int, bool]],
    bid_capacity: int,
) -> None:
    awarded = [
        auction_rules.AwardedLot(
            lot_order=index + 1,
            merchant_id="merchant" if mine else "other",
            seats=seats,
        )
        for index, (seats, mine) in enumerate(lots)
    ]
    used = sum(lot.seats for lot in awarded if lot.merchant_id == "merchant")
    assert auction_rules.remaining_capacity(total_capacity, "merchant", awarded) == (
        total_capacity - used
    )
    allowed = auction_rules.capacity_ok(total_capacity, "merchant", bid_capacity, awarded)
    assert allowed == (bid_capacity <= total_capacity - used)
    if allowed:
        assert used + bid_capacity <= total_capacity
