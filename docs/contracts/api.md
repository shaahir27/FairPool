# Contract: HTTP API

`backend/src/fairpool/api/schemas.py` (task T01B01) defines a Pydantic model for every payload below. The test `tests/unit/test_api_contract.py` parses the endpoint table in section 2 and fails if the FastAPI routes differ in method, path, or owner module. Owners are the member who implements the handler (`AB` means jointly, via the test helper in T04X01).

## 1. Conventions

- Base paths: app API `/api/v1`, agent API `/agent/v1`, PayPal webhook `/webhooks/paypal`, health `/health` and `/ready`.
- JSON in and out, snake_case keys, UTC ISO 8601 timestamps, money as integer cents (`*_cents`), IDs as UUID strings.
- Auth modes: `public`, `session` (HttpOnly cookie plus header `X-CSRF-Token` on every POST, PUT and DELETE), `merchant` (a session whose user has role merchant), `admin` (role admin), `agent` (header `Authorization: Bearer fpd_<prefix>_<secret>`, a buyer delegation token), `merchant_key` (header `Authorization: Bearer fpm_<prefix>_<secret>`, a merchant API key), `webhook` (PayPal signature headers). Tokens and keys are shown once at creation and stored only as HMACs.
- `Idempotency-Key` header (any string up to 128 characters) is **required** on `POST /api/v1/pools/{pool_id}/entries`, `POST /agent/v1/entries` and `PUT /merchant-api/v1/lots/{lot_id}/bid` (section 4.4 allows a body field for tool bridges). A replay with the same key and same body returns the original response; the same key with a different body returns `409 IDEMPOTENCY_CONFLICT`.
- Errors always use `{"error": {"code": "<CODE>", "message": "<human text>", "details": {}, "request_id": "<id>"}}` with codes from `config-and-errors.md`. Never put raw exception text in a response.
- Rate limits are in `config-and-errors.md`. Over the limit returns `429 RATE_LIMITED` with `Retry-After`.
- Responses never contain: PayPal secrets, the raw PayPal payer ID, another user's data, other merchants' bids, or unconfirmed AI output presented as confirmed.

## 2. Endpoint table

Columns: method, path, owner, auth, one-line purpose. Keep this table machine-parseable: one endpoint per row, path exactly as routed.

| Method | Path | Owner | Auth | Purpose |
|---|---|---|---|---|
| GET | /health | A | public | Liveness |
| GET | /ready | A | public | Readiness (database, migrations); before T01A01 it reports 503 `not_ready` with `database: not_configured` |
| POST | /api/v1/auth/register | B | public | Create account |
| POST | /api/v1/auth/login | B | public | Start session |
| POST | /api/v1/auth/logout | B | session | End session |
| GET | /api/v1/me | B | session | Current user, PayPal link state, unread notifications |
| GET | /api/v1/paypal/login/start | B | session | Begin Log in with PayPal, returns authorize URL |
| GET | /api/v1/paypal/login/callback | B | session | Finish login, store account key, redirect to app |
| DELETE | /api/v1/paypal/link | B | session | Revoke link (blocked while active entries exist) |
| POST | /api/v1/me/delegations | B | session | Create agent delegation, token shown once |
| GET | /api/v1/me/delegations | B | session | List delegations |
| DELETE | /api/v1/me/delegations/{delegation_id} | B | session | Revoke delegation |
| GET | /api/v1/pools | B | public | List and search pools (`q`, `status`, `sort=trending`) |
| GET | /api/v1/pools/{pool_id} | B | public | Pool detail and timeline |
| GET | /api/v1/pools/{pool_id}/rules | B | public | `{rules_document, rules_hash}` envelope containing the published rules and their hash |
| GET | /api/v1/pools/{pool_id}/events | B | public | Server-sent events for pool and lot status |
| POST | /api/v1/intake/messages | B | session | Buyer text to proposal or clarifying question |
| POST | /api/v1/intake/confirm | B | session | Confirm a proposal into a canonical request |
| POST | /api/v1/intake/manual | B | session | Manual form into a canonical request |
| POST | /api/v1/pools/{pool_id}/entries | B | session | Join a pool (idempotent), returns receipt |
| GET | /api/v1/pools/{pool_id}/entries/me | B | session | My entry in this pool |
| DELETE | /api/v1/pools/{pool_id}/entries/me | B | session | Withdraw before close (also deletes the saved PayPal permission in vault mode) |
| POST | /api/v1/entries/{entry_id}/vault | B | session | Vault mode: start saving PayPal; returns the consent version and the PayPal approval link; `Idempotency-Key` required |
| GET | /api/v1/entries/{entry_id}/vault/return | B | session | Vault mode: PayPal return handler; exchanges the setup token, stores the payment token encrypted, never returns it |
| DELETE | /api/v1/entries/{entry_id}/vault | B | session | Vault mode: delete the saved PayPal permission |
| GET | /api/v1/me/entries | B | session | My entries across pools |
| GET | /api/v1/entries/{entry_id}/status | B | session | Seat, waitlist position, offer |
| GET | /api/v1/public/pools/{pool_id}/audit | B | public | Public audit payload |
| GET | /api/v1/public/keys | B | public | Receipt signing public key |
| POST | /api/v1/merchant/profile | B | merchant | Create or update merchant profile and attestations |
| GET | /api/v1/merchant/lots | B | merchant | Lots open for bidding with requirement summaries (`q` search) |
| POST | /api/v1/merchant/lots/{lot_id}/quote | B | merchant | Paste a quote, get proposed fields |
| PUT | /api/v1/merchant/lots/{lot_id}/bid | B | merchant | Save a bid revision (structured fields and notes) |
| POST | /api/v1/merchant/bids/{bid_id}/confirm | B | merchant | Confirm a revision |
| GET | /api/v1/merchant/bids/{bid_id} | B | merchant | My bid, flags and result |
| POST | /api/v1/merchant/onboarding/start | A | merchant | Begin PayPal seller onboarding (Router A only) |
| GET | /api/v1/merchant/onboarding/return | A | merchant | Onboarding return handler |
| GET | /api/v1/offers/{buyer_order_id} | A | session | Offer disclosure |
| POST | /api/v1/offers/{buyer_order_id}/continue | A | session | Create PayPal order, return order ID and approve URL |
| POST | /api/v1/offers/{buyer_order_id}/decline | A | session | Decline the offer |
| GET | /api/v1/checkout/return | A | session | PayPal return handler |
| GET | /api/v1/checkout/cancel | A | session | PayPal cancel handler |
| GET | /api/v1/orders/{buyer_order_id} | A | session | Order status page data |
| POST | /api/v1/orders/{buyer_order_id}/withdraw | A | session | Withdraw (void) before capture |
| POST | /webhooks/paypal | A | webhook | PayPal webhook receiver |
| POST | /api/v1/admin/pools | B | admin | Create pool template (DRAFT) |
| POST | /api/v1/admin/pools/{pool_id}/publish | B | admin | Publish (freezes rules) |
| POST | /api/v1/admin/pools/{pool_id}/cancel | B | admin | Cancel before RUNNING |
| GET | /api/v1/admin/lots/{lot_id} | A | admin | Lot state view for ops |
| POST | /api/v1/admin/lots/{lot_id}/abort | A | admin | Abort a lot |
| POST | /api/v1/admin/lots/{lot_id}/force-award | AB | admin | Test and demo helper that writes an award (local, test, demo only) |
| POST | /api/v1/admin/reconciler/run | A | admin | Run the reconciler now |
| GET | /api/v1/admin/webhooks/dead-letter | A | admin | List dead-letter webhook events |
| POST | /api/v1/admin/webhooks/{event_id}/retry | A | admin | Retry one webhook event |
| GET | /api/v1/admin/alerts | A | admin | Open alerts |
| POST | /api/v1/admin/mock | A | admin | Set a demo mock toggle (only when `MOCK_TOGGLES_ENABLED`) |
| POST | /api/v1/admin/sim/run | B | admin | Start a simulation pool run |
| GET | /api/v1/admin/audit/export | A | admin | Export the audit chain |
| GET | /agent/v1/pools | B | agent | List and search open pools (`q`) with rules |
| POST | /agent/v1/entries | B | agent | Create an entry (idempotent) |
| GET | /agent/v1/entries/{entry_id} | B | agent | Entry status |
| DELETE | /agent/v1/entries/{entry_id} | B | agent | Withdraw before close |
| GET | /agent/v1/entries | B | agent | List my entries, optional `pool_id` or `entry_id` filter (flat form for tool bridges) |
| POST | /agent/v1/entries/withdraw | B | agent | Withdraw an entry by ID in the body (flat form for tool bridges) |
| POST | /mcp | B | agent | FairPool MCP server, Streamable HTTP (mounted app; tools in section 3) |
| GET | /mcp | B | agent | FairPool MCP server, Streamable HTTP stream |
| GET | /api/v1/checkout/config | A | public | JavaScript SDK v6 configuration (client ID, SDK URL, approval UI) |
| GET | /api/v1/checkout/client-token | A | session | Browser-safe client token (only when `PAYPAL_SDK_AUTH=client_token`) |
| POST | /api/v1/offers/{buyer_order_id}/approved | A | session | SDK `onApprove` notification; server verifies, then authorizes |
| POST | /api/v1/offers/{buyer_order_id}/cancelled | A | session | SDK `onCancel` notification |
| GET | /api/v1/me/orders | A | session | My orders with receipts |
| GET | /api/v1/merchant/events | B | merchant | Server-sent events: new lots, bid results, checkout progress |
| GET | /api/v1/merchant/bids | B | merchant | My bids by status |
| GET | /api/v1/merchant/lots/{lot_id}/progress | A | merchant | Holds, captures and refills for my awarded lot |
| GET | /api/v1/merchant/lots/{lot_id}/fulfillment | A | merchant | Shipping rows after FUNDED (JSON, or CSV by `Accept: text/csv`) |
| POST | /api/v1/merchant/lots/{lot_id}/shipments | A | merchant | Mark orders shipped with tracking numbers |
| GET | /api/v1/merchant/lots/{lot_id}/verification-manifest | A | merchant | PayPal order and capture IDs and amounts for verification |
| GET | /api/v1/merchant/lots/{lot_id}/verification | A | merchant | Live PayPal verification of the lot's captured orders |
| GET | /api/v1/merchant/api-keys | B | merchant | List API keys |
| POST | /api/v1/merchant/api-keys | B | merchant | Create an API key (secret shown once) |
| DELETE | /api/v1/merchant/api-keys/{key_id} | B | merchant | Revoke an API key |
| GET | /merchant-api/v1/lots | B | merchant_key | Lots open for bidding (`q`, `status`) |
| GET | /merchant-api/v1/lots/{lot_id} | B | merchant_key | Lot requirement detail |
| PUT | /merchant-api/v1/lots/{lot_id}/bid | B | merchant_key | Submit or revise a structured bid (idempotent) |
| GET | /merchant-api/v1/bids | B | merchant_key | My bids |
| GET | /merchant-api/v1/bids/{bid_id} | B | merchant_key | One bid with flags and result |
| GET | /merchant-api/v1/lots/{lot_id}/progress | A | merchant_key | Holds, captures and refills for my awarded lot |
| GET | /merchant-api/v1/lots/{lot_id}/fulfillment | A | merchant_key | Shipping rows after FUNDED |
| POST | /merchant-api/v1/lots/{lot_id}/shipments | A | merchant_key | Submit tracking numbers |
| GET | /merchant-api/v1/lots/{lot_id}/verification-manifest | A | merchant_key | Verification manifest |
| GET | /merchant-api/v1/lots/{lot_id}/verification | A | merchant_key | Live PayPal verification of the lot's captured orders |
| POST | /api/v1/admin/search/reindex | B | admin | Rebuild the search indexes |

## 3. Payload shapes (key endpoints)

### Intake

`POST /api/v1/intake/messages` request: `{"session_id": "uuid|null", "pool_id": "uuid|null", "message": "string up to 2000 chars"}`.
Response: `{"session_id": "uuid", "status": "NEEDS_CLARIFICATION" | "READY_TO_CONFIRM" | "NO_MATCH", "clarifying_question": "string|null", "confirmation_card": ConfirmationCard|null}`.

`ConfirmationCard` is rendered by the server from catalog data, never from AI prose:

```json
{
  "proposal_id": "uuid",
  "pool": {"id": "uuid", "title": "27-inch 4K monitor", "variant": "black", "condition": "NEW", "latest_delivery": "2026-11-17"},
  "delivery": {"zone_id": "US-EAST", "region": "NY"},
  "required_by": "2026-11-30",
  "max_total_cents": 60000,
  "firm": ["matte screen"],
  "preferences": ["black bezel"],
  "notices": {
    "no_charge": "Nothing is charged now. PayPal places a hold only after a merchant and exact price are known and you approve.",
    "lots_may_differ": "Separate lots in this pool can end with different winning merchants and prices."
  }
}
```

`POST /api/v1/intake/confirm` `{"proposal_id": "uuid"}` returns `201 {"confirmed_request_id": "uuid", "canonical_request": {...}}`. `POST /api/v1/intake/manual` takes `{"pool_id", "delivery": {"region"}, "required_by", "max_total_cents", "firm", "preferences"}` and returns the same shape.

### Entry

`POST /api/v1/pools/{pool_id}/entries` body `{"confirmed_request_id": "uuid"}`; returns `201` for a new entry or `200` for an existing one:

```json
{
  "entry_id": "uuid",
  "already_entered": false,
  "pool_status": "OPEN",
  "receipt": {
    "payload": {"commitment": "hex64", "entry_id": "uuid", "pool_id": "uuid", "received_at": "2026-11-02T10:00:01.123456Z", "v": 1},
    "salt_hex": "hex64",
    "request_hash": "hex64",
    "signature": "base64url"
  }
}
```

Vault mode (`vault-charge.md`): `POST /api/v1/entries/{entry_id}/vault` body `{"consent_version": "v1", "cap_cents": 60000}` returns `{"approve_url": "https://...", "consent_version": "v1"}`; it fails with `VAULT_SETUP_EXPIRED` if started too long ago. The entry status adds `vault_status` and `vault_label` (last four characters) and never a token. `GET /api/v1/entries/{entry_id}/vault/return` is an untrusted browser redirect: the server looks up its own setup token, exchanges it, and redirects `302` to the entry page.

`GET /api/v1/entries/{entry_id}/status`:

```json
{
  "entry_id": "uuid",
  "entry_status": "ELIGIBLE",
  "allocation": {"status": "SEATED", "zone_id": "US-EAST", "rank": 2, "lot_id": "uuid", "waitlist_position": null},
  "offer": {"buyer_order_id": "uuid", "status": "OFFERED", "offer_expires_at": "iso"}
}
```

### Public audit

`GET /api/v1/public/pools/{pool_id}/audit` returns `rules_hash`, `rules_document`, `pool_status`, `entries_root`, `entries_count`, `commitments` (sorted list, after close), `beacon`, `seed_hex`, `seed_is_demo`, `lots` (each with `lot_id`, `zone_id`, `lot_order`, `seats`, `status`, `rank_range`, and, after award, `award` with merchant display name, `item_cents`, `tier_index`, `award_hash`, `valid_until`), and `audit_checkpoints` (action plus hash). No personal data, no salts, no caps.

### Merchant

`POST /api/v1/merchant/lots/{lot_id}/quote` `{"quote_text": "string"}` returns `{"bid_id": "uuid", "revision": 1, "status": "PROPOSED", "proposed_fields": {structured with nulls}, "ambiguities": [{"field": "...", "question": "..."}]}`.
`PUT /api/v1/merchant/lots/{lot_id}/bid` `{"structured": {...}, "quote_text": "string|null", "notes": "string|null"}` returns `{"bid_id", "revision", "status", "receipt": {"hash": "hex64", "signature": "base64url"}}`.
`POST /api/v1/merchant/bids/{bid_id}/confirm` `{"revision": 2}` returns `{"bid_id", "revision", "status": "CONFIRMED"}`. The shape of `structured` is in `db-schema.md`.

### Offer and checkout

`GET /api/v1/offers/{buyer_order_id}`:

```json
{
  "buyer_order_id": "uuid",
  "status": "OFFERED",
  "merchant": {"display_name": "Demo Merchant One"},
  "product": {"title": "27-inch 4K monitor", "variant": "black", "condition": "NEW", "bundle_contents": ["monitor", "stand", "power cable"]},
  "terms": {"delivery_sla_days": 5, "returns_days": 30},
  "totals": {"item_cents": 47000, "shipping_cents": 1500, "tax_cents": 4113, "total_cents": 52613, "cap_cents": 55000},
  "offer_expires_at": "iso",
  "notices": {
    "hold": "PayPal places a hold for the total shown only after you approve. The hold is released if this lot does not reach its minimum.",
    "lots_may_differ": "Separate lots in this pool can end with different winning merchants and prices.",
    "fallback": null
  }
}
```

`notices.fallback` is a non-null string whenever `PAYMENT_ROUTER=single_seller` or `PAYMENT_MODE=capture_only` applies (DEP-4), for example `"Sandbox demo: one test seller stands in for the winning merchant."`.

`POST /api/v1/offers/{buyer_order_id}/continue` body `{"shipping": {"name", "line1", "line2", "city", "region", "postal_code", "country_code"}}` (the address is always required because fulfillment needs it; it is stored encrypted, N14, and is sent to PayPal only when `PAYPAL_PAYLOAD_LEVEL >= 3`); returns `{"paypal_order_id": "...", "approve_url": "https://www.sandbox.paypal.com/...", "approval_ui": "sdk_popup" | "redirect"}`. The browser sends **no amounts**. The server takes them from the award snapshot (I3).

`GET /api/v1/checkout/return?token=<paypal_order_id>&PayerID=<id>`: the query parameters are untrusted hints. The server looks up the order by `token`, fetches it from PayPal, runs the FR-CK-05 checks and redirects `302` to `{FRONTEND_BASE_URL}/orders/{buyer_order_id}`. `GET /api/v1/checkout/cancel` moves ORDER_CREATED to DECLINED (BO-22) and redirects the same way.

`GET /api/v1/orders/{buyer_order_id}`: `{"buyer_order_id", "status", "lot_status", "total_cents", "history": [{"status", "at"}], "paypal": {"authorization_status": "...|null", "capture_status": "...|null", "refund_status": "...|null"}, "labels": ["SANDBOX", "FALLBACK: single stand-in seller"]}`.

### Webhook

`POST /webhooks/paypal` takes the raw body and PayPal's transmission headers. Verified or duplicate events return `200 {}`. An unverified request returns `400` and is never processed. See `paypal-adapter.md`.

### Admin helpers

- `POST /api/v1/admin/lots/{lot_id}/force-award` body `{"merchant_id": "uuid", "item_cents": 47000, "tier_index": 0, "moq": 2, "valid_minutes": 60}` writes an award as `lot.award` would, for test and demo only. Enabled only when `APP_ENV` is `local` or `test` or `MOCK_TOGGLES_ENABLED` is true; otherwise `403 FEATURE_DISABLED`.
- `POST /api/v1/admin/mock` body `{"kind": "paypal_mock_response" | "force_capture_failure" | "delay_webhooks", "value": "string|null", "ttl_s": 300}`; only when `MOCK_TOGGLES_ENABLED`. Anything shown on screen while a mock is active carries a visible MOCK label.
- `POST /api/v1/admin/sim/run` body `{"entries": 10000, "merchants": 5, "seed": 42}` returns `202 {"sim_run_id": "uuid", "pool_id": "uuid"}`; the pool is `SIMULATION` mode.

### Agent API

`GET /agent/v1/pools` returns open pools: `[{"pool_id", "title", "status", "template", "timeline", "rules_hash"}]`.
`POST /agent/v1/entries` body `{"pool_id": "uuid", "request": {"delivery": {"region": "NY"}, "required_by": "2026-11-30", "max_total_cents": 60000, "firm": [], "preferences": []}}` with `Idempotency-Key`. It runs the same validator as the web flow. `max_total_cents` above the delegation's `max_cap_cents` returns `403 DELEGATION_CAP_EXCEEDED`. A second submission for the same account returns `200` with `already_entered: true` (the lane never creates extra entries, FR-SL-03). Response: the same body as the web join plus `"checkout_hint": "A human approves payment on PayPal; this API cannot pay."`.

### Server-sent events

`GET /api/v1/pools/{pool_id}/events` streams `event: pool_status`, `event: lot_status` and `event: tick` with JSON `data`, using server time only.

## 4. Integration endpoints and payloads

### 4.1 Checkout with the PayPal JavaScript SDK v6 (INT-7, FR-IG-06)

`GET /api/v1/checkout/config` returns only public values:

```json
{
  "approval_ui": "sdk_popup",
  "sdk_auth": "client_id",
  "client_id": "public sandbox client ID",
  "sdk_url": "https://www.sandbox.paypal.com/web-sdk/v6/core",
  "components": ["paypal-payments"],
  "page_type": "checkout",
  "currency": "USD",
  "labels": ["SANDBOX"]
}
```

`approval_ui` is `sdk_popup` or `redirect` (`PAYPAL_APPROVAL_UI`); `sdk_auth` is `client_id` or `client_token` (`PAYPAL_SDK_AUTH`, set by S13). With `client_token` the page first calls `GET /api/v1/checkout/client-token` (`{"client_token": "...", "expires_in": 900}`); the server obtains it from PayPal with `response_type=client_token` and the site's domain, caches it only until a minute before expiry, and never returns the secret.

Browser sequence (the contract the frontend implements):

1. Load `sdk_url`; `paypal.createInstance({clientId or clientToken, components, pageType})`; `findEligibleMethods({currencyCode: "USD"})`; show `<paypal-button>` only if `paypal` is eligible, else show the redirect button.
2. On click, `session.start({presentationMode: "auto"}, createOrder())` where `createOrder()` calls `POST /api/v1/offers/{id}/continue` and resolves `{orderId: paypal_order_id}`.
3. `onApprove(data)` posts `{"paypal_order_id": data.orderId}` to `POST /api/v1/offers/{id}/approved` and then polls `GET /api/v1/orders/{id}`. It never captures, authorizes or sends an amount.
4. `onCancel` posts to `POST /api/v1/offers/{id}/cancelled`; `onError` shows a retry and logs the SDK error code.
5. If the SDK fails to load or is not eligible, use `approve_url` from `continue` (redirect fallback, the path verified in the Sandbox).

`POST /api/v1/offers/{buyer_order_id}/approved` body `{"paypal_order_id": "..."}`. The server checks the ID belongs to this buyer order, fetches the order from PayPal, runs the FR-CK-05 checks and returns `{"buyer_order_id", "status": "APPROVED" | "REJECTED" | "EXPIRED", "reason": "<reason code>|null"}`; on APPROVED it enqueues `order.authorize` (BO-02). `POST .../cancelled` moves ORDER_CREATED to DECLINED (BO-22). Both callbacks are idempotent and only hints; PayPal's GET is the truth.

### 4.2 Merchant console endpoints (session)

`GET /api/v1/merchant/lots/{lot_id}/progress` (also on the Merchant Agent API; only the awarded merchant):

```json
{
  "lot_id": "uuid", "status": "CHECKOUT_OPEN", "seats": 3, "moq": 2,
  "holds_placed": 2, "captures_completed": 0, "refills_offered": 1,
  "counts": {"OFFERED": 1, "ORDER_CREATED": 0, "APPROVED": 0, "AUTHORIZING": 0, "AUTHORIZED": 2,
             "CAPTURING": 0, "CAPTURE_PENDING": 0, "CAPTURED": 0, "REFUNDING": 0, "EXPIRED": 0, "DECLINED": 0,
             "REJECTED": 0, "AUTH_FAILED": 0, "CAPTURE_FAILED": 0, "VOIDED": 0, "REFUNDED": 0},
  "fund_deadline_at": "iso", "labels": ["SANDBOX", "FALLBACK: single stand-in seller"]
}
```

Counts only; no buyer identities. The UI tracker shows `holds_placed` against `moq` until the sweep starts, then `captures_completed` against `moq` (design 11.6).

`GET /api/v1/merchant/lots/{lot_id}/fulfillment` returns `409 LOT_NOT_FUNDED` unless the lot is FUNDED or CLOSED. Rows only for buyer orders in CAPTURED: `[{"buyer_order_id", "name", "line1", "line2", "city", "region", "postal_code", "country_code", "item_cents", "shipping_cents", "tax_cents", "total_cents", "paypal_capture_id"}]`; with `Accept: text/csv` the same columns as CSV. The address is decrypted only here (N14).

`POST /api/v1/merchant/lots/{lot_id}/shipments` body `{"shipments": [{"buyer_order_id": "uuid", "carrier": "string", "tracking_number": "string"}]}` (at most 100 per call, idempotent per `buyer_order_id`): creates `shipments` rows and, when `SHIPMENT_TRACKING_ENABLED`, enqueues `shipments.submit`. Response `202 {"accepted": n, "rows": [{"buyer_order_id", "status": "RECORDED"|"INVALID", "paypal_tracker_status": null}]}`; invalid rows return `SHIPMENT_INVALID` per row.

`GET /api/v1/merchant/lots/{lot_id}/verification-manifest` (INT-6):

```json
{
  "lot_id": "uuid", "currency": "USD", "funded": true,
  "expected_captured_total_cents": 105226,
  "items": [{"paypal_order_id": "...", "paypal_capture_id": "...", "amount_cents": 52613, "captured_at": "iso"}],
  "how_to_verify": "In your AI client connected to the PayPal MCP server, look up each order ID with a read-only get-order tool and confirm the capture amounts add up to expected_captured_total_cents."
}
```

No buyer personal data. Only CAPTURED orders are listed.

`GET /api/v1/merchant/lots/{lot_id}/verification` (also `/merchant-api/v1/lots/{lot_id}/verification`) is the FairPool verification tool and the primary verification path in every configuration; `PAYPAL_MCP_VERIFICATION=paypal_read_subset` additionally allows the local, pinned, read-only PayPal MCP for inspection (S10), never for payment correctness. It fetches every listed order from PayPal through the adapter (read-only GETs) and returns:

```json
{
  "lot_id": "uuid", "checked_at": "iso", "matched": 2, "total": 2, "all_match": true,
  "expected_captured_total_cents": 105226, "paypal_captured_total_cents": 105226,
  "items": [{"paypal_order_id": "...", "paypal_capture_id": "...", "expected_amount_cents": 52613,
             "paypal_capture_status": "COMPLETED", "paypal_amount_cents": 52613, "match": true}]
}
```

It is rate limited to 10 requests per minute per merchant because each call makes live PayPal GETs.

API keys: `POST /api/v1/merchant/api-keys` body `{"name": "pricing-bot", "scopes": ["lots:read", "bids:write"]}` returns `201 {"id", "name", "key": "fpm_<prefix>_<secret>", "scopes": [...]}`; the key is shown once and stored only as an HMAC (`db-schema.md`). Creating a key requires the merchant's attestations to be accepted.

### 4.3 Merchant Agent API (INT-9, FR-IG-04)

A FastAPI sub-application mounted at `/merchant-api/v1` with its own OpenAPI document at `/merchant-api/v1/openapi.json`. That document is the **only** input to APIMatic (INT-4) and contains exactly the ten operations below, which is within the Lite plan's 20-endpoint limit. Operation IDs are fixed so generated SDK method names are stable.

| operationId | Method and path | Scope |
|---|---|---|
| list_lots | GET /merchant-api/v1/lots | lots:read |
| get_lot | GET /merchant-api/v1/lots/{lot_id} | lots:read |
| submit_bid | PUT /merchant-api/v1/lots/{lot_id}/bid | bids:write |
| list_bids | GET /merchant-api/v1/bids | bids:read |
| get_bid | GET /merchant-api/v1/bids/{bid_id} | bids:read |
| get_lot_progress | GET /merchant-api/v1/lots/{lot_id}/progress | fulfillment:read |
| get_lot_fulfillment | GET /merchant-api/v1/lots/{lot_id}/fulfillment | fulfillment:read |
| submit_shipments | POST /merchant-api/v1/lots/{lot_id}/shipments | shipments:write |
| get_verification_manifest | GET /merchant-api/v1/lots/{lot_id}/verification-manifest | manifest:read |
| get_lot_verification | GET /merchant-api/v1/lots/{lot_id}/verification | manifest:read |

Rules: `Authorization: Bearer fpm_<prefix>_<secret>`; wrong or revoked key is `401 API_KEY_INVALID`; missing scope is `403 API_KEY_SCOPE`; 120 requests per minute per key; `PUT .../bid` requires `Idempotency-Key`. Body: `{"structured": {...}, "notes": "string|null", "confirmed": true}`. `confirmed` must be true; the bot's structured submission is its confirmation (the pasted-quote path with human confirmation, DEP-2, exists only in the console). The same rules R1 to R9, sealing and receipts apply; a key can see only its own merchant's bids and lots it won. The response matches the console's: `{"bid_id", "revision", "status", "receipt": {"hash", "signature"}}`.

### 4.4 Agent API additions (FR-AG-01, INT-2, INT-3)

- `GET /agent/v1/pools?q=<text>&limit=<n>` searches open pools (hybrid search, FR-IG-01) and returns the same items as the list.
- Requests may give `max_total_usd` (a string such as `"600.00"`) instead of `max_total_cents`; exactly one of the two. The server converts with the regex `^\d+(\.\d{1,2})?$` and rejects anything else. This exists so AI clients never do cents arithmetic.
- Tool bridges that cannot set headers may send `idempotency_key` in the body; if both header and body are present they must match, else `400 IDEMPOTENCY_CONFLICT`.
- `GET /agent/v1/entries` returns the caller's entries: `[{"entry_id", "pool_id", "entry_status", "allocation": {...}, "offer": {...}|null, "checkout_url": "<FRONTEND_BASE_URL>/offers/<buyer_order_id>"|null}]`. `checkout_url` is for the human, who approves payment on PayPal.
- `POST /agent/v1/entries/withdraw` body `{"entry_id": "uuid"}`.
- Route order: register `/agent/v1/entries/withdraw` before `/agent/v1/entries/{entry_id}`.

### 4.5 FairPool MCP server (INT-3, FR-IG-02)

Mounted at `/mcp` using the official MCP Python SDK over Streamable HTTP. Auth is the same delegation token as the Agent API (`Authorization: Bearer fpd_<prefix>_<secret>`). The mounted app is excluded from the route-table test; its tools are checked by `tests/unit/test_mcp_contract.py`. Tools and input schemas:

| Tool | Input | Calls |
|---|---|---|
| list_pools | `{"q": "string\|null", "limit": 1 to 20}` | `GET /agent/v1/pools` |
| enter_pool | `{"pool_id", "delivery_region", "max_total_usd" or "max_total_cents", "required_by"?, "firm"?, "preferences"?, "idempotency_key"}` | `POST /agent/v1/entries` |
| list_entries | `{"pool_id"?, "entry_id"?}` | `GET /agent/v1/entries` |
| withdraw_entry | `{"entry_id"}` | `POST /agent/v1/entries/withdraw` |

There is no payment, order or PayPal tool (I1, I2). Tool results are the Agent API JSON, with `checkout_url` for the human.

### 4.6 Zapier managed-mode bridge (INT-2, FR-IG-03)

Documentation contract (nothing in our code reads Zapier): a Zapier MCP server in **managed mode** with four Webhooks by Zapier tools, each with URL and `Authorization` header locked to `{PUBLIC_BASE_URL}/agent/v1/...` and a delegation token; only the body or query fields are left for the AI to fill.

| Zapier tool | Locked URL | AI-filled fields |
|---|---|---|
| fairpool_list_pools | GET `/agent/v1/pools` | `q`, `limit` |
| fairpool_join_pool | POST `/agent/v1/entries` | body: `pool_id`, `request.*`, `idempotency_key` |
| fairpool_list_entries | GET `/agent/v1/entries` | `pool_id` |
| fairpool_withdraw_entry | POST `/agent/v1/entries/withdraw` | body: `entry_id` |

Rules: no PayPal app and no other app is added to the server; managed mode only (the default mode lets the agent discover and enable actions itself); the delegation token has a low `max_cap_cents` and a short expiry; the token is never pasted into prompts or committed.
