"""Live verification: read-only PayPal GETs, amount and status match per item.

This is the primary verification path when the PayPal MCP read tools are not
available (S10). Each manifest item is fetched with ``get_order`` and nothing else;
a capture matches only when its ID is present, its status is COMPLETED and its
amount equals the expected cents (I3, I4).

Three bounds keep one call finite: at most :data:`MAX_ITEMS` manifest items are
verified per request, the merchant's window is charged once per item, and at most
:data:`MAX_CONCURRENT_GETS` GETs are in flight at once. ``api.md`` section 4.2 caps
the endpoint at ten live calls a minute; charged per item that is a budget of 60
provider GETs per minute per merchant, and a request may cost at most the whole
budget so a large lot is still verifiable in one call. A refused call makes no GET,
and the response reports totals over the items it actually verified.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict, deque
from typing import TYPE_CHECKING, Any, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import ApplicationError
from fairpool.domain.payments import PaymentError, PayPalOrder
from fairpool.modules.fulfillment.manifest import manifest_items

if TYPE_CHECKING:
    from uuid import UUID

    from fairpool.modules.fulfillment.service import AwardedLot
    from fairpool.ports import Clock

#: One request verifies at most this many manifest items; the rest wait for the next
#: call, and the totals cover only the items this one read.
MAX_ITEMS = 200

#: Provider GETs in flight per request (the live endpoint is bound with ``asyncio``).
MAX_CONCURRENT_GETS = 5

#: api.md section 4.2's ten live calls a minute, charged per item: 60 GETs a minute.
VERIFY_PROVIDER_BUDGET = 60
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

    def take(self, key: str, cost: int, now: float) -> None:
        """Charge ``cost`` provider calls at once, or refuse without charging anything."""
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            self._hits.move_to_end(key)
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) + cost > self.limit:
                retry_after = max(1, int(self.window_s - (now - hits[0])) + 1)
                raise RateLimited(retry_after)
            hits.extend([now] * cost)
            while len(self._hits) > MAX_LIMIT_KEYS:
                self._sweep(now)
                if len(self._hits) <= MAX_LIMIT_KEYS:
                    break
                self._hits.popitem(last=False)

    def _sweep(self, now: float) -> None:
        expired = [
            key for key, hits in self._hits.items() if not hits or now - hits[-1] >= self.window_s
        ]
        for key in expired:
            del self._hits[key]


_LIMITER = _Window(limit=VERIFY_PROVIDER_BUDGET, window_s=VERIFY_WINDOW_S)


class ReadGateway(Protocol):
    async def get_order(self, paypal_order_id: str) -> PayPalOrder: ...


def _result(item: dict[str, Any], order: PayPalOrder) -> dict[str, Any]:
    capture = next(
        (found for found in order.captures if found.id == item["paypal_capture_id"]),
        None,
    )
    status = str(capture.status) if capture is not None else "NOT_FOUND"
    amount = int(capture.amount_cents) if capture is not None else 0
    return {
        "paypal_order_id": item["paypal_order_id"],
        "paypal_capture_id": item["paypal_capture_id"],
        "expected_amount_cents": item["amount_cents"],
        "paypal_capture_status": status,
        "paypal_amount_cents": amount,
        "match": capture is not None and status == "COMPLETED" and amount == item["amount_cents"],
    }


async def verify_lot(
    session: AsyncSession,
    *,
    awarded: AwardedLot,
    merchant_id: UUID,
    gateway: ReadGateway,
    clock: Clock,
) -> dict[str, Any]:
    manifest = await manifest_items(session, awarded.id)
    items = manifest[:MAX_ITEMS]
    # One charge per item, capped at the whole minute's budget: a lot with more
    # captures than the budget still verifies its first MAX_ITEMS in one request.
    charge = max(1, min(len(items), VERIFY_PROVIDER_BUDGET))
    _LIMITER.take(str(merchant_id), charge, time.monotonic())
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_GETS)

    async def fetch(item: dict[str, Any]) -> PayPalOrder:
        async with semaphore:
            return await gateway.get_order(item["paypal_order_id"])

    outcomes = await asyncio.gather(*(fetch(item) for item in items), return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome, PaymentError):
            # Without the provider's answer there is nothing honest to report.
            raise ApplicationError("PAYPAL_UNAVAILABLE") from None
        if isinstance(outcome, BaseException):
            raise outcome
    results = [
        _result(item, cast(PayPalOrder, outcome))
        for item, outcome in zip(items, outcomes, strict=True)
    ]
    matched = sum(1 for result in results if result["match"])
    checked_at = await clock.db_now(session)
    return {
        "lot_id": awarded.id,
        "checked_at": checked_at,
        "matched": matched,
        "total": len(results),
        "all_match": matched == len(results),
        "expected_captured_total_cents": sum(item["amount_cents"] for item in items),
        "paypal_captured_total_cents": sum(result["paypal_amount_cents"] for result in results),
        "items": results,
    }


__all__ = [
    "MAX_CONCURRENT_GETS",
    "MAX_ITEMS",
    "RateLimited",
    "ReadGateway",
    "VERIFY_PROVIDER_BUDGET",
    "VERIFY_WINDOW_S",
    "verify_lot",
]
