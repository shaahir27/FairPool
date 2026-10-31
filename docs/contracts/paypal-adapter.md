# Contract: PayPal adapter

Owner: Member A. Code lives in `backend/src/fairpool/adapters/paypal/`. This file is built from the checklist, the sandbox report (V1 to V13) and the spike results recorded in `docs/spike-results.md` (S2 and S3, Oct 20, 2026). Anything not backed by a V fact or a recorded spike is marked X and must not be relied on until a spike records it.

Hard rules: only this package calls PayPal (I2); only the PayPal Sandbox hosts are allowed (FR-PP-06); secrets stay in the environment (I14); raw REST over `httpx`, no PayPal SDK, no Payouts, no NVP or SOAP.

## 1. Host guard

The gateway constructor refuses to start unless `PAYPAL_API_BASE` host is exactly `api-m.sandbox.paypal.com` and `PAYPAL_CHECKOUT_BASE` host is exactly `www.sandbox.paypal.com`. A unit test asserts that a live host raises `ForbiddenHost`.

## 2. Types and ports

```python
@dataclass(frozen=True)
class Payee: email: str | None; merchant_id: str | None

@dataclass(frozen=True)
class PayPalAuthorization: id: str; status: str; amount_cents: int; expires_at: datetime | None
@dataclass(frozen=True)
class PayPalCapture: id: str; status: str; amount_cents: int; final_capture: bool; auth_id: str | None
@dataclass(frozen=True)
class PayPalRefund: id: str; status: str; amount_cents: int
@dataclass(frozen=True)
class TrackerItem: paypal_order_id: str; capture_id: str; carrier: str; tracking_number: str
class SetupToken: id: str; approve_url: str                       # vault-charge.md; the approve URL is never logged
class PaymentToken: id: str; label: str                            # id is a credential: encrypt, never log
class ChargeResult: order_id: str; capture_id: str | None; capture_status: str | None; error: str | None
@dataclass(frozen=True)
class TrackerResult: capture_id: str; ok: bool; error: str | None; debug_id: str | None

@dataclass(frozen=True)
class PayPalOrder:
    id: str; status: str; intent: str; currency: str; amount_cents: int
    payee_email: str | None; payee_merchant_id: str | None
    payer_id: str | None; payer_country: str | None; approve_url: str | None
    authorizations: list[PayPalAuthorization]; captures: list[PayPalCapture]
    debug_id: str | None; raw: dict          # raw is sanitized: no secrets, no approval URLs

class PayPalGateway(Protocol):
    async def create_order(self, req: CreateOrderRequest) -> PayPalOrder: ...
    async def get_order(self, paypal_order_id: str) -> PayPalOrder: ...
    async def authorize_order(self, paypal_order_id: str, *, request_key: str) -> PayPalOrder: ...
    async def get_authorization(self, auth_id: str) -> PayPalAuthorization: ...
    async def capture_authorization(self, auth_id: str, *, amount_cents: int, request_key: str) -> PayPalCapture: ...
    async def get_capture(self, capture_id: str) -> PayPalCapture: ...
    async def void_authorization(self, auth_id: str) -> None: ...      # no request ID: void does not replay (S2)
    async def refund_capture(self, capture_id: str, *, amount_cents: int | None, request_key: str) -> PayPalRefund: ...
    async def get_refund(self, refund_id: str) -> PayPalRefund: ...
    async def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool: ...
    async def list_webhooks(self) -> list[dict]: ...
    async def add_trackers(self, items: list[TrackerItem]) -> list[TrackerResult]: ...   # INT-8, Orders v2 track (S12 passed)
    async def create_setup_token(self, entry_id: str, return_url: str, cancel_url: str) -> SetupToken: ...   # vault-charge.md, key vs:{entry_id}
    async def create_payment_token(self, setup_token_id: str, entry_id: str) -> PaymentToken: ...           # key vp:{entry_id}
    async def delete_payment_token(self, payment_token_id: str, entry_id: str) -> None: ...                 # key vd:{entry_id}; 404 counts as deleted
    async def charge_vault(self, buyer_order_id: str, payment_token_id: str, total_cents: int, payee: Payee) -> ChargeResult: ...   # logical vc:{buyer_order_id}; HTTP UUIDv5 keys vc:{buyer_order_id}:create and :capture; one order, capture only if needed

class PaymentRouter(Protocol):
    name: str                                   # fake | single_seller | payee_email | platform
    gateway: PayPalGateway
    def payee_for(self, award: AwardView, payee_ref: PayeeRef) -> Payee: ...
    def label(self) -> str | None: ...          # fallback label shown to users, or None
```

`CreateOrderRequest` fields: `buyer_order_id`, `attempt`, `amount_cents`, `breakdown` (item, shipping, tax cents, level 2 and up), `description`, `reference_id`, `payee`, `return_url`, `cancel_url`, `shipping` (level 3), `payload_level`, `extra_headers` (mock toggles only).

## 3. Idempotency keys

`PayPal-Request-Id = uuid5(FAIRPOOL_NS, key_text)` with

`FAIRPOOL_NS = uuid5(NAMESPACE_URL, "https://fairpool.example/idempotency/v1") = 2c6dade6-420e-532e-8a9f-66c241f37634`

Example: key text `create:11111111-1111-4111-8111-111111111111:1` gives `af91b897-da70-5be9-acc5-1603b4fbdd08`; key text `auth:11111111-1111-4111-8111-111111111111` gives `ca61e904-9164-5d57-a861-efc021602ee6`.

| Operation | Key text | Replay behaviour (evidence) |
|---|---|---|
| Create order | `create:{buyer_order_id}:{attempt}` | 201 then 200, same order (V3) |
| Authorize | `auth:{buyer_order_id}` | 200 with the same result (S2), so `AUTHORIZE_USE_REQUEST_ID=true` |
| Capture | `cap:{paypal_auth_id}` | 200, one capture only (V10, S2) |
| Refund | `refund:{paypal_capture_id}:{seq}` | 200, original refund (V10, S2) |
| Void | none | **Does not replay**: a second void returns 422 with or without a request ID (S2). Always GET first |

A key is never reused with a different payload (I9). A re-quote increments `attempt`. Our own ledger also enforces uniqueness because PayPal's retention differs by API (P6).

## 4. Call catalogue

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Token | `POST /v1/oauth2/token` | 200, `expires_in` 32,400 s | Cache in memory, refresh 5 minutes early and once on 401 (V1) |
| Create order | `POST /v2/checkout/orders` | 201 CREATED | Headers: `PayPal-Request-Id`, `Prefer: return=representation` (V2) |
| Get order | `GET /v2/checkout/orders/{id}` | 200 | After approval shows payer and may show a payee merchant ID (S2) |
| Authorize | `POST /v2/checkout/orders/{id}/authorize` | 201 | Before approval: 422 ORDER_NOT_APPROVED (V4) |
| Get authorization | `GET /v2/payments/authorizations/{id}` | 200 | Status VOIDED after a void (V8) |
| Capture authorization | `POST /v2/payments/authorizations/{id}/capture` | 201 COMPLETED or PENDING | Verified in S2; `final_capture: true`, full amount |
| Get capture | `GET /v2/payments/captures/{id}` | 200 | |
| Void | `POST /v2/payments/authorizations/{id}/void` | 200 with body (observed) or 204 (P2) | Replay returns 422; capture after void returns 422 AUTHORIZATION_VOIDED (S2) |
| Refund | `POST /v2/payments/captures/{id}/refund` | 201 COMPLETED | Full refund only in the MVP |
| Get refund | `GET /v2/payments/refunds/{id}` | 200 | |
| Add trackers | `POST /v2/checkout/orders/{order_id}/track` | 201 first time, 200 on a repeat | S12 passed (Oct 28). Body carries the capture ID, tracking number and carrier; real seller-supplied tracking only, sent after shipment; `notify_payer=false` in tests. After the call, `GET` the order and confirm exactly one matching tracker. The legacy `/v1/shipping/trackers-batch` returned 403 for this app and is never called. Acceptance is not proof of shipment or delivery. Adapter only, never an AI call |
| Verify webhook | `POST /v1/notifications/verify-webhook-signature` | `verification_status: SUCCESS` | X until S5 |
| List webhooks and event types | `GET /v1/notifications/webhooks`, `/webhooks-event-types` | 200 | V7 |

**Where status lives.** Money state is read from the **authorization** object (`purchase_units[0].payments.authorizations[0].status`, expected `CREATED`) and the **capture** object (`COMPLETED` is the only paid status, P3). The order's own `status` is never a payment signal: it read COMPLETED after a void (V8) and the spike table lists COMPLETED on authorize (see open question O1 in `docs/spike-results.md`). If the authorization object reports a status other than CREATED, PENDING, DENIED, EXPIRED or VOIDED, treat the outcome as unknown, stay AUTHORIZING and alert.

Authorization statuses: CREATED means AUTHORIZED. PENDING means stay AUTHORIZING and poll until `pending_wait_s`, then AUTH_FAILED. DENIED, EXPIRED or VOIDED means AUTH_FAILED (or VOIDED if we voided). Capture statuses: COMPLETED is paid; PENDING polls; DECLINED and FAILED are CAPTURE_FAILED.

## 5. Payload ladder

Level 0 is exactly what V2 and V3 verified. Higher levels are enabled only up to `PAYPAL_PAYLOAD_LEVEL`, set by S4.

| Level | Adds | Notes |
|---|---|---|
| 0 | `intent: AUTHORIZE`; one purchase unit with `reference_id`, `description`, `amount {currency_code: USD, value}`, `payee.email_address` | V2, V3 |
| 1 | `custom_id` = buyer order ID; `invoice_id` unique per attempt | G8; test replay with invoice_id (V6 DUPLICATE_INVOICE_ID) |
| 2 | `amount.breakdown` (item_total, shipping, tax_total) and `items` | G8; must sum exactly |
| 3 | `payment_source.paypal.experience_context` with return and cancel URLs, pay-now action, provided shipping address with changes disabled | G8, X |
| 4 | `PayPal-Auth-Assertion`, payee merchant ID, platform fee | **Unavailable** (G4 and G9 failed) |

Mapping never depends on a level above the enabled one: we store the PayPal order ID we created, and `custom_id` is only a convenience for webhooks.

## 6. Payee verification and approval checks (FR-CK-05)

After approval, `GET` the order and require all of:

1. `status == APPROVED` and `intent == AUTHORIZE`.
2. `currency == USD` and `amount_cents` equals the expected cents.
3. Payee: if `payee_email` is present it must equal the expected email (case-insensitive); if `payee_merchant_id` is present it must equal the expected merchant ID when we hold one; at least one must be present and match; none may mismatch. Never require `payee_merchant_id` to exist (V2, checklist 3.4); report a missing one as missing.
4. `payer_country` is in `ALLOWED_PAYER_COUNTRIES` (default US) (V12).
5. Payer key: `HMAC(HMAC_KEY, payer_id)` is not held by another active seat in the pool and, when `DEDUPE_MODE=full`, equals the linked key (FR-ID-04). Under `two_keys` (S1 result) the login key and the checkout key are two separate provider identifiers, each checked for uniqueness on its own, with no equality required and no prefix-stripping to force a match; neither proves one human.

Any failure moves the order to REJECTED (BO-18 or BO-19) with a reason from `config-and-errors.md` and never authorizes. Never trust the return URL's `token` or `PayerID` beyond looking up our own order.

## 7. Error classes and retries

| Signal | Class | Action |
|---|---|---|
| Network error, timeout, 5xx, 429 | RETRYABLE | Backoff 1 s growing to 30 s with jitter, at most 5 tries, same key; then outcome UNKNOWN and hand to the reconciler (F1, F22) |
| 401 on a normal call | TOKEN | Refresh once, retry with the same key (F21) |
| 401 `invalid_subject` or 403 `NOT_AUTHORIZED` | CONFIG | Do not retry; alert; this is a permission problem (S3) |
| 422 `ORDER_NOT_APPROVED` | WAIT | Not an error (V4) |
| 422 `DUPLICATE_INVOICE_ID` | BUG | Alert, never loop (V6) |
| 422 on void | VOID_REPLAY | GET the authorization; if VOIDED treat as success; else alert (S2) |
| 422 `AUTHORIZATION_VOIDED` on capture | TERMINAL | Authorization is gone; mark the order and create a vacancy (S2) |
| 422 `UNSUPPORTED_PAYEE_CURRENCY` | TERMINAL | India or currency problem; reject (V12) |
| 422 `UNSUPPORTED_PAYMENT_INSTRUCTION` | CONFIG | Platform fee unsupported (S3); never sent |
| Other 4xx | TERMINAL | Record `debug_id`, no retry |
| 200 on a replay | OK | Return the original object (V3, V10, S2) |

Persist every result before the next step. A money-moving call is never fire-and-forget.

## 8. Webhooks

- Endpoint `POST /webhooks/paypal`: read the raw body, verify the signature (`verify_webhook` with `PAYPAL_WEBHOOK_ID`; method confirmed in S5), insert into `webhook_events` (unique event ID; a duplicate returns 200 and stops), return 200 quickly, enqueue `webhook.process`. Unverified: 400, audit, never processed (P4). Public HTTPS on port 443 (checklist 5.1).
- Subscribe to the seven event types of V7: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.PENDING`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.REFUNDED`.
- Mapping: capture and authorization events carry the resource ID we stored; capture events carry the order ID under `supplementary_data.related_ids.order_id`; order events carry the order ID. After mapping, `GET` the resource and apply it through the state machine (monotonic). The event text is never used. Unmappable events go to the dead-letter list.
- S5 (Oct 28) verified three real types: `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.REFUNDED`. `CHECKOUT.ORDER.APPROVED` did not arrive within four minutes, so approval is **never** awaited as a webhook: the approval step always GETs the order (section 6). With `WEBHOOKS_ENABLED=true` the handler processes only the verified types, as hints that trigger a GET. A verified signature does not replace checking the event's resource identity, amount, currency, seller and state. Duplicate delivery is real (a resend delivered the same event ID twice), so the unique event-ID insert above is required, not optional.
- Simulator events are mock (P4) and only test plumbing.

## 9. Routers

| Router | Value | Status | Behaviour |
|---|---|---|---|
| Fake | `fake` | Always available | In-memory gateway; supports failure injection: deny authorize, decline or pend a capture, timeout after send, drop webhooks. Never reaches the network. Used by tests and SIMULATION pools (I12) |
| Single seller (Router B) | `single_seller` | **In force and final** (G4 failed, S7 rejected the alternative) | Every order's payee is `SINGLE_SELLER_EMAIL`, which must be the sandbox business account that owns the REST app (and `SINGLE_SELLER_MERCHANT_ID` if set); a seller email accepted at order creation does not prove the app may void or refund its payments. The winning merchant's name appears in the order description and on screen. `label()` returns `Sandbox demo: one test seller stands in for the winning merchant.` |
| Payee email | `payee_email` | **Rejected** (S7, Oct 28) | A separately selected seller could receive captures, but void and refund returned `PERMISSION_DENIED`. The adapter raises `NotEnabled`; the enum value stays only so the schema and tests match |
| Platform (Router A) | `platform` | **Unavailable** (G4, G9) | Stub that raises `NotEnabled`. Would need partner permission, `PayPal-Auth-Assertion` and Partner Referrals |

The router is chosen at award time from `PAYMENT_ROUTER` and stamped on the lot (N8). A pool in SIMULATION mode always uses `fake`.

## 10. Demo mock toggles

Implemented by a wrapper `FaultInjectingGateway` around the real gateway, enabled only when `MOCK_TOGGLES_ENABLED`. `paypal_mock_response` sets the `PayPal-Mock-Response` header on the next call (only for codes verified by a spike; DUPLICATE_INVOICE_ID is V6). `force_capture_failure` makes the next capture call return a simulated DECLINED **without calling PayPal**, so the real authorization stays voidable. Anything shown while a toggle is active carries a visible MOCK label.

## 11. Sandbox contract tests

Tests live in `backend/tests/contract_sandbox/`, marked `sandbox` (non-interactive) or `sandbox_interactive` (needs a human to approve an order; the helper prints the approval link only to the local terminal and waits). They skip in CI. They use real Sandbox calls, never mocks, and USD 1.00.

| Test | Proves | Interactive |
|---|---|---|
| C-01 token | V1 | no |
| C-02 create order | V2 | no |
| C-03 create replay | V3 | no |
| C-04 authorize and capture before approval return 422 | V4 | no |
| C-05 two orders have distinct IDs | V5 | no |
| C-06 mock DUPLICATE_INVOICE_ID | V6 | no |
| C-07 event types listed | V7 | no |
| C-08 authorize then void, GET shows VOIDED | V8 | yes |
| C-09 authorize, capture the authorization, refund | G3, S2 | yes |
| C-10 replay authorize, capture, refund | V10, S2 | yes |
| C-11 void replay returns 422; capture after void returns AUTHORIZATION_VOIDED | S2 | yes |
| C-12 payer fields present, payee as shown on GET | V11, S2 | yes |
| C-13 India or INR is rejected | V12 | yes |
| C-14 payload ladder levels | S4, G8 | yes |
| C-15 webhook delivery and signature | S5, G5 | yes |
| C-16 the payee-email router raises NotEnabled (S7 rejected it: a second seller's void and refund returned PERMISSION_DENIED) | S7, G11 | no |
| C-17 JavaScript SDK v6 popup approval of an AUTHORIZE order, then server-side authorize | S13, G17 | yes |
| C-18 Orders v2 track for a captured sandbox order, GET shows one tracker, repeat stays one | S12, G16 | yes |
| VC-01 to VC-06 vault and charge tests | `vault-charge.md` section 9 | VC-01 yes, others no |

## 12. JavaScript SDK v6 server obligations (INT-7)

Official facts (developer.paypal.com/sdk/js/set-up): script `https://www.sandbox.paypal.com/web-sdk/v6/core`; `createInstance` with a client ID (the recommended option, chosen) or a client token (S13: works only for a configured public domain; `localhost` returns 401 `invalid_domain`); `createPayPalOneTimePaymentSession({onApprove, onCancel, onError})`; `session.start({presentationMode: "auto"}, createOrder())` with `createOrder` resolving `{orderId}`; the page says never to pass totals from the browser.

Our obligations:

1. `continue` creates the order with the same Level 0 payload as the redirect flow (`intent: AUTHORIZE`, amount from the award snapshot) and returns `paypal_order_id`; the SDK popup replaces only the approval step.
2. `onApprove` hands us the order ID. We never capture in the browser or server at that point: the server runs the approval checks of section 6 and then `order.authorize` authorizes (S2 verified `POST /v2/checkout/orders/{id}/authorize`). The SDK page's own sample captures in `onApprove`; ours must not. Where the SDK page's v4-to-v6 mapping names a different authorize endpoint, the verified S2 endpoint wins.
3. Record `approval_channel` (`sdk_popup` or `redirect`) on `paypal_orders`.
4. With `PAYPAL_SDK_AUTH=client_token`, the server calls `POST /v1/oauth2/token` with `grant_type=client_credentials`, `response_type=client_token` and the site's `domains[]`, returns only the `access_token`, and caches it until a minute before expiry (the docs state 15 minutes for the SDK token). The REST secret never leaves the server.
5. If the SDK is blocked, not eligible or errors, the UI uses the redirect `approve_url`; the redirect path is verified (V8, S2).
6. The `onApprove` argument carried `fundingSource`, `orderId` and `payerId` (S13). Treat them as hints: accept a callback only for an order this server created, and decide everything from a server-side GET.
7. `onCancel` leaves the order `CREATED` with no authorization or capture (S13); a cancelled or declined checkout is never counted as paid.
8. The client-ID flow passed on the owner's public HTTPS tunnel (Oct 29); task T07A01 repeats it once on the real deployed host, and if it fails sets `PAYPAL_SDK_AUTH=client_token` and registers that hostname. In vault mode this approval is only the fallback path.

## 13. PayPal MCP server and Agent Toolkit boundaries (INT-5, INT-6)

- FairPool's backend **never** runs the PayPal Agent Toolkit or the PayPal MCP server and never lets an AI create orders or move money. The toolkit's `create_order` takes only items and currency (no intent, payee, shipping or request ID) and `pay_order` captures an order, so it cannot express our flow.
- The merchant's own AI client may connect to the **local** `@paypal/mcp` (1.8.1 on `@paypal/agent-toolkit` 1.11.0 in S10; pin both in a lockfile) started with `--tools=orders.get,disputes.list,disputes.get,shipment.get,payments.getRefunds` for **read-only** inspection. The hosted sandbox server is not used: `/http` returned 404, and `/sse` listed tools but its `get_order` returned a business error (`ok=false`) with `isError` unset, so a client must parse the reply's own `ok` field, never `isError` alone. Allowed read tools: get order, get shipment tracking, get refund details, list disputes and get dispute. Forbidden for this use: pay order, create order, create refund, accept dispute claim and any other write tool. The explicit tool selection is a test boundary, not a read-only permission on the access token. `PAYPAL_MCP_VERIFICATION=paypal_read_subset` marks the local server as usable for inspection; FairPool's own verification tool doing the same GETs server-side stays the primary path, and nothing in payment correctness depends on MCP.
- Do not use the list-transactions tool in a live demo: Transaction Search can lag by up to three hours and needs a permission enabled on the app (which can take up to nine hours to take effect).
- The verification manifest (`api.md` section 4.2) is the only list of PayPal IDs we give out; it carries no buyer personal data.

## 14. Never

Call a host other than the two Sandbox hosts; run the PayPal Agent Toolkit or MCP server in the backend; let any AI call a PayPal write action; log or store secrets, assertion values or full approval URLs; infer payment from order status; authorize from anywhere but `order.authorize`; reuse a key with a different payload; replay a void; send a platform fee; use Payouts or NVP.
