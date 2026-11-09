"""A parsed quote's structured fields must pass the same validator a bid does.

The live sealed-bid gate found the gap: ``_structured`` always emitted an empty
``rate_bps_by_region``, while ``validate_structured`` refuses that key for INCLUDED tax,
so a quote the model parsed could never be submitted through the Merchant Agent API.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fairpool.modules.auction.bids import validate_structured
from fairpool.modules.auction.quote import QuoteService

POOL = SimpleNamespace(
    template={
        "product_key": "monitor-27",
        "condition": "NEW",
        "bundle_contents": ["monitor"],
        "zones": [{"zone_id": "US-EAST", "regions": ["NY"]}],
    }
)

PROPOSAL: dict[str, Any] = {
    "product_text": "monitor",
    "condition": "NEW",
    "bundle_contents": ["monitor"],
    "capacity": 2,
    "target_quantity": 2,
    "moq": 2,
    "tiers": [{"min_qty": 2, "item_price": "470.00"}],
    "shipping_by_zone": {},
    "tax": {"mode": "INCLUDED", "rate_bps_by_region": {}},
    "delivery_sla_days": 7,
    "returns_days": 14,
    "valid_until": "2026-12-31T23:59:00Z",
    "total_capacity": 2,
    "evidence_note": None,
    "ambiguities": [],
}


def service() -> QuoteService:
    return QuoteService(
        clock=None,  # type: ignore[arg-type]
        audit=None,  # type: ignore[arg-type]
        run_logger=None,  # type: ignore[arg-type]
        ai=None,
        model="m",
        prompt_version="p",
        signing_seed=b"k" * 32,
        flat_delivered=True,
    )


def test_an_included_tax_quote_leaves_the_rate_map_out() -> None:
    out = service()._structured(proposal=PROPOSAL, pool=POOL)  # noqa: SLF001 - the shape is the contract
    assert out["tax"] == {"mode": "INCLUDED"}
    validate_structured(out, flat_delivered=True)
