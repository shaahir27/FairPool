"""PT-04: money arithmetic is exact in integer cents.

Tax and mean rounding are checked against an independent half-up reference
(``Fraction`` plus ``math.floor``), PayPal strings must round-trip, and floats,
booleans and malformed strings are rejected at runtime.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fairpool.domain import money
from fairpool.domain.errors import MoneyError

pytestmark = pytest.mark.property

CENTS = st.integers(min_value=0, max_value=10**9)
RATE_BPS = st.integers(min_value=0, max_value=10_000)


def _half_up(numerator: int, denominator: int) -> int:
    return math.floor(Fraction(numerator, denominator) + Fraction(1, 2))


@given(CENTS, RATE_BPS)
def test_tax_matches_round_half_up(item_cents: int, rate_bps: int) -> None:
    assert money.tax_cents(item_cents, rate_bps) == _half_up(item_cents * rate_bps, 10_000)


@given(CENTS, CENTS, CENTS)
def test_total_is_item_plus_shipping_plus_tax(
    item_cents: int, shipping_cents: int, tax_cents: int
) -> None:
    assert money.total_cents(item_cents, shipping_cents, tax_cents) == (
        item_cents + shipping_cents + tax_cents
    )


@given(st.lists(CENTS, min_size=1, max_size=50))
def test_mean_matches_round_half_up_and_stays_within_bounds(values: list[int]) -> None:
    result = money.mean_total_cents(values)
    assert result == _half_up(sum(values), len(values))
    assert min(values) <= result <= max(values)


@given(CENTS)
def test_paypal_string_round_trips(cents: int) -> None:
    text = money.to_paypal_string(cents)
    assert re.fullmatch(r"\d+\.\d{2}", text)
    assert money.parse_paypal_string(text) == cents


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_money_rejects_floats(value: float) -> None:
    with pytest.raises(MoneyError):
        money.tax_cents(value, 100)
    with pytest.raises(MoneyError):
        money.to_paypal_string(value)
    with pytest.raises(MoneyError):
        money.parse_paypal_string(value)


def test_money_rejects_booleans_and_negatives() -> None:
    with pytest.raises(MoneyError):
        money.tax_cents(True, 100)
    with pytest.raises(MoneyError):
        money.total_cents(100, -1, 0)
    with pytest.raises(MoneyError):
        money.to_paypal_string(-1)
    with pytest.raises(MoneyError):
        money.mean_total_cents([])
    with pytest.raises(MoneyError):
        money.mean_total_cents([1, 2.0])  # type: ignore[list-item]


@pytest.mark.parametrize(
    "text",
    ["", "1", "1.2", "1.234", " 1.00", "1.00 ", "-1.00", "+1.00", ".99", "1,00", "1e3", "1.0O"],
)
def test_parse_rejects_malformed_strings(text: str) -> None:
    with pytest.raises(MoneyError):
        money.parse_paypal_string(text)


def test_parse_rejects_non_strings() -> None:
    with pytest.raises(MoneyError):
        money.parse_paypal_string(100)  # type: ignore[arg-type]
