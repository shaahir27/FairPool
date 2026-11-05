"""The live verification bounds: 200 items a request, five GETs in flight, 60 a minute."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from fairpool.domain.payments import PayPalCapture, PayPalOrder
from fairpool.modules.fulfillment.verification import (
    MAX_CONCURRENT_GETS,
    MAX_ITEMS,
    VERIFY_PROVIDER_BUDGET,
    RateLimited,
    verify_lot,
)


class Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> Rows:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class ManifestSession:
    """The one query ``manifest_items`` runs, answered from a list."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def execute(self, statement: Any, params: Any = None) -> Rows:
        return Rows(self.rows)


class Clock:
    async def db_now(self, session: Any) -> datetime:
        return datetime(2026, 11, 5, tzinfo=UTC)


class Awarded:
    def __init__(self) -> None:
        self.id = uuid4()


def manifest(count: int) -> list[dict[str, Any]]:
    return [
        {
            "paypal_order_id": f"ORDER-{index}",
            "paypal_capture_id": f"CAP-{index}",
            "amount_cents": 1_000,
            "created_at": datetime(2026, 11, 5, tzinfo=UTC),
        }
        for index in range(count)
    ]


class Gateway:
    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def get_order(self, paypal_order_id: str) -> PayPalOrder:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        capture = "CAP-" + paypal_order_id.split("-")[-1]
        return PayPalOrder(
            id=paypal_order_id,
            status="COMPLETED",
            intent="AUTHORIZE",
            currency="USD",
            amount_cents=1_000,
            payee_email=None,
            payee_merchant_id=None,
            payer_id=None,
            payer_country="US",
            approve_url=None,
            authorizations=[],
            captures=[PayPalCapture(capture, "COMPLETED", 1_000, True, None)],
            debug_id=None,
            raw={},
        )


async def run(count: int, *, merchant_id: UUID | None = None) -> tuple[dict[str, Any], Gateway]:
    session = ManifestSession(manifest(count))
    gateway = Gateway()
    result = await verify_lot(
        session,  # type: ignore[arg-type]
        awarded=Awarded(),  # type: ignore[arg-type]
        merchant_id=merchant_id or uuid4(),
        gateway=gateway,
        clock=Clock(),  # type: ignore[arg-type]
    )
    return result, gateway


async def test_one_request_verifies_at_most_two_hundred_items() -> None:
    """A lot with more captures reports totals over the first 200, not over the lot."""
    result, gateway = await run(250)

    assert gateway.calls == MAX_ITEMS == 200
    assert result["total"] == 200 and len(result["items"]) == 200
    assert result["matched"] == 200 and result["all_match"] is True
    assert result["expected_captured_total_cents"] == 200 * 1_000
    assert result["paypal_captured_total_cents"] == 200 * 1_000


async def test_provider_gets_run_behind_a_semaphore_of_five() -> None:
    result, gateway = await run(20)

    assert gateway.calls == 20
    assert 1 < gateway.max_active <= MAX_CONCURRENT_GETS == 5
    assert result["all_match"] is True


async def test_the_window_is_charged_per_item_against_a_sixty_call_budget() -> None:
    merchant_id = uuid4()
    first, _gateway = await run(40, merchant_id=merchant_id)
    assert first["total"] == 40

    # 40 charged, so 20 remain: a 25-item lot is refused and makes no provider GET.
    with pytest.raises(RateLimited) as refused:
        await run(25, merchant_id=merchant_id)
    assert refused.value.code == "RATE_LIMITED"
    assert refused.value.retry_after >= 1

    # Exactly the remaining budget still fits.
    second, _gateway = await run(VERIFY_PROVIDER_BUDGET - 40, merchant_id=merchant_id)
    assert second["total"] == VERIFY_PROVIDER_BUDGET - 40
