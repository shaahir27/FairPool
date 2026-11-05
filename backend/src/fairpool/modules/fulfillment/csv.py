"""The fulfillment CSV: every field quoted, spreadsheet formulas defused.

``QUOTE_ALL`` keeps commas, quotes and newlines inside one cell. A cell whose first
character is a spreadsheet formula prefix gets a leading apostrophe, so an address
a buyer typed cannot execute in a merchant's spreadsheet. Nothing here logs: the
rows are addresses (N14).
"""

from __future__ import annotations

import csv as stdlib_csv
import io
from typing import Any, Final

#: The contracted column order of ``FulfillmentRow`` (api.md section 4.2).
COLUMNS: Final[tuple[str, ...]] = (
    "buyer_order_id",
    "name",
    "line1",
    "line2",
    "city",
    "region",
    "postal_code",
    "country_code",
    "item_cents",
    "shipping_cents",
    "tax_cents",
    "total_cents",
    "paypal_capture_id",
)

_FORMULA_PREFIXES: Final[tuple[str, ...]] = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text[:1] in _FORMULA_PREFIXES:
        return "'" + text
    return text


def render(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = stdlib_csv.writer(buffer, quoting=stdlib_csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in COLUMNS])
    return buffer.getvalue()


__all__ = ["COLUMNS", "render"]
