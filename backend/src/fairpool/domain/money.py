"""Integer-cent money arithmetic.

Contract: ``docs/contracts/fairness-and-hashing.md`` section 9. Money is always
integer cents (BD-14, I3); floats are rejected at runtime even though the type
hints say ``int``. ``"D.CC"`` strings exist only at the PayPal boundary.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .errors import MoneyError

#: PayPal amount strings: exactly two decimals, no sign, no grouping (contract section 9).
PAYPAL_AMOUNT_PATTERN = re.compile(r"^\d+\.\d{2}$")


def _as_cents(value: object, field: str) -> int:
    """Return ``value`` as non-negative integer cents or raise ``MoneyError``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise MoneyError(f"{field} must be integer cents, got {type(value).__name__}")
    if value < 0:
        raise MoneyError(f"{field} must be non-negative, got {value}")
    return value


def tax_cents(item_cents: int, rate_bps: int) -> int:
    """Tax on the item price only, rounded half up: ``(item * rate + 5000) // 10000``."""
    item = _as_cents(item_cents, "item_cents")
    rate = _as_cents(rate_bps, "rate_bps")
    return (item * rate + 5000) // 10000


def total_cents(item_cents: int, shipping_cents: int, tax_cents: int) -> int:
    """Delivered total in cents; shipping is untaxed (contract section 9)."""
    item = _as_cents(item_cents, "item_cents")
    shipping = _as_cents(shipping_cents, "shipping_cents")
    tax = _as_cents(tax_cents, "tax_cents")
    return item + shipping + tax


def mean_total_cents(values: Sequence[int]) -> int:
    """Mean of integer-cent values, rounded half up: ``(sum + n // 2) // n``."""
    items = [_as_cents(value, "values[]") for value in values]
    count = len(items)
    if count == 0:
        raise MoneyError("mean_total_cents needs at least one value")
    return (sum(items) + count // 2) // count


def to_paypal_string(cents: int) -> str:
    """Format non-negative cents as ``"D.CC"`` with exactly two decimals."""
    value = _as_cents(cents, "cents")
    return f"{value // 100}.{value % 100:02d}"


def parse_paypal_string(amount: object) -> int:
    """Parse a PayPal ``"D.CC"`` string strictly; reject anything else."""
    if not isinstance(amount, str):
        raise MoneyError(f"PayPal amount must be a string, got {type(amount).__name__}")
    if PAYPAL_AMOUNT_PATTERN.fullmatch(amount) is None:
        raise MoneyError(f"PayPal amount must match ^\\d+\\.\\d{{2}}$: {amount!r}")
    dollars, fraction = amount.split(".")
    return int(dollars) * 100 + int(fraction)
