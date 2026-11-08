"""Grounding of a written money amount (``ai-schemas.md`` section 2.4, CR-12).

The grounders decide whether an amount the model proposes actually appears in the buyer's
message, so they are the only thing between a fabricated ``max_total`` and a confirmed
request. They had no direct test, which is how three of them went wrong at once: the label
alternation matched the letters inside "recap", a currency written after the number did not
ground its amount at all, and a comma-grouped figure grounded only its first one to three
digits.

``ai-schemas.md`` section 2.4 states the rule in words -- "$650", "650 dollars" and
"USD 650" all ground USD -- so these are those three spellings, plus the shapes that must
ground nothing.
"""

from __future__ import annotations

import pytest

from fairpool.adapters.ai.client import cap_values, monetary_values, money_cents

#: The three spellings section 2.4 names. All must ground 65000. A currency written
#: *before* the number in words ("us dollars 650") is deliberately not on this list: it
#: grounds nothing, the field stays null and the pipeline asks, which is the fail-closed
#: direction the contract wants rather than a reason to widen the matcher.
USD_SPELLINGS: tuple[str, ...] = ("$650", "650 dollars", "USD 650")

#: Each states no cap at all: the number is a quantity, or is not a money figure.
NOT_A_CAP: tuple[str, ...] = (
    "Recap 650 units available",
    "I want a recap of 650 monitors",
    "escape 600 total cost",
    "miccap 500",
    "we ordered 700 cables",
)


@pytest.mark.parametrize("text", USD_SPELLINGS)
def test_a_stated_amount_grounds_whatever_shape_the_currency_takes(text: str) -> None:
    assert monetary_values(text) == {65000}, text


def test_a_currency_written_after_the_number_grounds_it_too() -> None:
    """CR-12: "650 dollars" states the amount as plainly as "$650" does."""
    assert monetary_values("new monitor for 650 dollars to NY") == {65000}
    assert cap_values("new monitor for 650 dollars to NY") == {65000}


@pytest.mark.parametrize("text", NOT_A_CAP)
def test_a_number_that_is_not_stated_as_money_grounds_no_cap(text: str) -> None:
    """The letters inside a word are not a label, and a quantity is not a cap."""
    assert cap_values(text) == set(), text


def test_a_comma_grouped_figure_is_one_number_not_its_first_digits() -> None:
    """ "$1,200" is $1,200.00; grounding it as $1.00 also accepted a fabricated $1.00."""
    assert monetary_values("price was $1,200") == {120000}
    assert cap_values("cap: 1,200.50") == {120050}
    assert cap_values("cap 99,999") == {9999900}


def test_a_malformed_group_overshoots_in_the_safe_direction() -> None:
    """ "$1,20" is not a grouped figure, so only the plainly stated part grounds."""
    assert monetary_values("$1,20") == {100}


def test_money_cents_reads_a_grouped_figure_without_floats() -> None:
    assert money_cents("1,200.50") == 120050
    assert money_cents("1200") == 120000


def test_an_explicit_cap_label_still_wins_over_the_fallback() -> None:
    """``cap_values`` prefers its own bounded label and only then falls back."""
    assert cap_values("actual budget is $500, cap $600") == {50000}
    assert cap_values("my cap is $600") == {60000}
    assert cap_values("budget of 600 USD") == {60000}
