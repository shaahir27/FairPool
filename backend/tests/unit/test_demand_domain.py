"""CR-17 / FR-DM-02: the cluster key is deterministic, never a similarity score.

Two buyers who describe the same product in different words must land in one
cluster; a different condition, variant or bundle must not. These are the properties
the threshold rule and the one-pool-per-cluster guarantee rest on.
"""

from __future__ import annotations

import pytest

from fairpool.domain.demand import cluster_key, normalize_text


def key(**overrides: object) -> str:
    fields: dict[str, object] = {
        "product_key": "monitor-27-4k",
        "condition": "NEW",
        "variant": "black",
        "bundle_contents": ["monitor", "stand", "power cable"],
    }
    fields.update(overrides)
    return cluster_key(**fields)  # type: ignore[arg-type]


def test_case_whitespace_and_punctuation_do_not_split_a_cluster() -> None:
    assert key(product_key="Monitor 27 4K") == key(product_key="monitor-27-4k")
    assert key(product_key="  monitor-27-4k  ") == key()
    assert key(variant="Black") == key(variant="black")


def test_bundle_order_does_not_split_a_cluster() -> None:
    assert key(bundle_contents=["power cable", "monitor", "stand"]) == key()


def test_a_different_condition_variant_or_product_is_a_different_cluster() -> None:
    assert key(condition="REFURBISHED") != key()
    assert key(variant="white") != key()
    assert key(product_key="monitor-32-4k") != key()
    assert key(bundle_contents=["monitor"]) != key()


def test_a_missing_variant_is_its_own_cluster_not_a_wildcard() -> None:
    assert key(variant=None) != key(variant="black")
    assert key(variant=None) == key(variant="")


def test_the_key_is_bounded_hex() -> None:
    assert len(key()) == 64
    assert all(character in "0123456789abcdef" for character in key())
    long_bundle = [f"item {i}" for i in range(30)]
    assert len(key(bundle_contents=long_bundle)) == 64


def test_an_empty_product_or_bundle_is_refused() -> None:
    with pytest.raises(ValueError):
        key(product_key="   ")
    with pytest.raises(ValueError):
        key(bundle_contents=[])
    with pytest.raises(ValueError):
        key(condition="USED")


def test_normalize_text_collapses_separators() -> None:
    assert normalize_text("  27-inch   4K Monitor ") == "27 inch 4k monitor"
    assert normalize_text("USB-C / Dock") == "usb c dock"
