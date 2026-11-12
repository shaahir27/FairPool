"""The buyer-facing mandate proposal (CR-17, FR-AI-06, ai-schemas.md section 9).

The adapter owns the closed schema and the grounding rules; this module owns the
boundary the browser sees. Two guards are repeated here on purpose, because the card
must never offer a wider permission than the buyer asked for even if the provider is
replaced: the scope stays inside the candidates the server supplied, and the cap never
rises above the one the buyer stated. Anything else -- an outage, a refusal, a malformed
amount -- answers with the manual form rather than blocking the buyer (FR-IN-08's rule,
applied to the mandate by T09B06's acceptance).

The reserved acts are stamped here, never taken from the model: no AI-callable surface
has a payment verb to reserve against (I1, I2, rule 22).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool
from fairpool.domain.errors import MoneyError
from fairpool.domain.money import parse_paypal_string
from fairpool.ports import AIClient

RESERVED_ACTS: Final[tuple[str, ...]] = ("payment_approval",)


def _end_of_day(value: object) -> datetime | None:
    """A stated day becomes its last instant, so an expiry never lands at midnight."""
    if not isinstance(value, str) or not value:
        return None
    try:
        day = datetime.fromisoformat(value)
    except ValueError:
        return None
    return day.replace(hour=23, minute=59, second=59, microsecond=0, tzinfo=UTC)


class MandateProposalService:
    def __init__(self, *, ai: AIClient | None) -> None:
        self.ai = ai

    async def propose(
        self,
        session: AsyncSession,
        *,
        message: str,
        pools: Sequence[Pool],
        max_cap_cents: int | None,
    ) -> dict[str, Any]:
        candidates = [
            {
                "pool_id": str(pool.id),
                "category": pool.template["product_key"],
                "condition": pool.template["condition"],
            }
            for pool in pools
        ]
        selected = [str(pool.id) for pool in pools]
        if self.ai is None:
            return self._manual(selected, max_cap_cents)
        try:
            output = await self.ai.parse_mandate(
                session,
                message=message,
                proposal={"max_total_cents": max_cap_cents},
                candidates=candidates,
            )
            card = self._card(
                output,
                allowed={row["pool_id"]: row["category"] for row in candidates},
                stated_cap=max_cap_cents,
            )
        except Exception:  # noqa: BLE001 - any provider or shape failure means "manual form"
            return self._manual(selected, max_cap_cents)
        return card if card is not None else self._manual(selected, max_cap_cents)

    def _card(
        self, output: dict[str, Any], *, allowed: dict[str, str], stated_cap: int | None
    ) -> dict[str, Any] | None:
        scope = output.get("pool_scope") or {}
        pool_ids = [str(pool_id) for pool_id in scope.get("pool_ids") or []]
        if not set(pool_ids) <= allowed.keys():
            return None
        category = scope.get("category")
        if category is not None and category not in allowed.values():
            return None
        if not pool_ids:
            pool_ids = [pool_id for pool_id, value in allowed.items() if value == category]
        if not pool_ids:
            return None
        amount = (output.get("max_total") or {}).get("amount")
        cap: int | None = None
        if amount is not None:
            try:
                cap = parse_paypal_string(amount)
            except MoneyError:
                return None
            if stated_cap is not None and cap > stated_cap:
                return None
        return {
            "source": "ai",
            "pool_ids": pool_ids,
            # Product-key candidates resolve to explicit pools, not an unrelated template category.
            "category": None,
            "max_cap_cents": cap,
            "expires_at": _end_of_day(output.get("expires")),
            "conditions": list(output.get("conditions") or []),
            "reserved": list(RESERVED_ACTS),
            "ambiguities": list(output.get("ambiguities") or []),
            "clarifying_question": output.get("clarifying_question"),
        }

    @staticmethod
    def _manual(pool_ids: list[str], max_cap_cents: int | None) -> dict[str, Any]:
        return {
            "source": "manual",
            "pool_ids": pool_ids,
            "category": None,
            "max_cap_cents": max_cap_cents,
            "expires_at": None,
            "conditions": [],
            "reserved": list(RESERVED_ACTS),
            "ambiguities": [],
            "clarifying_question": None,
        }
