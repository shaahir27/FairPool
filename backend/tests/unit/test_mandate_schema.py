"""The MANDATE schema is closed (``ai-schemas.md`` section 9, CR-14, FR-AI-06).

The task's safety rests on the shape being unrepresentable when it is wrong: a predicate
outside the vocabulary, a parameter set that belongs to another predicate, and an invented
``reserved`` field must all fail validation rather than be carried into a mandate a buyer
ratifies and a token is minted from.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from fairpool.adapters.ai.schemas import Mandate

VALID: dict[str, Any] = {
    "pool_scope": {"pool_ids": ["6f1d0d9a-0000-4000-8000-000000000001"], "category": None},
    "max_total": {"amount": "600.00", "currency": "USD"},
    "expires": "2026-11-30",
    "conditions": [
        {"predicate": "PRICE_ABOVE", "action": "REASK", "params": {"amount": "520.00"}},
        {
            "predicate": "FUNDING_BELOW",
            "action": "HALT",
            "params": {"percent": 60, "hours_before_close": 24},
        },
        {"predicate": "BLOCKING_FLAG_ON_AWARD", "action": "REASK", "params": {}},
        {"predicate": "DELIVERY_AFTER", "action": "REASK", "params": {"date": "2026-11-25"}},
    ],
    "ambiguities": [],
    "clarifying_question": None,
}


def payload(**overrides: Any) -> dict[str, Any]:
    base = deepcopy(VALID)
    base.update(overrides)
    return base


def test_every_predicate_in_the_vocabulary_parses() -> None:
    mandate = Mandate.model_validate(VALID)
    assert [c.predicate for c in mandate.conditions] == [
        "PRICE_ABOVE",
        "FUNDING_BELOW",
        "BLOCKING_FLAG_ON_AWARD",
        "DELIVERY_AFTER",
    ]
    assert mandate.max_total.amount == "600.00"


def test_a_predicate_outside_the_vocabulary_is_refused() -> None:
    """An invented predicate is dropped-and-asked, never guessed at (section 9 rule 4)."""
    bad = payload(conditions=[{"predicate": "REFUND_IF_LATE", "action": "HALT", "params": {}}])
    with pytest.raises(ValidationError):
        Mandate.model_validate(bad)


def test_params_that_belong_to_another_predicate_are_refused() -> None:
    """Typed params, so a predicate cannot carry a parameter it does not use."""
    bad = payload(
        conditions=[{"predicate": "PRICE_ABOVE", "action": "REASK", "params": {"percent": 60}}]
    )
    with pytest.raises(ValidationError):
        Mandate.model_validate(bad)


def test_a_no_parameter_predicate_refuses_parameters() -> None:
    bad = payload(
        conditions=[
            {
                "predicate": "BLOCKING_FLAG_ON_AWARD",
                "action": "REASK",
                "params": {"amount": "10.00"},
            }
        ]
    )
    with pytest.raises(ValidationError):
        Mandate.model_validate(bad)


def test_the_model_cannot_set_the_reserved_acts() -> None:
    """``reserved`` has no field, and ``extra="forbid"`` rejects it outright."""
    with pytest.raises(ValidationError):
        Mandate.model_validate(payload(reserved=["payment_approval"]))


def test_an_action_outside_the_closed_set_is_refused() -> None:
    bad = payload(
        conditions=[
            {"predicate": "NO_AWARD_BY", "action": "IGNORE", "params": {"date": "2026-11-28"}}
        ]
    )
    with pytest.raises(ValidationError):
        Mandate.model_validate(bad)


def test_a_number_is_not_an_amount() -> None:
    """Amounts are strings so no floating point enters the system (section 1 rule 7)."""
    with pytest.raises(ValidationError):
        Mandate.model_validate(payload(max_total={"amount": 600.0, "currency": "USD"}))


def test_a_non_usd_currency_is_carried_and_left_for_the_server() -> None:
    """The schema does not decide currency; the server turns it into an ambiguity."""
    mandate = Mandate.model_validate(payload(max_total={"amount": "600.00", "currency": "EUR"}))
    assert mandate.max_total.currency == "EUR"


def test_expires_accepts_a_written_date_and_a_relative_phrase_becomes_null() -> None:
    assert Mandate.model_validate(payload(expires="30 November 2026")).expires == "2026-11-30"
    assert Mandate.model_validate(payload(expires="next Friday")).expires is None


def test_a_condition_date_is_canonicalised_the_same_way() -> None:
    mandate = Mandate.model_validate(
        payload(
            conditions=[
                {"predicate": "NO_AWARD_BY", "action": "HALT", "params": {"date": "Nov 28, 2026"}}
            ]
        )
    )
    assert mandate.conditions[0].params.date == "2026-11-28"


def test_more_than_five_conditions_is_refused() -> None:
    six = [
        {"predicate": "BLOCKING_FLAG_ON_AWARD", "action": "REASK", "params": {}} for _ in range(6)
    ]
    with pytest.raises(ValidationError):
        Mandate.model_validate(payload(conditions=six))
