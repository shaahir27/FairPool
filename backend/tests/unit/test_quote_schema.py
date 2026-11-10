from __future__ import annotations

import pytest
from pydantic import ValidationError

from fairpool.adapters.ai.schemas import Quote


def quote(**overrides: object) -> Quote:
    base: dict[str, object] = {
        "product_text": "27-inch 4K monitors",
        "condition": "NEW",
        "bundle_contents": ["monitor", "stand"],
        "capacity": 12,
        "target_quantity": None,
        "moq": 3,
        "tiers": [{"min_qty": 3, "item_price": "470.00"}],
        "shipping_by_zone": {},
        "tax": {"mode": "INCLUDED", "rate_bps_by_region": {}},
        "delivery_sla_days": 7,
        "returns_days": 30,
        "valid_until": "2026-12-01",
        "total_capacity": None,
        "evidence_note": None,
        "ambiguities": [],
    }
    base.update(overrides)
    return Quote.model_validate(base)


def test_a_date_only_valid_until_means_through_that_day_utc() -> None:
    assert quote().valid_until == "2026-12-01T23:59:59Z"


def test_an_explicit_timestamp_is_left_alone() -> None:
    assert quote(valid_until="2026-12-01T12:30:00Z").valid_until == "2026-12-01T12:30:00Z"


def test_a_timestamp_without_a_zone_is_still_refused() -> None:
    with pytest.raises(ValidationError):
        quote(valid_until="2026-12-01T12:30:00")
