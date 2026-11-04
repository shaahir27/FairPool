"""Demo fault injection around the gateway (T07A04; ``paypal-adapter.md`` §10).

The toggles live in this one module, in process, bounded by a TTL, and only the
``FaultInjectingGateway`` here ever sets ``PayPal-Mock-Response``. Nothing outside
this file may name that header (AGENTS.md section 5), and the adapter itself
refuses the header unless ``MOCK_TOGGLES_ENABLED`` is set.

The wrapper never invents a money signal: ``force_capture_failure`` returns a
capture resource that reads ``DECLINED``, which the existing BO-11 transition
already handles, and no PayPal call is made, so the real authorization stays
voidable. ``delay_webhooks`` is recorded and labelled only; webhook business
rules do not change (P4).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Final, cast
from uuid import uuid4

from fairpool.domain.errors import ApplicationError
from fairpool.domain.payments import (
    ChargeResult,
    CreateOrderRequest,
    Payee,
    PaymentToken,
    PayPalAuthorization,
    PayPalCapture,
    PayPalOrder,
    PayPalRefund,
    SetupToken,
    TrackerItem,
    TrackerResult,
)

#: The honesty label every affected response must carry while a toggle is active.
MOCK_LABEL: Final[str] = "MOCK"

#: ``api.md`` section 3 fixes the three toggle names.
KINDS: Final[tuple[str, ...]] = (
    "paypal_mock_response",
    "force_capture_failure",
    "delay_webhooks",
)

#: The only header this wrapper may add (V6; the adapter's own allowlist matches).
MOCK_HEADER: Final[str] = "PayPal-Mock-Response"

#: The simulated capture's prefix; it is not a PayPal identifier.
SIMULATED_CAPTURE_PREFIX: Final[str] = "SIMULATED-"


@dataclass
class _Toggle:
    value: str | None
    expires_at: float


#: Indirection so a test can advance the clock without sleeping.
_clock: Callable[[], float] = time.monotonic

_active: dict[str, _Toggle] = {}


def set_toggle(*, kind: str, value: str | None, ttl_s: int, enabled: bool) -> None:
    """Arm one toggle for ``ttl_s`` seconds; refuse when the gate is off."""
    if not enabled:
        # api.md section 3: the demo toggle exists only with MOCK_TOGGLES_ENABLED.
        raise ApplicationError("FEATURE_DISABLED")
    if kind not in KINDS:
        raise ApplicationError("VALIDATION_ERROR")
    _active[kind] = _Toggle(value, _clock() + max(1, int(ttl_s)))


def reset() -> None:
    """Clear every toggle (the ops reset helper and every test's cleanup)."""
    _active.clear()


def active_kinds() -> list[str]:
    """The toggles still inside their TTL, expired entries pruned."""
    now = _clock()
    for kind in list(_active):
        if _active[kind].expires_at <= now:
            del _active[kind]
    return sorted(_active)


def is_active() -> bool:
    return bool(active_kinds())


def label() -> str | None:
    """``MOCK`` while anything is active, so a response can say so (I13)."""
    return MOCK_LABEL if active_kinds() else None


def _take(kind: str) -> _Toggle | None:
    """Consume one pending toggle: its effect applies to the next call only."""
    if kind not in active_kinds():
        return None
    return _active.pop(kind, None)


class FaultInjectingGateway:
    """The gateway protocol with the three demo toggles in front of it.

    Built by ``wiring.payment_router`` only when ``MOCK_TOGGLES_ENABLED`` is set,
    so a deployment without the flag never has this object at all.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def client_token(self, domain: str) -> tuple[str, int]:
        return cast(tuple[str, int], await self.inner.client_token(domain))

    async def create_order(self, req: CreateOrderRequest) -> PayPalOrder:
        toggle = _take("paypal_mock_response")
        if toggle is not None:
            # V6 verified DUPLICATE_INVOICE_ID through this header; the request
            # carries it once so a later create is a normal call again.
            req = replace(req, extra_headers={MOCK_HEADER: toggle.value or ""})
        return cast(PayPalOrder, await self.inner.create_order(req))

    async def get_order(self, paypal_order_id: str) -> PayPalOrder:
        return cast(PayPalOrder, await self.inner.get_order(paypal_order_id))

    async def authorize_order(self, paypal_order_id: str, *, request_key: str) -> PayPalOrder:
        return cast(
            PayPalOrder,
            await self.inner.authorize_order(paypal_order_id, request_key=request_key),
        )

    async def get_authorization(self, auth_id: str) -> PayPalAuthorization:
        return cast(PayPalAuthorization, await self.inner.get_authorization(auth_id))

    async def capture_authorization(
        self, auth_id: str, *, amount_cents: int, request_key: str
    ) -> PayPalCapture:
        if _take("force_capture_failure") is not None:
            # No PayPal call: the simulated DECLINED resource is what BO-11 reads,
            # and the real authorization is still there to be voided.
            return PayPalCapture(
                f"{SIMULATED_CAPTURE_PREFIX}{uuid4().hex}",
                "DECLINED",
                amount_cents,
                True,
                auth_id,
            )
        return cast(
            PayPalCapture,
            await self.inner.capture_authorization(
                auth_id, amount_cents=amount_cents, request_key=request_key
            ),
        )

    async def get_capture(self, capture_id: str) -> PayPalCapture:
        return cast(PayPalCapture, await self.inner.get_capture(capture_id))

    async def void_authorization(self, auth_id: str) -> None:
        await self.inner.void_authorization(auth_id)

    async def refund_capture(
        self, capture_id: str, *, amount_cents: int | None, request_key: str
    ) -> PayPalRefund:
        return cast(
            PayPalRefund,
            await self.inner.refund_capture(
                capture_id, amount_cents=amount_cents, request_key=request_key
            ),
        )

    async def get_refund(self, refund_id: str) -> PayPalRefund:
        return cast(PayPalRefund, await self.inner.get_refund(refund_id))

    async def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        return cast(bool, await self.inner.verify_webhook(headers, raw_body))

    async def list_webhooks(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self.inner.list_webhooks())

    async def add_trackers(self, items: list[TrackerItem]) -> list[TrackerResult]:
        return cast(list[TrackerResult], await self.inner.add_trackers(items))

    async def create_setup_token(
        self, entry_id: str, attempt: str, return_url: str, cancel_url: str
    ) -> SetupToken:
        return cast(
            SetupToken,
            await self.inner.create_setup_token(entry_id, attempt, return_url, cancel_url),
        )

    async def create_payment_token(
        self, setup_token_id: str, entry_id: str, attempt: str
    ) -> PaymentToken:
        return cast(
            PaymentToken,
            await self.inner.create_payment_token(setup_token_id, entry_id, attempt),
        )

    async def delete_payment_token(self, payment_token_id: str, entry_id: str) -> None:
        await self.inner.delete_payment_token(payment_token_id, entry_id)

    async def charge_vault(
        self, buyer_order_id: str, payment_token_id: str, total_cents: int, payee: Payee
    ) -> ChargeResult:
        return cast(
            ChargeResult,
            await self.inner.charge_vault(buyer_order_id, payment_token_id, total_cents, payee),
        )
