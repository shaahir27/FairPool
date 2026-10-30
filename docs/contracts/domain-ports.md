# Contract: ports, jobs and handoffs

This file lets Member A and Member B build in parallel. Each module codes against a **port** (a Python `Protocol` in `backend/src/fairpool/ports.py`) and tests against a **fake** (in `backend/src/fairpool/fakes/`). The real implementation replaces the fake at the gate named in `docs/implementation-plan.md`. Ports are shared files: changing one needs a contract change request.

## 1. Rules for every port and service

- Every method that touches the database takes `session: AsyncSession` as its first argument and **never commits**. The job runner or the HTTP request handler owns the transaction (I10).
- No method reads the application clock for a deadline. Use `Clock.db_now(session)` (I15).
- Every method is `async`.
- Fakes are deterministic, in-memory, and record calls so tests can assert on them.

## 2. Platform ports (implemented by Member A, task T01A02; used by both)

```python
class Clock(Protocol):
    async def db_now(self, session) -> datetime: ...          # SELECT now() from the database

class JobQueue(Protocol):
    async def enqueue(self, session, kind: str, payload: dict, *, run_at: datetime | None = None,
                      concurrency_key: str | None = None, dedupe_key: str | None = None) -> UUID | None: ...
        # returns None when dedupe_key collides with a PENDING or RUNNING job

class AuditLog(Protocol):
    async def append(self, session, *, actor: str, action: str, subject_type: str,
                     subject_id: str | None, payload: dict) -> int: ...   # returns seq; hash chain per fairness-and-hashing.md

class IdempotencyStore(Protocol):
    async def begin(self, session, *, key: str, scope: str, request_hash: str) -> IdemResult: ...
        # IdemResult is New | Replay(response: dict) | Conflict
    async def complete(self, session, *, key: str, response: dict) -> None: ...

class Ledger(Protocol):                                      # Member A implements; only the checkout module writes
    async def record(self, session, *, lot_id: UUID, buyer_order_id: UUID, kind: str, amount_cents: int,
                     paypal_ref: str, idempotency_key: str, source: str) -> bool: ...   # False if the key already exists
    async def net_paid_cents(self, session, lot_id: UUID) -> int: ...
    async def completed_capture_count(self, session, lot_id: UUID) -> int: ...          # distinct buyers (I5)
```

Fakes: `FakeClock` (settable time), `FakeJobQueue` (list of jobs plus `run_due(now)`), `FakeAuditLog` (list, verifies the hash chain), `FakeIdempotencyStore`, `FakeLedger` (list, same idempotency behaviour as the real one).

## 3. Edge ports (implemented by Member B unless noted)

```python
class Notifier(Protocol):                                    # B implements; A calls
    async def notify(self, session, *, user_id: UUID, kind: str, payload: dict) -> None: ...

class BeaconClient(Protocol):                                # B implements
    async def announce(self, *, close_at: datetime, delay_s: int) -> dict: ...   # {"source", "chain_hash", "round"} or {"source": "demo"}
    async def fetch(self, announced: dict) -> dict | None: ...                   # adds "randomness" and "signature", or None if unavailable

class AiRunLogger(Protocol):                                 # B implements in modules/intake; injected into the AI adapter
    async def log(self, session, *, task: str, model: str, prompt_version: str, input_hash: str,
                  output: dict | None, ok: bool, error: str | None, latency_ms: int,
                  tokens_in: int, tokens_out: int) -> UUID: ...

class AIClient(Protocol):                                    # B implements; shapes in ai-schemas.md
    async def parse_intake(self, session, *, message: str, candidates: list[dict], history: list[dict]) -> IntakeProposal: ...
    async def parse_quote(self, session, *, quote_text: str, lot_requirement: dict) -> QuoteProposal: ...
    async def reconcile_offer(self, session, *, lot_requirement: dict, bid_structured: dict, text: str) -> ReconcileResult: ...
    async def sim_text(self, session, *, kind: str, facts: dict) -> str: ...
```

The AI adapter receives an `AiRunLogger` in its constructor and passes the session through to it untouched, so `adapters/ai` never imports the database layer.

```python
@dataclass(frozen=True)
class SearchHit:
    doc_id: str; doc_kind: str            # "pool" or "lot"
    pool_id: UUID; lot_id: UUID | None; product_key: str; title: str; score: float

@dataclass(frozen=True)
class SimilarityResult:
    own_rank: int | None                   # rank of the lot's own document for the quote text (1 is best)
    top_lot_id: UUID | None; top_product_key: str | None

class SearchService(Protocol):                               # B implements: Elastic or Postgres trigram (INT-1)
    async def search(self, session, *, q: str, kinds: list[str], status: list[str] | None, limit: int) -> list[SearchHit]: ...
    async def similarity_check(self, session, *, lot_id: UUID, text: str) -> SimilarityResult: ...

class SearchIndexer(Protocol):                               # B implements; only public pool and lot documents
    async def upsert(self, session, *, doc_kind: str, doc_id: UUID) -> None: ...
    async def delete(self, session, *, doc_kind: str, doc_id: UUID) -> None: ...

@dataclass(frozen=True)
class MerchantPrincipal:
    merchant_id: UUID; scopes: frozenset[str]; via: str    # "session" or "api_key"

class MerchantAuth(Protocol):                                # B implements; Member A's merchant routes depend on it
    async def from_session(self, session, user_id: UUID) -> MerchantPrincipal: ...
    async def from_api_key(self, session, bearer: str) -> MerchantPrincipal: ...   # raises API_KEY_INVALID
```

The search score is a retrieval score, not money, so `float` is allowed there only. `SearchService` never receives buyer requests, caps or user data (INT-1). Fakes: `FakeSearch` (substring match over fixtures, scripted similarity results), `FakeMerchantAuth` (table of keys), `FakeAiRunLogger` (list), `FakeNotifier` (list), `FakeBeacon` (fixed seed, can simulate "unavailable"), `FakeAI` (table-driven answers keyed by input hash, can simulate invalid JSON and timeouts).

## 4. Cross-member services

### 4.1 `AllocationReadService` (Member B implements; Member A calls)

```python
@dataclass(frozen=True)
class LotView:
    id: UUID; pool_id: UUID; zone_id: str; lot_order: int; seats: int
    status: str; payment_router: str | None; payment_mode: str | None
    fund_deadline_at: datetime | None; refill_cutoff_at: datetime | None
    offer_window_s: int; fund_deadline_s: int; max_refill_waves: int; pool_mode: str

@dataclass(frozen=True)
class SeatView:
    entry_id: UUID; user_id: UUID; cap_cents: int; zone_id: str; region: str; rank: int
    paypal_account_key: str | None

@dataclass(frozen=True)
class AwardView:
    lot_id: UUID; merchant_id: UUID; item_cents: int; moq: int; tier_index: int
    totals: dict[UUID, "Totals"]   # entry_id -> item, shipping, tax, total cents
    valid_until: datetime; award_hash: str

class AllocationReadService(Protocol):
    async def get_lot(self, session, lot_id: UUID) -> LotView: ...
    async def get_award(self, session, lot_id: UUID) -> AwardView: ...
    async def list_seated(self, session, lot_id: UUID) -> list[SeatView]: ...
    async def next_candidates(self, session, lot_id: UUID, count: int) -> list[SeatView]: ...
        # selects up to `count` WAITLISTED allocations in the lot's zone in ascending rank whose cap >= their total
        # at this lot's award and whose entry is ELIGIBLE, sets them SEATED with lot_id, and returns them (N12).
        # Called inside the caller's transaction; never commits.
```

Fake: `FakeAllocationRead` returns fixtures supplied by the test (built by the helper `make_award_fixture`, T01B02), including a waitlist, and implements `next_candidates` with the same rule.

### 4.2 `MerchantDirectory` (Member B implements; Member A calls)

```python
@dataclass(frozen=True)
class PayeeRef:
    merchant_id: UUID; display_name: str; payee_email: str | None
    paypal_merchant_id: str | None; onboarding_status: str

class MerchantDirectory(Protocol):
    async def get_payee(self, session, merchant_id: UUID) -> PayeeRef: ...
```

Under `PAYMENT_ROUTER=single_seller` the router ignores the merchant's payee fields and pays `SINGLE_SELLER_EMAIL`; the merchant's display name still appears on screens with the fallback label.

### 4.3 Checkout surface for the API layer (Member A implements; Member B's UI calls via HTTP only)

Member B never imports checkout code. The two members meet only at HTTP (`api.md`), jobs (below) and the services above.

## 5. Job kinds

One table is the source of truth. Handlers are registered by kind in `worker.py`. Payloads contain IDs only. `ck` is the concurrency key (jobs with the same key never run at the same time). `dedupe` coalesces repeated enqueues while one is pending.

| Kind | Owner | Payload | ck | dedupe | Enqueued by | Does |
|---|---|---|---|---|---|---|
| pool.open | B | pool_id | pool:{pool_id} | none | admin.publish | PUBLISHED to OPEN |
| pool.close | B | pool_id | pool:{pool_id} | none | admin.publish | OPEN to CLOSED, eligibility sweep, commitments, root |
| pool.seed | B | pool_id | pool:{pool_id} | none | pool.close | Fetch beacon (requeue +10 s if unavailable), set seed |
| pool.allocate | B | pool_id | pool:{pool_id} | none | pool.seed | Ordering, lots, waitlist |
| lot.bid_open | B | lot_id | lot:{lot_id} | none | pool.allocate | PLANNED to BIDDING |
| lot.bid_close | B | lot_id | lot:{lot_id} | none | lot.bid_open | BIDDING to BID_CLOSED |
| lot.award | B | lot_id | award:{pool_id} | none | lot.bid_close | Rules R1 to R9, award, price-out; requeue +2 s while a lower lot_order lot is not past BID_CLOSED |
| sim.run | B | sim_run_id | sim:{sim_run_id} | none | admin.sim | Run a simulation pool |
| lot.open_checkout | A | lot_id | lot:{lot_id} | none | lot.award | AWARDED to CHECKOUT_OPEN, create offers, schedule timers |
| offer.expire | A | buyer_order_id | bo:{buyer_order_id} | none | lot.open_checkout, lot.refill | Expire an offer, respecting I7 |
| order.authorize | A | buyer_order_id | bo:{buyer_order_id} | none | checkout return, reconciler | APPROVED to AUTHORIZING to AUTHORIZED |
| order.capture | A | buyer_order_id | bo:{buyer_order_id} | none | lot.try_fund | Capture one authorization |
| order.vault_charge | A | buyer_order_id | bo:{buyer_order_id} | none | lot.open_checkout, lot.refill (PAYMENT_MODE=vault_charge) | Precheck, then charge the saved permission once with key `vc:{buyer_order_id}`; at most `VAULT_CHARGE_CONCURRENCY` run at once |
| order.resolve | A | buyer_order_id | bo:{buyer_order_id} | none | reconciler.sweep | Fetch PayPal and heal one order |
| capture.poll | A | buyer_order_id | bo:{buyer_order_id} | none | order.capture | Poll a PENDING capture until pending_wait |
| void.run | A | buyer_order_id, reason | bo:{buyer_order_id} | none | lot.finalize_fail, withdraw, age guard | GET then void |
| refund.run | A | buyer_order_id, seq | bo:{buyer_order_id} | none | lot.finalize_fail, ops | Refund a capture |
| lot.try_fund | A | lot_id | lot:{lot_id} | try_fund:{lot_id} | authorization or capture events, deadline timer | Evaluate trigger and funding |
| lot.refill | A | lot_id | lot:{lot_id} | refill:{lot_id} | vacancy transitions | Offer vacancies to waitlist via next_candidates |
| lot.finalize_fail | A | lot_id | lot:{lot_id} | none | LS-08, LS-09 | Void, refund, reconcile to zero |
| lot.finalize_close | A | lot_id | lot:{lot_id} | none | LS-07 | FUNDED to CLOSED |
| webhook.process | A | webhook_event_id | wh:{webhook_event_id} | none | webhook ingest | Map event, fetch resource, apply |
| shipments.submit | A | lot_id | lot:{lot_id} | shipments:{lot_id} | merchant shipments endpoint | Submit pending trackers to PayPal through the adapter (when `SHIPMENT_TRACKING_ENABLED`) |
| search.index | B | doc_kind, doc_id | search:{doc_kind}:{doc_id} | search:{doc_kind}:{doc_id} | pool publish, lot creation or status change, admin reindex | Upsert or delete one public document in the search backend |
| reconciler.sweep | A | none | reconciler | reconciler | cron every `RECONCILER_INTERVAL_S` | Heal stale states, age guard |

Runner rules: claim with `FOR UPDATE SKIP LOCKED` where `status = 'PENDING' AND run_at <= now()`; honour `concurrency_key`; retry failures with backoff 2, 4, 8 up to `max_attempts` then mark FAILED and raise an alert; a handler is idempotent and re-checks deadlines against the database clock when it runs (I15). Timers are job rows with `run_at`; there are no in-memory timers.

## 6. Handoff protocols

**Award handoff (B to A).** `lot.award` (B) in one transaction: writes the immutable award, stamps `payment_router` and `payment_mode` on the lot from configuration (N8), marks priced-out allocations, sets the lot AWARDED, and enqueues `lot.open_checkout`. It never creates buyer orders.

**Checkout open (A).** `lot.open_checkout` (A) reads `get_lot`, `get_award`, `list_seated` and `get_payee`, creates OFFERED buyer orders for seated entries within the seat count (I8), asks `next_candidates` to refill any priced-out vacancies, sets `fund_deadline_at` and `refill_cutoff_at`, enqueues `offer.expire` per order and `lot.try_fund` at the fund deadline, and notifies buyers via `Notifier`.

**Refill (A orchestrates, B selects).** On a vacancy, `lot.refill` (A) computes open vacancies (seats minus active buyer orders), respects the wave limit and `refill_cutoff_at`, calls `next_candidates(count=vacancies)`, creates OFFERED orders for the returned seats, and enqueues their `offer.expire`.

**Merchant identity (B to A).** Member A's merchant routes (progress, fulfillment, shipments, verification manifest, on both `/api/v1/merchant/...` and `/merchant-api/v1/...`) call `MerchantAuth` for the principal and check the scope and that the lot was awarded to that merchant. They never read API keys themselves.

**Search indexing (B).** Handlers that change public pool or lot data enqueue `search.index`; search failures never fail the user action and the Postgres fallback answers meanwhile.

**Notifications.** Any module calls `Notifier.notify`; Member B's implementation writes `notifications` rows surfaced by `GET /api/v1/me`.

**Integration order.** Until the gate named in the plan, A tests against `FakeAllocationRead` and `FakeMerchantDirectory`, and B tests against `FakeJobQueue` plus a stub handler for `lot.open_checkout`. The first real wiring is task T04X01 (gate IG-4).
