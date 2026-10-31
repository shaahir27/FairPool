"""Contracted payment values shared by the network adapter and offline fake."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class PaymentError(Exception):
    def __init__(self, category: str, code: str, *, debug_id: str | None = None) -> None:
        self.category = category
        self.code = code
        self.debug_id = debug_id
        super().__init__(category)


class NotEnabled(PaymentError):
    def __init__(self) -> None:
        super().__init__("CONFIG", "ROUTER_DISABLED")


@dataclass(frozen=True)
class Payee:
    email: str | None
    merchant_id: str | None


@dataclass(frozen=True)
class PayPalAuthorization:
    id: str
    status: str
    amount_cents: int
    expires_at: datetime | None


@dataclass(frozen=True)
class PayPalCapture:
    id: str
    status: str
    amount_cents: int
    final_capture: bool
    auth_id: str | None


@dataclass(frozen=True)
class PayPalRefund:
    id: str
    status: str
    amount_cents: int


@dataclass(frozen=True)
class TrackerItem:
    paypal_order_id: str
    capture_id: str
    carrier: str
    tracking_number: str


@dataclass(frozen=True)
class TrackerResult:
    capture_id: str
    ok: bool
    error: str | None
    debug_id: str | None


@dataclass(frozen=True)
class SetupToken:
    id: str = field(repr=False)
    approve_url: str = field(repr=False)


@dataclass(frozen=True)
class PaymentToken:
    id: str = field(repr=False)
    label: str


@dataclass(frozen=True)
class ChargeResult:
    order_id: str
    capture_id: str | None
    capture_status: str | None
    error: str | None


@dataclass(frozen=True)
class PayPalOrder:
    id: str
    status: str
    intent: str
    currency: str
    amount_cents: int
    payee_email: str | None
    payee_merchant_id: str | None
    payer_id: str | None
    payer_country: str | None
    approve_url: str | None = field(repr=False)
    authorizations: list[PayPalAuthorization]
    captures: list[PayPalCapture]
    debug_id: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class CreateOrderRequest:
    buyer_order_id: str
    attempt: int
    amount_cents: int
    breakdown: dict[str, int]
    description: str
    reference_id: str
    payee: Payee
    return_url: str
    cancel_url: str
    shipping: dict[str, Any] | None
    payload_level: int
    extra_headers: dict[str, str]
