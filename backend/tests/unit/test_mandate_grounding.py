"""MANDATE grounding: the server, not the model, owns the cap and the vocabulary.

``GeminiAI._meaning`` is the deterministic half of every AI task: the model proposes, and
these rules accept, repair or refuse. For a mandate the load-bearing rule is that it may
narrow a ceiling but never raise one, so a fabricated cap cannot become authority a buyer
ratifies (``ai-schemas.md`` section 9, CR-14).
"""

from __future__ import annotations

from typing import Any

import pytest

from fairpool.adapters.ai.client import GeminiAI

CANDIDATES: list[dict[str, Any]] = [
    {"pool_id": "p1", "category": "monitors", "condition": "NEW"},
    {"pool_id": "p2", "category": "monitors", "condition": "NEW"},
]


class _Logger:
    async def write(self, **_kwargs: Any) -> None: ...

    log = write


async def _no_generate(**_kwargs: Any) -> Any:
    raise AssertionError("grounding must not call the provider")


def ai() -> GeminiAI:
    return GeminiAI(
        api_key="test", model_parse="m", model_sim="m", logger=_Logger(), generate=_no_generate
    )


def mandate(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pool_scope": {"pool_ids": ["p1"], "category": "monitors"},
        "max_total": {"amount": "600.00", "currency": "USD"},
        "expires": None,
        "conditions": [],
        "ambiguities": [],
        "clarifying_question": None,
    }
    base.update(overrides)
    return base


def payload(cap_cents: int | None = 60000) -> dict[str, Any]:
    return {
        "message": "my cap is $600",
        "proposal": {"max_total_cents": cap_cents},
        "candidates": CANDIDATES,
    }


def test_a_cap_at_the_buyers_own_cap_is_accepted() -> None:
    ai()._meaning("MANDATE", mandate(), payload(), "my cap is $600")


def test_the_model_cannot_raise_the_cap_the_buyer_stated() -> None:
    with pytest.raises(ValueError, match="cannot raise the cap"):
        ai()._meaning(
            "MANDATE",
            mandate(max_total={"amount": "900.00", "currency": "USD"}),
            payload(),
            "my cap is $600",
        )


def test_a_lower_cap_the_message_states_is_accepted() -> None:
    """Lowering a ceiling is allowed; only raising one is refused.

    The phrase has to be one the grounders read as a cap. "do not go over $520" is
    deliberately *not* one: it carries no label, so it grounds nothing and the proposal
    falls back to asking rather than turning an unlabelled number into authority. A
    ceiling stated that way belongs in a PRICE_ABOVE condition instead.
    """
    ai()._meaning(
        "MANDATE",
        mandate(max_total={"amount": "520.00", "currency": "USD"}),
        payload(),
        "my cap is $520",
    )


def test_a_lower_cap_the_message_never_states_is_refused() -> None:
    with pytest.raises(ValueError, match="Ungrounded amount"):
        ai()._meaning(
            "MANDATE",
            mandate(max_total={"amount": "520.00", "currency": "USD"}),
            payload(),
            "my cap is $600",
        )


def test_a_pool_outside_the_candidates_is_refused() -> None:
    with pytest.raises(ValueError, match="Unauthorized candidate ID"):
        ai()._meaning(
            "MANDATE",
            mandate(pool_scope={"pool_ids": ["p9"], "category": "monitors"}),
            payload(),
            "my cap is $600",
        )


def test_a_category_no_candidate_offers_is_refused() -> None:
    with pytest.raises(ValueError, match="Unauthorized category"):
        ai()._meaning(
            "MANDATE",
            mandate(pool_scope={"pool_ids": ["p1"], "category": "laptops"}),
            payload(),
            "my cap is $600",
        )


def test_an_expiry_the_message_never_states_is_dropped_not_guessed() -> None:
    output = mandate(expires="2026-11-30")
    ai()._meaning("MANDATE", output, payload(), "my cap is $600")
    assert output["expires"] is None


def test_a_stated_expiry_survives() -> None:
    output = mandate(expires="2026-11-30")
    ai()._meaning("MANDATE", output, payload(), "my cap is $600, do not act after Nov 30, 2026")
    assert output["expires"] == "2026-11-30"


def test_a_dated_condition_with_no_stated_date_is_dropped() -> None:
    """Better to show the buyer one fewer condition than one nobody can evaluate."""
    output = mandate(
        conditions=[
            {"predicate": "NO_AWARD_BY", "action": "HALT", "params": {"date": None}},
            {"predicate": "BLOCKING_FLAG_ON_AWARD", "action": "REASK", "params": {}},
        ]
    )
    ai()._meaning("MANDATE", output, payload(), "my cap is $600")
    assert [c["predicate"] for c in output["conditions"]] == ["BLOCKING_FLAG_ON_AWARD"]


def test_the_prompt_was_not_bumped_for_the_new_task() -> None:
    """A shared SYSTEM string means a new task would invalidate the v10 evidence.

    Bumping ``PROMPT_VERSION`` also switches off ``gate_check``'s v10 intake check, which
    is keyed on that constant, so the prompt sentences for MANDATE have to arrive together
    with their own measured spots. Until then MANDATE is confined to its closed schema and
    to ``_meaning``, and this test fails if someone bumps the version without doing that
    work -- the failure is the reminder, not an obstacle.
    """
    from fairpool.adapters.ai import client as client_module

    assert client_module.PROMPT_VERSION == "phase2-gemini-v10"
    assert "MANDATE," not in client_module.SYSTEM
