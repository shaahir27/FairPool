"""R1 to R7 bid guards, in the contract order of section 5 of config-and-errors.

The pure rules compare a normalised bid against the lot's published requirements;
R8 and R9 need the seated entries and are covered by PT-05, PT-06 and the vectors.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fairpool.domain import auction_rules
from fairpool.domain.auction_rules import BidFacts, LotFacts, Tier

CLOSE = "2026-11-05T12:00:00+00:00"
FUND_DEADLINE = "2026-11-07T12:00:00+00:00"
CAPTURE_GRACE_S = 120
# R6's horizon: the fund deadline plus the capture grace, per docs/registry.md.
VALIDITY_HORIZON = "2026-11-07T12:02:00+00:00"

LOT = LotFacts(
    lot_id="lot-1",
    lot_order=1,
    moq=2,
    seats=4,
    product_key="monitor-27",
    condition="new",
    bundle_key="monitor-stand-cable",
    max_delivery_days=7,
    min_returns_days=30,
    fund_deadline_at=FUND_DEADLINE,
    capture_grace_s=CAPTURE_GRACE_S,
)


def facts(**overrides: Any) -> BidFacts:
    base: dict[str, Any] = {
        "bid_id": "bid-1",
        "merchant_id": "m-1",
        "schema_ok": True,
        "confirmed": True,
        "submitted_at": "2026-11-05T11:00:00+00:00",
        "bid_close_at": CLOSE,
        "product_key": "monitor-27",
        "condition": "new",
        "bundle_key": "monitor-stand-cable",
        "tiers": (Tier(min_qty=2, item_price_cents=47000),),
        "capacity": 4,
        "tax_mode": "INCLUDED",
        "shipping_cents_by_zone": {},
        "delivery_days": 7,
        "returns_days": 30,
        "validity_end": "2026-11-08T12:00:00+00:00",
        "blocking_flags": (),
    }
    base.update(overrides)
    return BidFacts(**base)


def _rejects(
    candidate: BidFacts, *, merchant_eligible: bool = True, flat: bool = True
) -> str | None:
    return auction_rules.bid_rejection(
        candidate, LOT, merchant_eligible=merchant_eligible, flat_delivered=flat
    )


def test_a_complete_confirmed_bid_passes() -> None:
    assert _rejects(facts()) is None


def test_r1_schema_covers_a_missing_tier_list() -> None:
    assert _rejects(facts(schema_ok=False)) == auction_rules.R1_SCHEMA
    assert _rejects(facts(tiers=())) == auction_rules.R1_SCHEMA
    assert _rejects(facts(delivery_days=0)) == auction_rules.R1_SCHEMA


def test_r1_late_uses_the_contract_clock_boundary() -> None:
    # Clarification 1: admission is strictly before close, closure is at or after it.
    assert _rejects(facts(submitted_at="2026-11-05T12:00:01+00:00")) == auction_rules.R1_LATE
    assert _rejects(facts(submitted_at=CLOSE)) == auction_rules.R1_LATE


def test_r1_unconfirmed() -> None:
    assert _rejects(facts(confirmed=False)) == auction_rules.R1_UNCONFIRMED


def test_r2_merchant_ineligible() -> None:
    assert _rejects(facts(), merchant_eligible=False) == auction_rules.R2_MERCHANT_INELIGIBLE


def test_r3_product_condition_and_bundle() -> None:
    assert _rejects(facts(product_key="monitor-24")) == auction_rules.R3_PRODUCT_MISMATCH
    assert _rejects(facts(condition="used")) == auction_rules.R3_CONDITION_MISMATCH
    assert _rejects(facts(bundle_key=None)) == auction_rules.R3_BUNDLE_MISMATCH


def test_r3_bundle_is_not_required_when_the_lot_has_none() -> None:
    lot = replace(LOT, bundle_key=None)
    candidate = facts(bundle_key=None)
    assert auction_rules.bid_rejection(candidate, lot, merchant_eligible=True) is None


def test_r4_declared_capacity_must_cover_the_lot_seats() -> None:
    # R4 in docs/registry.md is seats, not the lot minimum: a winner that cannot
    # supply every seat would leave buyers holding an offer nobody can serve.
    assert _rejects(facts(capacity=None)) == auction_rules.R4_CAPACITY
    assert _rejects(facts(capacity=0)) == auction_rules.R4_CAPACITY
    assert _rejects(facts(capacity=3)) == auction_rules.R4_CAPACITY
    assert _rejects(facts(capacity=4)) is None


def test_r5_delivery_and_returns_against_the_lot_terms() -> None:
    assert _rejects(facts(delivery_days=8)) == auction_rules.R5_DELIVERY
    assert _rejects(facts(returns_days=29)) == auction_rules.R5_RETURNS


def test_r5_flat_delivered_requires_tax_included_and_no_shipping() -> None:
    assert _rejects(facts(tax_mode="RATE_TABLE")) == auction_rules.R5_TAX_COVERAGE
    assert _rejects(facts(shipping_cents_by_zone={"US-EAST": 500})) == auction_rules.R5_TAX_COVERAGE
    assert _rejects(facts(tax_mode="RATE_TABLE"), flat=False) is None


def test_r6_validity_must_reach_the_fund_deadline_plus_the_capture_grace() -> None:
    assert _rejects(facts(validity_end=VALIDITY_HORIZON)) is None
    assert _rejects(facts(validity_end="2026-11-07T12:01:59+00:00")) == auction_rules.R6_VALIDITY
    assert _rejects(facts(validity_end=CLOSE)) == auction_rules.R6_VALIDITY


def test_r7_blocking_flags_only() -> None:
    # LOW_SIMILARITY is a warning, so it never arrives in blocking_flags (INT-1).
    assert _rejects(facts(blocking_flags=("R3_BUNDLE_MISMATCH",))) == auction_rules.R7_AI_BLOCKING


def test_rules_are_applied_in_contract_order() -> None:
    broken = facts(schema_ok=False, confirmed=False, product_key="other")
    assert _rejects(broken, merchant_eligible=False) == auction_rules.R1_SCHEMA
