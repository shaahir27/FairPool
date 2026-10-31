"""Sandbox-only raw REST gateway. Only capture resources establish payment."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx

from fairpool.config import SANDBOX_API_HOST, SANDBOX_CHECKOUT_HOST, Settings, assert_sandbox_host
from fairpool.domain.money import parse_paypal_string, to_paypal_string
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

FAIRPOOL_NS = uuid5(NAMESPACE_URL, "https://fairpool.example/idempotency/v1")


def request_id(key: str) -> str:
    return str(uuid5(FAIRPOOL_NS, key))


def resource_id(value: str) -> str:
    if not value or len(value) > 200:
        raise ValueError("Invalid provider resource ID")
    return quote(value, safe="")


def amount(cents: int) -> dict[str, str]:
    return {"currency_code": "USD", "value": to_paypal_string(cents)}


def read_amount(data: dict[str, Any]) -> int:
    if data.get("currency_code") != "USD":
        raise PaymentError("TERMINAL", "CURRENCY_MISMATCH")
    return parse_paypal_string(data["value"])


def authorization(data: dict[str, Any]) -> PayPalAuthorization:
    expires = data.get("expiration_time")
    return PayPalAuthorization(
        data["id"],
        data["status"],
        read_amount(data["amount"]),
        datetime.fromisoformat(expires.replace("Z", "+00:00")) if expires else None,
    )


def capture(data: dict[str, Any]) -> PayPalCapture:
    return PayPalCapture(
        data["id"],
        data["status"],
        read_amount(data["amount"]),
        data.get("final_capture", False),
        data.get("supplementary_data", {}).get("related_ids", {}).get("authorization_id"),
    )


def order(data: dict[str, Any]) -> PayPalOrder:
    units = data.get("purchase_units", [])
    if len(units) != 1:
        raise PaymentError("UNKNOWN", "INVALID_ORDER_RESPONSE")
    unit = units[0]
    payments = unit.get("payments", {})
    auths = [authorization(x) for x in payments.get("authorizations", [])]
    caps = [capture(x) for x in payments.get("captures", [])]
    approval = next(
        (x["href"] for x in data.get("links", []) if x.get("rel") in {"approve", "payer-action"}),
        None,
    )
    if approval:
        assert_sandbox_host(approval, SANDBOX_CHECKOUT_HOST)
    # Allowlist persisted data: never persist payer identity, payment sources or URLs.
    sanitized = {k: data[k] for k in ("id", "status", "intent", "debug_id") if k in data}
    sanitized["captures"] = [
        {"id": c.id, "status": c.status, "amount_cents": c.amount_cents} for c in caps
    ]
    return PayPalOrder(
        data["id"],
        data["status"],
        data.get("intent", ""),
        unit["amount"]["currency_code"],
        read_amount(unit["amount"]),
        unit.get("payee", {}).get("email_address"),
        unit.get("payee", {}).get("merchant_id"),
        data.get("payer", {}).get("payer_id"),
        data.get("payer", {}).get("address", {}).get("country_code"),
        approval,
        auths,
        caps,
        data.get("debug_id"),
        sanitized,
    )


class RestPayPalGateway:
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        assert_sandbox_host(settings.paypal_api_base, SANDBOX_API_HOST)
        assert_sandbox_host(settings.paypal_checkout_base, SANDBOX_CHECKOUT_HOST)
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        self.owns_client = client is None
        self.token = ""
        self.token_until = 0.0
        self.token_lock = asyncio.Lock()

    async def close(self) -> None:
        if self.owns_client:
            await self.client.aclose()

    async def _token(self) -> str:
        async with self.token_lock:
            if self.token and time.monotonic() < self.token_until:
                return self.token
            response = await self.client.post(
                self.settings.paypal_api_base + "/v1/oauth2/token",
                auth=(
                    self.settings.paypal_client_id,
                    self.settings.paypal_client_secret.get_secret_value(),
                ),
                data={"grant_type": "client_credentials"},
                timeout=20,
            )
            if response.status_code != 200:
                raise PaymentError(
                    "RETRYABLE"
                    if response.status_code >= 500 or response.status_code == 429
                    else "CONFIG",
                    "TOKEN_FAILED",
                )
            body = response.json()
            self.token = body["access_token"]
            self.token_until = time.monotonic() + max(1, int(body["expires_in"]) - 300)
            return self.token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        key: str | None = None,
        extra_headers: dict[str, str] | None = None,
        missing_ok: bool = False,
    ) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Relative API path required")
        refreshed = False
        for attempt in range(5):
            try:
                token = await self._token()
                headers = {"Authorization": f"Bearer {token}", "Prefer": "return=representation"}
                if key:
                    headers["PayPal-Request-Id"] = request_id(key)
                if extra_headers:
                    if not self.settings.mock_toggles_enabled or set(extra_headers) != {
                        "PayPal-Mock-Response"
                    }:
                        raise PaymentError("CONFIG", "MOCK_HEADERS_DISABLED")
                    headers.update(extra_headers)
                response = await self.client.request(
                    method,
                    self.settings.paypal_api_base + path,
                    json=body,
                    headers=headers,
                    timeout=20,
                )
                if 200 <= response.status_code < 300 or (
                    missing_ok and response.status_code == 404
                ):
                    try:
                        data = (
                            response.json()
                            if response.content and response.status_code != 404
                            else {}
                        )
                    except ValueError:
                        raise PaymentError("UNKNOWN", "INVALID_PROVIDER_RESPONSE") from None
                    if not isinstance(data, dict):
                        raise PaymentError("UNKNOWN", "INVALID_PROVIDER_RESPONSE")
                    return data
                try:
                    error = response.json()
                except ValueError:
                    error = {}
                issue = next(
                    (d.get("issue") for d in error.get("details", []) if d.get("issue")),
                    error.get("error") or error.get("name", "HTTP_ERROR"),
                )
                debug_id = response.headers.get("paypal-debug-id")
                if issue in {
                    "invalid_subject",
                    "NOT_AUTHORIZED",
                    "UNSUPPORTED_PAYMENT_INSTRUCTION",
                }:
                    raise PaymentError("CONFIG", issue, debug_id=debug_id)
                if response.status_code == 401 and not refreshed:
                    async with self.token_lock:
                        if self.token == token:
                            self.token = ""
                    refreshed = True
                    continue
                if response.status_code != 429 and response.status_code < 500:
                    category = (
                        "WAIT"
                        if issue == "ORDER_NOT_APPROVED"
                        else "BUG"
                        if issue == "DUPLICATE_INVOICE_ID"
                        else "TERMINAL"
                    )
                    raise PaymentError(category, issue, debug_id=debug_id)
            except PaymentError as exc:
                if exc.category != "RETRYABLE":
                    raise
            except httpx.TransportError:
                pass
            if attempt < 4:
                await asyncio.sleep(min(30, 2**attempt + random.random()))
        raise PaymentError("UNKNOWN", "OUTCOME_UNKNOWN")

    def order_payload(self, req: CreateOrderRequest) -> dict[str, Any]:
        if (
            type(req.attempt) is not int
            or req.attempt < 1
            or not 0 <= req.payload_level <= self.settings.paypal_payload_level
        ):
            raise ValueError("Invalid attempt or unverified payload level")
        if req.amount_cents <= 0:
            raise ValueError("Positive amount required")
        if not req.payee.email:
            raise ValueError("Single seller email required")
        unit: dict[str, Any] = {
            "reference_id": req.reference_id,
            "description": req.description,
            "amount": amount(req.amount_cents),
            "payee": {"email_address": req.payee.email},
        }
        if req.payload_level >= 1:
            unit.update(
                custom_id=req.buyer_order_id, invoice_id=f"{req.buyer_order_id}:{req.attempt}"
            )
        if req.payload_level >= 2:
            parts = [req.breakdown[k] for k in ("item_cents", "shipping_cents", "tax_cents")]
            if any(type(x) is not int or x < 0 for x in parts) or sum(parts) != req.amount_cents:
                raise ValueError("Breakdown must sum exactly to total")
            unit["amount"]["breakdown"] = dict(
                zip(("item_total", "shipping", "tax_total"), map(amount, parts), strict=True)
            )
            unit["items"] = [
                {"name": req.description, "quantity": "1", "unit_amount": amount(parts[0])}
            ]
        payload: dict[str, Any] = {"intent": "AUTHORIZE", "purchase_units": [unit]}
        if req.payload_level >= 3:
            if not req.shipping:
                raise ValueError("Provided shipping required at level 3")
            unit["shipping"] = req.shipping
            payload["payment_source"] = {
                "paypal": {
                    "experience_context": {
                        "return_url": req.return_url,
                        "cancel_url": req.cancel_url,
                        "user_action": "PAY_NOW",
                        "shipping_preference": "SET_PROVIDED_ADDRESS",
                    }
                }
            }
        return payload

    async def create_order(self, req: CreateOrderRequest) -> PayPalOrder:
        return order(
            await self._request(
                "POST",
                "/v2/checkout/orders",
                body=self.order_payload(req),
                key=f"create:{req.buyer_order_id}:{req.attempt}",
                extra_headers=req.extra_headers or None,
            )
        )

    async def get_order(self, paypal_order_id: str) -> PayPalOrder:
        return order(
            await self._request("GET", f"/v2/checkout/orders/{resource_id(paypal_order_id)}")
        )

    async def authorize_order(self, paypal_order_id: str, *, request_key: str) -> PayPalOrder:
        return order(
            await self._request(
                "POST",
                f"/v2/checkout/orders/{resource_id(paypal_order_id)}/authorize",
                body={},
                key=request_key,
            )
        )

    async def get_authorization(self, auth_id: str) -> PayPalAuthorization:
        return authorization(
            await self._request("GET", f"/v2/payments/authorizations/{resource_id(auth_id)}")
        )

    async def capture_authorization(
        self, auth_id: str, *, amount_cents: int, request_key: str
    ) -> PayPalCapture:
        return capture(
            await self._request(
                "POST",
                f"/v2/payments/authorizations/{resource_id(auth_id)}/capture",
                body={"amount": amount(amount_cents), "final_capture": True},
                key=request_key,
            )
        )

    async def get_capture(self, capture_id: str) -> PayPalCapture:
        return capture(
            await self._request("GET", f"/v2/payments/captures/{resource_id(capture_id)}")
        )

    async def void_authorization(self, auth_id: str) -> None:
        if (await self.get_authorization(auth_id)).status == "VOIDED":
            return
        try:
            await self._request(
                "POST", f"/v2/payments/authorizations/{resource_id(auth_id)}/void", body={}
            )
        except PaymentError as exc:
            if (
                exc.category != "TERMINAL"
                or (await self.get_authorization(auth_id)).status != "VOIDED"
            ):
                raise

    async def refund_capture(
        self, capture_id: str, *, amount_cents: int | None, request_key: str
    ) -> PayPalRefund:
        data = await self._request(
            "POST",
            f"/v2/payments/captures/{resource_id(capture_id)}/refund",
            body={"amount": amount(amount_cents)} if amount_cents is not None else {},
            key=request_key,
        )
        return PayPalRefund(data["id"], data["status"], read_amount(data["amount"]))

    async def get_refund(self, refund_id: str) -> PayPalRefund:
        data = await self._request("GET", f"/v2/payments/refunds/{resource_id(refund_id)}")
        return PayPalRefund(data["id"], data["status"], read_amount(data["amount"]))

    async def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        if not self.settings.paypal_webhook_id:
            raise PaymentError("CONFIG", "WEBHOOK_ID_REQUIRED")
        lower = {k.lower(): v for k, v in headers.items()}
        required = {
            "auth_algo": "paypal-auth-algo",
            "cert_url": "paypal-cert-url",
            "transmission_id": "paypal-transmission-id",
            "transmission_sig": "paypal-transmission-sig",
            "transmission_time": "paypal-transmission-time",
        }
        if any(value not in lower for value in required.values()):
            return False
        body = {key: lower[value] for key, value in required.items()}
        body.update(webhook_id=self.settings.paypal_webhook_id, webhook_event=json.loads(raw_body))
        return (
            await self._request("POST", "/v1/notifications/verify-webhook-signature", body=body)
        ).get("verification_status") == "SUCCESS"

    async def list_webhooks(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v1/notifications/webhooks")
        return [
            {"id": item["id"], "event_types": item.get("event_types", [])}
            for item in data.get("webhooks", [])
        ]

    async def list_webhook_event_types(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/v1/notifications/webhooks-event-types")
        return [{"name": item["name"]} for item in data.get("event_types", [])]

    async def add_trackers(self, items: list[TrackerItem]) -> list[TrackerResult]:
        results = []
        for item in items:
            try:
                path = f"/v2/checkout/orders/{resource_id(item.paypal_order_id)}"
                await self._request(
                    "POST",
                    path + "/track",
                    body={
                        "capture_id": item.capture_id,
                        "tracking_number": item.tracking_number,
                        "carrier": item.carrier,
                        "notify_payer": False,
                    },
                )
                data = await self._request("GET", path)
                trackers = [
                    t
                    for u in data.get("purchase_units", [])
                    for t in u.get("shipping", {}).get("trackers", [])
                ]
                matches = [
                    t
                    for t in trackers
                    if t.get("tracking_number") == item.tracking_number
                    and t.get("carrier") == item.carrier
                    and item.capture_id in t.get("capture_ids", [])
                ]
                results.append(
                    TrackerResult(
                        item.capture_id,
                        len(matches) == 1,
                        None if len(matches) == 1 else "TRACKER_UNCONFIRMED",
                        data.get("debug_id"),
                    )
                )
            except PaymentError as exc:
                results.append(TrackerResult(item.capture_id, False, exc.category, exc.debug_id))
        return results

    async def create_setup_token(
        self, entry_id: str, return_url: str, cancel_url: str
    ) -> SetupToken:
        data = await self._request(
            "POST",
            "/v3/vault/setup-tokens",
            key=f"vs:{entry_id}",
            body={
                "payment_source": {
                    "paypal": {
                        "usage_type": "MERCHANT",
                        "experience_context": {"return_url": return_url, "cancel_url": cancel_url},
                    }
                }
            },
        )
        approval = next(
            x["href"] for x in data["links"] if x.get("rel") in {"approve", "payer-action"}
        )
        assert_sandbox_host(approval, SANDBOX_CHECKOUT_HOST)
        return SetupToken(data["id"], approval)

    async def create_payment_token(self, setup_token_id: str, entry_id: str) -> PaymentToken:
        data = await self._request(
            "POST",
            "/v3/vault/payment-tokens",
            key=f"vp:{entry_id}",
            body={"payment_source": {"token": {"id": setup_token_id, "type": "SETUP_TOKEN"}}},
        )
        return PaymentToken(data["id"], data["id"][-4:])

    async def delete_payment_token(self, payment_token_id: str, entry_id: str) -> None:
        await self._request(
            "DELETE",
            f"/v3/vault/payment-tokens/{resource_id(payment_token_id)}",
            key=f"vd:{entry_id}",
            missing_ok=True,
        )

    async def charge_vault(
        self, buyer_order_id: str, payment_token_id: str, total_cents: int, payee: Payee
    ) -> ChargeResult:
        if (
            total_cents <= 0
            or not payee.email
            or payee.email.lower() != (self.settings.single_seller_email or "").lower()
        ):
            raise PaymentError("CONFIG", "VAULT_PAYEE_INVALID")
        unit = {
            "amount": amount(total_cents),
            "payee": {"email_address": payee.email},
            "custom_id": buyer_order_id,
            "invoice_id": f"vault:{buyer_order_id}",
        }
        data = await self._request(
            "POST",
            "/v2/checkout/orders",
            key=f"vc:{buyer_order_id}:create",
            body={
                "intent": "CAPTURE",
                "purchase_units": [unit],
                "payment_source": {"paypal": {"vault_id": payment_token_id}},
            },
        )
        result = order(data)
        try:
            if not result.captures:
                result = order(
                    await self._request(
                        "POST",
                        f"/v2/checkout/orders/{resource_id(result.id)}/capture",
                        key=f"vc:{buyer_order_id}:capture",
                        body={},
                    )
                )
        except PaymentError as exc:
            return ChargeResult(result.id, None, None, exc.code)
        if len(result.captures) != 1:
            return ChargeResult(result.id, None, None, "OUTCOME_UNKNOWN")
        cap = result.captures[0]
        if cap.amount_cents != total_cents:
            raise PaymentError("UNKNOWN", "AMOUNT_MISMATCH")
        return ChargeResult(result.id, cap.id, cap.status, None)
