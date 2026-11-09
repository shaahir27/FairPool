"""The MANDATE request names its closed vocabulary; the shared SYSTEM does not.

A live model guessed its own predicate tags (``price_above``) because nothing in the
request named the closed set, so every proposal failed the schema. The guidance is
appended per task, which keeps the retained INTAKE/QUOTE/RECONCILE prompt untouched.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from fairpool.adapters.ai.client import MANDATE_GUIDANCE, SYSTEM, GeminiAI

VALID = {
    "pool_scope": {"pool_ids": ["p1"], "category": None},
    "max_total": {"amount": "600.00", "currency": "USD"},
    "expires": None,
    "conditions": [],
    "ambiguities": [],
    "clarifying_question": None,
}


class _Logger:
    async def log(self, *_args: Any, **_kwargs: Any) -> None: ...

    write = log


async def test_the_mandate_request_carries_the_closed_vocabulary() -> None:
    captured: dict[str, str] = {}

    async def generate(**kwargs: Any) -> Any:
        captured["prompt"] = str(kwargs["contents"])
        return SimpleNamespace(
            text=json.dumps(VALID),
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=None,
        )

    ai = GeminiAI(
        api_key="offline",
        model_parse="m",
        model_sim="m",
        logger=_Logger(),
        generate=generate,
    )
    out = await ai.parse_mandate(
        None,
        message="my cap is $600",
        proposal={"max_total_cents": 60000},
        candidates=[{"pool_id": "p1", "category": "monitors", "condition": "NEW"}],
    )
    assert out["max_total"]["amount"] == "600.00"
    prompt = captured["prompt"]
    for tag in (
        "PRICE_ABOVE",
        "FUNDING_BELOW",
        "BLOCKING_FLAG_ON_AWARD",
        "DELIVERY_AFTER",
        "NO_AWARD_BY",
    ):
        assert tag in prompt
    assert "reserved" in prompt


def test_the_shared_system_prompt_stays_unchanged() -> None:
    assert MANDATE_GUIDANCE not in SYSTEM
