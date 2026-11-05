"""Live verification: read-only PayPal GETs, amount and status match per item.

This is the primary verification path when the PayPal MCP read tools are not
available (S10). Each manifest order is fetched with ``get_order`` and nothing else;
a capture matches only when its ID is present, its status is COMPLETED and its
amount equals the expected cents (I3, I4). The endpoint makes live calls, so each
merchant is limited to 10 requests a minute. The window lives here rather than in
``infra/limits`` so this module owns its bound; a refused call makes no GET.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import ApplicationError
from fairpool.domain.payments import PaymentError, PayPalOrder
from fairpool.modules.fulfillment.manifest import manifest_items

if TYPE_CHECKING:
    from uuid import UUID

    from fairpool.modules.fulfillment.service import AwardedLot
    from fairpool.ports import Clock

#: api.md section 4.2: the live endpoint makes PayPal GETs, so it is capped.
VERIFY_LIMIT = 10
VERIFY_WINDOW_S = 60.0
MAX_LIMIT_KEYS = 4096


class RateLimited(ApplicationError):
    """The contract's 429; the router adds ``Retry-After`` to the envelope."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("RATE_LIMITED")
        self.retry_after = retry_after


class _Window:
    def __init__(self, *, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str, now: float) -> None:
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            self._hits.move_to_end(key)
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                raise RateLimited(max(1, int(self.window_s - (now - hits[0])) + 1))
            hits.append(now)
            while len(self._hits) > MAX_LIMIT_KEYS:
                self._hits.popitem(last=False)


_LIMITER = _Window(limit=VERIFY_LIMIT, window_s=VERIFY_WINDOW_S)


def reset_rate_limiter() -> None:
    """Clear the process-local window (tests that need a fresh merchant budget)."""
    with _LIMITER._lock:
        _LIMITER._hits.clear()


class ReadGateway(Protocol):
    async def get_order(self, paypal_order_id: str) -> PayPalOrder: ...


async def verify_lot(
    session: AsyncSession,
    *,
    awarded: AwardedLot,
    merchant_id: UUID,
    gateway: ReadGateway,
    clock: Clock,
) -> dict[str, Any]:
    _LIMITER.check(str(merchant_id), time.monotonic())
    items = await manifest_items(session, awarded.id)
    results: list[dict[str, Any]] = []
    matched = 0
    paypal_total = 0
    for item in items:
        try:
            order = await gateway.get_order(item["paypal_order_id"])
        except PaymentError:
            # Without the provider's answer there is nothing honest to report.
            raise ApplicationError("PAYPAL_UNAVAILABLE") from None
        capture = next(
            (found for found in order.captures if found.id == item["paypal_capture_id"]),
            None,
        )
        status = str(capture.status) if capture is not None else "NOT_FOUND"
        amount = int(capture.amount_cents) if capture is not None else 0
        if capture is not None:
            paypal_total += amount
        match = capture is not None and status == "COMPLETED" and amount == item["amount_cents"]
        matched += 1 if match else 0
        results.append(
            {
                "paypal_order_id": item["paypal_order_id"],
                "paypal_capture_id": item["paypal_capture_id"],
                "expected_amount_cents": item["amount_cents"],
                "paypal_capture_status": status,
                "paypal_amount_cents": amount,
                "match": match,
            }
        )
    checked_at = await clock.db_now(session)
    return {
        "lot_id": awarded.id,
        "checked_at": checked_at,
        "matched": matched,
        "total": len(items),
        "all_match": matched == len(items),
        "expected_captured_total_cents": sum(item["amount_cents"] for item in items),
        "paypal_captured_total_cents": paypal_total,
        "items": results,
    }


__all__ = [
    "RateLimited",
    "ReadGateway",
    "VERIFY_LIMIT",
    "VERIFY_WINDOW_S",
    "reset_rate_limiter",
    "verify_lot",
]
