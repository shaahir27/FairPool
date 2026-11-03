"""T06A04: the payload ladder, level by level, and the ceiling that refuses it.

``docs/contracts/paypal-adapter.md`` section 5 fixes what each level adds and says level
0 is "exactly what V2 and V3 verified". ``PAYPAL_PAYLOAD_LEVEL`` is the ceiling, and
S4 verified levels 1 and 2 only, so a request above the ceiling must fail closed rather
than send a shape nobody has seen PayPal accept.

The money in these payloads is strings at the boundary and integer cents everywhere
before it (BD-14, I3): a breakdown that does not sum to the total is a bug, and the
bug has to stop the call.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from fairpool.adapters.paypal.gateway import RestPayPalGateway
from tests.unit.test_payment_gateway import request
from tests.unit.test_settings import make_settings

#: A flat-delivered seat: one delivered price, no shipping or tax line (flat-delivered-bids.md).
FLAT_TOTAL = 47_000


def gateway(level: int) -> RestPayPalGateway:
    return RestPayPalGateway(make_settings(paypal_payload_level=level))


def flat_request(level: int) -> Any:
    """One flat-delivered seat at the given ladder level."""
    return replace(
        request(),
        amount_cents=FLAT_TOTAL,
        breakdown={"item_cents": FLAT_TOTAL, "shipping_cents": 0, "tax_cents": 0},
        payload_level=level,
    )


ADDRESS = {
    "name": "Casey Buyer",
    "line1": "1 Example Street",
    "line2": "",
    "city": "Ithaca",
    "region": "NY",
    "postal_code": "14850",
    "country_code": "US",
}


async def test_level_zero_is_exactly_the_verified_payload() -> None:
    """V2 and V3: intent, one unit, the amount, the payee email, and nothing else."""
    payload = gateway(3).order_payload(flat_request(0))

    assert payload["intent"] == "AUTHORIZE"
    (unit,) = payload["purchase_units"]
    assert unit["amount"] == {"currency_code": "USD", "value": "470.00"}
    assert unit["payee"] == {"email_address": "seller@example.test"}
    assert set(unit) == {"reference_id", "description", "amount", "payee"}
    assert "payment_source" not in payload


async def test_level_one_names_the_order_and_a_per_attempt_invoice() -> None:
    """G8: ``custom_id`` is the buyer order and ``invoice_id`` is unique per attempt.

    The per-attempt suffix is what lets a re-quote be distinguished at PayPal while the
    create key for the same attempt replays to the same order (V6, N9).
    """
    payload = gateway(3).order_payload(flat_request(1))
    (unit,) = payload["purchase_units"]

    assert unit["custom_id"] == "11111111-1111-4111-8111-111111111111"
    assert unit["invoice_id"] == "11111111-1111-4111-8111-111111111111:1"


async def test_level_two_breaks_the_amount_out_and_the_lines_sum() -> None:
    """G8: the breakdown and the item list must add up to the total exactly."""
    payload = gateway(3).order_payload(flat_request(2))
    (unit,) = payload["purchase_units"]
    breakdown = unit["amount"]["breakdown"]

    assert breakdown == {
        "item_total": {"currency_code": "USD", "value": "470.00"},
        "shipping": {"currency_code": "USD", "value": "0.00"},
        "tax_total": {"currency_code": "USD", "value": "0.00"},
    }
    assert unit["items"] == [
        {
            "name": "Fictional item",
            "quantity": "1",
            "unit_amount": {"currency_code": "USD", "value": "470.00"},
        }
    ]
    cents = sum(int(row["value"].replace(".", "")) for row in breakdown.values())
    assert cents == FLAT_TOTAL


async def test_level_three_sends_the_provided_address_and_locks_it() -> None:
    """X and G8: the address the buyer gave us travels with the order, marked provided.

    ``SET_PROVIDED_ADDRESS`` is what stops PayPal offering a different address, which is
    which is why the address is stored encrypted at all (BD-11, N14).
    """
    sent = replace(flat_request(3), shipping=ADDRESS)
    payload = gateway(3).order_payload(sent)
    (unit,) = payload["purchase_units"]

    assert unit["shipping"] == ADDRESS
    context = payload["payment_source"]["paypal"]["experience_context"]
    assert context["shipping_preference"] == "SET_PROVIDED_ADDRESS"
    assert context["user_action"] == "PAY_NOW"
    assert context["return_url"] == "https://example.test/return"
    assert context["cancel_url"] == "https://example.test/cancel"


@pytest.mark.parametrize("ceiling", [0, 1, 2])
async def test_a_level_above_the_ceiling_is_refused_before_any_call(ceiling: int) -> None:
    """The switch is the whole control: nothing unverified leaves the process (FR-PP-06)."""
    with pytest.raises(ValueError):
        gateway(ceiling).order_payload(flat_request(ceiling + 1))


async def test_level_three_without_an_address_is_refused() -> None:
    """A level that cannot be honoured is a bug, not a payload with the field missing."""
    with pytest.raises(ValueError):
        gateway(3).order_payload(flat_request(3))


async def test_a_breakdown_that_does_not_sum_never_reaches_paypal() -> None:
    """I3: the strings are derived from cents, so a mismatch means the math was wrong."""
    wrong = replace(
        request(),
        amount_cents=47_001,
        breakdown={"item_cents": 47_000, "shipping_cents": 0, "tax_cents": 0},
        payload_level=2,
    )
    with pytest.raises(ValueError):
        gateway(2).order_payload(wrong)


async def test_a_negative_breakdown_line_is_refused() -> None:
    wrong = replace(
        request(),
        amount_cents=47_000,
        breakdown={"item_cents": 48_000, "shipping_cents": -1_000, "tax_cents": 0},
        payload_level=2,
    )
    with pytest.raises(ValueError):
        gateway(2).order_payload(wrong)
