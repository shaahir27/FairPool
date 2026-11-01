"""T03B01: the deterministic manual-request validator (api.md "Intake", CR-3).

Every acceptance rule from the contract paragraph gets a named case: template
identity, quantity one, USD only, a region inside a frozen zone, integer cents
inside the pool's band, an absolute ``required_by`` date and only firm terms the
template supports. Unsupported or float-shaped input is a rejection, never a
guess.
"""

from __future__ import annotations

from typing import Any

import pytest

from fairpool.domain.errors import ApplicationError
from fairpool.domain.request_rules import (
    ValidatedRequest,
    revalidate_canonical,
    validate_manual_request,
)

TEMPLATE: dict[str, Any] = {
    "pool_id": "11111111-1111-4111-8111-111111111111",
    "product_key": "monitor-27-4k",
    "variant": "black",
    "title": "27-inch 4K monitor",
    "condition": "NEW",
    "quantity": 1,
    "currency": "USD",
    "bundle_contents": ["monitor", "stand", "power cable"],
    "firm_terms": ["matte screen"],
    "delivery_sla_days": 7,
    "fund_by": "2026-11-10",
    "min_return_days": 14,
    "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY", "NJ", "PA"]}],
    "cap_min_cents": 1000,
    "cap_max_cents": 100000,
}


def payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "delivery": {"region": "NY"},
        "required_by": "2026-11-30",
        "max_total_cents": 60000,
        "firm": ["matte screen"],
        "preferences": ["black bezel"],
    }
    base.update(overrides)
    return base


def test_valid_request_produces_the_canonical_shape_and_hash() -> None:
    result = validate_manual_request(TEMPLATE, payload())
    assert isinstance(result, ValidatedRequest)
    assert result.zone_id == "US-EAST"
    assert result.cap_cents == 60000
    canonical = result.canonical
    assert canonical["v"] == 1
    assert canonical["pool_id"] == TEMPLATE["pool_id"]
    assert canonical["product_key"] == "monitor-27-4k"
    assert canonical["variant"] == "black"
    assert canonical["condition"] == "NEW"
    assert canonical["quantity"] == 1
    assert canonical["currency"] == "USD"
    assert canonical["delivery"] == {"zone_id": "US-EAST", "region": "NY", "country": "US"}
    assert canonical["required_by"] == "2026-11-30"
    assert canonical["max_total_cents"] == 60000
    assert canonical["firm"] == ["matte screen"]
    assert canonical["preferences"] == ["black bezel"]
    # request_hash is SHA-256 of the canonical JSON (fairness-and-hashing.md §2).
    from fairpool.domain.hashing import request_hash

    assert result.request_hash == request_hash(canonical)
    assert len(result.request_hash) == 64


def test_region_resolves_its_zone_from_the_frozen_template() -> None:
    for region, zone in (("NY", "US-EAST"), ("NJ", "US-EAST"), ("PA", "US-EAST")):
        result = validate_manual_request(TEMPLATE, payload(delivery={"region": region}))
        assert result.zone_id == zone
        assert result.canonical["delivery"]["region"] == region


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda p: p.update(delivery={"region": "CA"}), id="region-outside-zones"),
        pytest.param(lambda p: p.update(delivery={"region": "ny"}), id="region-lowercase"),
        pytest.param(lambda p: p.update(delivery={"region": ""}), id="region-empty"),
        pytest.param(lambda p: p.update(delivery={"zone_id": "US-EAST"}), id="zone-not-region"),
        pytest.param(lambda p: p.pop("delivery"), id="missing-delivery"),
        pytest.param(lambda p: p.pop("required_by"), id="missing-required-by"),
        pytest.param(lambda p: p.pop("max_total_cents"), id="missing-cap"),
        pytest.param(lambda p: p.update(extra_field=1), id="unknown-field"),
        pytest.param(lambda p: p.update(product_key="other-monitor"), id="product-mismatch"),
        pytest.param(lambda p: p.update(condition="REFURBISHED"), id="condition-mismatch"),
        pytest.param(lambda p: p.update(variant="white"), id="variant-mismatch"),
        pytest.param(lambda p: p.update(quantity=2), id="quantity-above-one"),
        pytest.param(lambda p: p.update(currency="EUR"), id="currency-not-usd"),
        pytest.param(lambda p: p.update(required_by="in three weeks"), id="relative-date"),
        pytest.param(lambda p: p.update(required_by="2026-13-01"), id="impossible-date"),
        pytest.param(lambda p: p.update(required_by="2026-11-16"), id="before-latest-delivery"),
        pytest.param(lambda p: p.update(max_total_cents=0), id="cap-zero"),
        pytest.param(lambda p: p.update(max_total_cents=-1), id="cap-negative"),
        pytest.param(lambda p: p.update(max_total_cents=60000.0), id="cap-float"),
        pytest.param(lambda p: p.update(max_total_cents="600.00"), id="cap-string"),
        pytest.param(lambda p: p.update(max_total_cents=True), id="cap-bool"),
        pytest.param(lambda p: p.update(max_total_cents=999), id="cap-below-band"),
        pytest.param(lambda p: p.update(max_total_cents=100001), id="cap-above-band"),
        pytest.param(lambda p: p.update(firm=["quantum screen"]), id="unsupported-firm-term"),
        pytest.param(lambda p: p.update(firm=["matte screen", "Matte Screen"]), id="dup-firm-case"),
        pytest.param(lambda p: p.update(firm=[7]), id="firm-not-strings"),
        pytest.param(
            lambda p: p.update(delivery={"region": "NY", "country": "US"}), id="delivery-extra-key"
        ),
    ],
)
def test_invalid_requests_are_rejected_not_guessed(mutation: Any) -> None:
    bad = payload()
    mutation(bad)
    with pytest.raises(ApplicationError) as excinfo:
        validate_manual_request(TEMPLATE, bad)
    assert excinfo.value.code == "VALIDATION_ERROR"


def test_boundary_dates_and_caps_are_inclusive() -> None:
    # fund_by 2026-11-10 plus 7 days SLA: the latest delivery date itself is valid.
    assert validate_manual_request(TEMPLATE, payload(required_by="2026-11-17")).zone_id
    assert validate_manual_request(TEMPLATE, payload(max_total_cents=1000)).cap_cents == 1000
    assert validate_manual_request(TEMPLATE, payload(max_total_cents=100000)).cap_cents == 100000


def test_bundle_items_are_supported_firm_terms() -> None:
    result = validate_manual_request(TEMPLATE, payload(firm=["monitor", "stand"]))
    assert result.canonical["firm"] == ["monitor", "stand"]


def test_template_without_band_accepts_any_positive_cap() -> None:
    template = {k: v for k, v in TEMPLATE.items() if k not in ("cap_min_cents", "cap_max_cents")}
    assert validate_manual_request(template, payload(max_total_cents=1)).cap_cents == 1
    with pytest.raises(ApplicationError):
        validate_manual_request(template, payload(max_total_cents=0))


def test_revalidation_round_trips_a_stored_canonical() -> None:
    result = validate_manual_request(TEMPLATE, payload())
    revalidate_canonical(TEMPLATE, result.canonical, result.request_hash)


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(lambda c, h: (c.update(max_total_cents=59000), None)[1], id="cap-rewritten"),
        pytest.param(lambda c, h: (c["delivery"].update(region="ON"), None)[1], id="region-moved"),
        pytest.param(lambda c, h: (c.update(required_by="2026-11-15"), None)[1], id="date-moved"),
        pytest.param(lambda c, h: (c["firm"].append("quantum screen"), None)[1], id="firm-added"),
        pytest.param(lambda c, h: (c.update(currency="EUR"), None)[1], id="currency-changed"),
        pytest.param(lambda c, h: (c.update(v=2), None)[1], id="version-changed"),
        pytest.param(lambda c, h: (c.pop("preferences"), None)[1], id="key-removed"),
        pytest.param(lambda c, h: (c.update(injected=1), None)[1], id="key-added"),
        pytest.param(
            lambda c, h: h[:-1] + ("0" if h[-1] != "0" else "1"),
            id="hash-mismatch",
        ),
    ],
)
def test_corrupted_stored_records_are_integrity_errors(corrupt: Any) -> None:
    import json

    result = validate_manual_request(TEMPLATE, payload())
    canonical = json.loads(json.dumps(result.canonical))
    stored_hash = corrupt(canonical, result.request_hash) or result.request_hash
    with pytest.raises(ApplicationError) as excinfo:
        revalidate_canonical(TEMPLATE, canonical, stored_hash)
    assert excinfo.value.code == "INTEGRITY_ERROR"


def test_missing_product_key_in_template_fails_closed() -> None:
    template = {k: v for k, v in TEMPLATE.items() if k != "product_key"}
    with pytest.raises(ApplicationError) as excinfo:
        validate_manual_request(template, payload())
    assert excinfo.value.code == "VALIDATION_ERROR"
