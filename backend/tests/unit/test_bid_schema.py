"""CR-11: the bid schema requires one declared total, and the crowd code is coarsened.

``total_capacity`` used to be optional, and ``handlers.py`` then read that lot's own
``capacity`` as the merchant's total -- so one merchant stating 10,000 on each of ten
lots was treated as able to supply 10,000 to every one of them. The key is now required
by ``bids.py`` and R9 compares a single declared number across the pool.
"""

from __future__ import annotations

from typing import Any

import pytest

from fairpool.domain.errors import ApplicationError
from fairpool.modules.auction.bids import BID_KEYS, validate_structured
from fairpool.modules.auction.handlers import merchant_reject_copy


def bid(*, drop: str | None = None, **overrides: Any) -> dict[str, Any]:
    """The contracted ``bid_revisions.structured`` shape (db-schema.md, FR-AU-02)."""
    base: dict[str, Any] = {
        "v": 1,
        "product_key": "monitor-27",
        "condition": "NEW",
        "bundle_contents": ["monitor"],
        "capacity": 12,
        "total_capacity": 24,
        "target_quantity": 12,
        "moq": 3,
        "tiers": [{"min_qty": 3, "item_price_cents": 47000}],
        "shipping_cents_by_zone": {},
        "tax": {"mode": "INCLUDED"},
        "delivery": {"sla_days": 7},
        "returns": {"days": 30},
        "valid_until": "2026-12-01T00:00:00Z",
        "evidence": {"note": "reserved", "url": None},
    }
    base.update(overrides)
    if drop is not None:
        base.pop(drop)
    return base


def test_total_capacity_is_a_required_bid_key() -> None:
    # T06A06 acceptance (CR-11): a bid that states no total is not a bid.
    assert "total_capacity" in BID_KEYS
    with pytest.raises(ApplicationError) as raised:
        validate_structured(bid(drop="total_capacity"), flat_delivered=True)
    assert raised.value.code == "VALIDATION_ERROR"


@pytest.mark.parametrize("value", [0, -1, "12", None])
def test_total_capacity_must_be_a_positive_integer(value: Any) -> None:
    with pytest.raises(ApplicationError) as raised:
        validate_structured(bid(total_capacity=value), flat_delivered=True)
    assert raised.value.code == "VALIDATION_ERROR"


def test_a_bid_that_declares_its_total_still_validates() -> None:
    validate_structured(bid(), flat_delivered=True)
    validate_structured(bid(total_capacity=12), flat_delivered=True)


@pytest.mark.parametrize(
    "reason",
    ["R8_INFEASIBLE", "R8_NO_FEASIBLE_TIER", "R9_CAPACITY_EXHAUSTED"],
)
def test_the_codes_that_describe_the_crowd_are_coarsened(reason: str) -> None:
    # CR-11: R8 and R9 are decided from seated buyers' hidden caps.
    assert merchant_reject_copy(reason) == "did not meet the lot's feasibility or capacity rules"


@pytest.mark.parametrize("reason", ["R1_LATE", "R1_UNCONFIRMED", "R6_VALIDITY", "R7_AI_BLOCKING"])
def test_a_bid_that_failed_its_own_terms_is_told_exactly_why(reason: str) -> None:
    assert merchant_reject_copy(reason) == reason
