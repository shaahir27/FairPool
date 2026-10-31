# Contract: configuration, errors and reason codes

`backend/src/fairpool/config.py` defines a typed `Settings` class (pydantic-settings) with exactly the variables below. Startup fails with a clear message if a required variable is missing or a value is not allowed. `.env.example` lists names only, never values. `tools/validate_docs.py` checks that every `PAYPAL_`, `PAYMENT_`, `AI_` and similar variable named anywhere in `docs/` appears in this table.

## 1. Environment variables

Owner is who maintains the code that reads it. Secrets are marked S and never appear in logs, the repo or the client (I14).

| Variable | Default | Owner | S | Meaning |
|---|---|---|---|---|
| `APP_ENV` | `local` | A | | `local`, `test`, `render` |
| `DATABASE_URL` | none (required) | A | S | Postgres connection string |
| `SECRET_KEY` | none (required) | A | S | Session signing |
| `HMAC_KEY` | none (required) | A | S | HMAC for PayPal account keys (BD-12) |
| `RECEIPT_SIGNING_KEY` | none (required) | B | S | Ed25519 private key for receipts, base64url |
| `ADDRESS_ENCRYPTION_KEY` | none (required) | A | S | Fernet key for shipping addresses (BD-11) |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | A | | Public API origin (used in return URLs and webhook docs) |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | B | | Frontend origin (redirect targets) |
| `CORS_ORIGINS` | `http://localhost:5173` | A | | Allowed origins, comma separated |
| `LOG_LEVEL` | `INFO` | A | | Log level |
| `PAYPAL_ENV` | `sandbox` | A | | Only `sandbox` is accepted (FR-PP-06) |
| `PAYPAL_CLIENT_ID` | none (required) | A | | Sandbox REST client ID |
| `PAYPAL_CLIENT_SECRET` | none (required) | A | S | Sandbox REST secret |
| `PAYPAL_API_BASE` | `https://api-m.sandbox.paypal.com` | A | | Host must equal the Sandbox API host |
| `PAYPAL_CHECKOUT_BASE` | `https://www.sandbox.paypal.com` | A | | Host must equal the Sandbox checkout host |
| `PAYPAL_WEBHOOK_ID` | empty | A | | Registered webhook ID (S5) |
| `PAYPAL_LOGIN_ENABLED` | `false` | B | | Enable Log in with PayPal (S1) |
| `PAYPAL_LOGIN_REDIRECT_URI` | `${PUBLIC_BASE_URL}/api/v1/paypal/login/callback` | B | | Registered web return URL |
| `PAYMENT_ROUTER` | `single_seller` | A | | `fake`, `single_seller`, `payee_email`, `platform` (see `decisions.md`) |
| `PAYMENT_MODE` | `vault_charge` | A | | `vault_charge` (primary, owner decision Oct 29), `authorize_capture` (fallback) or `capture_only` |
| `BID_PRICING_MODE` | `flat_delivered` | A | | `flat_delivered` (one delivered price per tier, shipping and tax included) or `itemised` |
| `VAULT_TOKEN_KEY` | none (required when `PAYMENT_MODE=vault_charge`) | A | S | 32-byte base64 key that encrypts saved PayPal permissions at rest (AES-256-GCM) |
| `VAULT_CONSENT_VERSION` | `v1` | A | | Names the consent wording a buyer accepted before saving PayPal |
| `VAULT_CHARGE_CONCURRENCY` | `5` | A | | Parallel vault charges per worker |
| `AUTHORIZE_USE_REQUEST_ID` | `true` | A | | Replay authorize with the request ID (S2 result) |
| `PAYPAL_PAYLOAD_LEVEL` | `0` | A | | Highest payload ladder level, 0 to 3 (level 4 unavailable) |
| `PAYPAL_APPROVAL_UI` | `sdk_popup` | A | | `sdk_popup` (primary, S13 passed) or `redirect` (fallback) |
| `PAYPAL_SDK_AUTH` | `client_id` | A | | `client_id` or `client_token` for SDK v6 initialisation (S13) |
| `SHIPMENT_TRACKING_ENABLED` | `true` | A | | Submit trackers to PayPal with Orders v2 `POST .../track` (S12 passed) |
| `PAYPAL_MCP_VERIFICATION` | `paypal_read_subset` | A | | `paypal_read_subset` (local pinned read-only MCP for inspection; FairPool's verification endpoint stays primary) or `fairpool_tool` (S10) |
| `SINGLE_SELLER_EMAIL` | none (required when router is `single_seller`) | A | | The verified sandbox seller email used as payee |
| `SINGLE_SELLER_MERCHANT_ID` | empty | A | | Optional merchant ID for payee verification |
| `ALLOWED_PAYER_COUNTRIES` | `US` | A | | Comma-separated payer countries allowed at approval |
| `PLATFORM_FEE_ENABLED` | `false` | A | | Always false (G9 failed) |
| `DEDUPE_MODE` | `two_keys` | B | | `full`, `two_keys`, `checkout_only` (S1 recorded `two_keys`) |
| `REQUIRE_PAYPAL_LINK` | `false` | B | | Default for new pools; may be true when `DEDUPE_MODE` is not `checkout_only`; login uses scope `openid` only |
| `WEBHOOKS_ENABLED` | `false` | A | | `true` (set when the T03A03 handler ships) processes only the three event types verified in S5, as hints that trigger a GET; never gates approval |
| `MOCK_TOGGLES_ENABLED` | `false` | A | | Enables demo mock toggles and force-award |
| `SEARCH_BACKEND` | `postgres` | B | | `elastic` or `postgres` (S8) |
| `ELASTICSEARCH_URL` | empty | B | | Elasticsearch endpoint when the backend is `elastic` |
| `ELASTICSEARCH_API_KEY` | empty | B | S | Elasticsearch API key |
| `ELASTIC_INFERENCE_ID` | empty | B | | Explicit inference endpoint for the `semantic_text` field |
| `ELASTIC_INDEX_PREFIX` | `fairpool` | B | | Index name prefix |
| `SIMILARITY_CHECK_ENABLED` | `true` | B | | Run the advisory wrong-product check |
| `MCP_ENABLED` | `true` | B | | Mount the FairPool MCP server at `/mcp` |
| `MERCHANT_API_ENABLED` | `true` | B | | Mount the Merchant Agent API at `/merchant-api/v1` |
| `ZAPIER_BRIDGE` | `off` | B | | Documentation switch only (`off` or `managed`); no code reads it |
| `AI_ENABLED` | `true` | B | | When false, intake uses the manual form and quotes go to ops review |
| `GEMINI_API_KEY` | empty | B | S | Gemini API key |
| `AI_MODEL_PARSE` | `gemini-3.5-flash-lite` | B | | Model for INTAKE, QUOTE, RECONCILE (verify the name in Google's Gemini docs) |
| `AI_MODEL_SIM` | `gemini-3.5-flash-lite` | B | | Model for SIM_TEXT |
| `BEACON_MODE` | `demo` | B | | `drand` or `demo` (S6) |
| `DRAND_BASE_URL` | empty | B | | drand HTTP endpoint (S6) |
| `DRAND_CHAIN_HASH` | empty | B | | drand chain hash (S6) |
| `TIMING_PROFILE` | `demo` | A | | `demo` or `prodlike` (section 2) |
| `CAPTURE_BUFFER` | `0` | A | | Capture buffer b (decision: default 0) |
| `CAPTURE_CONCURRENCY` | `5` | A | | Captures in flight per lot |
| `RECONCILER_INTERVAL_S` | `60` | A | | Reconciler period |
| `WORKER_CONCURRENCY` | `4` | A | | Parallel jobs per worker |
| `RATE_LIMIT_ENABLED` | `true` | A | | Enable rate limits (section 3) |

The sandbox-only guard is in `paypal-adapter.md`.

## 2. Timing profiles

Copied into `pools.timeline` at pool creation, then frozen with the rules.

| Field | `demo` | `prodlike` (assumptions) |
|---|---|---|
| Entry window (`close_at - open_at`) | 180 s | 1,200 s |
| `beacon_delay_s` | 10 | 30 |
| `bid_window_s` | 120 | 3,600 |
| `offer_window_s` | 180 | 900 |
| `fund_deadline_s` (from checkout open) | 600 | 172,800 (48 h) |
| `capture_grace_s` | 120 | 3,600 |
| `pending_wait_s` | 120 | 86,400 |
| `max_refill_waves` | 1 | 3 |
| `authorization_age_guard_s` | 216,000 (60 h) | 216,000 (60 h) |

`prodlike` stays inside PayPal's three-day honor period (P1): the 48 h fund deadline plus the 60 h age guard void any uncaptured authorization before day 3, so the design never needs a reauthorization.

## 3. Rate limits

| Scope | Limit |
|---|---|
| `POST /api/v1/auth/login` and `/register` | 10 per minute per IP |
| `POST /api/v1/intake/messages` | 20 per minute per user |
| `POST /api/v1/pools/{pool_id}/entries` | 10 per minute per user |
| `/agent/v1/*` and `/mcp` | 60 per minute per token |
| `/merchant-api/v1/*` | 120 per minute per key |
| `POST /api/v1/offers/{buyer_order_id}/approved` and `/cancelled` | 30 per minute per user |
| `GET .../verification` (live PayPal GETs) | 10 per minute per merchant |
| `POST /webhooks/paypal` | 300 per minute per IP |
| Everything else | 120 per minute per IP |

## 4. Error codes

Response shape in `api.md`. Codes are UPPER_SNAKE.

| Code | HTTP | Meaning |
|---|---|---|
| VALIDATION_ERROR | 422 | Body or parameters invalid; `details` lists fields |
| UNAUTHENTICATED | 401 | No valid session or token |
| FORBIDDEN | 403 | Wrong role or not the owner |
| NOT_FOUND | 404 | Unknown resource |
| RATE_LIMITED | 429 | Over the limit; `Retry-After` set |
| IDEMPOTENCY_KEY_REQUIRED | 400 | Missing `Idempotency-Key` |
| IDEMPOTENCY_CONFLICT | 409 | Same key, different body |
| FEATURE_DISABLED | 403 | Helper or toggle not enabled |
| POOL_NOT_OPEN | 409 | Pool is not OPEN |
| POOL_CLOSED | 409 | The entry window has closed |
| PAYPAL_LINK_REQUIRED | 403 | The pool needs a linked PayPal account |
| PAYPAL_LINK_CONFLICT | 409 | Account key already linked to another user, or relink blocked by active entries |
| REQUEST_INVALID | 422 | Confirmed request fails pool validation |
| NO_MATCHING_POOL | 404 | No open pool matches |
| DELEGATION_INVALID | 401 | Agent token unknown, expired or revoked |
| DELEGATION_CAP_EXCEEDED | 403 | Agent cap above the delegation limit |
| API_KEY_INVALID | 401 | Merchant API key unknown, revoked or malformed |
| API_KEY_SCOPE | 403 | The key lacks the scope for this operation |
| LOT_NOT_FUNDED | 409 | Fulfillment, shipments or manifest requested before the lot is FUNDED |
| VAULT_REQUIRED | 409 | The entry has no active saved PayPal permission |
| VAULT_SETUP_EXPIRED | 409 | The saving step was not completed in time; start again |
| SHIPMENT_INVALID | 422 | A shipment row is invalid (reported per row) |
| BID_FORBIDDEN | 403 | Not your bid or lot |
| LOT_NOT_BIDDING | 409 | Lot not in BIDDING |
| BID_WINDOW_CLOSED | 409 | Past the bid deadline |
| BID_UNCONFIRMED | 409 | Fields not confirmed by the merchant |
| OFFER_EXPIRED | 409 | Offer window ended |
| SEAT_NOT_VALID | 409 | The seat was released |
| ORDER_STATE_INVALID | 409 | Action not allowed in the order's state |
| PAYPAL_UNAVAILABLE | 502 | PayPal call failed after retries |
| INTERNAL_ERROR | 500 | Unexpected; details only in logs |

## 5. Reason codes

**Buyer order rejected** (stored in `buyer_orders.reject_reason`): `DUPLICATE_PAYER`, `WRONG_COUNTRY`, `CURRENCY_MISMATCH`, `AMOUNT_MISMATCH`, `PAYEE_MISMATCH`, `PAYER_MISMATCH`, `STATUS_NOT_APPROVED`.

**Entry rejected at close** (`pool_entries.reject_reason`): `LINK_INACTIVE`, `REQUEST_INVALID`.

**Bid rejected** (`bids.reject_reason`): `R1_SCHEMA`, `R1_LATE`, `R1_UNCONFIRMED`, `R2_MERCHANT_INELIGIBLE`, `R3_PRODUCT_MISMATCH`, `R3_CONDITION_MISMATCH`, `R3_BUNDLE_MISMATCH`, `R4_CAPACITY`, `R5_DELIVERY`, `R5_RETURNS`, `R5_TAX_COVERAGE`, `R6_VALIDITY`, `R7_AI_BLOCKING`, `R8_NO_FEASIBLE_TIER`, `R8_INFEASIBLE`, `R9_CAPACITY_EXHAUSTED`.

**Void sources** (`buyer_orders.void_source`): `lot_failing`, `buyer_withdraw`, `age_guard`, `paypal_expired`.
