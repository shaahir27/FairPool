#!/usr/bin/env python3
"""
FairPool spike check: one script that runs every pending spike (S1, S4-S13) plus the
PayPal Sandbox regression checks and the S2 follow-up, then writes a sanitized report.

Sandbox only. Every payment test uses USD 1.00. Secrets are read from the environment
or a git-ignored env file and are never printed or written to the report.

Usage:
  python fairpool_spike_check.py list
  python fairpool_spike_check.py check-env  [--env-file .env.spike]
  python fairpool_spike_check.py run        [--env-file .env.spike] [--only s1,s4] [--skip s9]
                                            [--non-interactive] [--print-approval-urls]
                                            [--out-dir spike_out]
Spike keys: core s1 s2 s3 s4 s5 s6 s7 s8 s9 s10 s11 s12 s13
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import hmac as hmaclib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, quote, urlencode, urlparse

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.exit("Missing dependency: pip install httpx")

VERSION = "1.0.0"
SANDBOX_API_HOST = "api-m.sandbox.paypal.com"
SANDBOX_WWW_HOST = "www.sandbox.paypal.com"
FAIRPOOL_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://fairpool.example/idempotency/v1")
USD_ONE = "1.00"
MAX_ORDERS_PER_RUN = 40
SEVEN_EVENTS = [
    "CHECKOUT.ORDER.APPROVED", "PAYMENT.AUTHORIZATION.CREATED", "PAYMENT.AUTHORIZATION.VOIDED",
    "PAYMENT.CAPTURE.PENDING", "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.REFUNDED",
]
# quicknet (drand) facts published by drand; pinned so the public key is never read from the data being verified
QUICKNET_HASH = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
QUICKNET_PUBKEY = ("83cf0f2896adee7eb8b5f01fcad3912212c437e0073e911fb90022d3e760183c8c4b450b6a0a6c3ac6a5776a2d1064510d1fec758c921cc22b"
                   "0e17e63aaf4bcb5ed66304de9cf809bd274ca73bab4af5a6e9c76a4bc09e76eae8991ef5ece45a")
QUICKNET_GENESIS = 1692803367
QUICKNET_PERIOD = 3
BLS_G1_DST = b"BLS_SIG_BLS12381G1_XMD:SHA-256_SSWU_RO_NUL_"
BLS_G2_GEN = ("93e02b6052719f607dacd3a088274f65596bd0d09920b61ab5da61bbdc7f5049334cf11213945d57e5ac7d055d042b7e024aa2b2f08f0a91260805272dc"
              "51051c6e47ad4fa403b02b4510b647ae3d1770bac0326a805bbefd48056c8c121bdb8")
ZAPIER_META_TOOLS = {
    "inspect_zapier_actions", "discover_zapier_actions", "enable_zapier_action", "disable_zapier_action",
    "auto_provision_mcp", "execute_zapier_read_action", "execute_zapier_write_action",
    "list_zapier_connections", "manage_zapier_connections", "get_configuration_url", "list_zapier_skills",
    "get_zapier_skill", "create_zapier_skill", "update_zapier_skill", "delete_zapier_skill", "send_feedback",
    "write_code_action",
}
PAYPAL_MCP_READ_ALLOW = {"get_order", "get_shipment_tracking", "get_refund", "list_disputes", "get_dispute"}
MERCHANT_OPERATIONS = {  # api.md section 4.3: exactly these ten operations (operationId -> (method, path))
    "list_lots": ("get", "/merchant-api/v1/lots"),
    "get_lot": ("get", "/merchant-api/v1/lots/{lot_id}"),
    "submit_bid": ("put", "/merchant-api/v1/lots/{lot_id}/bid"),
    "list_bids": ("get", "/merchant-api/v1/bids"),
    "get_bid": ("get", "/merchant-api/v1/bids/{bid_id}"),
    "get_lot_progress": ("get", "/merchant-api/v1/lots/{lot_id}/progress"),
    "get_lot_fulfillment": ("get", "/merchant-api/v1/lots/{lot_id}/fulfillment"),
    "submit_shipments": ("post", "/merchant-api/v1/lots/{lot_id}/shipments"),
    "get_verification_manifest": ("get", "/merchant-api/v1/lots/{lot_id}/verification-manifest"),
    "get_lot_verification": ("get", "/merchant-api/v1/lots/{lot_id}/verification"),
}

# ----------------------------------------------------------------------------------------------
# Spike catalogue: single source for `list`, `check-env` and the README
# ----------------------------------------------------------------------------------------------
SPIKES: dict[str, dict] = {
    "core": dict(title="PayPal Sandbox regression (V1-V7, checklist 1.x, 6.1, 6.2)", human="none",
                 env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL"], tools=[]),
    "s1": dict(title="S1 Log in with PayPal, scope openid (G1, G2) -> DEDUPE_MODE", human="Log in as a US sandbox buyer twice (consent, then approve a USD 1.00 order)",
               env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL", "PAYPAL_LOGIN_REDIRECT_URI"], tools=["a browser"]),
    "s2": dict(title="S2 follow-up: authorize/capture/void/refund replays, O1, O2", human="Approve 2 USD 1.00 orders as a US sandbox buyer",
               env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL"], tools=["a browser"]),
    "s3": dict(title="S3 second-seller re-probe (optional, recorded result was 403)", human="none",
               env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET"], tools=[]),
    "s4": dict(title="S4 payload ladder (G8) -> PAYPAL_PAYLOAD_LEVEL", human="Approve 1 USD 1.00 order and confirm the address is locked",
               env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL"], tools=["a browser"]),
    "s5": dict(title="S5 webhooks (G5) -> WEBHOOKS_ENABLED", human="none beyond the approvals of S2/S13 (events are collected during the run)",
               env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "WEBHOOK_PUBLIC_URL"], tools=["a public HTTPS tunnel on port 443 to WEBHOOK_LISTEN_PORT"]),
    "s6": dict(title="S6 drand beacon and sandbox buyers (G6) -> BEACON_MODE, buyer count", human="Approve one USD 1.00 order per buyer account (default 6)",
               env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL"], tools=["pip install pyblst", "a browser"]),
    "s7": dict(title="S7 payee-email routing (G11): authorize, void, capture AND refund must all work", human="Approve 2 USD 1.00 orders as a US sandbox buyer",
               env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SECOND_SELLER_EMAIL"], tools=["a browser"]),
    "s8": dict(title="S8 Elastic hybrid search (G12) -> SEARCH_BACKEND", human="none",
               env=["ELASTICSEARCH_URL", "ELASTICSEARCH_API_KEY"], tools=[]),
    "s9": dict(title="S9 Zapier MCP managed mode (G13) -> ZAPIER_BRIDGE", human="Confirm task usage and trial expiry from the Zapier dashboard; run the four calls if the Agent API is deployed",
               env=["ZAPIER_MCP_TOKEN"], tools=[]),
    "s10": dict(title="S10 PayPal MCP read-only verification (G14) -> PAYPAL_MCP_VERIFICATION", human="none",
                env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET"], tools=["node 18+ and npx (for the local server probe)"]),
    "s11": dict(title="S11 APIMatic SDK and portal (G15) -> SDK outcome", human="Read APIMatic's terms (licensing) and confirm",
                env=["OPENAPI_JSON_PATH or FAIRPOOL_API_URL"], tools=["node + @apimatic/cli, logged in (apimatic auth login)"]),
    "s12": dict(title="S12 shipment tracking via Orders v2 track (G16) -> SHIPMENT_TRACKING_ENABLED", human="Approve 1 USD 1.00 order if S2 did not run first",
                env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL"], tools=["a browser"]),
    "s13": dict(title="S13 JavaScript SDK v6 approval (G17) -> PAYPAL_APPROVAL_UI, PAYPAL_SDK_AUTH", human="Approve in the popup, cancel once, test a blocked popup",
                env=["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "SINGLE_SELLER_EMAIL"], tools=["a browser that allows localhost", "optional: S13_PUBLIC_URL, an https tunnel to S13_LISTEN_PORT (needed for client_token)"]),
}
RUN_ORDER = ["core", "s6", "s5", "s1", "s4", "s7", "s2", "s12", "s10", "s13", "s8", "s9", "s11", "s3"]


# ----------------------------------------------------------------------------------------------
# Redaction, recording
# ----------------------------------------------------------------------------------------------
class Redactor:
    def __init__(self) -> None:
        self._secrets: set[str] = set()

    def add(self, value: Optional[str]) -> None:
        if value and len(value) >= 6:
            self._secrets.add(value)

    def __call__(self, text: Any) -> str:
        s = str(text)
        for sec in sorted(self._secrets, key=len, reverse=True):
            s = s.replace(sec, "<redacted>")
        s = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer <redacted>", s)
        s = re.sub(r"A21[A-Za-z0-9_-]{20,}", "<redacted-token>", s)
        s = re.sub(r"(?i)(client_secret|access_token|api[_-]?key|password|PayPal-Auth-Assertion)(\"?\s*[:=]\s*\"?)[^\s\",&}]+", r"\1\2<redacted>", s)
        return s


REDACT = Redactor()


def log(msg: str = "") -> None:
    print(REDACT(msg), flush=True)


@dataclasses.dataclass
class Row:
    spike: str
    step: str
    http: str
    status: str      # PayPal status or issue name
    debug_id: str
    result: str      # PASS FAIL BLOCKED MANUAL SKIP INFO
    note: str = ""


class Recorder:
    def __init__(self) -> None:
        self.rows: list[Row] = []
        self.facts: dict[str, Any] = {}        # derived settings and measurements
        self.implications: dict[str, str] = {}
        self.manual_open: list[str] = []

    def add(self, spike: str, step: str, result: str, *, http: Any = "", status: str = "", debug_id: str = "", note: str = "") -> Row:
        row = Row(spike.upper(), step, str(http) if http != "" else "-", REDACT(status) or "-", REDACT(debug_id) or "-", result, REDACT(note))
        self.rows.append(row)
        colour = {"PASS": "PASS", "FAIL": "FAIL", "BLOCKED": "BLOCKED", "MANUAL": "MANUAL", "SKIP": "SKIP", "INFO": "INFO"}[result]
        log(f"  [{colour:7}] {row.spike} {step}" + (f"  (HTTP {row.http}" + (f", {row.status}" if row.status != "-" else "") + ")" if row.http != "-" else "")
            + (f"  -- {row.note}" if row.note else ""))
        return row

    def fact(self, key: str, value: Any) -> None:
        self.facts[key] = value

    def implication(self, spike: str, text: str) -> None:
        self.implications[spike.upper()] = text


REC = Recorder()


# ----------------------------------------------------------------------------------------------
# Config and safety
# ----------------------------------------------------------------------------------------------
def load_env_file(path: Optional[str]) -> None:
    if not path:
        return
    p = Path(path)
    if not p.exists():
        log(f"env file {path} not found (continuing with the process environment only)")
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class ForbiddenHost(Exception):
    pass


def guard_paypal_hosts(api_base: str, checkout_base: str) -> None:
    selftest = env("FAIRPOOL_SPIKE_SELFTEST") == "1"
    for label, url, expected in (("PAYPAL_API_BASE", api_base, SANDBOX_API_HOST), ("PAYPAL_CHECKOUT_BASE", checkout_base, SANDBOX_WWW_HOST)):
        host = (urlparse(url).hostname or "").lower()
        if host == expected:
            if urlparse(url).scheme != "https":
                raise ForbiddenHost(f"{label} must use https")
            continue
        if selftest and host in ("127.0.0.1", "localhost"):
            continue
        raise ForbiddenHost(f"{label} host must be exactly {expected}; got {host!r}. Live PayPal endpoints are prohibited.")


def key_uuid(key_text: str) -> str:
    return str(uuid.uuid5(FAIRPOOL_NS, key_text))


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def now_s() -> float:
    return time.time()


# ----------------------------------------------------------------------------------------------
# HTTP layer
# ----------------------------------------------------------------------------------------------
@dataclasses.dataclass
class Resp:
    status: int
    data: Any
    text: str
    headers: dict
    error: str = ""

    @property
    def debug_id(self) -> str:
        return self.headers.get("paypal-debug-id", "")

    @property
    def issue(self) -> str:
        if 200 <= self.status < 300:
            return ""      # success bodies can hold personal data (e.g. userinfo 'name'); never surface them
        d = self.data
        if isinstance(d, dict):
            det = d.get("details")
            if isinstance(det, list) and det and isinstance(det[0], dict) and det[0].get("issue"):
                return str(det[0]["issue"])
            for k in ("name", "error", "message"):
                if d.get(k):
                    return str(d[k])
        return ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def field_names(self) -> list[str]:
        return sorted(self.data.keys()) if isinstance(self.data, dict) else []


class Http:
    def __init__(self, timeout: float = 30.0) -> None:
        self.client = httpx.Client(timeout=timeout, follow_redirects=False)

    def request(self, method: str, url: str, *, headers: Optional[dict] = None, json_body: Any = None,
                content: Optional[bytes] = None, data: Optional[dict] = None, auth: Optional[tuple] = None,
                retries: int = 0) -> Resp:
        last: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                kw: dict[str, Any] = {"headers": headers or {}}
                if json_body is not None:
                    kw["json"] = json_body
                if content is not None:
                    kw["content"] = content
                if data is not None:
                    kw["data"] = data
                if auth is not None:
                    kw["auth"] = auth
                r = self.client.request(method, url, **kw)
                try:
                    parsed = r.json() if r.content else None
                except ValueError:
                    parsed = None
                return Resp(r.status_code, parsed, r.text if parsed is None else "", {k.lower(): v for k, v in r.headers.items()})
            except httpx.HTTPError as ex:
                last = ex
                time.sleep(min(2 ** attempt, 8))
        return Resp(0, None, "", {}, error=f"{type(last).__name__}: {last}")


# ----------------------------------------------------------------------------------------------
# PayPal REST client (Sandbox only)
# ----------------------------------------------------------------------------------------------
class PayPal:
    def __init__(self, http: Http, client_id: str, secret: str, api_base: str, checkout_base: str) -> None:
        guard_paypal_hosts(api_base, checkout_base)
        self.http, self.cid, self.secret = http, client_id, secret
        self.api, self.www = api_base.rstrip("/"), checkout_base.rstrip("/")
        self._tok: Optional[str] = None
        self._tok_exp = 0.0
        self.token_meta: dict = {}
        self.orders_created = 0
        REDACT.add(secret)

    # --- auth
    def token(self, force: bool = False) -> str:
        if not force and self._tok and now_s() < self._tok_exp - 300:
            return self._tok
        r = self.http.request("POST", f"{self.api}/v1/oauth2/token", auth=(self.cid, self.secret),
                              headers={"Accept": "application/json", "Accept-Language": "en_US"},
                              data={"grant_type": "client_credentials"})
        self.last_token_resp = r
        if not r.ok or not isinstance(r.data, dict) or "access_token" not in r.data:
            raise RuntimeError(f"OAuth failed: HTTP {r.status} {r.issue or r.error}")
        self._tok = r.data["access_token"]
        REDACT.add(self._tok)
        self._tok_exp = now_s() + float(r.data.get("expires_in", 3600))
        self.token_meta = {"fields": sorted(r.data.keys()), "expires_in": r.data.get("expires_in"),
                           "scope_names": sorted(str(r.data.get("scope", "")).split())}
        return self._tok

    def call(self, method: str, path: str, *, request_key: Optional[str] = None, json_body: Any = None,
             extra_headers: Optional[dict] = None, prefer: bool = False, empty_json: bool = False,
             retries: int = 0) -> Resp:
        for attempt in (0, 1):
            h = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json", "Accept": "application/json"}
            if request_key:
                h["PayPal-Request-Id"] = key_uuid(request_key)
            if prefer:
                h["Prefer"] = "return=representation"
            if extra_headers:
                h.update(extra_headers)
            r = self.http.request(method, f"{self.api}{path}", headers=h, json_body=json_body,
                                  content=(b"" if (json_body is None and method in ("POST", "PUT")) else None), retries=retries)
            if r.status == 401 and attempt == 0:
                self.token(force=True)
                continue
            return r
        return r  # pragma: no cover

    # --- orders
    def create_order(self, payload: dict, request_key: str, extra_headers: Optional[dict] = None) -> Resp:
        if self.orders_created >= MAX_ORDERS_PER_RUN:
            raise RuntimeError("order cap reached for this run (safety)")
        amt = payload["purchase_units"][0]["amount"]
        if amt.get("value") != USD_ONE or amt.get("currency_code") != "USD":
            raise RuntimeError("safety: every spike payment is exactly USD 1.00")
        self.orders_created += 1
        return self.call("POST", "/v2/checkout/orders", request_key=request_key, json_body=payload, prefer=True, extra_headers=extra_headers)

    def get_order(self, oid: str) -> Resp:
        return self.call("GET", f"/v2/checkout/orders/{oid}", retries=2)

    def authorize(self, oid: str, request_key: str) -> Resp:
        return self.call("POST", f"/v2/checkout/orders/{oid}/authorize", request_key=request_key, json_body={}, prefer=True)

    def get_auth(self, aid: str) -> Resp:
        return self.call("GET", f"/v2/payments/authorizations/{aid}", retries=2)

    def capture(self, aid: str, request_key: str) -> Resp:
        body = {"amount": {"value": USD_ONE, "currency_code": "USD"}, "final_capture": True}
        return self.call("POST", f"/v2/payments/authorizations/{aid}/capture", request_key=request_key, json_body=body, prefer=True)

    def get_capture(self, cid: str) -> Resp:
        return self.call("GET", f"/v2/payments/captures/{cid}", retries=2)

    def void(self, aid: str) -> Resp:
        return self.call("POST", f"/v2/payments/authorizations/{aid}/void")

    def refund(self, cap_id: str, request_key: str) -> Resp:
        return self.call("POST", f"/v2/payments/captures/{cap_id}/refund", request_key=request_key, json_body={}, prefer=True)

    def get_refund(self, rid: str) -> Resp:
        return self.call("GET", f"/v2/payments/refunds/{rid}", retries=2)

    # --- webhooks, trackers, tokens
    def list_webhooks(self) -> Resp:
        return self.call("GET", "/v1/notifications/webhooks", retries=2)

    def event_types(self) -> Resp:
        return self.call("GET", "/v1/notifications/webhooks-event-types", retries=2)

    def create_webhook(self, url: str, events: list[str]) -> Resp:
        return self.call("POST", "/v1/notifications/webhooks", json_body={"url": url, "event_types": [{"name": e} for e in events]})

    def delete_webhook(self, wid: str) -> Resp:
        return self.call("DELETE", f"/v1/notifications/webhooks/{wid}")

    def simulate_event(self, webhook_id: str, event_type: str) -> Resp:
        return self.call("POST", "/v1/notifications/simulate-event", json_body={"webhook_id": webhook_id, "event_type": event_type})

    def resend_event(self, event_id: str, webhook_id: str) -> Resp:
        return self.call("POST", f"/v1/notifications/webhooks-events/{event_id}/resend", json_body={"webhook_ids": [webhook_id]})

    def verify_webhook(self, headers: dict, raw_body: bytes, webhook_id: str) -> Resp:
        h = {k.lower(): v for k, v in headers.items()}
        parts = {
            "auth_algo": h.get("paypal-auth-algo", ""), "cert_url": h.get("paypal-cert-url", ""),
            "transmission_id": h.get("paypal-transmission-id", ""), "transmission_sig": h.get("paypal-transmission-sig", ""),
            "transmission_time": h.get("paypal-transmission-time", ""), "webhook_id": webhook_id,
        }
        # embed the received body verbatim: PayPal computes a CRC over the exact bytes
        body = ("{" + ",".join(f"{json.dumps(k)}:{json.dumps(v)}" for k, v in parts.items())
                + ',"webhook_event":' + raw_body.decode("utf-8") + "}").encode("utf-8")
        hh = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}
        return self.http.request("POST", f"{self.api}/v1/notifications/verify-webhook-signature", headers=hh, content=body)

    def trackers_batch(self, trackers: list[dict]) -> Resp:
        return self.call("POST", "/v1/shipping/trackers-batch", json_body={"trackers": trackers})

    def get_tracker(self, tracker_id: str) -> Resp:
        return self.call("GET", f"/v1/shipping/trackers/{tracker_id}", retries=1)

    def sdk_client_token(self, domains: list[str]) -> Resp:
        data = [("grant_type", "client_credentials"), ("response_type", "client_token")] + [("domains[]", d) for d in domains]
        return self.http.request("POST", f"{self.api}/v1/oauth2/token", auth=(self.cid, self.secret),
                                 headers={"Accept": "application/json"}, data=data)  # type: ignore[arg-type]

    def partner_referral(self, tracking_id: str) -> Resp:
        body = {"tracking_id": tracking_id,
                "operations": [{"operation": "API_INTEGRATION", "api_integration_preference": {"rest_api_integration": {
                    "integration_method": "PAYPAL", "integration_type": "THIRD_PARTY",
                    "third_party_details": {"features": ["PAYMENT", "REFUND"]}}}}],
                "products": ["EXPRESS_CHECKOUT"],
                "legal_consents": [{"type": "SHARE_DATA_CONSENT", "granted": True}]}
        return self.call("POST", "/v2/customer/partner-referrals", json_body=body)


# ----------------------------------------------------------------------------------------------
# Order payloads (payload ladder, api contract section 5)
# ----------------------------------------------------------------------------------------------
class Ctx:
    """Shared run context."""
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_id = secrets.token_hex(4)
        self.http = Http()
        self.pp: Optional[PayPal] = None
        self.interactive = not args.non_interactive
        self.print_urls = args.print_approval_urls
        self.hmac_key = secrets.token_bytes(32)           # per-run key, never stored
        self.seq = 0
        self.auths_open: dict[str, str] = {}              # authorization id -> note (to void in cleanup)
        self.caps_open: dict[str, str] = {}               # capture id -> note (to refund in cleanup)
        self.captured: Optional[dict] = None              # {"order_id","capture_id","auth_id"} from S2 phase A
        self.webhook: Optional["WebhookListener"] = None
        self.webhook_id = ""
        self.created_webhook = False
        self.seller = env("SINGLE_SELLER_EMAIL")
        self.payer_hmacs: dict[str, str] = {}
        self.actions: set[str] = set()                    # real PayPal actions performed (for S5 expectations)

    def n(self) -> int:
        self.seq += 1
        return self.seq

    def hm(self, value: str) -> str:
        return hmaclib.new(self.hmac_key, value.encode(), hashlib.sha256).hexdigest()[:16]


def order_payload(ctx: Ctx, label: str, *, payee_email: Optional[str] = None, level: int = 0, intent: str = "AUTHORIZE") -> dict:
    n = ctx.n()
    unit: dict[str, Any] = {
        "reference_id": f"spike-{ctx.run_id}-{n}",
        "description": f"FairPool spike {label}",
        "amount": {"currency_code": "USD", "value": USD_ONE},
        "payee": {"email_address": payee_email or ctx.seller},
    }
    payload: dict[str, Any] = {"intent": intent, "purchase_units": [unit]}
    if level >= 1:
        unit["custom_id"] = str(uuid.uuid4())
        unit["invoice_id"] = f"FP-SPIKE-{ctx.run_id}-{n}"
    if level >= 2:
        unit["amount"] = {"currency_code": "USD", "value": USD_ONE, "breakdown": {
            "item_total": {"currency_code": "USD", "value": "0.80"},
            "shipping": {"currency_code": "USD", "value": "0.10"},
            "tax_total": {"currency_code": "USD", "value": "0.10"}}}
        unit["items"] = [{"name": "FairPool spike item", "quantity": "1", "category": "PHYSICAL_GOODS",
                          "unit_amount": {"currency_code": "USD", "value": "0.80"}, "tax": {"currency_code": "USD", "value": "0.10"}}]
    if level >= 3:
        unit["shipping"] = {"type": "SHIPPING", "name": {"full_name": "Spike Buyer"},
                            "address": {"address_line_1": "123 Spike Street", "admin_area_2": "San Jose", "admin_area_1": "CA",
                                        "postal_code": "95131", "country_code": "US"}}
        payload["payment_source"] = {"paypal": {"experience_context": {
            "return_url": "https://example.com/fairpool-spike/return", "cancel_url": "https://example.com/fairpool-spike/cancel",
            "user_action": "PAY_NOW", "shipping_preference": "SET_PROVIDED_ADDRESS"}}}
    return payload


def link_of(order: dict, *rels: str) -> str:
    for ln in (order or {}).get("links", []) or []:
        if ln.get("rel") in rels and ln.get("href"):
            return ln["href"]
    return ""


def order_view(order: dict) -> dict:
    """Flatten the fields the contract section 6 needs. Missing values stay None (never inferred)."""
    pu = ((order or {}).get("purchase_units") or [{}])[0]
    payee = pu.get("payee") or {}
    payer = (order or {}).get("payer") or {}
    pays = pu.get("payments") or {}
    auths = pays.get("authorizations") or []
    caps = pays.get("captures") or []
    amt = pu.get("amount") or {}
    return {
        "status": order.get("status"), "intent": order.get("intent"),
        "currency": amt.get("currency_code"), "value": amt.get("value"),
        "payee_email": payee.get("email_address"), "payee_merchant_id": payee.get("merchant_id"),
        "payer_id": payer.get("payer_id"), "payer_country": (payer.get("address") or {}).get("country_code"),
        "auths": [{"id": a.get("id"), "status": a.get("status")} for a in auths],
        "caps": [{"id": c.get("id"), "status": c.get("status")} for c in caps],
        "shipping_address": (pu.get("shipping") or {}).get("address"),
        "trackings": [{"tracking_number": x.get("tracking_number"), "status": x.get("status")} for x in ((pu.get("shipping") or {}).get("trackings") or [])],
    }


def approval_checks(view: dict, expected_email: str) -> list[tuple[str, bool, str]]:
    """Contract paypal-adapter.md section 6, items 1 to 4 (item 5 needs the app's pool state)."""
    out = []
    out.append(("status APPROVED and intent AUTHORIZE", view["status"] == "APPROVED" and view["intent"] == "AUTHORIZE",
                f"status={view['status']} intent={view['intent']}"))
    out.append(("currency USD and amount 1.00", view["currency"] == "USD" and view["value"] == USD_ONE, f"{view['currency']} {view['value']}"))
    em, mid = view["payee_email"], view["payee_merchant_id"]
    email_ok = (em is None) or (em.lower() == expected_email.lower())
    out.append(("payee present and matches (merchant ID reported as missing, never required)", (em is not None or mid is not None) and email_ok,
                f"email={'present' if em else 'MISSING'} merchant_id={'present' if mid else 'MISSING'}"))
    out.append(("payer country US", view["payer_country"] == "US", f"country={view['payer_country']}"))
    return out


# ----------------------------------------------------------------------------------------------
# Human steps: approval flow
# ----------------------------------------------------------------------------------------------
def ask(ctx: Ctx, prompt: str, default: str = "") -> str:
    if not ctx.interactive:
        return default
    try:
        return input(REDACT(prompt)).strip()
    except EOFError:
        return default


def ask_yes(ctx: Ctx, prompt: str) -> Optional[bool]:
    """True / False from the user; None when running non-interactively."""
    if not ctx.interactive:
        return None
    a = ask(ctx, f"{prompt} [y/n]: ").lower()
    return a.startswith("y")


def wait_for_approval(ctx: Ctx, order: dict, label: str, *, timeout_s: int = 900) -> Optional[Resp]:
    """Open the approval page (URL withheld from logs), poll GET order until APPROVED. Returns the GET response or None."""
    assert ctx.pp
    url = link_of(order, "approve", "payer-action")
    if not url:
        return None
    if not ctx.interactive:
        return None
    log(f"\n>>> ACTION NEEDED ({label}): approve this USD 1.00 Sandbox order as the US sandbox BUYER.")
    log("    Opening your browser. The approval URL is withheld from the log" + (" (printing it because --print-approval-urls was set)." if ctx.print_urls else "."))
    if ctx.print_urls:
        print(url, flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        log("    (could not open a browser; rerun with --print-approval-urls to print the link to this terminal only)")
    start = now_s()
    last_status = ""
    while now_s() - start < timeout_s:
        time.sleep(3)
        r = ctx.pp.get_order(order["id"])
        if r.ok and isinstance(r.data, dict):
            st = r.data.get("status", "")
            if st != last_status:
                log(f"    order status: {st}")
                last_status = st
            if st == "APPROVED":
                return r
            if st in ("COMPLETED", "VOIDED"):
                return r
    log("    timed out waiting for approval")
    return None


def create_and_approve(ctx: Ctx, spike: str, label: str, *, level: int = 0, payee_email: Optional[str] = None,
                       expect_email: Optional[str] = None, record_checks: bool = True) -> tuple[Optional[Resp], Optional[Resp]]:
    """Create a USD 1.00 AUTHORIZE order, have the buyer approve it, and run contract section 6 checks."""
    pp = ctx.pp
    assert pp
    payload = order_payload(ctx, label, level=level, payee_email=payee_email)
    key = f"spike:{ctx.run_id}:create:{payload['purchase_units'][0]['reference_id']}"
    cr = pp.create_order(payload, key)
    ok = cr.status == 201 and isinstance(cr.data, dict) and cr.data.get("id")
    REC.add(spike, f"create {label} (level {level})", "PASS" if ok else "FAIL", http=cr.status,
            status=(cr.data or {}).get("status", "") if ok else cr.issue or cr.error, debug_id=cr.debug_id)
    if not ok:
        return cr, None
    if not ctx.interactive:
        REC.add(spike, f"buyer approval of {label}", "MANUAL", note="--non-interactive: approval skipped")
        return cr, None
    ar = wait_for_approval(ctx, cr.data, label)
    if ar is None or not ar.ok or ar.data.get("status") != "APPROVED":
        REC.add(spike, f"buyer approval of {label}", "FAIL", note="order did not reach APPROVED")
        return cr, ar
    REC.add(spike, f"buyer approval of {label}", "PASS", http=ar.status, status="APPROVED", debug_id=ar.debug_id)
    ctx.actions.add("approved")
    if record_checks:
        v = order_view(ar.data)
        for name, good, detail in approval_checks(v, expect_email or payee_email or ctx.seller):
            REC.add(spike, f"check after approval: {name}", "PASS" if good else "FAIL", note=detail)
    if (v := order_view(ar.data))["payer_id"]:
        ctx.payer_hmacs[cr.data["id"]] = ctx.hm(v["payer_id"])
    return cr, ar


# ----------------------------------------------------------------------------------------------
# Cleanup: never leave a Sandbox authorization or capture behind
# ----------------------------------------------------------------------------------------------
def cleanup(ctx: Ctx) -> None:
    pp = ctx.pp
    if not pp:
        return
    for aid, note in list(ctx.auths_open.items()):
        g = pp.get_auth(aid)
        st = (g.data or {}).get("status") if g.ok and isinstance(g.data, dict) else None
        if st in ("CREATED", "PENDING"):
            r = pp.void(aid)
            REC.add("cleanup", f"void leftover authorization ({note})", "PASS" if r.status in (200, 204) else "FAIL", http=r.status, status=r.issue, debug_id=r.debug_id)
            if r.status not in (200, 204):
                REC.manual_open.append(f"cleanup: a USD 1.00 authorization ending ...{aid[-4:]} could not be voided through the API (it holds no captured money and expires on its own); void it in the Sandbox dashboard if you can")
        ctx.auths_open.pop(aid, None)
    for cid, note in list(ctx.caps_open.items()):
        g = pp.get_capture(cid)
        st = (g.data or {}).get("status") if g.ok and isinstance(g.data, dict) else None
        if st == "COMPLETED":
            r = pp.refund(cid, f"spike:{ctx.run_id}:cleanup-refund:{cid}")
            rst = (r.data or {}).get("status", "") if isinstance(r.data, dict) else ""
            done = r.status in (200, 201) and rst == "COMPLETED"
            REC.add("cleanup", f"refund leftover capture ({note})", "PASS" if done else "FAIL", http=r.status, status=r.issue or rst, debug_id=r.debug_id,
                    note="" if done else "refund not confirmed COMPLETED: do not resubmit under a new key; check it by GET or in the dashboard")
            if not done:
                REC.manual_open.append(f"cleanup: a USD 1.00 capture ending ...{cid[-4:]} has no confirmed refund; check it in the Sandbox dashboard")
        ctx.caps_open.pop(cid, None)


# ----------------------------------------------------------------------------------------------
# CORE: Sandbox regression (checklist 1.1, 1.2, 6.1, 6.2; registry V1-V7)
# ----------------------------------------------------------------------------------------------
def run_core(ctx: Ctx) -> None:
    pp = ctx.pp
    assert pp
    S = "core"
    REC.add(S, "host guard: only the two Sandbox hosts are used (checklist 1.1)", "PASS", note=f"{urlparse(pp.api).hostname}, {urlparse(pp.www).hostname}")
    tm = pp.token_meta
    need = {"access_token", "app_id", "expires_in", "nonce", "scope", "token_type"}
    REC.add(S, "R1 OAuth token (V1, checklist 1.2)", "PASS" if need.issubset(set(tm.get("fields", []))) else "FAIL", http=200,
            note=f"fields={tm.get('fields')} expires_in={tm.get('expires_in')} scopes={len(tm.get('scope_names', []))}")
    # R2 create, R3 replay
    payload = order_payload(ctx, "core-create")
    key = f"spike:{ctx.run_id}:core-create"
    r2 = pp.create_order(payload, key)
    ok2 = r2.status == 201 and isinstance(r2.data, dict) and r2.data.get("status") == "CREATED"
    v = order_view(r2.data) if ok2 else {}
    REC.add(S, "R2 create AUTHORIZE order, payee set (V2)", "PASS" if ok2 else "FAIL", http=r2.status,
            status=(r2.data or {}).get("status", "") if ok2 else r2.issue or r2.error, debug_id=r2.debug_id,
            note=f"payee_email={'present' if v.get('payee_email') else 'MISSING'} merchant_id={'present' if v.get('payee_merchant_id') else 'MISSING (not required)'}" if ok2 else "")
    oid = (r2.data or {}).get("id") if ok2 else None
    r3 = pp.create_order(payload, key)
    REC.add(S, "R3 replay create with the same PayPal-Request-Id: 200 and same order (V3, checklist 6.2)",
            "PASS" if (r3.status == 200 and oid and (r3.data or {}).get("id") == oid) else "FAIL", http=r3.status, debug_id=r3.debug_id)
    # R4 authorize/capture before approval
    if oid:
        r4 = pp.authorize(oid, f"spike:{ctx.run_id}:core-auth-early")
        REC.add(S, "R4a authorize before approval -> 422 ORDER_NOT_APPROVED (V4)", "PASS" if (r4.status == 422 and r4.issue == "ORDER_NOT_APPROVED") else "FAIL",
                http=r4.status, status=r4.issue, debug_id=r4.debug_id)
        r4b = pp.call("POST", f"/v2/checkout/orders/{oid}/capture", request_key=f"spike:{ctx.run_id}:core-cap-early", json_body={})
        REC.add(S, "R4b capture before approval is rejected (V4)", "PASS" if r4b.status in (400, 422) else "FAIL", http=r4b.status, status=r4b.issue, debug_id=r4b.debug_id)
    # R5 distinct ids
    r5 = pp.create_order(order_payload(ctx, "core-second"), f"spike:{ctx.run_id}:core-second")
    REC.add(S, "R5 a second order gets a distinct ID (V5)", "PASS" if (r5.status == 201 and oid and (r5.data or {}).get("id") not in (None, oid)) else "FAIL",
            http=r5.status, debug_id=r5.debug_id)
    # R6 duplicate invoice mock
    mock = {"PayPal-Mock-Response": json.dumps({"mock_application_codes": "DUPLICATE_INVOICE_ID"})}
    r6 = pp.create_order(order_payload(ctx, "core-mock-dup", level=1), f"spike:{ctx.run_id}:core-mock-dup", extra_headers=mock)
    created = isinstance(r6.data, dict) and bool(r6.data.get("id"))
    REC.add(S, "R6 negative test DUPLICATE_INVOICE_ID: 422 and no order created (V6, checklist 6.1)",
            "PASS" if (r6.status == 422 and r6.issue == "DUPLICATE_INVOICE_ID" and not created) else "FAIL", http=r6.status, status=r6.issue, debug_id=r6.debug_id,
            note="if this fails with a different error, enable Negative Testing on the sandbox business account" if r6.status not in (422,) else "")
    # R7 event types, R8 webhook list
    r7 = pp.event_types()
    names = {e.get("name") for e in (r7.data or {}).get("event_types", [])} if r7.ok and isinstance(r7.data, dict) else set()
    missing = [e for e in SEVEN_EVENTS if e not in names]
    REC.add(S, "R7 the seven event types of V7 are listed", "PASS" if (r7.ok and not missing) else "FAIL", http=r7.status, debug_id=r7.debug_id,
            note=f"missing={missing}" if missing else f"{len(names)} types listed")
    r8 = pp.list_webhooks()
    n = len((r8.data or {}).get("webhooks", [])) if r8.ok and isinstance(r8.data, dict) else -1
    REC.add(S, "R8 list webhooks", "PASS" if r8.ok else "FAIL", http=r8.status, debug_id=r8.debug_id, note=f"{n} listeners registered")
    REC.add(S, "R9 INR is not a supported currency for Orders v2 (V12; checklist 3.7)", "INFO",
            note="not re-tested by this script; recorded fact from the earlier run")
    REC.implication("CORE", "The PayPal Sandbox basics the adapter contract relies on (token, create, replay, early-authorize rejection, mock error) behave as recorded." )


# ----------------------------------------------------------------------------------------------
# S2 follow-up (replays, O1, O2) and the shared capture used by S10 and S12
# ----------------------------------------------------------------------------------------------
def poll_capture(pp: PayPal, cap_id: str, timeout_s: int = 90) -> Resp:
    start = now_s()
    r = pp.get_capture(cap_id)
    while r.ok and isinstance(r.data, dict) and r.data.get("status") == "PENDING" and now_s() - start < timeout_s:
        time.sleep(5)
        r = pp.get_capture(cap_id)
    return r


def authorize_flow(ctx: Ctx, S: str, order_id: str, tag: str) -> Optional[dict]:
    """authorize + replay. Returns {'auth_id','order_status','auth_status'} or None."""
    pp = ctx.pp
    assert pp
    key = f"spike:{ctx.run_id}:auth:{tag}:{order_id}"
    a1 = pp.authorize(order_id, key)
    auth = ((((a1.data or {}).get("purchase_units") or [{}])[0].get("payments") or {}).get("authorizations") or [{}])[0] if a1.ok and isinstance(a1.data, dict) else {}
    ok = a1.status == 201 and auth.get("id") and auth.get("status") == "CREATED"
    REC.add(S, f"authorize ({tag}): 201 and AUTHORIZATION status CREATED", "PASS" if ok else "FAIL", http=a1.status,
            status=f"authorization={auth.get('status')}; order={(a1.data or {}).get('status') if isinstance(a1.data, dict) else ''}" if a1.ok else a1.issue or a1.error,
            debug_id=a1.debug_id, note="O1: the COMPLETED seen earlier is the ORDER status; the authorization object must read CREATED" if ok else "")
    if not auth.get("id"):
        return None
    ctx.auths_open[auth["id"]] = tag
    ctx.actions.add("authorized")
    a2 = pp.authorize(order_id, key)
    auth2 = ((((a2.data or {}).get("purchase_units") or [{}])[0].get("payments") or {}).get("authorizations") or [{}])[0] if a2.ok and isinstance(a2.data, dict) else {}
    REC.add(S, f"replay authorize with the same request ID ({tag}): 200 and same authorization", "PASS" if (a2.status == 200 and auth2.get("id") == auth["id"]) else "FAIL",
            http=a2.status, status=a2.issue, debug_id=a2.debug_id)
    return {"auth_id": auth["id"], "order_status": (a1.data or {}).get("status"), "auth_status": auth.get("status")}


def run_s2(ctx: Ctx) -> None:
    S = "s2"
    pp = ctx.pp
    assert pp
    if not ctx.interactive:
        REC.add(S, "S2 follow-up needs two buyer approvals", "MANUAL", note="--non-interactive")
        return
    # ---- Phase A: authorize, replay, capture, replay (capture is kept for S10/S12 and refunded in phase C)
    cr, ar = create_and_approve(ctx, S, "S2-A capture order")
    if ar is not None and ar.ok and ar.data.get("status") == "APPROVED":
        info = authorize_flow(ctx, S, cr.data["id"], "S2-A")
        if info:
            g = pp.get_auth(info["auth_id"])
            REC.add(S, "GET authorization reads CREATED", "PASS" if (g.ok and (g.data or {}).get("status") == "CREATED") else "FAIL", http=g.status, status=(g.data or {}).get("status", "") if g.ok else g.issue, debug_id=g.debug_id)
            ck = f"spike:{ctx.run_id}:cap:{info['auth_id']}"
            c1 = pp.capture(info["auth_id"], ck)
            cap_ok = c1.status == 201 and isinstance(c1.data, dict) and c1.data.get("id") and c1.data.get("status") in ("COMPLETED", "PENDING")
            REC.add(S, "capture the authorization (full USD 1.00, final_capture)", "PASS" if cap_ok else "FAIL", http=c1.status,
                    status=(c1.data or {}).get("status", "") if cap_ok else c1.issue or c1.error, debug_id=c1.debug_id,
                    note=f"final_capture={(c1.data or {}).get('final_capture')}" if cap_ok else "")
            if cap_ok:
                cap_id = c1.data["id"]
                ctx.caps_open[cap_id] = "S2-A"
                ctx.actions.add("captured")
                c2 = pp.capture(info["auth_id"], ck)
                REC.add(S, "replay capture with the same request ID: 200, same capture, one capture only", "PASS" if (c2.status == 200 and (c2.data or {}).get("id") == cap_id) else "FAIL", http=c2.status, status=c2.issue, debug_id=c2.debug_id)
                gc = poll_capture(pp, cap_id)
                st = (gc.data or {}).get("status") if gc.ok and isinstance(gc.data, dict) else ""
                REC.add(S, "GET capture: COMPLETED is the only paid status", "PASS" if st == "COMPLETED" else "FAIL", http=gc.status, status=st or gc.issue, debug_id=gc.debug_id)
                go = pp.get_order(cr.data["id"])
                ov = order_view(go.data) if go.ok else {}
                REC.add(S, "GET order lists exactly one capture", "PASS" if len(ov.get("caps", [])) == 1 else "FAIL", http=go.status, note=f"captures={len(ov.get('caps', []))}")
                ctx.captured = {"order_id": cr.data["id"], "capture_id": cap_id, "auth_id": info["auth_id"]}
    # ---- Phase B: authorize, void, void replay (O2), capture after void
    cr, ar = create_and_approve(ctx, S, "S2-B void order")
    if ar is not None and ar.ok and ar.data.get("status") == "APPROVED":
        info = authorize_flow(ctx, S, cr.data["id"], "S2-B")
        if info:
            v1 = pp.void(info["auth_id"])
            REC.add(S, "void the authorization (200 with body or 204)", "PASS" if v1.status in (200, 204) else "FAIL", http=v1.status, status=v1.issue, debug_id=v1.debug_id)
            if v1.status in (200, 204):
                ctx.actions.add("voided")
            g = pp.get_auth(info["auth_id"])
            REC.add(S, "GET authorization reads VOIDED", "PASS" if (g.ok and (g.data or {}).get("status") == "VOIDED") else "FAIL", http=g.status, status=(g.data or {}).get("status", "") if g.ok else g.issue, debug_id=g.debug_id)
            v2 = pp.void(info["auth_id"])
            REC.add(S, "O2: void replay returns 422 (record the issue name)", "PASS" if v2.status == 422 else "FAIL", http=v2.status, status=v2.issue or "(no issue name in body)", debug_id=v2.debug_id,
                    note="issue name recorded for the adapter's VOID_REPLAY class")
            REC.fact("O2_void_replay_issue", v2.issue)
            c = pp.capture(info["auth_id"], f"spike:{ctx.run_id}:cap-after-void")
            REC.add(S, "capture after void -> 422 AUTHORIZATION_VOIDED", "PASS" if (c.status == 422 and c.issue == "AUTHORIZATION_VOIDED") else "FAIL", http=c.status, status=c.issue, debug_id=c.debug_id)
            go = pp.get_order(cr.data["id"])
            REC.add(S, "O1: order status after void (never a payment signal)", "INFO", http=go.status, status=(go.data or {}).get("status", "") if go.ok else go.issue, note="V8 recorded COMPLETED")
    REC.implication("S2", "Authorize, capture, void and refund replay behaviour is re-confirmed; O1 and O2 are recorded.")


def run_s2_refund_phase(ctx: Ctx) -> None:
    """Phase C: refund the kept capture and replay (run after S10 and S12 have used it)."""
    S = "s2"
    pp = ctx.pp
    if not (pp and ctx.captured):
        return
    cap_id = ctx.captured["capture_id"]
    rk = f"spike:{ctx.run_id}:refund:{cap_id}:1"
    r1 = pp.refund(cap_id, rk)
    ok = r1.status == 201 and isinstance(r1.data, dict) and r1.data.get("id")
    REC.add(S, "full refund of the capture: 201", "PASS" if ok else "FAIL", http=r1.status, status=(r1.data or {}).get("status", "") if ok else r1.issue or r1.error, debug_id=r1.debug_id)
    if ok:
        ctx.caps_open.pop(cap_id, None)
        ctx.actions.add("refunded")
        r2 = pp.refund(cap_id, rk)
        REC.add(S, "replay refund with the same request ID: 200 and the original refund", "PASS" if (r2.status == 200 and (r2.data or {}).get("id") == r1.data["id"]) else "FAIL", http=r2.status, status=r2.issue, debug_id=r2.debug_id)
        g = pp.get_refund(r1.data["id"])
        REC.add(S, "GET refund: COMPLETED", "PASS" if (g.ok and (g.data or {}).get("status") == "COMPLETED") else "FAIL", http=g.status, status=(g.data or {}).get("status", "") if g.ok else g.issue, debug_id=g.debug_id)
    ctx.captured = None


def ensure_capture(ctx: Ctx, S: str) -> Optional[dict]:
    """Return a captured sandbox transaction (reuses S2's, else creates one: one buyer approval)."""
    if ctx.captured:
        return ctx.captured
    pp = ctx.pp
    assert pp
    if not ctx.interactive:
        return None
    cr, ar = create_and_approve(ctx, S, f"{S}-capture source", record_checks=False)
    if ar is None or not ar.ok or ar.data.get("status") != "APPROVED":
        return None
    info = authorize_flow(ctx, S, cr.data["id"], f"{S}-src")
    if not info:
        return None
    c = pp.capture(info["auth_id"], f"spike:{ctx.run_id}:cap:{info['auth_id']}")
    if c.status != 201 or not (c.data or {}).get("id"):
        REC.add(S, "capture for the tracker/MCP test", "FAIL", http=c.status, status=c.issue, debug_id=c.debug_id)
        return None
    ctx.caps_open[c.data["id"]] = f"{S}-src"
    ctx.captured = {"order_id": cr.data["id"], "capture_id": c.data["id"], "auth_id": info["auth_id"]}
    return ctx.captured


# ----------------------------------------------------------------------------------------------
# S4 payload ladder
# ----------------------------------------------------------------------------------------------
def run_s4(ctx: Ctx) -> None:
    S = "s4"
    pp = ctx.pp
    assert pp
    highest = 0
    # Level 1: custom_id + invoice_id, replay with same request ID and same invoice_id
    p1 = order_payload(ctx, "S4-L1", level=1)
    k1 = f"spike:{ctx.run_id}:s4-l1"
    r = pp.create_order(p1, k1)
    ok1 = r.status == 201 and (r.data or {}).get("id")
    REC.add(S, "Level 1: custom_id and unique invoice_id accepted", "PASS" if ok1 else "FAIL", http=r.status, status=(r.data or {}).get("status", "") if ok1 else r.issue, debug_id=r.debug_id)
    if ok1:
        rr = pp.create_order(p1, k1)
        good = rr.status == 200 and (rr.data or {}).get("id") == r.data["id"] and rr.issue != "DUPLICATE_INVOICE_ID"
        REC.add(S, "Level 1: replay (same request ID, same invoice_id) returns 200, same order, not DUPLICATE_INVOICE_ID", "PASS" if good else "FAIL", http=rr.status, status=rr.issue, debug_id=rr.debug_id)
        if good:
            highest = 1
    # Level 2: breakdown + items; mismatch rejected
    if highest == 1:
        p2 = order_payload(ctx, "S4-L2", level=2)
        r = pp.create_order(p2, f"spike:{ctx.run_id}:s4-l2")
        ok2 = r.status == 201 and (r.data or {}).get("id")
        REC.add(S, "Level 2: breakdown (item_total + shipping + tax_total) and items sum exactly: accepted", "PASS" if ok2 else "FAIL", http=r.status, status=(r.data or {}).get("status", "") if ok2 else r.issue, debug_id=r.debug_id)
        bad = order_payload(ctx, "S4-L2-mismatch", level=2)
        bad["purchase_units"][0]["amount"]["breakdown"]["item_total"]["value"] = "0.70"   # 0.70 + 0.10 + 0.10 != 1.00
        bad["purchase_units"][0]["items"][0]["unit_amount"]["value"] = "0.70"
        rb = pp.create_order(bad, f"spike:{ctx.run_id}:s4-l2-bad")
        REC.add(S, "Level 2: a mismatching breakdown is rejected", "PASS" if rb.status in (400, 422) else "FAIL", http=rb.status, status=rb.issue, debug_id=rb.debug_id)
        if ok2 and rb.status in (400, 422):
            highest = 2
    # Level 3: experience_context + provided shipping address with changes disabled
    if highest == 2:
        cr, ar = create_and_approve(ctx, S, "S4-L3", level=3, record_checks=False)
        if cr is not None and cr.status == 201:
            REC.add(S, "Level 3: payment_source.paypal.experience_context + provided address accepted", "PASS", http=cr.status, status=(cr.data or {}).get("status", ""), debug_id=cr.debug_id,
                    note=f"approval link rel: {'payer-action' if link_of(cr.data, 'payer-action') else ('approve' if link_of(cr.data, 'approve') else 'NONE')}")
            if ar is not None and ar.ok and ar.data.get("status") == "APPROVED":
                v = order_view(ar.data)
                addr = v.get("shipping_address") or {}
                ret = addr.get("address_line_1") == "123 Spike Street" and addr.get("postal_code") == "95131"
                REC.add(S, "Level 3: GET order returns the provided shipping address", "PASS" if ret else "FAIL", note=f"address returned={bool(addr)}")
                said = ask_yes(ctx, "On the PayPal approval page, was the shipping address LOCKED (the buyer could not change it)?")
                if said is None:
                    REC.add(S, "Level 3: address changes disabled on the approval page", "MANUAL", note="non-interactive")
                else:
                    REC.add(S, "Level 3: address changes disabled on the approval page (user-attested)", "PASS" if said else "FAIL")
                if ret and said:
                    highest = 3
            else:
                REC.add(S, "Level 3 evidence incomplete (no approval)", "MANUAL", note="level 3 stays unverified; PAYPAL_PAYLOAD_LEVEL=2")
        else:
            REC.add(S, "Level 3: payload accepted", "FAIL", http=(cr.status if cr is not None else ""), status=(cr.issue if cr is not None else ""), debug_id=(cr.debug_id if cr is not None else ""))
    REC.fact("PAYPAL_PAYLOAD_LEVEL", highest)
    REC.add(S, "highest accepted level (level 4 is unavailable per S3)", "INFO", status=f"PAYPAL_PAYLOAD_LEVEL={highest}")
    REC.implication("S4", f"Orders can carry payload level {highest}; the adapter must not send anything above it.")


# ----------------------------------------------------------------------------------------------
# S7 payee-email routing
# ----------------------------------------------------------------------------------------------
def run_s7(ctx: Ctx) -> None:
    """S7 payee routing. Recorded Oct 28: a separately selected seller received captures but void and refund returned PERMISSION_DENIED,
    so payee_email is rejected. A payee is usable only if the app can authorize, void, capture AND fully refund its payments."""
    S = "s7"
    pp = ctx.pp
    assert pp
    second = env("SECOND_SELLER_EMAIL")
    if not second:
        REC.add(S, "needs SECOND_SELLER_EMAIL", "BLOCKED")
        return
    if not ctx.interactive:
        REC.add(S, "S7 needs two buyer approvals", "MANUAL", note="--non-interactive")
        return
    all_ok = True
    # order 1: approve, authorize, void
    cr, ar = create_and_approve(ctx, S, "S7-A second-seller payee (authorize then void)", payee_email=second, expect_email=second)
    if ar is None or not ar.ok or ar.data.get("status") != "APPROVED":
        all_ok = False
    else:
        v = order_view(ar.data)
        REC.add(S, "GET order payee fields (what PayPal shows)", "INFO", note=f"payee_email={'present' if v['payee_email'] else 'MISSING'} merchant_id={'present' if v['payee_merchant_id'] else 'MISSING'}; matches second seller={((v['payee_email'] or '').lower() == second.lower())}")
        all_ok &= (v["payee_email"] or "").lower() == second.lower()
        info = authorize_flow(ctx, S, cr.data["id"], "S7-A")
        if info is None:
            all_ok = False
        else:
            vr = pp.void(info["auth_id"])
            good = vr.status in (200, 204)
            all_ok &= good
            REC.add(S, "void the second seller's authorization", "PASS" if good else "FAIL", http=vr.status, status=vr.issue, debug_id=vr.debug_id,
                    note="PERMISSION_DENIED here means the app cannot manage that seller's payments" if not good else "")
            if good:
                ctx.actions.add("voided")
    # order 2: approve, authorize, capture, full refund
    cr2, ar2 = create_and_approve(ctx, S, "S7-B second-seller payee (capture then refund)", payee_email=second, expect_email=second, record_checks=False)
    if ar2 is None or not ar2.ok or ar2.data.get("status") != "APPROVED":
        all_ok = False
    else:
        info2 = authorize_flow(ctx, S, cr2.data["id"], "S7-B")
        if info2 is None:
            all_ok = False
        else:
            c = pp.capture(info2["auth_id"], f"spike:{ctx.run_id}:cap:{info2['auth_id']}")
            cap_ok = c.status == 201 and isinstance(c.data, dict) and bool(c.data.get("id"))
            REC.add(S, "capture the second seller's authorization", "PASS" if cap_ok else "FAIL", http=c.status, status=(c.data or {}).get("status", "") if cap_ok else c.issue, debug_id=c.debug_id)
            all_ok &= cap_ok
            if cap_ok:
                cap_id = c.data["id"]
                ctx.caps_open[cap_id] = "S7-B"
                ctx.actions.add("captured")
                rr = pp.refund(cap_id, f"spike:{ctx.run_id}:refund:{cap_id}:s7")
                done = rr.status == 201 and isinstance(rr.data, dict) and rr.data.get("status") in ("COMPLETED", "PENDING")
                REC.add(S, "fully refund the second seller's capture", "PASS" if done else "FAIL", http=rr.status, status=(rr.data or {}).get("status", "") if done else rr.issue, debug_id=rr.debug_id,
                        note="PERMISSION_DENIED here means the app cannot refund that seller's payments" if not done else "")
                all_ok &= done
                if done:
                    ctx.caps_open.pop(cap_id, None)
                    ctx.actions.add("refunded")
                else:
                    ctx.caps_open.pop(cap_id, None)       # do not retry under a new key; the owner refunds it by hand
                    REC.manual_open.append(f"S7: a USD 1.00 capture ending ...{cap_id[-4:]} could not be refunded through the API; refund it from that seller's Sandbox dashboard")
    # control: payee that is not a sandbox account
    ctrl_email = f"fairpool-no-such-seller-{ctx.run_id}@example.com"
    cc = pp.create_order(order_payload(ctx, "S7-control", payee_email=ctrl_email), f"spike:{ctx.run_id}:s7-control")
    REC.add(S, "control: payee that is not a sandbox account (record the failure mode)", "INFO", http=cc.status, status=(cc.data or {}).get("status", "") if cc.ok else cc.issue or cc.error, debug_id=cc.debug_id,
            note="order creation outcome only")
    REC.fact("S7_payee_email_eligible", bool(all_ok))
    REC.add(S, "result", "INFO", status=f"payee_email {'ELIGIBLE: authorize, void, capture and refund all worked' if all_ok else 'REJECTED: single_seller stays final'}")
    REC.implication("S7", "The second payee can be fully managed by the app; the owner may choose payee_email (sandbox-only, labelled)." if all_ok else "payee_email is rejected; single_seller (the business account that owns the app) is final.")


# ----------------------------------------------------------------------------------------------
# S12 shipment tracking
# ----------------------------------------------------------------------------------------------
def run_s12(ctx: Ctx) -> None:
    """S12 tracking. Recorded Oct 28: Orders v2 POST /v2/checkout/orders/{id}/track works (201; repeat 200; GET shows one tracker);
    the legacy /v1/shipping/trackers-batch returned 403 for this app."""
    S = "s12"
    pp = ctx.pp
    assert pp
    cap = ensure_capture(ctx, S)
    if not cap:
        REC.add(S, "needs a captured sandbox transaction", "BLOCKED", note="no capture available (non-interactive or approval failed)")
        REC.fact("SHIPMENT_TRACKING_ENABLED", False)
        return
    tn = "FP" + "".join(secrets.choice("0123456789") for _ in range(10))
    body = {"capture_id": cap["capture_id"], "tracking_number": tn, "carrier": "OTHER", "carrier_name_other": "FairPool Test Carrier", "notify_payer": False}
    path = f"/v2/checkout/orders/{cap['order_id']}/track"
    r = pp.call("POST", path, json_body=body)
    ok = r.status == 201
    REC.add(S, "Orders v2 track (fictional carrier, notify_payer=false)", "PASS" if ok else "FAIL", http=r.status, status=r.issue or "created", debug_id=r.debug_id)
    one = False
    if ok:
        g = pp.get_order(cap["order_id"])
        tr = order_view(g.data)["trackings"] if g.ok and isinstance(g.data, dict) else []
        mine = [x for x in tr if x["tracking_number"] == tn]
        one = len(mine) == 1
        REC.add(S, "GET the order: exactly one matching tracker", "PASS" if one else "FAIL", http=g.status, debug_id=g.debug_id, note=f"trackers on the order={len(tr)} matching={len(mine)}")
        r2 = pp.call("POST", path, json_body=body)
        g2 = pp.get_order(cap["order_id"])
        tr2 = [x for x in (order_view(g2.data)["trackings"] if g2.ok and isinstance(g2.data, dict) else []) if x["tracking_number"] == tn]
        REC.add(S, "repeat the same request: still exactly one tracker (idempotent in effect)", "PASS" if (r2.status in (200, 201) and len(tr2) == 1) else "FAIL", http=r2.status, status=r2.issue, debug_id=r2.debug_id, note=f"matching trackers after repeat={len(tr2)}")
        one = one and len(tr2) == 1
        seen = ask_yes(ctx, "In the sandbox dashboard, can the BUYER or SELLER see the tracking info on the transaction? (check, then answer)")
        REC.add(S, "dashboard visibility (user-attested)", "MANUAL" if seen is None else ("PASS" if seen else "INFO"), note="API acceptance is not proof of shipment or delivery")
    REC.fact("SHIPMENT_TRACKING_ENABLED", bool(ok and one))
    REC.implication("S12", "Tracking can be written to PayPal with Orders v2 and read back." if (ok and one) else "Tracking is stored in FairPool only and labelled.")


# ----------------------------------------------------------------------------------------------
# S1 Log in with PayPal
# ----------------------------------------------------------------------------------------------
def run_s1(ctx: Ctx) -> None:
    """S1 Log in with PayPal. Recorded Oct 28: scope `openid` works; the account-attributes scope was rejected (invalid_scope);
    userinfo returned `sub` and `user_id`, which differed from the checkout payer_id. Identifiers are compared RAW (never normalised)."""
    S = "s1"
    pp = ctx.pp
    assert pp
    redirect = env("PAYPAL_LOGIN_REDIRECT_URI")
    if not redirect:
        REC.add(S, "needs PAYPAL_LOGIN_REDIRECT_URI", "BLOCKED")
        REC.fact("DEDUPE_MODE", "checkout_only")
        return
    if not redirect.startswith("https://") and not redirect.startswith("http://localhost"):
        REC.add(S, "return URL must be a web URL registered in the app (not nativexo://)", "FAIL", note="register a web return URL")
        return
    if not ctx.interactive:
        REC.add(S, "S1 needs the buyer's consent", "MANUAL", note="--non-interactive")
        return
    attr = "https://uri.paypal.com/services/paypalattributes"
    variants = [("A", "openid")]
    if env("S1_TRY_ATTRIBUTES_SCOPE") == "1":
        variants.append(("B", f"openid {attr}"))    # optional re-check: rejected with invalid_scope on Oct 28
    primary: dict = {}
    for tag, scope in variants:
        state, nonce = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
        url = (f"{pp.www}/connect?flowEntry=static&client_id={quote(pp.cid)}&response_type=code&scope={quote(scope)}"
               f"&redirect_uri={quote(redirect, safe='')}&state={state}&nonce={nonce}")
        log(f"\n>>> ACTION NEEDED (S1 variant {tag}, scope {scope!r}): log in as the US sandbox BUYER and give consent.")
        if ctx.print_urls:
            print(url, flush=True)
        try:
            webbrowser.open(url)
        except Exception:
            pass
        log("    After consent the browser is sent to your return URL. Even if that page fails to load, copy the FULL address from the address bar.")
        pasted = ask(ctx, "    Paste the full redirected URL here (or press Enter to mark this variant as failed): ")
        q = parse_qs(urlparse(pasted).query) if pasted else {}
        if not pasted or "code" not in q:
            err = (q.get("error") or ["no_code"])[0]
            REC.add(S, f"variant {tag}: authorization request", "FAIL" if tag == "A" else "INFO", status=err,
                    note=f"scopes={scope!r} encoded={quote(scope)!r} return_url={redirect} error_description={(q.get('error_description') or [''])[0]}")
            continue
        if (q.get("state") or [""])[0] != state:
            REC.add(S, f"variant {tag}: state matches", "FAIL", note="state mismatch: do not use this code")
            continue
        REC.add(S, f"variant {tag}: authorization request accepted, code returned", "PASS", status="code")
        tr = ctx.http.request("POST", f"{pp.api}/v1/oauth2/token", auth=(pp.cid, pp.secret), headers={"Accept": "application/json"},
                              data={"grant_type": "authorization_code", "code": q["code"][0]})
        if not tr.ok and "redirect" in (tr.text + json.dumps(tr.data or {})).lower():
            tr = ctx.http.request("POST", f"{pp.api}/v1/oauth2/token", auth=(pp.cid, pp.secret), headers={"Accept": "application/json"},
                                  data={"grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": redirect})
        REC.add(S, f"variant {tag}: exchange code for a user token (server side)", "PASS" if tr.ok else "FAIL", http=tr.status, status=tr.issue,
                debug_id=tr.debug_id, note=f"fields={tr.field_names()}")
        if not (tr.ok and isinstance(tr.data, dict) and tr.data.get("access_token")):
            continue
        REDACT.add(tr.data["access_token"])
        hdr = {"Authorization": f"Bearer {tr.data['access_token']}", "Accept": "application/json"}
        ui = ctx.http.request("GET", f"{pp.api}/v1/identity/oauth2/userinfo?schema=paypalv1.1", headers=hdr)
        if not ui.ok:
            ui = ctx.http.request("GET", f"{pp.api}/v1/identity/oauth2/userinfo?schema=openid", headers=hdr)
        ids = {k: str(ui.data[k]) for k in ("payer_id", "user_id", "sub") if ui.ok and isinstance(ui.data, dict) and ui.data.get(k)}
        REC.add(S, f"variant {tag}: userinfo; identifier fields present (values never recorded)", "PASS" if ids else "FAIL", http=ui.status, status=ui.issue,
                debug_id=ui.debug_id, note=f"fields={ui.field_names()}; identifier fields={sorted(ids)}")
        if tag == "A":
            primary = ids
    if not primary:
        REC.fact("DEDUPE_MODE", "checkout_only")
        REC.fact("REQUIRE_PAYPAL_LINK", False)
        REC.add(S, "rule: no usable login identifier", "INFO", status="DEDUPE_MODE=checkout_only; REQUIRE_PAYPAL_LINK=false")
        REC.implication("S1", "Login cannot provide an identifier: dedupe by checkout payer_id only.")
        return
    cr, ar = create_and_approve(ctx, S, "S1 checkout payer_id comparison (use the SAME buyer as the consent)", record_checks=False)
    pay = (order_view(ar.data)["payer_id"] if ar is not None and ar.ok and isinstance(ar.data, dict) else None)
    if not pay:
        REC.add(S, "order payer_id available for comparison", "FAIL")
        REC.fact("DEDUPE_MODE", "two_keys")
        return
    matches = sorted(k for k, v in primary.items() if hmaclib.compare_digest(ctx.hm(v), ctx.hm(pay)))   # RAW comparison, no prefix stripping
    REC.add(S, "compare HMAC(each raw userinfo identifier) with HMAC(order payer_id) (values never recorded; raw strings, never normalised)", "PASS",
            status=f"EQUAL via {matches}" if matches else "DIFFERENT")
    mode = "full" if matches else "two_keys"
    REC.fact("DEDUPE_MODE", mode)
    REC.fact("login_scope", "openid")
    REC.add(S, "rule applied", "INFO", status=f"DEDUPE_MODE={mode}", note="neither identifier proves one human; do not strip prefixes to force equality")
    REC.implication("S1", "A login identifier equals the checkout payer_id: one key per PayPal account." if matches else "Login and checkout identifiers differ: keep two separate provider identifiers.")


# ----------------------------------------------------------------------------------------------
# S5 webhooks: listener, registration, evaluation
# ----------------------------------------------------------------------------------------------
class WebhookListener:
    def __init__(self, port: int, run_id: str) -> None:
        self.events: list[dict] = []     # {t, id, type, headers, raw}
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:  # silence
                pass

            def do_GET(self) -> None:
                body = f"fairpool-spike-listener {run_id}".encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    j = json.loads(raw.decode("utf-8"))
                except Exception:
                    j = {}
                with outer.lock:
                    outer.events.append({"t": now_s(), "id": j.get("id", ""), "type": j.get("event_type", ""),
                                         "headers": {k.lower(): v for k, v in self.headers.items()}, "raw": raw})
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("0.0.0.0", port), H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()

    def snapshot(self) -> list[dict]:
        with self.lock:
            return list(self.events)


def webhook_setup(ctx: Ctx) -> None:
    S = "s5"
    pp = ctx.pp
    assert pp
    pub = env("WEBHOOK_PUBLIC_URL")
    if not pub:
        REC.add(S, "needs WEBHOOK_PUBLIC_URL (public https URL on port 443 that tunnels to this script)", "BLOCKED")
        return
    u = urlparse(pub)
    selftest_local = env("FAIRPOOL_SPIKE_SELFTEST") == "1" and (u.hostname in ("127.0.0.1", "localhost"))
    if not selftest_local and (u.scheme != "https" or (u.port not in (None, 443))):
        REC.add(S, "listener URL must be https on port 443 (checklist 5.1)", "FAIL", note=f"got scheme={u.scheme} port={u.port}")
        return
    port = int(env("WEBHOOK_LISTEN_PORT", "8787"))
    try:
        ctx.webhook = WebhookListener(port, ctx.run_id)
        ctx.webhook.start()
    except OSError as ex:
        REC.add(S, f"start local listener on port {port}", "FAIL", note=str(ex))
        return
    full = pub.rstrip("/") + "/webhooks/paypal"
    r = ctx.http.request("GET", pub.rstrip("/") + "/health", retries=1)
    reach = r.status == 200 and ctx.run_id in (r.text or "")
    REC.add(S, "public URL reaches this script's listener (tunnel check)", "PASS" if reach else "FAIL", http=r.status, note="the tunnel must forward https:443 to the local listener port" if not reach else "")
    if not reach:
        ctx.webhook.stop()
        ctx.webhook = None
        return
    cr = pp.create_webhook(full, SEVEN_EVENTS)
    if cr.status in (200, 201) and isinstance(cr.data, dict) and cr.data.get("id"):
        ctx.webhook_id, ctx.created_webhook = cr.data["id"], True
        REC.add(S, "register the listener for the seven V7 event types", "PASS", http=cr.status, debug_id=cr.debug_id)
    else:
        lw = pp.list_webhooks()
        found = [w for w in (lw.data or {}).get("webhooks", []) if w.get("url") == full] if lw.ok and isinstance(lw.data, dict) else []
        if found:
            ctx.webhook_id = found[0]["id"]
            REC.add(S, "listener URL already registered: reusing it (not deleted at the end)", "PASS", http=cr.status, status=cr.issue, debug_id=cr.debug_id)
        else:
            REC.add(S, "register the listener", "FAIL", http=cr.status, status=cr.issue or cr.error, debug_id=cr.debug_id)
            ctx.webhook.stop()
            ctx.webhook = None


EXPECTED_BY_ACTION = {
    "approved": "CHECKOUT.ORDER.APPROVED", "authorized": "PAYMENT.AUTHORIZATION.CREATED",
    "voided": "PAYMENT.AUTHORIZATION.VOIDED", "captured": "PAYMENT.CAPTURE.COMPLETED", "refunded": "PAYMENT.CAPTURE.REFUNDED",
}


def webhook_evaluate(ctx: Ctx) -> None:
    S = "s5"
    pp = ctx.pp
    if not (pp and ctx.webhook and ctx.webhook_id):
        REC.fact("WEBHOOKS_ENABLED", False)
        return
    wl = ctx.webhook
    expected = {EXPECTED_BY_ACTION[a] for a in ctx.actions if a in EXPECTED_BY_ACTION}
    REC.fact("WEBHOOK_TYPES_EXPECTED", sorted(expected))
    if not expected:
        REC.add(S, "no real lifecycle ran, so no real events to check", "BLOCKED", note="run S2 or S13 in the same run")
        REC.fact("WEBHOOKS_ENABLED", False)
        return
    log(f"\nWaiting up to 4 minutes for webhook deliveries of: {sorted(expected)}")
    deadline = now_s() + 240
    while now_s() < deadline:
        seen = {e["type"] for e in wl.snapshot()}
        if expected.issubset(seen):
            break
        time.sleep(5)
    events = wl.snapshot()
    by_type: dict[str, list[dict]] = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    verified: list[str] = []
    failed: list[str] = []
    missing: list[str] = []
    for et in sorted(expected):
        got = by_type.get(et, [])
        if not got:
            missing.append(et)
            REC.add(S, f"real event arrived: {et}", "INFO", note="not delivered within 4 minutes: never wait for this event; confirm by GET (recorded Oct 28 for CHECKOUT.ORDER.APPROVED)")
            continue
        e = got[0]
        vr = pp.verify_webhook(e["headers"], e["raw"], ctx.webhook_id)
        st = (vr.data or {}).get("verification_status") if vr.ok and isinstance(vr.data, dict) else ""
        good = st == "SUCCESS"
        (verified if good else failed).append(et)
        REC.add(S, f"real event arrived and verifies: {et}", "PASS" if good else "FAIL", http=vr.status, status=st or vr.issue, debug_id=vr.debug_id)
    for et in SEVEN_EVENTS:
        if et not in expected:
            REC.add(S, f"event {et}", "INFO", note="seen" if et in by_type else "not produced by this lifecycle (not forced; PENDING and DENIED cannot be triggered on demand)")
    # dedup: resend one real event and expect the same event ID twice
    pick = next((by_type[t][0] for t in sorted(expected) if by_type.get(t)), None)
    if pick:
        before = sum(1 for e in wl.snapshot() if e["id"] == pick["id"])
        rr = pp.resend_event(pick["id"], ctx.webhook_id)
        t0 = now_s()
        while now_s() - t0 < 90 and sum(1 for e in wl.snapshot() if e["id"] == pick["id"]) <= before:
            time.sleep(4)
        after = sum(1 for e in wl.snapshot() if e["id"] == pick["id"])
        REC.add(S, "resend one event: the same event ID arrives again (so the app must de-duplicate by event ID)", "PASS" if after > before else "FAIL",
                http=rr.status, status=rr.issue, debug_id=rr.debug_id, note=f"arrivals of that ID: {before} -> {after}")
    # simulator event (mock)
    known = {e["id"] for e in wl.snapshot()}
    sr = pp.simulate_event(ctx.webhook_id, "PAYMENT.CAPTURE.COMPLETED")
    t0 = now_s()
    sim = None
    while now_s() - t0 < 90 and sim is None:
        for e in wl.snapshot():
            if e["id"] not in known and e["type"] == "PAYMENT.CAPTURE.COMPLETED":
                sim = e
        time.sleep(3)
    if sim:
        vv = pp.verify_webhook(sim["headers"], sim["raw"], ctx.webhook_id)
        st = (vv.data or {}).get("verification_status") if vv.ok and isinstance(vv.data, dict) else ""
        REC.add(S, "simulator event: arrived; verification result recorded (P4 says simulator events are mock)", "INFO", http=vv.status, status=st or vv.issue, debug_id=vv.debug_id)
    else:
        REC.add(S, "simulator event did not arrive", "INFO", http=sr.status, status=sr.issue, debug_id=sr.debug_id)
    enabled = bool(verified) and not failed
    REC.fact("WEBHOOK_TYPES_VERIFIED", sorted(verified))
    REC.fact("WEBHOOK_TYPES_NOT_DELIVERED", sorted(missing))
    REC.fact("WEBHOOK_TYPES_FAILED_VERIFICATION", sorted(failed))
    REC.fact("WEBHOOKS_ENABLED", enabled)
    REC.add(S, "rule applied (per event type)", "INFO", status=f"WEBHOOKS_ENABLED={'true for the verified types only' if enabled else 'false'}",
            note="a handler may act only on verified types, as a hint that triggers a GET; absent types are never awaited")
    REC.implication("S5", f"Verified types: {sorted(verified)}. Webhooks are hints; GET reconciliation stays authoritative." if enabled else "No event type verified: the reconciler is the only update path.")


def webhook_teardown(ctx: Ctx) -> None:
    if ctx.pp and ctx.webhook_id and ctx.created_webhook:
        r = ctx.pp.delete_webhook(ctx.webhook_id)
        REC.add("s5", "remove the spike's webhook registration", "PASS" if r.status in (200, 204) else "FAIL", http=r.status, status=r.issue, debug_id=r.debug_id)
    if ctx.webhook:
        ctx.webhook.stop()


# ----------------------------------------------------------------------------------------------
# S6 drand beacon + sandbox buyers
# ----------------------------------------------------------------------------------------------
def bls_verify_quicknet(round_no: int, sig_hex: str, pubkey_hex: str) -> Optional[bool]:
    """True/False, or None when pyblst is not installed."""
    try:
        import pyblst  # type: ignore
    except ImportError:
        return None
    msg = hashlib.sha256(round_no.to_bytes(8, "big")).digest()
    h = pyblst.BlstP1Element.hash_to_group(msg, BLS_G1_DST)
    s = pyblst.BlstP1Element.uncompress(bytes.fromhex(sig_hex))
    pk = pyblst.BlstP2Element.uncompress(bytes.fromhex(pubkey_hex))
    g = pyblst.BlstP2Element.uncompress(bytes.fromhex(BLS_G2_GEN))
    return bool(pyblst.final_verify(pyblst.miller_loop(s, g), pyblst.miller_loop(h, pk)))


def round_at_or_after(t: float, genesis: int, period: int) -> int:
    """First drand round whose publication time (genesis + (r-1)*period) is >= t."""
    if t <= genesis:
        return 1
    return int(-(-(t - genesis) // period)) + 1


def run_s6_beacon(ctx: Ctx) -> None:
    S = "s6"
    base = (env("DRAND_BASE_URL") or "https://api.drand.sh").rstrip("/")
    chain = env("DRAND_CHAIN_HASH") or QUICKNET_HASH
    ok_all = True
    info = ctx.http.request("GET", f"{base}/{chain}/info", retries=2)
    if not info.ok or not isinstance(info.data, dict):
        REC.add(S, "drand chain info", "FAIL", http=info.status, status=info.issue or info.error)
        REC.fact("BEACON_MODE", "demo")
        return
    d = info.data
    genesis, period = int(d.get("genesis_time", 0)), int(d.get("period", 0))
    pinned = chain == QUICKNET_HASH
    pk = QUICKNET_PUBKEY if pinned else str(d.get("public_key", ""))
    good_info = d.get("hash") == chain and period > 0 and (not pinned or (d.get("public_key") == QUICKNET_PUBKEY and d.get("schemeID") == "bls-unchained-g1-rfc9380"))
    REC.add(S, "chain info: hash matches the pinned chain; scheme and public key as published", "PASS" if good_info else "FAIL", http=info.status,
            note=f"chain_hash={d.get('hash')} period={period}s scheme={d.get('schemeID')} public_key_pinned={pinned}")
    ok_all &= good_info
    latest = ctx.http.request("GET", f"{base}/{chain}/public/latest", retries=2)
    if not latest.ok or not isinstance(latest.data, dict):
        REC.add(S, "fetch the latest round", "FAIL", http=latest.status, status=latest.issue or latest.error)
        REC.fact("BEACON_MODE", "demo")
        return
    L = latest.data
    rnd, sig, rand = int(L["round"]), L["signature"], L["randomness"]
    rand_ok = hashlib.sha256(bytes.fromhex(sig)).hexdigest() == rand
    bls = bls_verify_quicknet(rnd, sig, pk) if pinned or d.get("schemeID") == "bls-unchained-g1-rfc9380" else None
    if bls is None:
        REC.add(S, "verify the round's BLS signature", "BLOCKED", note="install pyblst (pip install pyblst) so the signature can be verified")
        ok_all = False
    else:
        REC.add(S, "verify the round's BLS signature (G1 signature, pinned public key)", "PASS" if bls else "FAIL", http=latest.status)
        ok_all &= bool(bls)
    REC.add(S, "randomness equals SHA-256(signature)", "PASS" if rand_ok else "FAIL", note=f"round={rnd} randomness={rand}")
    ok_all &= rand_ok
    exp = int((now_s() - genesis) // period) + 1
    REC.add(S, "round number agrees with the wall clock and the round-time formula", "PASS" if abs(rnd - exp) <= 2 else "FAIL", note=f"latest={rnd} expected~{exp}")
    ok_all &= abs(rnd - exp) <= 2
    # cross relay agreement
    custom = [x.strip() for x in env("DRAND_OTHER_RELAYS").split(",") if x.strip()]
    others = custom or [b for b in ("https://api2.drand.sh", "https://api3.drand.sh", "https://drand.cloudflare.com", "https://api.drand.sh") if b.rstrip("/") != base]
    agreed = 0
    for b in others:
        r = ctx.http.request("GET", f"{b}/{chain}/public/{rnd}", retries=1)
        if r.ok and isinstance(r.data, dict) and r.data.get("signature") == sig:
            agreed += 1
    REC.add(S, "another independent relay returns the identical signature for that round", "PASS" if agreed >= 1 else "FAIL", note=f"{agreed} of {len(others)} relays agreed")
    ok_all &= agreed >= 1
    # announced future round
    delay = int(env("S6_BEACON_DELAY_S", "20"))
    t_target = now_s() + delay
    r_future = round_at_or_after(t_target, genesis, period)
    early = ctx.http.request("GET", f"{base}/{chain}/public/{r_future}")
    REC.add(S, f"the announced round ({r_future}) does not exist before its time", "PASS" if not early.ok else "FAIL", http=early.status)
    wait = max(0.0, (genesis + (r_future - 1) * period) - now_s()) + period + 2
    log(f"    waiting {int(wait)}s for round {r_future} to be published ...")
    time.sleep(wait)
    late = ctx.http.request("GET", f"{base}/{chain}/public/{r_future}", retries=3)
    if late.ok and isinstance(late.data, dict):
        v2 = bls_verify_quicknet(int(late.data["round"]), late.data["signature"], pk)
        pub_time = genesis + (r_future - 1) * period
        REC.add(S, "the announced round exists after its time, verifies, and was published at or after the target time",
                "PASS" if (v2 and pub_time >= t_target - 1e-6) else ("BLOCKED" if v2 is None else "FAIL"), http=late.status,
                note=f"round={r_future} randomness={late.data.get('randomness')}")
        ok_all &= bool(v2) and pub_time >= t_target - 1e-6
    else:
        REC.add(S, "the announced round exists after its time", "FAIL", http=late.status, status=late.issue or late.error)
        ok_all = False
    REC.fact("drand_chain_hash", chain)
    REC.fact("drand_period_s", period)
    REC.fact("BEACON_MODE", "drand" if ok_all else "demo")
    REC.add(S, "rule applied", "INFO", status=f"BEACON_MODE={'drand' if ok_all else 'demo'}")
    REC.implication("S6", "A verified public beacon works: use drand." if ok_all else "Beacon not proven: BEACON_MODE=demo (labelled).")


def run_s6_buyers(ctx: Ctx) -> None:
    S = "s6"
    pp = ctx.pp
    assert pp
    n = int(env("S6_BUYER_COUNT", "6"))
    if not ctx.interactive:
        REC.add(S, f"approve a USD 1.00 order with each of {n} different US sandbox buyers", "MANUAL", note="--non-interactive")
        return
    log(f"\nS6 buyers: you will approve {n} orders, each with a DIFFERENT sandbox buyer. Use a private window and log out between buyers.")
    seen: dict[str, str] = {}
    for i in range(1, n + 1):
        go = ask(ctx, f"  Ready for buyer #{i}? Press Enter to open the approval page, or type 's' to stop here: ")
        if go.lower().startswith("s"):
            break
        cr, ar = create_and_approve(ctx, S, f"S6 buyer #{i}", record_checks=False)
        if ar is not None and ar.ok and isinstance(ar.data, dict) and ar.data.get("status") == "APPROVED":
            v = order_view(ar.data)
            h = ctx.hm(v["payer_id"]) if v["payer_id"] else ""
            dup = bool(h) and h in seen
            good = v["payer_country"] == "US" and bool(h) and not dup
            if good:
                seen[h] = f"buyer#{i}"
            REC.add(S, f"buyer #{i}: approved, payer country {v['payer_country']}, different account from the earlier buyers", "PASS" if good else "FAIL",
                    note=f"same account as {seen[h]}: log in with a different buyer" if dup else "")
        else:
            REC.add(S, f"buyer #{i}: approval", "FAIL", note="order did not reach APPROVED")
    REC.fact("sandbox_us_buyers_distinct", len(seen))
    REC.add(S, "distinct US sandbox buyers that approved", "PASS" if len(seen) >= n else "FAIL", note=f"{len(seen)} of {n} target (D11 target: six)")


# ----------------------------------------------------------------------------------------------
# S13 JavaScript SDK v6 approval (local page on http://localhost; HTTPS deployed check stays in T02B05)
# ----------------------------------------------------------------------------------------------
S13_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>FairPool spike S13</title></head><body>
<h3>FairPool spike S13: PayPal JS SDK v6 (Sandbox, USD 1.00 AUTHORIZE)</h3>
<div id="status">loading SDK...</div><div id="btn"></div><pre id="log"></pre>
<script>
const MODE="__MODE__", CLIENT_ID="__CLIENT_ID__";
function post(kind, extra){ return fetch('/api/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign({kind:kind},extra||{}))}).catch(()=>{}); }
function log(m){ document.getElementById('log').textContent += m+"\\n"; }
window.addEventListener('error', e=>{ log('console error: '+e.message); post('console_error',{msg:String(e.message).slice(0,300)}); });
window.addEventListener('unhandledrejection', e=>{ const m=(e.reason&&e.reason.message)||String(e.reason); log('unhandled rejection: '+m); post('console_error',{msg:String(m).slice(0,300)}); });
async function createOrder(){ const r=await fetch('/api/orders',{method:'POST'}); const j=await r.json(); if(!j.id) throw new Error('server could not create the order'); return {orderId:j.id}; }
async function onApprove(data){
  const fields=Object.keys(data||{}).sort(); log('onApprove fields: '+fields.join(','));
  const r=await fetch('/api/approved',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fields:fields,orderId:(data||{}).orderId})});
  const j=await r.json(); document.getElementById('status').textContent='approved; server checks: '+JSON.stringify(j.summary);
}
function onCancel(data){ const f=Object.keys(data||{}).sort(); log('onCancel fields: '+f.join(',')); post('cancel',{fields:f,orderId:(data||{}).orderId}); }
function onError(err){ const m=(err&&err.message)||String(err); log('onError: '+m); post('error',{msg:String(m).slice(0,300)}); }
async function onLoad(){
  try{
    const opts={components:["paypal-payments"],pageType:"checkout"};
    if(MODE==="client_token"){ const t=await (await fetch('/api/client-token',{method:'POST'})).json(); if(!t.token) throw new Error('no client token: '+(t.error||'')); opts.clientToken=t.token; }
    else { opts.clientId=CLIENT_ID; }
    const sdk=await window.paypal.createInstance(opts);
    post('init_ok',{mode:MODE});
    const methods=await sdk.findEligibleMethods({currencyCode:"USD"});
    const eligible=methods.isEligible("paypal"); post('eligible',{eligible:!!eligible});
    if(!eligible){ document.getElementById('status').textContent='PayPal not eligible'; return; }
    const btn=document.createElement('paypal-button'); document.getElementById('btn').append(btn);
    const session=await sdk.createPayPalOneTimePaymentSession({onApprove:onApprove,onCancel:onCancel,onError:onError});
    document.getElementById('status').textContent='ready: click the PayPal button';
    btn.addEventListener('click', async ()=>{
      try{ const p=createOrder(); await session.start({presentationMode:"auto"}, p); post('start_called',{}); }
      catch(e){ log('start error: '+e.message); post('start_error',{msg:String(e.message).slice(0,300)}); }
    });
  }catch(e){ const m=(e&&e.message)||String(e); log('init error: '+m); post('init_failed',{mode:MODE,msg:String(m).slice(0,300)}); }
}
</script>
<script async src="__SDK_URL__" onload="onLoad()"></script></body></html>"""


class S13Server:
    def __init__(self, ctx: Ctx, port: int, mode: str) -> None:
        self.ctx, self.mode = ctx, mode
        self.events: list[dict] = []
        self.orders: list[str] = []
        self.summary: Optional[dict] = None
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                page = (S13_PAGE.replace("__MODE__", outer.mode).replace("__CLIENT_ID__", ctx.pp.cid)
                        .replace("__SDK_URL__", f"{ctx.pp.www}/web-sdk/v6/core"))
                self._send(200, page.encode(), "text/html; charset=utf-8")

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    body = json.loads(raw.decode() or "{}")
                except ValueError:
                    body = {}
                try:
                    out = outer.route(self.path, body)
                    self._send(200, json.dumps(out).encode())
                except Exception as ex:   # never leak details to the page
                    self._send(500, json.dumps({"error": REDACT(str(ex))[:200]}).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def route(self, path: str, body: dict) -> dict:
        ctx, pp = self.ctx, self.ctx.pp
        assert pp
        if path == "/api/orders":
            payload = order_payload(ctx, "S13-sdk")
            r = pp.create_order(payload, f"spike:{ctx.run_id}:s13:{payload['purchase_units'][0]['reference_id']}")
            if r.status == 201 and isinstance(r.data, dict):
                with self.lock:
                    self.orders.append(r.data["id"])
                REC.add("s13", "createOrder() on the server returned the order ID to the SDK", "PASS", http=r.status, status=r.data.get("status", ""), debug_id=r.debug_id)
                return {"id": r.data["id"]}
            REC.add("s13", "createOrder() on the server", "FAIL", http=r.status, status=r.issue, debug_id=r.debug_id)
            return {"error": "create failed"}
        if path == "/api/client-token":
            dom = urlparse(env("S13_PUBLIC_URL")).hostname or env("S13_CLIENT_TOKEN_DOMAIN", "localhost")   # localhost returns 401 invalid_domain (recorded Oct 28)
            r = pp.sdk_client_token([dom])
            if r.ok and isinstance(r.data, dict) and r.data.get("access_token"):
                REDACT.add(r.data["access_token"])
                REC.add("s13", "server obtained an SDK client token (grant_type=client_credentials, response_type=client_token)", "PASS", http=r.status, note=f"expires_in={r.data.get('expires_in')}")
                return {"token": r.data["access_token"]}
            REC.add("s13", "server obtained an SDK client token", "FAIL", http=r.status, status=r.issue, debug_id=r.debug_id)
            return {"error": r.issue or "token failed"}
        if path == "/api/event":
            with self.lock:
                self.events.append(body)
            return {"ok": True}
        if path == "/api/approved":
            oid = str(body.get("orderId") or "")
            with self.lock:
                known = oid in self.orders
            if not known:      # accept callbacks only for orders this server created
                REC.add("s13", "approval callback for an order this server did not create is rejected", "PASS")
                return {"summary": {"rejected": True}}
            g = pp.get_order(oid)
            checks = approval_checks(order_view(g.data), ctx.seller) if g.ok and isinstance(g.data, dict) else []
            ctx.actions.add("approved")
            info = None
            if g.ok and checks and all(c[1] for c in checks):
                info = authorize_flow(ctx, "s13", oid, "S13")
            vr = pp.void(info["auth_id"]) if info else None
            voided = vr is not None and vr.status in (200, 204)
            if voided:
                ctx.actions.add("voided")
            REC.add("s13", "server-side checks, authorize (S2 endpoint) and void after SDK approval",
                    "PASS" if (info and voided) else "FAIL", http=(vr.status if vr is not None else ""), status=(vr.issue if vr is not None else "checks failed"),
                    note=f"onApprove fields={body.get('fields')}; checks_ok={all(c[1] for c in checks) if checks else False}")
            self.summary = {"checks_ok": bool(checks) and all(c[1] for c in checks), "authorized": bool(info), "voided": bool(voided)}
            with self.lock:     # emitted only AFTER validation, authorize and void finished (the first harness run raced here)
                self.events.append({"kind": "approved", "fields": body.get("fields"), "orderId": oid})
            return {"summary": self.summary}
        return {"error": "unknown route"}

    def wait_for(self, kinds: set[str], timeout_s: int) -> Optional[dict]:
        t0 = now_s()
        seen = 0
        while now_s() - t0 < timeout_s:
            with self.lock:
                evs = self.events[seen:]
                seen = len(self.events)
            for e in evs:
                if e.get("kind") in kinds:
                    return e
            time.sleep(1)
        return None


def run_s13(ctx: Ctx) -> None:
    S = "s13"
    pp = ctx.pp
    assert pp
    if not ctx.interactive:
        REC.add(S, "S13 needs a browser and a buyer", "MANUAL", note="--non-interactive")
        REC.fact("PAYPAL_APPROVAL_UI", "redirect")
        return
    port = int(env("S13_LISTEN_PORT", "8788"))
    public = env("S13_PUBLIC_URL").rstrip("/")     # an https tunnel to S13_LISTEN_PORT: needed for client_token (localhost -> invalid_domain)
    worked_mode = ""
    for mode in (("client_id", "client_token") if public else ("client_id",)):
        srv = S13Server(ctx, port, mode)
        srv.thread.start()
        url = (public + "/") if public else f"http://localhost:{port}/"
        log(f"\n>>> ACTION NEEDED (S13, init mode {mode}): a test page is open at {url} . Click the PayPal button, approve as the US sandbox BUYER.")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        ev = srv.wait_for({"init_ok", "init_failed"}, 180)
        if ev is None or ev.get("kind") == "init_failed":
            REC.add(S, f"createInstance with {mode}", "FAIL", note=(ev or {}).get("msg", "no response from the page in 60s (script blocked or page not opened?)"))
            srv.server.shutdown()
            continue
        REC.add(S, f"createInstance with {mode} (components paypal-payments, pageType checkout)", "PASS")
        el = srv.wait_for({"eligible"}, 20)
        REC.add(S, "findEligibleMethods({currencyCode: USD}) and render <paypal-button>", "PASS" if (el and el.get("eligible")) else "FAIL", note=f"eligible={(el or {}).get('eligible')}")
        ap = srv.wait_for({"approved", "error", "start_error", "cancel"}, 600)
        if ap and ap.get("kind") == "approved":
            REC.add(S, "SDK popup approval: onApprove argument fields recorded (hints only; the server GET decides)", "PASS", note=f"fields={ap.get('fields')}")
            worked_mode = mode if (srv.summary or {}).get("voided") else ""
            # cancel test
            log(">>> ACTION NEEDED (S13 cancel test): click the PayPal button again, then CANCEL in the popup.")
            cn = srv.wait_for({"cancel", "error"}, 300)
            if cn and cn.get("kind") == "cancel" and srv.orders:
                oid = srv.orders[-1]
                g = pp.get_order(oid)
                v = order_view(g.data) if g.ok and isinstance(g.data, dict) else {}
                clean = bool(v) and v["status"] in ("CREATED", "PAYER_ACTION_REQUIRED") and not v["auths"] and not v["caps"]
                REC.add(S, "onCancel fired; the cancelled order is not approved and has no authorization or capture (checklist 2.7)", "PASS" if clean else "FAIL", http=g.status, status=v.get("status", ""), note=f"fields={cn.get('fields')}")
            else:
                REC.add(S, "onCancel fired", "FAIL", note=f"event={(cn or {}).get('kind')}")
            fb = ask_yes(ctx, "Now BLOCK popups for localhost in your browser, click the button again: did the flow still work (fallback)?")
            REC.add(S, "blocked popup: presentationMode auto falls back (user-attested)", "MANUAL" if fb is None else ("PASS" if fb else "FAIL"))
            errs = [e.get("msg") for e in srv.events if e.get("kind") == "console_error"]
            REC.add(S, "console errors seen by the page", "INFO", note=f"{len(errs)} error(s): {errs[:3]}" if errs else "none")
        else:
            REC.add(S, "SDK popup approval", "FAIL", note=f"event={(ap or {}).get('kind')} {(ap or {}).get('msg', '')}")
        srv.server.shutdown()
        if worked_mode:
            break
    REC.fact("PAYPAL_APPROVAL_UI", "sdk_popup" if worked_mode else "redirect")
    REC.fact("PAYPAL_SDK_AUTH", worked_mode or "client_id")
    REC.add(S, "rule applied", "INFO", status=f"PAYPAL_APPROVAL_UI={'sdk_popup' if worked_mode else 'redirect'}; PAYPAL_SDK_AUTH={worked_mode or 'client_id'}",
            note=("tested on the public HTTPS URL" if public else "tested on http://localhost only (set S13_PUBLIC_URL to an https tunnel to also test client_token and an HTTPS page)") + "; blocked-popup row is user-attested")
    REC.implication("S13", f"The v6 popup approves AUTHORIZE orders using {worked_mode}." if worked_mode else "Redirect approval stays; the README says so.")


# ----------------------------------------------------------------------------------------------
# Minimal MCP clients (no SDK dependency): Streamable HTTP, legacy SSE, stdio
# ----------------------------------------------------------------------------------------------
MCP_PROTOCOL = "2025-06-18"


class McpError(Exception):
    pass


def _sse_messages(text: str) -> list[dict]:
    out: list[dict] = []
    for block in re.split(r"\r?\n\r?\n", text):
        data = []
        for line in block.splitlines():
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data:
            try:
                out.append(json.loads("\n".join(data)))
            except ValueError:
                pass
    return out


class McpHttp:
    """MCP over Streamable HTTP (one POST per JSON-RPC message; reply is JSON or an SSE stream)."""
    def __init__(self, url: str, headers: Optional[dict] = None, timeout: float = 60.0) -> None:
        self.url, self.base_headers = url, dict(headers or {})
        self.client = httpx.Client(timeout=timeout, follow_redirects=False)
        self.session_id = ""
        self.protocol = MCP_PROTOCOL
        self._id = 0
        self.server_info: dict = {}
        self.last_status = 0
        self.init_status = 0

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.base_headers}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.session_id or self._id > 0:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    def _post(self, msg: dict) -> list[dict]:
        r = self.client.post(self.url, headers=self._headers(), content=json.dumps(msg).encode())
        self.last_status = r.status_code
        sid = r.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        if r.status_code in (202, 204):
            return []
        if r.status_code >= 400:
            raise McpError(f"HTTP {r.status_code}")
        ctype = r.headers.get("content-type", "")
        if ctype.startswith("text/event-stream"):
            return _sse_messages(r.text)
        try:
            j = r.json()
        except ValueError:
            raise McpError(f"non-JSON reply (content-type {ctype})")
        return j if isinstance(j, list) else [j]

    def rpc(self, method: str, params: Optional[dict] = None) -> Any:
        self._id += 1
        rid = self._id
        msgs = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        for m in msgs:
            if m.get("id") == rid:
                if "error" in m:
                    raise McpError(f"{method}: {m['error'].get('message', m['error'])}")
                return m.get("result")
        raise McpError(f"{method}: no response for request {rid}")

    def initialize(self) -> dict:
        res = self.rpc("initialize", {"protocolVersion": MCP_PROTOCOL, "capabilities": {},
                                      "clientInfo": {"name": "fairpool-spike-check", "version": VERSION}})
        self.protocol = (res or {}).get("protocolVersion", MCP_PROTOCOL)
        self.server_info = (res or {}).get("serverInfo", {})
        self.init_status = self.last_status
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res or {}

    def list_tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor = None
        for _ in range(20):
            res = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools += (res or {}).get("tools", [])
            cursor = (res or {}).get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, name: str, args: dict) -> dict:
        return self.rpc("tools/call", {"name": name, "arguments": args}) or {}

    def close(self) -> None:
        try:
            if self.session_id:
                self.client.delete(self.url, headers=self._headers())
        except Exception:
            pass
        self.client.close()


class McpSse:
    """Legacy MCP SSE transport: GET the stream, read the 'endpoint' event, POST requests there, read replies from the stream."""
    def __init__(self, url: str, headers: Optional[dict] = None) -> None:
        self.url, self.headers = url, dict(headers or {})
        self.client = httpx.Client(timeout=None, follow_redirects=False)
        self.endpoint = ""
        self.msgs: list[dict] = []
        self.lock = threading.Lock()
        self.err = ""
        self.ready = threading.Event()
        self._id = 0
        self.t = threading.Thread(target=self._reader, daemon=True)
        self.status = 0

    def _reader(self) -> None:
        try:
            with self.client.stream("GET", self.url, headers={"Accept": "text/event-stream", **self.headers}) as r:
                self.status = r.status_code
                if r.status_code >= 400:
                    self.err = f"HTTP {r.status_code}"
                    self.ready.set()
                    return
                ev, data = "", []
                for line in r.iter_lines():
                    if line == "":
                        if ev == "endpoint" and data:
                            self.endpoint = "\n".join(data).strip()
                            self.ready.set()
                        elif data:
                            try:
                                with self.lock:
                                    self.msgs.append(json.loads("\n".join(data)))
                            except ValueError:
                                pass
                        ev, data = "", []
                    elif line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
        except Exception as ex:
            self.err = f"{type(ex).__name__}: {ex}"
            self.ready.set()

    def open(self, timeout: float = 20.0) -> None:
        self.t.start()
        if not self.ready.wait(timeout) or not self.endpoint:
            raise McpError(self.err or "no endpoint event from the SSE stream")
        if self.endpoint.startswith("/"):
            p = urlparse(self.url)
            self.endpoint = f"{p.scheme}://{p.netloc}{self.endpoint}"

    def rpc(self, method: str, params: Optional[dict] = None, timeout: float = 60.0) -> Any:
        self._id += 1
        rid = self._id
        r = httpx.post(self.endpoint, headers={"Content-Type": "application/json", **self.headers},
                       content=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}).encode(), timeout=30)
        if r.status_code >= 400:
            raise McpError(f"HTTP {r.status_code}")
        t0 = now_s()
        while now_s() - t0 < timeout:
            with self.lock:
                for m in self.msgs:
                    if m.get("id") == rid:
                        if "error" in m:
                            raise McpError(str(m["error"].get("message", m["error"])))
                        return m.get("result")
            time.sleep(0.2)
        raise McpError(f"{method}: timeout")

    def initialize(self) -> dict:
        res = self.rpc("initialize", {"protocolVersion": MCP_PROTOCOL, "capabilities": {}, "clientInfo": {"name": "fairpool-spike-check", "version": VERSION}})
        httpx.post(self.endpoint, headers={"Content-Type": "application/json", **self.headers},
                   content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(), timeout=30)
        return res or {}

    def list_tools(self) -> list[dict]:
        return (self.rpc("tools/list") or {}).get("tools", [])

    def call_tool(self, name: str, args: dict) -> dict:
        return self.rpc("tools/call", {"name": name, "arguments": args}) or {}

    def close(self) -> None:
        self.client.close()


class McpStdio:
    def __init__(self, cmd: list[str], env_extra: Optional[dict] = None) -> None:
        e = dict(os.environ)
        e.update(env_extra or {})
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=e, text=True, bufsize=1)
        self.msgs: list[dict] = []
        self.lock = threading.Lock()
        self._id = 0
        self.stderr_tail: list[str] = []
        threading.Thread(target=self._out, daemon=True).start()
        threading.Thread(target=self._err, daemon=True).start()

    def _out(self) -> None:
        assert self.p.stdout
        for line in self.p.stdout:
            line = line.strip()
            if line.startswith("{"):
                try:
                    with self.lock:
                        self.msgs.append(json.loads(line))
                except ValueError:
                    pass

    def _err(self) -> None:
        assert self.p.stderr
        for line in self.p.stderr:
            self.stderr_tail = (self.stderr_tail + [line.rstrip()])[-8:]

    def _send(self, obj: dict) -> None:
        assert self.p.stdin
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def rpc(self, method: str, params: Optional[dict] = None, timeout: float = 90.0) -> Any:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        t0 = now_s()
        while now_s() - t0 < timeout:
            with self.lock:
                for m in self.msgs:
                    if m.get("id") == rid:
                        if "error" in m:
                            raise McpError(str(m["error"].get("message", m["error"])))
                        return m.get("result")
            if self.p.poll() is not None:
                raise McpError("server exited: " + " | ".join(self.stderr_tail[-3:]))
            time.sleep(0.2)
        raise McpError(f"{method}: timeout")

    def initialize(self) -> dict:
        res = self.rpc("initialize", {"protocolVersion": MCP_PROTOCOL, "capabilities": {}, "clientInfo": {"name": "fairpool-spike-check", "version": VERSION}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res or {}

    def list_tools(self) -> list[dict]:
        return (self.rpc("tools/list") or {}).get("tools", [])

    def call_tool(self, name: str, args: dict) -> dict:
        return self.rpc("tools/call", {"name": name, "arguments": args}) or {}

    def close(self) -> None:
        try:
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def mcp_reply_ok(res: dict) -> tuple[bool, str]:
    """A tool call succeeded only if isError is unset AND the reply's own JSON does not say ok=false or carry an error code
    (PayPal's hosted MCP returned ok=false with isError unset)."""
    if (res or {}).get("isError"):
        return False, "isError"
    txt = tool_text(res)
    try:
        j = json.loads(txt)
    except ValueError:
        return True, ""
    if isinstance(j, dict):
        if j.get("ok") is False:
            return False, f"ok=false {j.get('code') or j.get('error') or ''}".strip()
        if j.get("error") and not j.get("ok"):
            return False, f"error {str(j.get('error'))[:60]}"
    return True, ""


def tool_text(res: dict) -> str:
    return "\n".join(c.get("text", "") for c in (res or {}).get("content", []) if isinstance(c, dict))


# ----------------------------------------------------------------------------------------------
# S8 Elastic hybrid search
# ----------------------------------------------------------------------------------------------
S8_DOCS = [  # id, product_key, status, title, content (generic products only)
    ("d01", "monitor-27-4k", "OPEN", "27 inch 4K monitor", "27 inch 4K UHD monitor, IPS panel, USB-C, height adjustable stand, new"),
    ("d02", "monitor-24-fhd", "OPEN", "24 inch Full HD monitor", "24 inch Full HD 1080p office monitor, HDMI, new"),
    ("d03", "laptop-14-ultra", "OPEN", "14 inch ultralight laptop", "14 inch ultralight laptop, 16GB RAM, 512GB SSD, 15 hour battery life, new"),
    ("d04", "laptop-16-gaming", "OPEN", "16 inch gaming laptop", "16 inch gaming laptop, dedicated graphics, 32GB RAM, 1TB SSD, new"),
    ("d05", "headphones-anc", "OPEN", "Noise cancelling headphones", "Wireless over-ear noise cancelling headphones, 30 hour battery, Bluetooth"),
    ("d06", "earbuds-sport", "OPEN", "Sport earbuds", "True wireless sport earbuds, sweatproof, secure fit for running"),
    ("d07", "robot-vacuum", "OPEN", "Robot vacuum", "Robot vacuum cleaner with room mapping, self emptying dock, works on carpet and hard floors"),
    ("d08", "air-fryer-6l", "OPEN", "6 litre air fryer", "6 litre digital air fryer, oil free cooking, dishwasher safe basket"),
    ("d09", "espresso-machine", "OPEN", "Espresso machine", "Semi automatic espresso machine with steam wand milk frother, 15 bar pump"),
    ("d10", "standing-desk", "OPEN", "Electric standing desk", "Electric height adjustable standing desk, 140 cm, memory presets"),
    ("d11", "office-chair", "OPEN", "Ergonomic office chair", "Ergonomic mesh office chair with lumbar support and adjustable armrests"),
    ("d12", "mech-keyboard", "OPEN", "Mechanical keyboard", "Wireless mechanical keyboard, tactile switches, hot swappable"),
    ("d13", "webcam-4k", "OPEN", "4K webcam", "4K webcam with autofocus and built in microphone for video calls"),
    ("d14", "mesh-router", "OPEN", "WiFi 6 mesh router", "WiFi 6 mesh router system covering large homes, 3 pack"),
    ("d15", "tablet-10", "OPEN", "10 inch tablet", "10 inch tablet with stylus, 128GB storage, good for note taking"),
    ("d16", "smartwatch-fit", "OPEN", "Fitness smartwatch", "Fitness smartwatch with heart rate, GPS and sleep tracking"),
    ("d17", "power-bank-20k", "OPEN", "20000 mAh power bank", "20000 mAh portable power bank, USB-C fast charging, airline safe"),
    ("d18", "ssd-1tb", "OPEN", "1TB portable SSD", "1TB portable external solid state drive, USB 3.2, pocket size"),
    ("d19", "projector-fhd", "CLOSED", "Full HD projector", "Full HD portable home projector, 300 inch screen, built in speaker"),
    ("d20", "monitor-32-4k", "CLOSED", "32 inch 4K monitor", "32 inch 4K monitor, VA panel, curved, closed pool"),
]
S8_QUERIES = [
    ("a big 4k screen for my desk", "d01"), ("light laptop that lasts all day for travelling", "d03"),
    ("headphones that block out noise on flights", "d05"), ("something to clean floors by itself", "d07"),
    ("cook crispy food without oil", "d08"), ("coffee machine with steamed milk", "d09"),
    ("desk that goes up and down", "d10"), ("comfy chair for long work hours back pain", "d11"),
    ("wifi for a big house no dead spots", "d14"), ("charger brick to carry on plane for phone", "d17"),
]


def trigrams(text: str) -> set[str]:
    """pg_trgm's trigram set: lower-case words of letters/digits, each padded with two spaces before and one after."""
    out: set[str] = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        p = f"  {w} "
        out.update(p[i:i + 3] for i in range(len(p) - 2))
    return out


def trgm_similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    return (len(ta & tb) / len(ta | tb)) if (ta | tb) else 0.0


def run_s8(ctx: Ctx) -> None:
    S = "s8"
    url, key = env("ELASTICSEARCH_URL").rstrip("/"), env("ELASTICSEARCH_API_KEY")
    if not url or not key:
        REC.add(S, "needs ELASTICSEARCH_URL and ELASTICSEARCH_API_KEY", "BLOCKED")
        REC.fact("SEARCH_BACKEND", "postgres")
        return
    REDACT.add(key)
    H = {"Authorization": f"ApiKey {key}", "Content-Type": "application/json", "Accept": "application/json"}
    idx = f"{env('ELASTIC_INDEX_PREFIX', 'fairpool')}-spike-search-v1"
    r = ctx.http.request("GET", url + "/", headers=H, retries=1)
    REC.add(S, "connect to the Elasticsearch endpoint", "PASS" if r.ok else "FAIL", http=r.status, status=r.issue or r.error,
            note=f"flavor={(r.data or {}).get('version', {}).get('build_flavor')} version={(r.data or {}).get('version', {}).get('number')}" if r.ok and isinstance(r.data, dict) else "")
    if not r.ok:
        REC.fact("SEARCH_BACKEND", "postgres")
        return
    inf = ctx.http.request("GET", url + "/_inference", headers=H)
    eps = (inf.data or {}).get("endpoints", []) if inf.ok and isinstance(inf.data, dict) else []
    ids = [e.get("inference_id") for e in eps if e.get("task_type") in ("text_embedding", "sparse_embedding")]
    REC.add(S, "list inference endpoints", "PASS" if inf.ok else "FAIL", http=inf.status, status=inf.issue, note=f"usable embedding endpoints: {ids[:8]}")
    chosen = env("ELASTIC_INFERENCE_ID")
    if not chosen:
        for pref in (".jina-embeddings-v5-text-small", ".jina-embeddings-v5-text-nano", ".elser-2-elastic"):
            if pref in ids:
                chosen = pref
                break
        chosen = chosen or (ids[0] if ids else "")
    if not chosen:
        REC.add(S, "an embedding inference endpoint is available to name in the mapping", "FAIL", note="set ELASTIC_INFERENCE_ID or create an endpoint first")
        REC.fact("SEARCH_BACKEND", "postgres")
        return
    REC.add(S, "inference endpoint chosen (named explicitly in the mapping)", "INFO", status=chosen)
    REC.fact("ELASTIC_INFERENCE_ID", chosen)
    ctx.http.request("DELETE", f"{url}/{idx}", headers=H)
    mapping = {"mappings": {"properties": {
        "doc_kind": {"type": "keyword"}, "pool_id": {"type": "keyword"}, "lot_id": {"type": "keyword"}, "status": {"type": "keyword"},
        "product_key": {"type": "keyword"}, "condition": {"type": "keyword"}, "title": {"type": "text"},
        "content": {"type": "text", "copy_to": "content_embedding"},
        "content_embedding": {"type": "semantic_text", "inference_id": chosen}}}}
    cr = ctx.http.request("PUT", f"{url}/{idx}", headers=H, json_body=mapping)
    REC.add(S, "create the index (content copy_to a semantic_text field)", "PASS" if cr.ok else "FAIL", http=cr.status, status=cr.issue or cr.error)
    if not cr.ok:
        REC.fact("SEARCH_BACKEND", "postgres")
        return
    lines = []
    for did, pk, st, title, content in S8_DOCS:
        lines.append(json.dumps({"index": {"_index": idx, "_id": did}}))
        lines.append(json.dumps({"doc_kind": "pool", "pool_id": did, "lot_id": f"lot-{did}", "status": st, "product_key": pk, "condition": "new", "title": title, "content": f"{title}. {content}"}))
    t0 = now_s()
    br = ctx.http.request("POST", f"{url}/_bulk?refresh=wait_for", headers={**H, "Content-Type": "application/x-ndjson"}, content=("\n".join(lines) + "\n").encode())
    ingest_s = now_s() - t0
    errors = bool((br.data or {}).get("errors")) if br.ok and isinstance(br.data, dict) else True
    REC.add(S, f"index {len(S8_DOCS)} public documents (ingest latency {ingest_s:.1f}s)", "PASS" if (br.ok and not errors) else "FAIL", http=br.status, status=br.issue,
            note="" if not errors else "bulk reported item errors")
    REC.fact("elastic_ingest_s", round(ingest_s, 2))
    if errors:
        REC.fact("SEARCH_BACKEND", "postgres")
        return
    src = ["pool_id", "product_key", "title", "status"]
    flt = [{"term": {"status": "OPEN"}}]

    def hybrid(q: str, sem_shape: int) -> dict:
        sem = {"semantic": {"field": "content_embedding", "query": q}} if sem_shape == 0 else {"match": {"content_embedding": q}}
        return {"retriever": {"rrf": {"retrievers": [
            {"standard": {"query": {"bool": {"must": [{"match": {"content": q}}], "filter": flt}}}},
            {"standard": {"query": {"bool": {"must": [sem], "filter": flt}}}}],
            "rank_window_size": 20, "rank_constant": 60}}, "size": 5, "_source": src}

    def semantic_only(q: str) -> dict:
        return {"query": {"bool": {"must": [{"semantic": {"field": "content_embedding", "query": q}}], "filter": flt}}, "size": 5, "_source": src}

    shape = -1
    for s_try in (0, 1):
        t = ctx.http.request("POST", f"{url}/{idx}/_search", headers=H, json_body=hybrid(S8_QUERIES[0][0], s_try))
        if t.ok:
            shape = s_try
            break
        REC.add(S, f"hybrid rrf query, semantic leg as {'semantic query' if s_try == 0 else 'match on the semantic_text field'}", "FAIL", http=t.status, status=t.issue, note=(t.data or {}).get("error", {}).get("reason", "")[:160] if isinstance(t.data, dict) and isinstance(t.data.get("error"), dict) else "")
    if shape < 0:
        REC.fact("SEARCH_BACKEND", "postgres")
        return
    REC.add(S, "hybrid rrf query accepted (match on content + " + ("semantic query" if shape == 0 else "match on semantic_text") + " on content_embedding, status filter)", "PASS",
            note="request shape recorded for the contract")
    hits_h = hits_s = hits_t = 0
    lat_h: list[float] = []
    for q, expect in S8_QUERIES:
        t0 = now_s()
        rh = ctx.http.request("POST", f"{url}/{idx}/_search", headers=H, json_body=hybrid(q, shape))
        lat_h.append(now_s() - t0)
        ids_h = [h["_id"] for h in (rh.data or {}).get("hits", {}).get("hits", [])] if rh.ok and isinstance(rh.data, dict) else []
        rs = ctx.http.request("POST", f"{url}/{idx}/_search", headers=H, json_body=semantic_only(q))
        ids_s = [h["_id"] for h in (rs.data or {}).get("hits", {}).get("hits", [])] if rs.ok and isinstance(rs.data, dict) else []
        open_docs = [d for d in S8_DOCS if d[2] == "OPEN"]
        ids_t = [d[0] for d in sorted(open_docs, key=lambda d: (-trgm_similarity(q, d[4]), d[0]))[:5]]
        hits_h += expect in ids_h
        hits_s += expect in ids_s
        hits_t += expect in ids_t
        closed_leak = any(i in ("d19", "d20") for i in ids_h + ids_s)
        if closed_leak:
            REC.add(S, f"status filter holds for query: {q!r}", "FAIL", note="a CLOSED document was returned")
    n = len(S8_QUERIES)
    REC.add(S, f"hybrid: expected pool in top 5 for {hits_h} of {n} messy queries (median latency {sorted(lat_h)[n // 2] * 1000:.0f} ms)", "INFO", status=f"{hits_h}/{n}")
    REC.add(S, f"semantic-only: expected pool in top 5 for {hits_s} of {n}", "INFO", status=f"{hits_s}/{n}")
    REC.add(S, f"pg_trgm fallback (same algorithm emulated in Python; no database): {hits_t} of {n}", "INFO", status=f"{hits_t}/{n}",
            note="similarity() over the OPEN documents' content; the real fallback must be re-measured against Postgres in T02B04")
    good = hits_h >= hits_t and hits_h > 0
    REC.fact("SEARCH_BACKEND", "elastic" if good else "postgres")
    REC.fact("elastic_recall_hybrid", hits_h)
    REC.fact("trgm_recall", hits_t)
    REC.add(S, "rule applied (hybrid recall at least the fallback's)", "INFO", status=f"SEARCH_BACKEND={'elastic' if good else 'postgres'}")
    REC.manual_open.append("S8: record the Elastic trial start and end dates (the script cannot read them).")
    REC.implication("S8", "Elastic hybrid retrieval is at least as good as the fallback." if good else "Postgres pg_trgm stays; the README says so.")
    ctx.http.request("DELETE", f"{url}/{idx}", headers=H)


# ----------------------------------------------------------------------------------------------
# S9 Zapier MCP managed mode
# ----------------------------------------------------------------------------------------------
def run_s9(ctx: Ctx) -> None:
    S = "s9"
    tok = env("ZAPIER_MCP_TOKEN")
    if not tok:
        REC.add(S, "needs ZAPIER_MCP_TOKEN (the connection token from the MCP server's Connect page)", "BLOCKED")
        REC.fact("ZAPIER_BRIDGE", "off")
        return
    REDACT.add(tok)
    url = env("ZAPIER_MCP_URL") or "https://mcp.zapier.com/api/v1/connect"
    c = McpHttp(url, {"Authorization": f"Bearer {tok}"})
    try:
        info = c.initialize()
        REC.add(S, "connect and initialize over Streamable HTTP with the bearer token", "PASS", http=c.init_status, note=f"server={c.server_info.get('name')} protocol={info.get('protocolVersion')}")
        tools = c.list_tools()
    except Exception as ex:
        REC.add(S, "connect and list tools", "FAIL", status=str(ex)[:200])
        REC.fact("ZAPIER_BRIDGE", "off")
        return
    names = sorted(t.get("name", "") for t in tools)
    metas = sorted(set(names) & ZAPIER_META_TOOLS)
    REC.add(S, f"managed mode: exactly four tools are exposed (found {len(names)})", "PASS" if len(names) == 4 else "FAIL", note=f"tools={names}")
    REC.add(S, "managed mode: no Zapier meta-tools (agentic mode would show them)", "PASS" if not metas else "FAIL", note=f"meta tools present={metas}" if metas else "")
    leak = []
    for t in tools:
        props = ((t.get("inputSchema") or {}).get("properties") or {})
        for k in props:
            if k.lower() in ("url", "headers", "authorization", "api_key", "token", "secret"):
                leak.append(f"{t.get('name')}.{k}")
    REC.add(S, "no tool exposes a URL, header or credential field to the AI (locked fields)", "PASS" if not leak else "FAIL", note=f"exposed={leak}" if leak else "")
    # optional calls
    agent_api = env("FAIRPOOL_AGENT_API_URL")
    roles = {"list_pools": env("ZAPIER_TOOL_LIST_POOLS"), "join": env("ZAPIER_TOOL_JOIN"), "list_entries": env("ZAPIER_TOOL_LIST_ENTRIES"), "withdraw": env("ZAPIER_TOOL_WITHDRAW")}
    if not agent_api or not all(roles.values()):
        REC.add(S, "list pools, join with a cap, list entries, withdraw through the tools", "BLOCKED",
                note="needs the deployed Agent API (task T07B02) and ZAPIER_TOOL_LIST_POOLS/JOIN/LIST_ENTRIES/WITHDRAW with ZAPIER_*_ARGS_JSON; run these four by hand in an AI client until then")
    else:
        for role, tname in roles.items():
            args = {}
            raw = env(f"ZAPIER_{role.upper()}_ARGS_JSON")
            try:
                args = json.loads(raw) if raw else {}
            except ValueError:
                REC.add(S, f"{role}: ZAPIER_{role.upper()}_ARGS_JSON is not valid JSON", "FAIL")
                continue
            try:
                res = c.call_tool(tname, args)
                REC.add(S, f"call tool for {role}", "PASS" if not res.get("isError") else "FAIL", note=f"reply chars={len(tool_text(res))}")
            except Exception as ex:
                REC.add(S, f"call tool for {role}", "FAIL", status=str(ex)[:160])
    c.close()
    ok_connect = len(names) == 4 and not metas and not leak
    REC.fact("ZAPIER_BRIDGE", "managed" if ok_connect else "off")
    for item in ("S9 manual: from the Zapier dashboard record tasks consumed per tool call (expected 2) and the trial's expiry date",
                 "S9 manual: confirm the locked URL cannot be changed by an AI prompt (ask the AI to call a different URL; check the Zapier history)",
                 "S9 manual: confirm the idempotency key from the AI's call is accepted by your intake (once the Agent API exists)"):
        REC.manual_open.append(item)
    REC.add(S, "tasks per call, trial expiry, locked-URL override, idempotency", "MANUAL", note="listed under 'Manual confirmations' in the report")
    REC.implication("S9", "Zapier managed mode exposes the four locked tools: ZAPIER_BRIDGE=managed (pending the manual checks and the four live calls)." if ok_connect else "ZAPIER_BRIDGE=off: FairPool's own MCP server (INT-3) stays the agent path and the README says the Zapier bridge was not demonstrated.")


# ----------------------------------------------------------------------------------------------
# S10 PayPal MCP (hosted sandbox server and local @paypal/mcp)
# ----------------------------------------------------------------------------------------------
def classify_tools(names: list[str]) -> tuple[list[str], list[str]]:
    read = sorted(n for n in names if n in PAYPAL_MCP_READ_ALLOW)
    other = sorted(n for n in names if n not in PAYPAL_MCP_READ_ALLOW)
    return read, other


def discover_paypal_mcp_permissions(npx: str, token: str) -> list[str]:
    """Run @paypal/mcp with a deliberately invalid tool name; it answers with 'Accepted tools are: a, b, c'."""
    try:
        r = subprocess.run([npx, "-y", "@paypal/mcp", "--tools=__fairpool_probe__"], capture_output=True, text=True, timeout=180,
                           env={**os.environ, "PAYPAL_ACCESS_TOKEN": token, "PAYPAL_ENVIRONMENT": "SANDBOX"}, stdin=subprocess.DEVNULL)
    except Exception:
        return []
    out = re.sub(r"\x1b\[[0-9;]*m", "", (r.stdout or "") + "\n" + (r.stderr or ""))
    m = re.search(r"Accepted tools are:\s*([^\n]+)", out)
    return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []


def run_s10(ctx: Ctx) -> None:
    S = "s10"
    pp = ctx.pp
    assert pp
    token = pp.token()
    base = (env("PAYPAL_MCP_BASE") or "https://mcp.sandbox.paypal.com").rstrip("/")
    connected: Any = None
    # hosted: Streamable HTTP candidates, then legacy SSE
    for path in ("/http", "/mcp"):
        c = McpHttp(base + path, {"Authorization": f"Bearer {token}"}, timeout=30)
        try:
            c.initialize()
            tools = c.list_tools()
            names = sorted(t["name"] for t in tools)
            REC.add(S, f"hosted sandbox server over Streamable HTTP at {path}", "PASS", http=c.init_status, note=f"{len(names)} tools: {names}")
            connected = ("hosted-http" + path, c, names)
            break
        except Exception as ex:
            REC.add(S, f"hosted sandbox server over Streamable HTTP at {path}", "INFO", status=str(ex)[:120])
            c.close()
    if connected is None:
        s = McpSse(base + "/sse", {"Authorization": f"Bearer {token}"})
        try:
            s.open()
            s.initialize()
            names = sorted(t["name"] for t in s.list_tools())
            REC.add(S, "hosted sandbox server over legacy SSE at /sse", "PASS", http=s.status, note=f"{len(names)} tools: {names}")
            connected = ("hosted-sse", s, names)
        except Exception as ex:
            REC.add(S, "hosted sandbox server over legacy SSE at /sse", "FAIL", status=str(ex)[:160],
                    note="bearer access token was tried; the docs may expect different credentials (check S10 note in the report)")
            s.close()
    # step 3: get_order against the S2 capture
    cap = ctx.captured
    if connected and cap:
        label, cli, names = connected
        tname = "get_order" if "get_order" in names else ""
        if tname:
            try:
                tool = next(t for t in cli.list_tools() if t["name"] == tname)
            except Exception:
                tool = {}
            props = list(((tool.get("inputSchema") or {}).get("properties") or {}).keys())
            arg = "payment_id" if "payment_id" in props else (props[0] if props else "payment_id")
            t0 = now_s()
            try:
                res = cli.call_tool(tname, {arg: cap["order_id"]})
                txt = tool_text(res)
                reply_ok, why = mcp_reply_ok(res)
                seen_cap = cap["capture_id"] in txt
                seen_amt = "1.00" in txt
                REC.add(S, f"get_order via the HOSTED MCP ({arg}=order ID): reply ok and returns the captured payment", "PASS" if (reply_ok and seen_cap and seen_amt) else "FAIL",
                        note=f"argument name={arg}; reply_ok={reply_ok} {why}; capture id found={seen_cap}; amount found={seen_amt}; latency={now_s() - t0:.1f}s (recorded Oct 28: hosted get_order returned ok=false with isError unset)")
            except Exception as ex:
                REC.add(S, "get_order via MCP", "FAIL", status=str(ex)[:160])
        else:
            REC.add(S, "get_order tool present on the hosted server", "FAIL", note=f"tools seen={names}")
    elif connected and not cap:
        REC.add(S, "get_order against a captured order", "BLOCKED", note="needs the S2 capture (run S2 in the same run, with buyer approvals)")
    if connected:
        label, cli, names = connected
        read, other = classify_tools(names)
        REC.add(S, "hosted server tool set vs the FairPool read-only allowlist", "INFO", note=f"allowed read tools present={read}; tools outside the allowlist={other} (hosted server has no documented subset flag: restriction must be enforced by the FairPool wrapper)")
    # step 4: list-transactions once (record latency and permission state; never depended on)
    if connected:
        label, cli, names = connected
        lt = next((n for n in names if "list_transaction" in n), "")
        if lt:
            t0 = now_s()
            try:
                tool = next((t for t in cli.list_tools() if t["name"] == lt), {})
                props = ((tool.get("inputSchema") or {}).get("properties") or {})
                end = datetime.now(timezone.utc)
                args = {}
                for k in props:
                    if k.lower() in ("start_date", "startdate"):
                        args[k] = (end.replace(microsecond=0) - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S-0000")
                    if k.lower() in ("end_date", "enddate"):
                        args[k] = end.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S-0000")
                res = cli.call_tool(lt, args)
                REC.add(S, f"{lt} once (not depended on)", "INFO", status="error" if res.get("isError") else "ok", note=f"latency={now_s() - t0:.1f}s; reply: {tool_text(res)[:120]!r}")
            except Exception as ex:
                REC.add(S, f"{lt} once (not depended on)", "INFO", status=str(ex)[:140], note=f"latency={now_s() - t0:.1f}s")
        else:
            REC.add(S, "list-transactions tool", "INFO", note="not present on the connected server")
    if connected:
        connected[1].close()
    # step 2: local @paypal/mcp allowlist probing
    npx = shutil.which("npx")
    if not npx:
        REC.add(S, "local @paypal/mcp allowlist probe", "BLOCKED", note="needs node 18+ and npx on PATH")
        REC.fact("PAYPAL_MCP_VERIFICATION", "fairpool_tool")
        return
    # the server prints its accepted --tools values when given an invalid one: read them instead of guessing
    accepted = discover_paypal_mcp_permissions(npx, token)
    wanted = ["orders.get", "disputes.list", "disputes.get", "shipment.get", "payments.getRefunds"]
    REC.add(S, "permission names the local server accepts for --tools", "INFO" if accepted else "FAIL", note=f"{len(accepted)} names, e.g. {accepted[:6]}" if accepted else "could not read the accepted list from the server's error output")
    subset = [w for w in wanted if (not accepted) or w in accepted]
    candidates = [",".join(subset)] if subset else []
    enforceable = ""
    for cand in candidates:
        cli2 = None
        try:
            cli2 = McpStdio([npx, "-y", "@paypal/mcp", f"--tools={cand}"],
                            {"PAYPAL_ACCESS_TOKEN": token, "PAYPAL_ENVIRONMENT": "SANDBOX"})
            cli2.initialize()
            names2 = sorted(t["name"] for t in cli2.list_tools())
            read2, other2 = classify_tools(names2)
            clean = bool(names2) and not other2
            si = (cli2.server_info if hasattr(cli2, "server_info") else {}) or {}
            REC.add(S, f"local server with --tools={cand}", "PASS" if clean else "INFO", note=f"tools={names2}")
            if clean and not enforceable:
                enforceable = cand
                if cap and env("S10_LOCAL_CALL") != "0" and "get_order" in names2:
                    tool2 = next((x for x in cli2.list_tools() if x["name"] == "get_order"), {})
                    props2 = list(((tool2.get("inputSchema") or {}).get("properties") or {}).keys())
                    arg2 = "payment_id" if "payment_id" in props2 else (props2[0] if props2 else "payment_id")
                    res2 = cli2.call_tool("get_order", {arg2: cap["order_id"]})
                    ok2, why2 = mcp_reply_ok(res2)
                    txt2 = tool_text(res2)
                    match = cap["order_id"] in txt2
                    REC.add(S, "get_order via the LOCAL restricted MCP: reply ok and the order ID matches", "PASS" if (ok2 and match) else "FAIL",
                            note=f"argument={arg2}; reply_ok={ok2} {why2}; order id matches={match}")
                    if not (ok2 and match):
                        enforceable = ""
        except Exception as ex:
            REC.add(S, f"local server with --tools={cand}", "INFO", status=str(ex)[:140])
        finally:
            if cli2:
                cli2.close()
        if enforceable:
            break
    if enforceable:
        REC.add(S, "an enforceable read-only allowlist exists on the local server", "PASS", note=f"working subset: {enforceable}")
    else:
        REC.add(S, "an enforceable read-only allowlist exists on the local server", "FAIL", note="no probed subset restricted the tools to the five read tools; FairPool's own verification tool is the primary path")
    ok = bool(enforceable)
    REC.fact("PAYPAL_MCP_VERIFICATION", "paypal_read_subset" if ok else "fairpool_tool")
    REC.add(S, "rule applied", "INFO", status=f"PAYPAL_MCP_VERIFICATION={'paypal_read_subset' if ok else 'fairpool_tool'}")
    REC.implication("S10", "PayPal MCP can serve as a read-only verification copilot." if ok else "FairPool's own verification tool is the primary path; PayPal MCP is not demonstrated.")


# ----------------------------------------------------------------------------------------------
# S11 APIMatic (OpenAPI validation, SDK generation, static checks)
# ----------------------------------------------------------------------------------------------
def load_openapi(ctx: Ctx) -> tuple[Optional[dict], str]:
    path = env("OPENAPI_JSON_PATH")
    if path:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8")), path
        except Exception as ex:
            return None, f"cannot read {path}: {ex}"
    base = env("FAIRPOOL_API_URL").rstrip("/")
    if base:
        r = ctx.http.request("GET", f"{base}/merchant-api/v1/openapi.json", retries=1)
        if r.ok and isinstance(r.data, dict):
            return r.data, f"{base}/merchant-api/v1/openapi.json"
        return None, f"GET openapi.json failed: HTTP {r.status} {r.error}"
    return None, "set OPENAPI_JSON_PATH or FAIRPOOL_API_URL"


def camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def run_s11(ctx: Ctx) -> None:
    S = "s11"
    doc, where = load_openapi(ctx)
    if doc is None:
        REC.add(S, "OpenAPI document for the merchant API", "BLOCKED", note=f"{where} (the document comes from task T01B01)")
        REC.fact("SDK", "handwritten_client")
        return
    ver = str(doc.get("openapi", ""))
    REC.add(S, "OpenAPI version is 3.1", "PASS" if ver.startswith("3.1") else "FAIL", note=f"openapi={ver}")
    ops: dict[str, tuple[str, str]] = {}
    for pth, item in (doc.get("paths") or {}).items():
        for m, op in (item or {}).items():
            if m.lower() in ("get", "put", "post", "delete", "patch") and isinstance(op, dict):
                ops[op.get("operationId", f"<missing:{m} {pth}>")] = (m.lower(), pth)
    want = MERCHANT_OPERATIONS
    missing = sorted(set(want) - set(ops))
    extra = sorted(set(ops) - set(want))
    wrong = sorted(k for k in want if k in ops and ops[k] != want[k])
    REC.add(S, "exactly the ten operations of api.md section 4.3, with the fixed operationIds, methods and paths", "PASS" if not (missing or extra or wrong) and len(ops) == 10 else "FAIL",
            note=f"count={len(ops)} missing={missing} extra={extra} wrong_method_or_path={wrong}")
    REC.fact("merchant_endpoint_count", len(ops))
    cli = shutil.which("apimatic")
    out_dir = Path(ctx.args.out_dir) / "apimatic"
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_file = out_dir / "openapi.json"
    spec_file.write_text(json.dumps(doc), encoding="utf-8")
    if not cli:
        REC.add(S, "APIMatic CLI generation (Python and TypeScript SDKs)", "BLOCKED", note="install: npm install -g @apimatic/cli, then apimatic auth login")
        REC.fact("SDK", "handwritten_client")
        return
    v = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=60)
    REC.add(S, "APIMatic CLI present", "PASS" if v.returncode == 0 else "FAIL", note=REDACT((v.stdout or v.stderr).strip()[:100]))
    h_new = subprocess.run([cli, "sdk", "generate", "--help"], capture_output=True, text=True, timeout=60)
    new_style = h_new.returncode == 0 and "language" in (h_new.stdout + h_new.stderr).lower()
    results: dict[str, Path] = {}
    for lang, old_platform in (("python", "PYTHON_GENERIC_LIB"), ("typescript", "TS_GENERIC_LIB")):
        dest = out_dir / f"sdk-{lang}"
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        if new_style:
            proj = out_dir / f"project-{lang}"
            (proj / "src" / "spec").mkdir(parents=True, exist_ok=True)
            shutil.copy(spec_file, proj / "src" / "spec" / "openapi.json")
            cmd = [cli, "sdk", "generate", f"--language={lang}", f"--input={proj}", f"--destination={dest}"]
        else:
            cmd = [cli, "sdk:generate", f"--platform={old_platform}", f"--file={spec_file}", f"--destination={dest}"]
        try:
            g = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            ok = g.returncode == 0 and any(dest.rglob("*"))
            REC.add(S, f"generate the {lang} SDK ({'new' if new_style else 'legacy'} CLI syntax)", "PASS" if ok else "FAIL",
                    note=REDACT(((g.stdout or "") + (g.stderr or "")).strip().replace("\n", " | ")[:260]) if not ok else f"{sum(1 for _ in dest.rglob('*') if _.is_file())} files")
            if ok:
                results[lang] = dest
        except Exception as ex:
            REC.add(S, f"generate the {lang} SDK", "FAIL", status=str(ex)[:160])
    # static checks on the generated code
    for lang, dest in results.items():
        exts = (".py",) if lang == "python" else (".ts",)
        blob = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in dest.rglob("*") if f.is_file() and f.suffix in exts)
        absent = [k for k in want if k not in blob and camel(k) not in blob]
        REC.add(S, f"{lang} SDK exposes all ten operations (by operation name)", "PASS" if not absent else "FAIL", note=f"absent={absent}" if absent else "")
        if lang == "python":
            bad = []
            for f in dest.rglob("*.py"):
                try:
                    compile(f.read_text(encoding="utf-8"), str(f), "exec")
                except SyntaxError:
                    bad.append(f.name)
            REC.add(S, "every generated Python file compiles", "PASS" if not bad else "FAIL", note=f"bad={bad[:5]}" if bad else "")
    REC.add(S, "smoke script with the Python SDK against a local API (list lots, submit a bid, read progress)", "BLOCKED", note="needs the running API (T01B01 onward); not automated here")
    for item in ("S11 manual: read APIMatic's terms on ownership and licensing of generated code; confirm the SDKs may be committed to a public MIT repository",
                 "S11 manual: record the plan or trial used and its end date",
                 "S11 manual: install the ContextMatic PayPal plugin in a coding agent and ask one PayPal Orders question"):
        REC.manual_open.append(item)
    ok_all = set(results) == {"python", "typescript"}
    REC.fact("SDK", "generated_pending_smoke" if ok_all else "handwritten_client")
    REC.implication("S11", "SDKs generate and expose the ten operations; the smoke test and licensing confirmation remain." if ok_all else "Generation failed: ship the OpenAPI document and a hand-written minimal client, labelled as such.")


# ----------------------------------------------------------------------------------------------
# S3 second-seller re-probe (optional)
# ----------------------------------------------------------------------------------------------
def run_s3(ctx: Ctx) -> None:
    S = "s3"
    pp = ctx.pp
    assert pp
    r = pp.partner_referral(f"fairpool-spike-{ctx.run_id}")
    REC.add(S, "Partner Referrals create (re-probe; recorded result on Oct 19 was 403)", "INFO", http=r.status, status=r.issue or ("created" if r.ok else r.error), debug_id=r.debug_id,
            note="a 201 here would reopen Router A: then run S3 steps 2 to 6 by hand (onboard a second seller, authorize with PayPal-Auth-Assertion)" if r.ok else "second-seller onboarding remains unavailable")
    REC.fact("S3_partner_referrals_http", r.status)
    REC.implication("S3", "Router A is still unavailable: single_seller stays." if not r.ok else "Partner Referrals now succeeds: S3 deserves a full manual re-run.")


# ----------------------------------------------------------------------------------------------
# Environment check, run orchestration, report
# ----------------------------------------------------------------------------------------------
def env_missing(key: str) -> list[str]:
    miss = []
    for req in SPIKES[key]["env"]:
        if " or " in req:
            if not any(env(x.strip()) for x in req.split(" or ")):
                miss.append(req)
        elif not env(req):
            miss.append(req)
    return miss


def tool_status() -> list[tuple[str, bool, str]]:
    try:
        import pyblst  # noqa: F401
        pyb = True
    except ImportError:
        pyb = False
    return [("python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0]),
            ("httpx", True, httpx.__version__), ("pyblst (S6 signature check)", pyb, "pip install pyblst"),
            ("node / npx (S10 local probe)", bool(shutil.which("npx")), "install Node.js 18+"),
            ("apimatic CLI (S11)", bool(shutil.which("apimatic")), "npm install -g @apimatic/cli")]


def cmd_list() -> int:
    print(f"FairPool spike check v{VERSION}\n")
    for k in RUN_ORDER:
        s = SPIKES[k]
        print(f"{k:5} {s['title']}\n      human: {s['human']}\n      env  : {', '.join(s['env']) or '-'}\n      tools: {', '.join(s['tools']) or '-'}\n")
    return 0


def cmd_check_env(selected: list[str]) -> int:
    print(f"FairPool spike check v{VERSION}: environment check (no network calls)\n")
    for name, ok, hint in tool_status():
        print(f"  [{'ok' if ok else 'MISSING':7}] {name}  {'' if ok else '-> ' + hint}")
    print()
    blocked = 0
    for k in selected:
        miss = env_missing(k)
        print(f"  {k:5} {'READY' if not miss else 'NEEDS ' + ', '.join(miss)}")
        blocked += bool(miss)
    print("\nOptional: WEBHOOK_LISTEN_PORT, S13_LISTEN_PORT, S6_BUYER_COUNT, S6_BEACON_DELAY_S, DRAND_BASE_URL, ELASTIC_INFERENCE_ID, ZAPIER_MCP_URL,")
    print("          FAIRPOOL_AGENT_API_URL, ZAPIER_TOOL_LIST_POOLS/JOIN/LIST_ENTRIES/WITHDRAW and ZAPIER_<ROLE>_ARGS_JSON")
    return 0 if not blocked else 1


SETTING_SOURCE = {
    "DEDUPE_MODE": "S1", "REQUIRE_PAYPAL_LINK": "S1", "PAYPAL_PAYLOAD_LEVEL": "S4", "WEBHOOKS_ENABLED": "S5", "BEACON_MODE": "S6",
    "sandbox_us_buyers_distinct": "S6", "S7_payee_email_eligible": "S7", "SEARCH_BACKEND": "S8", "ELASTIC_INFERENCE_ID": "S8",
    "ZAPIER_BRIDGE": "S9", "PAYPAL_MCP_VERIFICATION": "S10", "SDK": "S11", "merchant_endpoint_count": "S11",
    "SHIPMENT_TRACKING_ENABLED": "S12", "PAYPAL_APPROVAL_UI": "S13", "PAYPAL_SDK_AUTH": "S13", "O2_void_replay_issue": "S2",
    "S3_partner_referrals_http": "S3", "drand_chain_hash": "S6", "drand_period_s": "S6", "login_scope": "S1",
    "WEBHOOK_TYPES_VERIFIED": "S5", "WEBHOOK_TYPES_NOT_DELIVERED": "S5", "WEBHOOK_TYPES_FAILED_VERIFICATION": "S5", "WEBHOOK_TYPES_EXPECTED": "S5",
}
CHECKLIST_MAP = [
    ("0.1", "Rotate the Sandbox secret", "manual: do this after the run (see the reminders)"),
    ("1.1, 1.2", "Sandbox host guard, OAuth scopes", "CORE"), ("2.1 to 2.3", "approve, authorize, void", "S2"),
    ("2.4 to 2.6", "approve, capture, refund", "S2 (AUTHORIZE flow re-run; a CAPTURE-intent order is not re-tested)"),
    ("2.7", "cancel is not paid", "S13 (cancel test)"), ("2.8, 3.5, 6.3", "pool rules against PayPal", "needs the FairPool application; not covered by this script"),
    ("3.1 to 3.4, 3.8", "second seller gate", "S3 re-probe plus S7 (a second payee is usable only if authorize, void, capture and refund all work; recorded Oct 28: it is not); full onboarding stays blocked while Partner Referrals returns 403"),
    ("4.1, 4.2", "Login with PayPal account ID", "S1"), ("4.3", "payer_id only after approval", "S1, S2, S4 (approval checks)"),
    ("5.1, 5.2", "webhook listener, signature, dedupe", "S5"), ("6.1, 6.2", "negative tests, idempotent retries", "CORE, S2, S4"),
]


def write_report(ctx: Ctx, out_dir: Path, selected: list[str]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for r in REC.rows:
        counts[r.result] = counts.get(r.result, 0) + 1
    lines = [f"# FairPool spike check report", "",
             f"- Run ID: `{ctx.run_id}`; date (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}; script v{VERSION}; Python {sys.version.split()[0]}",
             f"- Spikes selected: {', '.join(selected)}",
             f"- PayPal hosts used: {urlparse(ctx.pp.api).hostname if ctx.pp else '-'} and {urlparse(ctx.pp.www).hostname if ctx.pp else '-'} (Sandbox only; every payment USD 1.00)",
             "- Redaction: no secret, token, password, approval URL, buyer name or email, or account ID value is written here",
             f"- Totals: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), "",
             "## Derived settings (apply the rules in `docs/spikes.md`; the owner confirms before changing `.env.example`)", "",
             "| Setting or measurement | Value | From |", "|---|---|---|"]
    for k, v in REC.facts.items():
        lines.append(f"| `{k}` | `{REDACT(v)}` | {SETTING_SOURCE.get(k, '-')} |")
    lines += ["", "## Results by spike", ""]
    order = ["CORE", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13", "CLEANUP"]
    for sp in order:
        rows = [r for r in REC.rows if r.spike == sp]
        if not rows:
            continue
        title = SPIKES.get(sp.lower(), {}).get("title", "Cleanup")
        lines += [f"### {title}", "", "| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |", "|---|---|---|---|---|---|"]
        for r in rows:
            esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {esc(r.step)} | {r.http} | {esc(r.status)} | {esc(r.debug_id)} | {r.result} | {esc(r.note)} |")
        if sp in REC.implications:
            lines += ["", f"**Implication:** {REC.implications[sp]}"]
        lines.append("")
    lines += ["## Checklist mapping", "", "| Checklist item | What | Covered by |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in CHECKLIST_MAP]
    lines += ["", "## Manual confirmations still needed", ""]
    lines += [f"- {m}" for m in REC.manual_open] or ["- none recorded"]
    lines += ["", "## After this run", "",
              "- Rotate the Sandbox app secret now (checklist 0.1), and change any buyer password that was ever shown on screen or pasted anywhere.",
              "- Delete the `.env.spike` file or keep it out of git; never commit it.",
              "- Copy the derived settings and each spike's table into `docs/spike-results.md` and mark the spikes RECORDED in `docs/progress.md`.", ""]
    md = out_dir / "spike_report.md"
    md.write_text(REDACT("\n".join(lines)), encoding="utf-8")
    js = out_dir / "spike_report.json"
    js.write_text(REDACT(json.dumps({"run_id": ctx.run_id, "version": VERSION, "facts": REC.facts, "implications": REC.implications,
                                      "rows": [dataclasses.asdict(r) for r in REC.rows], "manual": REC.manual_open}, indent=2, default=str)), encoding="utf-8")
    return md


def confirm_stage(ctx: Ctx, key: str) -> bool:
    if not ctx.interactive or ctx.args.no_confirm:
        return True
    s = SPIKES[key]
    log(f"\n=== Next: {s['title']}")
    log(f"    You will need to: {s['human']}")
    a = ask(ctx, "    Press Enter to run, or type 's' to skip: ")
    return not a.lower().startswith("s")


def parse_keys(s: str) -> list[str]:
    keys = [x.strip().lower() for x in s.split(",") if x.strip()]
    bad = [k for k in keys if k not in SPIKES]
    if bad:
        sys.exit(f"unknown spike key(s): {bad}; valid: {sorted(SPIKES)}")
    return keys


def cmd_run(args: argparse.Namespace) -> int:
    selected = [k for k in RUN_ORDER if k in (parse_keys(args.only) if args.only else [x for x in RUN_ORDER if x != "s3" or args.with_s3])]
    if args.skip:
        selected = [k for k in selected if k not in parse_keys(args.skip)]
    if "core" not in selected and any(k in selected for k in ("s1", "s2", "s4", "s5", "s6", "s7", "s10", "s12", "s13")):
        selected = ["core"] + selected
    ctx = Ctx(args)
    for name in ("PAYPAL_CLIENT_SECRET", "ELASTICSEARCH_API_KEY", "ZAPIER_MCP_TOKEN", "APIMATIC_AUTH_KEY"):
        REDACT.add(env(name))
    log(f"FairPool spike check v{VERSION}, run {ctx.run_id}. Sandbox only; every payment is USD 1.00.")
    paypal_keys = {"core", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s10", "s12", "s13"}
    if paypal_keys & set(selected):
        cid, sec = env("PAYPAL_CLIENT_ID"), env("PAYPAL_CLIENT_SECRET")
        api = env("PAYPAL_API_BASE") or f"https://{SANDBOX_API_HOST}"
        www = env("PAYPAL_CHECKOUT_BASE") or f"https://{SANDBOX_WWW_HOST}"
        if not (cid and sec):
            log("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET missing: PayPal spikes will be recorded as BLOCKED")
        else:
            try:
                ctx.pp = PayPal(ctx.http, cid, sec, api, www)
                ctx.pp.token()
            except ForbiddenHost as ex:
                log(f"REFUSING TO RUN: {ex}")
                return 2
            except Exception as ex:
                REC.add("core", "OAuth with the Sandbox credentials", "FAIL", note=str(ex)[:200])
                ctx.pp = None
    code = 0
    try:
        if ctx.pp and "s5" in selected and not env_missing("s5"):
            webhook_setup(ctx)
        for key in selected:
            miss = env_missing(key)
            if miss:
                REC.add(key, f"needs {', '.join(miss)}", "BLOCKED")
                continue
            if key in paypal_keys and not ctx.pp:
                REC.add(key, "needs working PayPal Sandbox credentials", "BLOCKED")
                continue
            if key == "s5":
                continue    # evaluated after the lifecycle flows
            if key != "core" and not confirm_stage(ctx, key):
                REC.add(key, "skipped by you", "SKIP")
                continue
            log(f"\n=== {SPIKES[key]['title']}")
            fn = {"core": run_core, "s1": run_s1, "s2": run_s2, "s3": run_s3, "s4": run_s4, "s6": lambda c: (run_s6_beacon(c), run_s6_buyers(c)),
                  "s7": run_s7, "s8": run_s8, "s9": run_s9, "s10": run_s10, "s11": run_s11, "s12": run_s12, "s13": run_s13}[key]
            try:
                fn(ctx)
            except KeyboardInterrupt:
                raise
            except Exception as ex:
                REC.add(key, "script error (this is a bug in the script or an unexpected reply)", "FAIL", note=f"{type(ex).__name__}: {str(ex)[:200]}")
            if key == "s10" or (key == "s12" and "s10" not in selected):
                run_s2_refund_phase(ctx)
        if ctx.captured:
            run_s2_refund_phase(ctx)
        if "s5" in selected:
            if env_missing("s5"):
                REC.add("s5", f"needs {', '.join(env_missing('s5'))}", "BLOCKED")
            elif ctx.pp:
                try:
                    webhook_evaluate(ctx)
                except Exception as ex:
                    REC.add("s5", "script error in webhook evaluation", "FAIL", note=f"{type(ex).__name__}: {str(ex)[:200]}")
    except KeyboardInterrupt:
        log("\nInterrupted: cleaning up leftover Sandbox authorizations and captures ...")
        code = 130
    finally:
        try:
            cleanup(ctx)
            webhook_teardown(ctx)
        except Exception as ex:
            log(f"cleanup error: {type(ex).__name__}: {str(ex)[:160]}")
    md = write_report(ctx, Path(args.out_dir), selected)
    fails = sum(1 for r in REC.rows if r.result == "FAIL")
    log(f"\nReport written: {md}  (and spike_report.json). FAIL rows: {fails}")
    log("Now rotate the Sandbox app secret (checklist 0.1) and change any buyer password that was shown on screen.")
    return code or (1 if fails else 0)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="FairPool spike check (Sandbox only)")
    ap.add_argument("command", choices=["list", "check-env", "run"])
    ap.add_argument("--env-file", default=".env.spike")
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    ap.add_argument("--with-s3", action="store_true", help="also re-probe the second-seller onboarding (S3)")
    ap.add_argument("--non-interactive", action="store_true", help="never prompt; human steps are recorded as MANUAL")
    ap.add_argument("--no-confirm", action="store_true", help="do not ask before each stage")
    ap.add_argument("--print-approval-urls", action="store_true", help="print approval URLs to the terminal (never to the report)")
    ap.add_argument("--out-dir", default="spike_out")
    args = ap.parse_args(argv)
    load_env_file(args.env_file)
    if args.command == "list":
        return cmd_list()
    selected = [k for k in RUN_ORDER if k in (parse_keys(args.only) if args.only else RUN_ORDER)]
    if args.command == "check-env":
        return cmd_check_env(selected)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
