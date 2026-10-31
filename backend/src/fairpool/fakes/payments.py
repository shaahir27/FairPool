"""Deterministic offline payments; never imports a network adapter."""

from dataclasses import replace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fairpool.domain.payments import (
    ChargeResult,
    CreateOrderRequest,
    Payee,
    PaymentError,
    PaymentToken,
    PayPalAuthorization,
    PayPalCapture,
    PayPalOrder,
    PayPalRefund,
    SetupToken,
    TrackerItem,
    TrackerResult,
)


class FakePayPalGateway:
    def __init__(self, *, outcome: str = "completed") -> None:
        if outcome not in {"completed", "declined", "pending", "revoked", "timeout_after_send"}:
            raise ValueError("Unknown fake outcome")
        self.outcome = outcome
        self.replays: dict[str, tuple[object, Any]] = {}
        self.orders: dict[str, PayPalOrder] = {}
        self.authorizations: dict[str, PayPalAuthorization] = {}
        self.captures: dict[str, PayPalCapture] = {}
        self.refunds: dict[str, PayPalRefund] = {}
        self.deleted: set[str] = set()
        self.timeouts: set[str] = set()

    def _id(self, key: str) -> str:
        return "FAKE-" + uuid5(NAMESPACE_URL, key).hex

    def _replay(self, key: str, payload: object, result: Any) -> Any:
        if key in self.replays:
            previous, result = self.replays[key]
            if previous != payload:
                raise PaymentError("BUG", "IDEMPOTENCY_CONFLICT")
            return result
        self.replays[key] = (payload, result)
        return result

    def _timeout(self, key: str) -> None:
        if self.outcome == "timeout_after_send" and key not in self.timeouts:
            self.timeouts.add(key)
            raise PaymentError("UNKNOWN", "OUTCOME_UNKNOWN")

    async def create_order(self, req: CreateOrderRequest) -> PayPalOrder:
        key = f"create:{req.buyer_order_id}:{req.attempt}"
        result = self._replay(
            key,
            req,
            PayPalOrder(
                self._id(key),
                "APPROVED",
                "AUTHORIZE",
                "USD",
                req.amount_cents,
                req.payee.email,
                req.payee.merchant_id,
                "FAKE-PAYER",
                "US",
                None,
                [],
                [],
                None,
                {"simulated": True},
            ),
        )
        self.orders[result.id] = result
        self._timeout(key)
        return result

    async def get_order(self, paypal_order_id: str) -> PayPalOrder:
        return self.orders[paypal_order_id]

    async def authorize_order(self, paypal_order_id: str, *, request_key: str) -> PayPalOrder:
        value = self.orders[paypal_order_id]
        auth = PayPalAuthorization(
            self._id(request_key),
            "DENIED" if self.outcome == "declined" else "CREATED",
            value.amount_cents,
            None,
        )
        result = self._replay(request_key, paypal_order_id, replace(value, authorizations=[auth]))
        self.authorizations[auth.id] = auth
        self.orders[paypal_order_id] = result
        self._timeout(request_key)
        return result

    async def get_authorization(self, auth_id: str) -> PayPalAuthorization:
        return self.authorizations[auth_id]

    async def capture_authorization(
        self, auth_id: str, *, amount_cents: int, request_key: str
    ) -> PayPalCapture:
        if self.authorizations[auth_id].status == "VOIDED":
            raise PaymentError("TERMINAL", "AUTHORIZATION_VOIDED")
        status = {"pending": "PENDING", "declined": "DECLINED"}.get(self.outcome, "COMPLETED")
        result = self._replay(
            request_key,
            (auth_id, amount_cents),
            PayPalCapture(self._id(request_key), status, amount_cents, True, auth_id),
        )
        self.captures[result.id] = result
        self._timeout(request_key)
        return result

    async def get_capture(self, capture_id: str) -> PayPalCapture:
        return self.captures[capture_id]

    async def void_authorization(self, auth_id: str) -> None:
        self.authorizations[auth_id] = replace(self.authorizations[auth_id], status="VOIDED")

    async def refund_capture(
        self, capture_id: str, *, amount_cents: int | None, request_key: str
    ) -> PayPalRefund:
        result = self._replay(
            request_key,
            (capture_id, amount_cents),
            PayPalRefund(
                self._id(request_key),
                "COMPLETED",
                self.captures[capture_id].amount_cents if amount_cents is None else amount_cents,
            ),
        )
        self.refunds[result.id] = result
        self._timeout(request_key)
        return result

    async def get_refund(self, refund_id: str) -> PayPalRefund:
        return self.refunds[refund_id]

    async def verify_webhook(self, headers: object, raw_body: bytes) -> bool:
        return False

    async def list_webhooks(self) -> list[dict[str, Any]]:
        return []

    async def add_trackers(self, items: list[TrackerItem]) -> list[TrackerResult]:
        return [TrackerResult(x.capture_id, True, None, None) for x in items]

    async def create_setup_token(
        self, entry_id: str, return_url: str, cancel_url: str
    ) -> SetupToken:
        return SetupToken(self._id(f"vs:{entry_id}"), "https://www.sandbox.paypal.com/simulated")

    async def create_payment_token(self, setup_token_id: str, entry_id: str) -> PaymentToken:
        return PaymentToken(self._id(f"vp:{entry_id}"), "FAKE")

    async def delete_payment_token(self, payment_token_id: str, entry_id: str) -> None:
        self.deleted.add(payment_token_id)

    async def charge_vault(
        self, buyer_order_id: str, payment_token_id: str, total_cents: int, payee: Payee
    ) -> ChargeResult:
        if self.outcome == "revoked" or payment_token_id in self.deleted:
            raise PaymentError("TERMINAL", "TOKEN_REVOKED")
        key = f"vc:{buyer_order_id}"
        status = {"pending": "PENDING", "declined": "DECLINED"}.get(self.outcome, "COMPLETED")
        result = self._replay(
            key,
            (payment_token_id, total_cents, payee),
            ChargeResult(self._id(key), self._id(key + ":capture"), status, None),
        )
        cap = PayPalCapture(result.capture_id, status, total_cents, True, None)
        self.captures[cap.id] = cap
        self.orders[result.order_id] = PayPalOrder(
            result.order_id,
            "COMPLETED",
            "CAPTURE",
            "USD",
            total_cents,
            payee.email,
            payee.merchant_id,
            "FAKE-PAYER",
            "US",
            None,
            [],
            [cap],
            None,
            {"simulated": True},
        )
        self._timeout(key)
        return result
