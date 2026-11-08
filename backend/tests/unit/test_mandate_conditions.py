"""CR-14: a ratified mandate carries only conditions the server can evaluate (FR-AI-06).

``ai-schemas.md`` section 9 defines a closed five-predicate vocabulary with typed params.
The browser renders the mandate and the buyer ratifies it, but the browser is not the
authority: these tests prove the server refuses to mint a token from a condition it cannot
evaluate, whether the predicate is invented or the params belong to another predicate.
"""

from __future__ import annotations

from typing import Any

import pytest

from fairpool.domain.errors import ApplicationError
from fairpool.modules.identity.mandate import validate_conditions

SHA = "a" * 64


def refuse(conditions: Any, *, sha: str | None = SHA) -> None:
    with pytest.raises(ApplicationError) as refused:
        validate_conditions(conditions, ratification_sha256=sha)
    assert refused.value.code == "VALIDATION_ERROR"


def test_every_predicate_in_the_vocabulary_is_accepted() -> None:
    accepted = validate_conditions(
        [
            {"predicate": "PRICE_ABOVE", "action": "REASK", "params": {"amount": "520.00"}},
            {
                "predicate": "FUNDING_BELOW",
                "action": "HALT",
                "params": {"percent": 60, "hours_before_close": 24},
            },
            {"predicate": "BLOCKING_FLAG_ON_AWARD", "action": "PROCEED", "params": {}},
            {"predicate": "DELIVERY_AFTER", "action": "REASK", "params": {"date": "2026-11-25"}},
            {"predicate": "NO_AWARD_BY", "action": "HALT", "params": {"date": "2026-11-28"}},
        ],
        ratification_sha256=SHA,
    )
    assert [condition["predicate"] for condition in accepted] == [
        "PRICE_ABOVE",
        "FUNDING_BELOW",
        "BLOCKING_FLAG_ON_AWARD",
        "DELIVERY_AFTER",
        "NO_AWARD_BY",
    ]
    assert accepted[0] == {
        "predicate": "PRICE_ABOVE",
        "params": {"amount": "520.00"},
        "action": "REASK",
    }


def test_an_unknown_predicate_is_refused() -> None:
    refuse([{"predicate": "REFUND_IF_LATE", "action": "HALT", "params": {}}])


def test_params_belonging_to_another_predicate_are_refused() -> None:
    refuse([{"predicate": "PRICE_ABOVE", "action": "REASK", "params": {"percent": 60}}])


def test_an_extra_param_is_refused() -> None:
    """Closed means closed: a key the predicate does not use has nowhere to be evaluated."""
    refuse(
        [
            {
                "predicate": "BLOCKING_FLAG_ON_AWARD",
                "action": "REASK",
                "params": {"amount": "10.00"},
            }
        ]
    )


def test_an_unknown_action_is_refused() -> None:
    refuse([{"predicate": "NO_AWARD_BY", "action": "IGNORE", "params": {"date": "2026-11-28"}}])


def test_more_than_five_conditions_is_refused() -> None:
    six = [
        {"predicate": "BLOCKING_FLAG_ON_AWARD", "action": "REASK", "params": {}} for _ in range(6)
    ]
    refuse(six)


def test_a_condition_without_a_ratification_hash_is_refused() -> None:
    """The hash is the buyer's ratification; conditions nobody ratified cannot bind a token."""
    refuse(
        [{"predicate": "BLOCKING_FLAG_ON_AWARD", "action": "REASK", "params": {}}],
        sha=None,
    )


def test_a_malformed_amount_is_refused() -> None:
    """Money crosses the boundary as a ``D.CC`` string; a float would lose cents (I3)."""
    refuse([{"predicate": "PRICE_ABOVE", "action": "REASK", "params": {"amount": 520.0}}])
    refuse([{"predicate": "PRICE_ABOVE", "action": "REASK", "params": {"amount": "520.123"}}])


def test_a_percentage_outside_one_to_one_hundred_is_refused() -> None:
    refuse(
        [
            {
                "predicate": "FUNDING_BELOW",
                "action": "HALT",
                "params": {"percent": 0, "hours_before_close": 24},
            }
        ]
    )


def test_a_condition_date_must_be_a_calendar_day() -> None:
    """A relative phrase the model could not resolve is not a value the server can test."""
    refuse([{"predicate": "DELIVERY_AFTER", "action": "REASK", "params": {"date": "next Friday"}}])
    refuse([{"predicate": "NO_AWARD_BY", "action": "HALT", "params": {"date": None}}])


def test_a_condition_that_is_not_an_object_is_refused() -> None:
    refuse(["PRICE_ABOVE"])
