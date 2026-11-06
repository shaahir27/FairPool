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
| POST | /api/v1/auth/paypal/start | B | public | Begin browser-bound PayPal signup |
| GET | /api/v1/auth/paypal/callback | B | public | Consume signup state and verify PayPal identity |
| GET | /api/v1/auth/paypal/status | B | public | Read this browser's signup progress |
| POST | /api/v1/auth/login | B | public | Start session |
| POST | /api/v1/auth/logout | B | session | End session |
| GET | /api/v1/me | B | session | Current user, PayPal link state, unread notifications |
| GET | /api/v1/me/addresses | B | session | List this buyer's saved delivery addresses |
| POST | /api/v1/me/addresses | B | session | Save a delivery address |
| PUT | /api/v1/me/addresses/{address_id} | B | session | Edit an owned delivery address or make it default |
| DELETE | /api/v1/me/addresses/{address_id} | B | session | Remove an owned saved address |
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
| GET | /api/v1/merchant/profile | B | merchant | CR-10: read the signed-in merchant's stored profile, payee and attestations; 404 if absent |
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

### PayPal-first signup (CR-6 draft, owner request 2026-11-02)

`POST /api/v1/auth/paypal/start` accepts no body, requires the configured frontend
Origin, returns `{authorize_url}` and sets an HttpOnly, SameSite=Lax browser cookie.
The scopes it asks for are the attribute set in `paypal-adapter.md` CR-7; signed-in
linking stays `openid`. Repeated starts from one browser reuse that browser's single
pending attempt rather than adding another. The signup callback is
`${PUBLIC_BASE_URL}/api/v1/auth/paypal/callback` and must be registered with PayPal.
The callback verifies browser binding, single-use state and database-clock expiry
before exchanging the code. It redirects to `/register/connected` on success or
`/register?reason=cancelled|expired|unavailable|account_exists` on failure. Codes and
identifiers never reach the frontend. `GET .../status` returns
`{enabled, status: not_started|pending|ready|expired|registered}` without an identifier.
A `registered` answer means that browser's PayPal proof already produced an account, so
no form is offered again.

`POST /api/v1/auth/register` requires a ready browser-bound signup attempt and the
configured frontend Origin. Body: `{email,password,password_confirm,display_name}`.
Passwords must match. Buyer creation, PayPal linking, signup consumption and session
creation are atomic; response `{user_id,email,csrf_token}` plus the session cookie.
Previously linked PayPal identifiers cannot enroll another user, even after unlink.
Duplicate control is the PayPal account, never the device or the live session: a browser
that already holds a session can still begin a signup, so a second person on one shared
device enrolls their own PayPal account (owner decision 2026-11-02, which replaced an
earlier session-holder refusal). Existing email/password login stays available. Login
grants no payment permission and does not establish one unique human or account-verified
status.

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
    "no_charge": "Nothing is charged now. A merchant and an exact price are confirmed first, you are never charged above the maximum you set here, and any payment follows your own approval of that offer.",
    "lots_may_differ": "Separate lots in this pool can end with different winning merchants and prices."
  }
}
```

`POST /api/v1/intake/confirm` `{"proposal_id": "uuid"}` returns `201 {"confirmed_request_id": "uuid", "canonical_request": {...}}`. `POST /api/v1/intake/manual` takes `{"pool_id", "delivery": {"region"}, "required_by", "max_total_cents", "firm", "preferences"}` and returns the same shape.

The manual form is the deterministic half of intake and ships early (Phase 3, CR-3): it validates product and variant against the pool's frozen template, condition, a quantity of exactly one unit, `USD` only, a delivery region inside a frozen zone, `max_total_cents` as an integer-cents value inside the pool's cap band, absolute `required_by` dates, and only the firm terms the template supports. An unsupported firm term or a non-integer money value is a `422 VALIDATION_ERROR`, never a guess. Each confirmation writes an immutable `confirmed_requests` row bound to the confirming user, the pool and its frozen `rules_hash`; the full AI intake pipeline stays in Phase 4 (`T04B01`) and nothing about this endpoint depends on it.

### Account link

`GET /api/v1/paypal/login/start` requires an authenticated session and returns the authorize URL only. It writes a single-use `oauth_states` row with a high-entropy `state` and `nonce`, a database-clock expiry of `OAUTH_STATE_TTL_S` and the **initiating session id**. `GET /api/v1/paypal/login/callback` rejects a missing, expired, already-consumed or cross-session `state` before it exchanges a code; a consumed row is never reused. `error=access_denied` from the provider is a `400` decline with no row written.

On success the provider account identifier is stored only as its HMAC with `HMAC_KEY` (`paypal_links.paypal_account_key`); the raw `user_id`/`sub` and the bearer token are never persisted, logged or returned. Under the recorded S1 outcome `DEDUPE_MODE=two_keys`, the login key and the checkout `payer_id` key are two separate identifiers, each deduplicated on its own, with no equality requirement and no prefix stripping; `full` additionally requires them to be equal and stays unavailable because equivalence was never proved, and `checkout_only` keeps the weaker disclosure wording. Relinking cannot evade participation: link, unlink and join serialise on a user-then-pool lock order, and `DELETE /api/v1/paypal/link` is blocked while an entry exists. Login identity and vault permissions are separate resources: unlinking never deletes a saved permission and deleting a permission never unlinks an account.

### Entry

CR-10 merchant profile amendment: `GET /api/v1/merchant/profile` returns the
signed-in merchant's own `MerchantProfileResponse`, or `404 NOT_FOUND` when none
exists; a non-merchant receives `403 FORBIDDEN`. GET and POST profile responses
add optional nullable `payee_email` and `paypal_merchant_id` to the previously
documented fields. These are private configuration reads, not public merchant data.

CR-10 admin read amendment: `GET /api/v1/admin/lots/{lot_id}` adds optional nullable
`pool_title`, `product_title` and `merchant_display_name`. These are the pool title,
published product title and awarded merchant display name, not buyer details. The
existing admin guard, states and abort permissions do not change.

CR-10 (owner authorized 2026-11-05): `GET /api/v1/me/entries` additionally returns
optional nullable `pool_title`, `pool_status` and `product`, plus `labels` (default
empty array), on each item. Labels use the same lot-derived simulation/fallback
registry as checkout; a simulated pool without a lot is labeled SIMULATED. `product` uses the same
`{title, variant, condition, bundle_contents}` shape as the offer disclosure.
`GET /api/v1/me/orders` additionally returns optional nullable `pool_id`, `pool_title`,
`product`, `merchant` (`{display_name}`), `terms` (`{delivery_sla_days, returns_days}`),
`placed_at` and `capture_id`, plus `labels` (default empty array). Product and terms
come from the published pool template, merchant display from the award's merchant,
and `capture_id` from the latest stored capture row by `(created_at, id)` descending.
The capture reference is an identifier, never evidence of a completed payment.
The core entry list includes its latest buyer order across terminal and active states
so declined, released and completed entries remain distinguishable in history. This
does not change agent API live-offer filtering or payment eligibility.
Both lists remain strictly owner-scoped. These additive fields let the workspace
render useful commerce records without fetching every order or pool individually.

`POST /api/v1/pools/{pool_id}/entries` body `{"confirmed_request_id": "uuid"}`; `Idempotency-Key` required; returns `201` for a new entry or `200` for an existing one:

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

Join rules (CR-3): the request is fetched by id **and owner** (a row belonging to another buyer is `404 NOT_FOUND`, the same answer as an unknown id, so the endpoint leaks no existence information); its stored `rules_hash` must equal the pool's frozen hash or the call is `409 RULES_MISMATCH`; the canonical request is re-validated by the same deterministic validator before anything is written; the pool must be `OPEN` and the database wall clock must still be strictly before `close_at` **after** the pool lock is held (`409 POOL_NOT_OPEN` / `409 POOL_CLOSED`). On success the entry, its salt, commitment, Ed25519 receipt and audit row are written in one transaction, and the receipt is signed over the same database timestamp that is stored, so a signature always verifies against the row it describes.

A confirmed request that has already been consumed replays to the entry it created — `200` with that entry's original receipt — including after the cutoff, and it never creates a second entry, never reactivates a withdrawn one and never overwrites a cap, request or receipt. Withdrawal is `DELETE /api/v1/pools/{pool_id}/entries/me`, owner-only, legal only while the pool is `OPEN` and before `close_at`; it serialises against `pool.close` under the same pool lock, and a vault permission that arrives afterwards is quarantined for deletion rather than activated.

`GET /api/v1/pools/{pool_id}/entries/me` returns the caller's own entry: `entry_id`, `entry_status`, the `allocation` and `offer` views when they exist, the vault status and label, and **`receipt`** (CR-9) — the same signed receipt the join issued, rebuilt from the stored `entry_receipts` row and returned as the exact bytes that were signed, so the timestamp the signature covers is never re-serialised. This is what makes the proof durable rather than a one-time response: a buyer who reloads in another browser still gets what they can keep, and a copy they download still verifies against `GET /api/v1/public/keys`. A withdrawn entry keeps its receipt, because the row is the record that the entry existed. If that row is absent — only a data-integrity fault can cause it, because the join writes it in the same transaction — the status read still answers and `receipt` is `null`, so a broken proof cannot take the buyer's own entry screen down with it. The read is owner-scoped and answers the same `404 NOT_FOUND` when the caller has no entry in the pool as for an unknown pool, so it leaks no existence information.

Vault mode (`vault-charge.md`): `POST /api/v1/entries/{entry_id}/vault` body `{"consent_version": "v1", "cap_cents": 60000}` returns `{"approve_url": "https://...", "consent_version": "v1"}`; it fails with `VAULT_SETUP_EXPIRED` if started too long ago. The entry status adds `vault_status` and `vault_label` (last four characters) and never a token. `GET /api/v1/entries/{entry_id}/vault/return` is an untrusted browser redirect: the server looks up its own setup token, exchanges it, and redirects `302` to the entry page. Until `T05A01` ships the real save path, `VAULT_REAL_SAVE_ENABLED=false` makes `POST .../vault` return `403 FEATURE_DISABLED` — a consented-but-unsaved permission must not be able to exist — and the entry status reports `vault_status` `SETUP_PENDING` only for the fake path used by tests and simulation (DEP-5).

`GET /api/v1/public/keys` returns the receipt signing public key (base64url Ed25519) and arrives with Phase 3 so a buyer can verify a receipt; `GET /api/v1/public/pools/{pool_id}/audit` publishes `rules_hash`, `rules_document`, `pool_status`, `entries_root`, `entries_count`, the sorted `commitments` and `audit_checkpoints` once the pool is closed. Both are public, carry no personal data, no salts, no caps, and arrive in Phase 3; the `lots`, `beacon`, `seed_hex` and `award` fields of the same endpoint fill in with Phase 4 (`T04A06`) when that data exists.

`GET /api/v1/pools/{pool_id}/events` (SSE) is public and emits only `pool_status`, `lot_status` and `tick`, computed with short read transactions on the database clock; no transaction and no lock is held for the life of a stream.

`GET /api/v1/entries/{entry_id}/status`:

```json
{
  "entry_id": "uuid",
  "entry_status": "ELIGIBLE",
  "allocation": {"status": "SEATED", "zone_id": "US-EAST", "rank": 2, "lot_id": "uuid", "waitlist_position": null},
  "offer": {"buyer_order_id": "uuid", "status": "OFFERED", "offer_expires_at": "iso"}
}
```

F6 adds two optional fields to `AllocationView`, populated on `GET /api/v1/me/entries` where both rows are already loaded: `cap_cents` is this buyer's own confirmed maximum total and `item_cents` is the awarded delivered price, which the public audit page publishes for the lot anyway. They exist because a buyer who is `PRICED_OUT` cannot otherwise tell a wrong cap from a real one -- the cap is the number the intake AI proposed and the buyer confirmed, so a misread value silently costs them their seat with nothing to appeal against. Other surfaces that reuse `AllocationView` (`/entries/{id}/status`, the agent entry reads) leave both `null`: they do not load the award, and an invented or re-queried number here would be worse than an absent one.

### Public audit

`GET /api/v1/public/pools/{pool_id}/audit` returns `rules_hash`, `rules_document`, `pool_status`, `entries_root`, `entries_count`, `commitments` (sorted list, after close), `beacon`, `seed_hex`, `seed_is_demo`, `lots` (each with `lot_id`, `zone_id`, `lot_order`, `seats`, `status`, `rank_range`, `bids_root` and `bids_count` once bidding has closed, and, after award, `award` with merchant display name, `item_cents`, `tier_index`, `award_hash`, `valid_until`), `audit_checkpoints` (action plus hash, covering the pool, its lots and their bids), and `checkpoint` (CR-11). No personal data, no salts, no caps, no bid contents.

CR-11 reveal gate, two windows for two different leaks. `seed_hex` and `beacon` are published only once no lot of the pool is still `PLANNED` or `BIDDING`: `tiebreak_hash` is hash(seed, lot, merchant), so a seed visible while bidding is possible hands every merchant its exact tie-break position before it prices anything. `audit_checkpoints` and `checkpoint` wait only while some lot is `BIDDING`, because the bid rows in the chain disclose how many bids a lot received and when -- and those rows cannot exist before bidding opens, so the close subset that T04A06 requires stays published while lots are `PLANNED`. `commitments`, `entries_root` and `lots` keep their existing after-close gate: they are what the draw is computed from, not what it depends on.

CR-11 `checkpoint`: a flat object `{"v": 1, "pool_id", "entries_root", "bids_roots", "head_seq", "head_hash", "signature"}`, where `bids_roots` maps `lot_id` to that lot's `bids_root` (null while bidding is open), `head_seq`/`head_hash` are the last row of this pool's audit chain across the `pool`, `lot` and `bid` subjects, and `signature` is the Ed25519 signature over `canonical_json` of the other six keys using the receipt signing key served at `GET /api/v1/public/keys`. A verifier drops `signature`, canonicalises what remains and calls `verify_ed25519`. It is computed at read time and stored nowhere, so it cannot drift from the rows it describes; with no signing context available the field is `null` rather than an unverifiable claim.

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
  "offer_started_at": "iso",
  "server_now": "iso",
  "pool_id": "uuid",
  "pool_title": "27-inch 4K monitor",
  "notices": {
    "hold": "PayPal places a hold for the total shown only after you approve. The hold is released if this lot does not reach its minimum.",
    "lots_may_differ": "Separate lots in this pool can end with different winning merchants and prices.",
    "fallback": null
  }
}
```

`offer_started_at` is the moment the offer was created, `server_now` is the database clock at read time, and together they let a client render a countdown and a progress ring from the server's clock instead of the device's (I15); the countdown is presentation only and every handler still re-checks `offer_expires_at`. `pool_id` and `pool_title` let the screen link to the pool's published rules. All four are optional additions: a client that ignores them behaves exactly as before.

**The `hold` notice is the stamped mode's sentence, not one fixed string** (CR-8; `Q-2026-11-01-17`). The example above is `PAYMENT_MODE=authorize_capture` or `capture_only`, where a hold really is placed. On a lot stamped `vault_charge` the key carries `vault-charge.md` section 1's truth instead, because that mode reserves nothing and PayPal's approval screen shows no amount: `"Nothing is charged or held now, and PayPal's approval screen shows no amount. FairPool charges this saved account once, after the lot is awarded, for the final price if it is at or below your maximum."` The offer endpoint may branch because the mode is on the lot from award (N8); the intake card above may not, because it is read before any lot exists, which is why its `no_charge` sentence is written mode-neutral. A client renders what the API returns and never re-words it (FR-UI-08, I13).

`notices.fallback` is a non-null string whenever `PAYMENT_ROUTER=single_seller` or `PAYMENT_MODE=capture_only` applies (DEP-4), for example `"Sandbox demo: one test seller stands in for the winning merchant."`.

`POST /api/v1/offers/{buyer_order_id}/continue` body `{"shipping": {"name", "line1", "line2", "city", "region", "postal_code", "country_code"}}` (the address is always required because fulfillment needs it; it is stored encrypted, N14, and is sent to PayPal only when `PAYPAL_PAYLOAD_LEVEL >= 3`); returns `{"paypal_order_id": "...", "approve_url": "https://www.sandbox.paypal.com/...", "approval_ui": "sdk_popup" | "redirect"}`. The browser sends **no amounts**. The server takes them from the award snapshot (I3).

`GET /api/v1/checkout/return?token=<paypal_order_id>&PayerID=<id>`: the query parameters are untrusted hints. The server looks up the order by `token`, fetches it from PayPal, runs the FR-CK-05 checks and redirects `302` to `{FRONTEND_BASE_URL}/orders/{buyer_order_id}`. `GET /api/v1/checkout/cancel` moves ORDER_CREATED to DECLINED (BO-22) and redirects the same way.

`GET /api/v1/orders/{buyer_order_id}`: `{"buyer_order_id", "status", "lot_status", "total_cents", "history": [{"status", "at"}], "paypal": {"authorization_status": "...|null", "capture_status": "...|null", "refund_status": "...|null"}, "labels": ["SANDBOX", "FALLBACK: single stand-in seller"], "pool_id": "uuid|null", "lot_id": "uuid|null", "placed_at": "iso|null", "reject_reason": "PAYEE_MISMATCH|null", "receipt": {"payload": {"commitment", "entry_id", "pool_id", "received_at", "v"}, "salt_hex", "request_hash", "signature"}|null}`.

The five later keys are optional additions. `reject_reason` is one of the seven buyer-order codes in `config-and-errors.md` section 5 and is present whenever the order was rejected, so the redirect path can explain a failure it used to swallow. `receipt` is the buyer's own entry receipt, returned in the same typed shape as `POST /api/v1/entries`; it is shown only to the order's owner and is what makes the proof verifiable against `/api/v1/public/keys`. `history[].at` and the three `paypal.*_status` fields are the lot-history timestamps and provider references the screen needs, and both are already returned (CR-8; `Q-2026-11-02-22`); a screen must still read them from here rather than compose them in the browser (I4, I13). **A verified net result is not returned and is not contracted**: `history` and the `paypal` block together imply it, but an explicit per-order figure needs a ledger aggregate no Phase 6 task names, so it is deferred to the merchant fulfillment path rather than computed on the client or invented as a response field.

### Webhook

`POST /webhooks/paypal` takes the raw body and PayPal's transmission headers. Verified or duplicate events return `200 {}`. An unverified request returns `400` and is never processed. See `paypal-adapter.md`.

### Admin helpers

- `POST /api/v1/admin/lots/{lot_id}/force-award` body `{"merchant_id": "uuid", "item_cents": 47000, "tier_index": 0, "moq": 2, "valid_minutes": 60}` writes an award as `lot.award` would, for test and demo only. Enabled only when `APP_ENV` is `local` or `test` or `MOCK_TOGGLES_ENABLED` is true; otherwise `403 FEATURE_DISABLED`.

It answers `201 {"lot_id", "award": {"award_hash", "item_cents", "moq", "tier_index", "valid_until"}, "lot_status": "AWARDED"}`. In flat delivered mode the awarded total is `item_cents` per seat, so the body carries no breakdown (`flat-delivered-bids.md`). The helper applies the whitelisted `admin.force_award` transition; it never writes a status directly, and every step is audited.

`POST /api/v1/admin/reconciler/run` takes no body and returns `202 {"enqueued": <n>}`, the number of stale orders it re-queued. It re-enqueues only existing triggers: `order.authorize` for `APPROVED`, `offer.expire` for an expired offer. It never invents a transition.

`POST /api/v1/offers/{buyer_order_id}/cancelled` takes no body and returns the same shape as `/approved`: `{"buyer_order_id", "status": "DECLINED", "reason": null}`. It is a hint like the SDK's `onCancel`; a second call returns the same result.

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

`POST /api/v1/merchant/profile` creates or updates the merchant row and returns exactly the row's own fields: `{"merchant_id": "uuid", "display_name": "string", "onboarding_status": "NONE|PENDING|COMPLETE|DEMO", "attestations": {"inventory_reserved": {"at": "iso", "accepted": true}, "map_compliance": {"at": "iso", "accepted": true}, "delivery_terms_accurate": {"at": "iso", "accepted": true}}}` (CR-8; `Q-2026-11-02-23`). The body is `{"display_name", "payee_email": "string|null", "paypal_merchant_id": "string|null", "attestations": {...}}`; an attestation key outside the three named in `db-schema.md` is a `422 VALIDATION_ERROR`, and an attestation already accepted keeps its original `at` timestamp rather than being re-stamped. `onboarding_status` is set when the row is created (`DEMO` under `PAYMENT_ROUTER=single_seller`, otherwise `NONE`) and is not recomputed by this endpoint: no Phase 5 or Phase 6 task ships a merchant review queue, so nothing moves it afterwards. What a later gate can check is the attestation map itself, and that is what "the merchant's attestations are accepted" means for the API-key endpoints below — three `accepted: true` entries, read from the row, not a status this endpoint cannot set.

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

## CR-7: owner-requested delivery address book and signup prefill

Signup requests the documented attribute set, including the URI-form account scope:
`openid profile email address https://uri.paypal.com/services/paypalattributes`
(`paypal-adapter.md` CR-7). Dropping that URI scope is what made the prefill never
arrive. `GET /api/v1/auth/paypal/status` adds nullable `prefill`, available only
to the browser with a ready, unexpired signup: `{email, display_name, address}`.
Address is partial and editable; missing provider fields require manual entry.
`POST /api/v1/auth/register` adds optional `delivery_address`; the buyer UI collects
it in a separate step, and account, link, session and first default address save
atomically. Passwords are never prefilled.

DeliveryAddress: `{name, line1, line2, city, region, postal_code, country_code}`.
All fields are strings, line2 defaults to empty, country_code is two uppercase
letters, and required fields cannot be blank. Bounds: name/city 120, line1/line2
200, region 100, postal_code 32.

Saved-address GET returns `{addresses:[{id,address,is_default}]}`. POST and PUT
accept `{address:DeliveryAddress,is_default:false}` and return `{id,address,is_default}`.
DELETE returns 204. These session endpoints require the buyer role; every write
requires CSRF. IDs belonging to another buyer return NOT_FOUND. Reads and writes
return Cache-Control: no-store. Only the owner receives address plaintext; logs
and audits contain no address fields. Deletes choose a remaining default when
necessary. No address-book edit alters an existing order's shipping snapshot.
