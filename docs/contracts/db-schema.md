# Contract: database schema

Migration `backend/migrations/versions/0001_initial.py` implements this file exactly (task T01A01). `alembic check` must show no difference between the SQLAlchemy models and the migration, and a test (`tests/unit/test_schema_contract.py`) compares the enum table below with `state-machines.md`.

## Conventions

- Primary keys are `uuid` (v4, generated in the application, BD-09) unless stated. Names are snake_case plural.
- Times are `timestamptz` (UTC). Deadlines and windows use the database clock `now()` (I15, BD-08).
- Money is `bigint` cents with a `currency char(3) CHECK (currency = 'USD')` where a currency is stored (BD-14).
- `jsonb` columns that hold snapshots are written once and treated as immutable; their shapes are in the "JSON shapes" section.
- Every table has `created_at timestamptz NOT NULL DEFAULT now()` unless stated.
- PostgreSQL extensions required by migration `0001`: `citext`, `pg_trgm`.
- Enums are PostgreSQL enum types named exactly as in the first column below. Values are UPPER_SNAKE unless the value is a lowercase word shown in the table.

## Enums

The first five rows are compared by test with the `states:` lists in `state-machines.md`; keep them in sync.

| Enum | Values |
|---|---|
| pool_status | DRAFT, PUBLISHED, OPEN, CLOSED, SEEDED, ALLOCATED, RUNNING, COMPLETED, CANCELLED |
| lot_status | PLANNED, BIDDING, BID_CLOSED, AWARDED, CHECKOUT_OPEN, FUNDING, FUNDED, CLOSED, FAILING, FAILED_CLOSED, CANCELLED |
| buyer_order_status | OFFERED, ORDER_CREATED, APPROVED, AUTHORIZING, AUTHORIZED, CAPTURING, CAPTURE_PENDING, CAPTURED, REFUNDING, EXPIRED, REJECTED, AUTH_FAILED, CAPTURE_FAILED, VOIDED, REFUNDED, DECLINED |
| bid_status | DRAFT, PROPOSED, CONFIRMED, FLAGGED, REJECTED, ELIGIBLE, AWARDED, LOST |
| entry_status | SUBMITTED, ELIGIBLE, REJECTED, WITHDRAWN |
| allocation_status | SEATED, WAITLISTED, PRICED_OUT |
| user_role | buyer, merchant, admin |
| pool_mode | LIVE_SANDBOX, SIMULATION |
| submitted_via | human, agent |
| item_condition | NEW, REFURBISHED, OPEN_BOX |
| payment_router | fake, single_seller, payee_email, platform |
| payment_mode | authorize_capture, capture_only, vault_charge |
| vault_status | SETUP_PENDING, ACTIVE, DELETED, FAILED |
| merchant_onboarding | NONE, PENDING, COMPLETE, DEMO |
| flag_severity | BLOCKING, WARNING |
| flag_code | BUNDLE_MISMATCH, CONDITION_MISMATCH, DELIVERY_CONFLICT, HIDDEN_FEE, QUANTITY_CONFLICT, RETURN_CONFLICT, LOW_SIMILARITY, OTHER |
| ledger_kind | AUTH_CREATED, AUTH_VOIDED, CAPTURE_COMPLETED, CAPTURE_PENDING, CAPTURE_DECLINED, REFUND_COMPLETED, REFUND_PENDING |
| ledger_source | api, webhook, reconciler |
| webhook_status | RECEIVED, PROCESSED, DEAD_LETTER, REJECTED |
| job_status | PENDING, RUNNING, DONE, FAILED |
| ai_task | INTAKE, QUOTE, RECONCILE, SIM_TEXT |

Active buyer-order statuses (used by I8 and the partial unique index; see N1): OFFERED, ORDER_CREATED, APPROVED, AUTHORIZING, AUTHORIZED, CAPTURING, CAPTURE_PENDING, CAPTURED, REFUNDING.

## Tables

### Identity

**users**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| email | citext | UNIQUE NOT NULL |
| password_hash | text | argon2id (BD-10) |
| role | user_role | default `buyer` |
| display_name | text | NOT NULL |

**sessions**: `id uuid PK`, `user_id uuid FK users`, `csrf_token text NOT NULL`, `expires_at timestamptz NOT NULL`, `revoked_at timestamptz NULL`.

**oauth_states**: `state text PK`, `nonce text NOT NULL`, `user_id uuid FK users`, `expires_at timestamptz NOT NULL`.

**vault_tokens** (used when `PAYMENT_MODE=vault_charge`; one row per saved PayPal permission)

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| entry_id | uuid FK pool_entries | one active token per entry |
| user_id | uuid FK users | |
| status | vault_status | default SETUP_PENDING; the stored value follows a GET, never a webhook alone |
| token_ciphertext | bytea NULL | AES-256-GCM of the PayPal payment token ID with `VAULT_TOKEN_KEY`; NULL until exchanged and after deletion |
| token_nonce | bytea NULL | per-row nonce |
| token_label | text NULL | last four characters only, for display |
| cap_cents | int | the buyer's cap at consent time (FairPool-enforced) |
| consent_version | text | `VAULT_CONSENT_VERSION` at consent |
| consent_text_sha256 | char(64) | hash of the exact rendered consent text |
| consented_at | timestamptz | |
| deleted_at | timestamptz NULL | |
| created_at | timestamptz | default now() |

The ciphertext column is never selected by list queries, logged, or returned by any API (`vault-charge.md` section 5).

**paypal_links**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK users | |
| paypal_account_key | text | HMAC-SHA256 hex of the PayPal account ID with `HMAC_KEY` (BD-12); the raw ID is never stored |
| linked_at | timestamptz | default now() |
| revoked_at | timestamptz NULL | |

Indexes: `UNIQUE (user_id) WHERE revoked_at IS NULL`; `UNIQUE (paypal_account_key) WHERE revoked_at IS NULL`.

**delegations** (agent API): `id uuid PK`, `user_id uuid FK`, `token_hash text UNIQUE NOT NULL`, `scope jsonb NOT NULL` (`{"pool_ids": [uuid], "category": string or null}`), `max_cap_cents bigint NOT NULL`, `expires_at timestamptz NOT NULL`, `revoked_at timestamptz NULL`.

### Catalog and pools

**catalog_products**: `id uuid PK`, `product_key text UNIQUE NOT NULL`, `name text`, `variant text`, `description text`, `image_url text NULL`, `reference_price_cents bigint NULL`, `source text default 'seed'`.

**pools**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| mode | pool_mode | immutable once status leaves DRAFT (trigger) |
| status | pool_status | default DRAFT |
| title | text | |
| template | jsonb | shape below |
| lot_plan | jsonb | shape below |
| timeline | jsonb | shape below |
| require_paypal_link | boolean | default true |
| rule_version | text | for example `allocation_v1` |
| rules_hash | char(64) NULL | set at publish (fairness contract) |
| beacon | jsonb NULL | announced round at publish; fetched value after seeding |
| seed_hex | char(64) NULL | set at SEEDED |
| seed_is_demo | boolean | default false |
| entries_root | char(64) NULL | set at close |
| entries_count | integer NULL | set at close |
| published_at, closed_at | timestamptz NULL | |
| created_by | uuid FK users | |
| search_text | text | derived at publish from title, variant, condition, bundle contents and zone regions; `GIN (search_text gin_trgm_ops)` index serves the Postgres search fallback (INT-1) |

**pool_entries**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| pool_id | uuid FK pools | |
| user_id | uuid FK users | |
| paypal_account_key | text NULL | copied from the active link at join; NULL when `DEDUPE_MODE=checkout_only` |
| canonical_request | jsonb | shape below; immutable |
| request_hash | char(64) | SHA-256 of canonical JSON |
| cap_cents | bigint | equals `max_total_cents` in the request |
| zone_id | text | |
| status | entry_status | default SUBMITTED |
| reject_reason | text NULL | |
| submitted_via | submitted_via | |
| delegation_id | uuid NULL FK delegations | |
| received_at | timestamptz | default now() (database clock) |
| synthetic | boolean | default false |

Indexes: `UNIQUE (pool_id, user_id)`; `UNIQUE (pool_id, paypal_account_key) WHERE paypal_account_key IS NOT NULL`; `(pool_id, status)`.

**entry_receipts**: `entry_id uuid PK FK pool_entries`, `commitment char(64) NOT NULL`, `salt char(64) NOT NULL`, `signature text NOT NULL`, `signed_at timestamptz NOT NULL`.

### Allocation and lots

**lots**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| pool_id | uuid FK | |
| zone_id | text | |
| lot_index | integer | position within the zone |
| lot_order | integer | position within the pool (N7) |
| seats | integer | CHECK seats > 0 |
| min_seats | integer | |
| status | lot_status | default PLANNED |
| payment_router | payment_router NULL | stamped at award (N8) |
| payment_mode | payment_mode NULL | stamped at award (N8) |
| award_id | uuid NULL FK awards | |
| bid_open_at, bid_close_at | timestamptz | |
| fund_deadline_at, refill_cutoff_at | timestamptz NULL | set at checkout open |
| funded_at | timestamptz NULL | |

Indexes: `UNIQUE (pool_id, zone_id, lot_index)`; `UNIQUE (pool_id, lot_order)`.

**allocations**: `id uuid PK`, `pool_id uuid FK`, `entry_id uuid FK pool_entries`, `zone_id text`, `rank integer NOT NULL` (1-based within zone), `rank_hash char(64) NOT NULL`, `lot_id uuid NULL FK lots` (NULL while WAITLISTED), `status allocation_status`.
Indexes: `UNIQUE (pool_id, entry_id)`; `UNIQUE (pool_id, zone_id, rank)`; `(lot_id, status)`.

### Merchants and auction

**merchants**: `id uuid PK`, `user_id uuid UNIQUE FK users`, `display_name text`, `onboarding_status merchant_onboarding default NONE`, `payee_email text NULL`, `paypal_merchant_id text NULL`, `attestations jsonb NOT NULL default '{}'`.

**bids**: `id uuid PK`, `lot_id uuid FK`, `merchant_id uuid FK`, `status bid_status default DRAFT`, `current_revision integer default 0`, `reject_reason text NULL` (an R-prefixed reason code), `UNIQUE (lot_id, merchant_id)` (N10).

**bid_revisions**: `id uuid PK`, `bid_id uuid FK`, `revision integer`, `structured jsonb NOT NULL` (shape below), `quote_text text NULL`, `notes text NULL`, `confirmed_at timestamptz NULL`, `receipt_hash char(64) NOT NULL`, `receipt_signature text NOT NULL`, `UNIQUE (bid_id, revision)`.

**bid_flags**: `id uuid PK`, `bid_revision_id uuid FK`, `ai_run_id uuid FK ai_runs`, `code flag_code`, `severity flag_severity`, `field text`, `evidence text` (at most 200 characters).

**awards** (immutable; trigger blocks UPDATE and DELETE)

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| lot_id | uuid UNIQUE FK lots | |
| bid_revision_id | uuid FK | |
| merchant_id | uuid FK | |
| tier_index | integer | |
| item_cents | bigint | |
| moq | integer | |
| totals | jsonb | map of entry_id to `{item_cents, shipping_cents, tax_cents, total_cents}` |
| valid_until | timestamptz | |
| rule_version | text | `ranking_v1` |
| award_hash | char(64) | |

### Checkout and PayPal mirrors

**buyer_orders**

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| lot_id | uuid FK | |
| entry_id | uuid FK pool_entries | |
| status | buyer_order_status | default OFFERED |
| current_attempt | integer | default 0 (N9) |
| offer_expires_at | timestamptz | |
| total_cents | bigint | from the award |
| breakdown | jsonb | `{item_cents, shipping_cents, tax_cents}` |
| shipping_enc | bytea NULL | Fernet-encrypted address (N14, BD-11) |
| seat_locked_until | timestamptz NULL | set while AUTHORIZING |
| reject_reason | text NULL | |
| void_source | text NULL | `lot_failing`, `buyer_withdraw`, `age_guard`, `paypal_expired` |
| updated_at | timestamptz | |

Index: `UNIQUE (entry_id) WHERE status IN (active statuses)`; `(lot_id, status)`.

**paypal_orders**: `id uuid PK`, `buyer_order_id uuid FK`, `attempt integer`, `paypal_order_id text UNIQUE NOT NULL`, `status text` (as PayPal reports), `intent text`, `amount_cents bigint`, `payee_email text`, `payee_merchant_id text NULL`, `payer_key text NULL` (HMAC of payer_id), `payer_country text NULL`, `approve_url text NULL` (never logged), `last_debug_id text NULL`, `approval_channel text NULL` (`sdk_popup` or `redirect`, INT-7), `raw jsonb` (sanitized, no secrets), `UNIQUE (buyer_order_id, attempt)`.

**paypal_authorizations**: `id uuid PK`, `buyer_order_id uuid FK`, `paypal_order_id text FK paypal_orders.paypal_order_id`, `paypal_auth_id text UNIQUE NOT NULL`, `status text`, `amount_cents bigint`, `expires_at timestamptz NULL`, `raw jsonb`.

**paypal_captures**: `id uuid PK`, `buyer_order_id uuid FK`, `paypal_auth_id text NULL`, `paypal_capture_id text UNIQUE NOT NULL`, `status text`, `amount_cents bigint`, `final_capture boolean`, `raw jsonb`.

**paypal_refunds**: `id uuid PK`, `buyer_order_id uuid FK`, `paypal_capture_id text FK`, `paypal_refund_id text UNIQUE NOT NULL`, `seq integer`, `status text`, `amount_cents bigint`, `raw jsonb`, `UNIQUE (paypal_capture_id, seq)`.

**ledger_entries** (append-only; trigger blocks UPDATE and DELETE): `id uuid PK`, `lot_id uuid FK`, `buyer_order_id uuid FK`, `kind ledger_kind`, `amount_cents bigint`, `paypal_ref text`, `idempotency_key text UNIQUE NOT NULL`, `source ledger_source`. Net paid for a lot is the sum of CAPTURE_COMPLETED minus the sum of REFUND_COMPLETED (I4).

**webhook_events**: `id uuid PK`, `paypal_event_id text UNIQUE NOT NULL`, `event_type text`, `raw_body text NOT NULL` (immutable), `verified boolean`, `verification_detail text NULL`, `status webhook_status default RECEIVED`, `received_at timestamptz`, `processed_at timestamptz NULL`.

### Merchant API and fulfillment

**merchant_api_keys** (INT-9): `id uuid PK`, `merchant_id uuid FK merchants`, `name text`, `key_prefix text UNIQUE NOT NULL` (public identifier, 8 characters), `key_hash text NOT NULL` (HMAC-SHA256 of the full key with `HMAC_KEY`; the key itself is never stored and is shown once), `scopes text[] NOT NULL` (values `lots:read`, `bids:read`, `bids:write`, `fulfillment:read`, `shipments:write`, `manifest:read`), `last_used_at timestamptz NULL`, `revoked_at timestamptz NULL`. Key format: `fpm_<prefix>_<43 base64url characters>`.

**shipments** (INT-8): `id uuid PK`, `lot_id uuid FK lots`, `buyer_order_id uuid UNIQUE FK buyer_orders`, `merchant_id uuid FK merchants`, `carrier text NOT NULL`, `tracking_number text NOT NULL`, `shipped_at timestamptz NOT NULL`, `paypal_tracker_status text NULL` (`SUBMITTED`, `FAILED`, `SKIPPED`), `paypal_debug_id text NULL`. Index `(lot_id)`.

### Platform

**jobs**: `id uuid PK`, `kind text NOT NULL`, `run_at timestamptz NOT NULL`, `payload jsonb NOT NULL`, `attempts integer default 0`, `max_attempts integer default 8`, `status job_status default PENDING`, `locked_by text NULL`, `locked_until timestamptz NULL`, `concurrency_key text NULL`, `dedupe_key text NULL`, `last_error text NULL`. Indexes: `(status, run_at)`; `UNIQUE (dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('PENDING','RUNNING')`.

**idempotency_keys**: `key text PK`, `scope text`, `request_hash char(64)`, `response jsonb NULL`.

**audit_log** (append-only): `seq bigserial PK`, `prev_hash char(64)`, `hash char(64)`, `actor text`, `action text`, `subject_type text`, `subject_id text NULL`, `payload jsonb`, `created_at timestamptz`. Hash rule in `fairness-and-hashing.md`.

**ai_runs**: `id uuid PK`, `task ai_task`, `model text`, `prompt_version text`, `input_hash char(64)`, `output jsonb NULL`, `ok boolean`, `error text NULL`, `latency_ms integer`, `tokens_in integer`, `tokens_out integer`.

**sim_runs**: `id uuid PK`, `pool_id uuid FK`, `seed bigint`, `config jsonb`, `results jsonb NULL`.

**notifications**: `id uuid PK`, `user_id uuid FK`, `kind text`, `payload jsonb`, `read_at timestamptz NULL`.

## Triggers and constraints that carry invariants

| Name | Rule | Carries |
|---|---|---|
| trg_audit_append_only | Block UPDATE and DELETE on `audit_log` | FR-AD-02 |
| trg_ledger_append_only | Block UPDATE and DELETE on `ledger_entries` | I4, I5 |
| trg_awards_immutable | Block UPDATE and DELETE on `awards` | I3 |
| trg_webhook_raw_immutable | Block changing `raw_body` | P4 |
| trg_pool_mode_immutable | Block changing `pools.mode` once status is not DRAFT | I12 |
| trg_entry_insert_window | On insert into `pool_entries`, require the pool status OPEN and `now() < close_at` from `timeline` | I15, FR-SL-02 |
| trg_entry_synthetic_matches_mode | `synthetic` must be false for LIVE_SANDBOX pools and true for SIMULATION pools | I12 |
| trg_paypal_rows_live_only | Inserts into `paypal_orders`, `paypal_authorizations`, `paypal_captures`, `paypal_refunds` require the lot's pool to be LIVE_SANDBOX | I12 |
| trg_shipments_funded_only | Inserts into `shipments` require the lot status FUNDED or CLOSED and the buyer order status CAPTURED | I4, FR-IG-08 |
| idx_one_active_order_per_entry | Partial unique index on `buyer_orders(entry_id)` over active statuses | FR-LT-04, I8 |
| chk_usd_only | `currency = 'USD'` wherever stored | DEP-1 |

## JSON shapes

**pools.template**

```json
{
  "product_key": "monitor-27-4k",
  "variant": "black",
  "title": "27-inch 4K monitor",
  "condition": "NEW",
  "quantity": 1,
  "currency": "USD",
  "bundle_contents": ["monitor", "stand", "power cable"],
  "delivery_sla_days": 7,
  "fund_by": "2026-11-10",
  "min_return_days": 14,
  "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY", "NJ", "PA"]}]
}
```

`fund_by` is the buyer-facing date used to compute the latest delivery date (fund_by plus delivery_sla_days). It is separate from `fund_deadline_s`, the timer after checkout opens.

**pools.lot_plan**

```json
[{"zone_id": "US-EAST", "lots": [{"seats": 3, "min_seats": 2}, {"seats": 3, "min_seats": 2}]}]
```

**pools.timeline** (all durations in seconds; timestamps ISO 8601 UTC)

```json
{
  "open_at": "2026-11-02T10:00:00.000000Z",
  "close_at": "2026-11-02T10:03:00.000000Z",
  "beacon_delay_s": 10,
  "bid_window_s": 120,
  "offer_window_s": 180,
  "fund_deadline_s": 600,
  "capture_grace_s": 120,
  "pending_wait_s": 120,
  "max_refill_waves": 1,
  "authorization_age_guard_s": 216000
}
```

`timeline` values come from the timing profile (`TIMING_PROFILE`) at pool creation and are then frozen with the rules.

**pools.beacon**: announced at publish `{"source": "drand", "chain_hash": "...", "round": 123456}` or `{"source": "demo"}`; after seeding add `{"randomness": "<64 hex>", "signature": "<hex>"}`.

**pool_entries.canonical_request** (key order irrelevant; hashing uses canonical JSON)

```json
{
  "v": 1,
  "pool_id": "uuid",
  "product_key": "monitor-27-4k",
  "variant": "black",
  "condition": "NEW",
  "quantity": 1,
  "currency": "USD",
  "delivery": {"zone_id": "US-EAST", "region": "NY", "country": "US"},
  "required_by": "2026-11-30",
  "max_total_cents": 60000,
  "firm": ["matte screen"],
  "preferences": ["black bezel"]
}
```

`firm` are firm requirements that must be a subset of what the template provides; `preferences` are stored and shown but never enter the engine (design 8.2).

**bid_revisions.structured** (merchant-confirmed fields are authoritative, DEP-2, DEP-3)

```json
{
  "v": 1,
  "product_key": "monitor-27-4k",
  "condition": "NEW",
  "bundle_contents": ["monitor", "stand", "power cable"],
  "capacity": 3,
  "target_quantity": 3,
  "moq": 2,
  "tiers": [{"min_qty": 1, "item_price_cents": 50000}, {"min_qty": 3, "item_price_cents": 47000}],
  "shipping_cents_by_zone": {"US-EAST": 1500},
  "tax": {"mode": "RATE_TABLE", "rate_bps_by_region": {"NY": 875, "NJ": 663, "PA": 600}},
  "delivery": {"sla_days": 5},
  "returns": {"days": 30},
  "valid_until": "2026-11-02T11:00:00.000000Z",
  "total_capacity": 6,
  "evidence": {"note": "units reserved in warehouse A", "url": null}
}
```

Rules: 1 to 3 tiers, `min_qty` strictly ascending, `item_price_cents` non-increasing; `tax.mode` is `INCLUDED` (no `rate_bps_by_region`) or `RATE_TABLE` (must cover every region of the lot's zone, else R5); tax is simulated and labelled.

**awards.totals**: `{"<entry_id>": {"item_cents": 47000, "shipping_cents": 1500, "tax_cents": 4113, "total_cents": 52613}}`. The tax formula is in `fairness-and-hashing.md`.

**merchants.attestations**: `{"inventory_reserved": {"at": "iso", "accepted": true}, "map_compliance": {"at": "iso", "accepted": true}, "delivery_terms_accurate": {"at": "iso", "accepted": true}}`.
