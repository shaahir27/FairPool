# Contract: state machines

The YAML blocks in this file are the source of truth. `backend/src/fairpool/domain/states.py` loads them (or is generated from them), and `tests/unit/test_state_machines_contract.py` fails if code and YAML differ. Any transition not listed here is illegal and must raise `IllegalTransition` and raise an alert (I10).

Every transition runs in one database transaction with its audit record, ledger fact (if any) and next-job enqueue (I10). Effects use three prefixes: `job:<kind>` (a kind from the table in `domain-ports.md`), `ledger:<kind>` (a `ledger_kind` from `db-schema.md`), `audit`, and `notify` (an in-app notification). Guards name the checks that must hold; they use the database clock (I15). A `key` on a transition is the idempotency key text of `paypal-adapter.md` section 3; a `key` on a void transition (BO-12, BO-20) is for our own records only and is never sent to PayPal, because void does not replay (S2).

Resolutions of design ambiguities are cited as N1 to N14 (`README.md`). Triggers `buyer.approved_callback` and `buyer.cancelled_callback` are the JavaScript SDK v6 `onApprove` and `onCancel` notifications posted to our server (INT-7); like `buyer.return`, they are only hints: the server always fetches the order from PayPal before acting.

## Pool

```yaml
pool:
  initial: DRAFT
  states: [DRAFT, PUBLISHED, OPEN, CLOSED, SEEDED, ALLOCATED, RUNNING, COMPLETED, CANCELLED]
  terminal: [COMPLETED, CANCELLED]
  transitions:
    - {id: PS-01, from: [DRAFT], to: PUBLISHED, trigger: admin.publish, guard: "rules valid; lot_plan present; beacon round announced; timeline frozen", effects: [audit, "job:pool.open", "job:pool.close"]}
    - {id: PS-02, from: [PUBLISHED], to: OPEN, trigger: "job:pool.open", guard: "now >= open_at", effects: [audit]}
    - {id: PS-03, from: [OPEN], to: CLOSED, trigger: "job:pool.close", guard: "now >= close_at", effects: [audit, "job:pool.seed"]}
    - {id: PS-04, from: [CLOSED], to: SEEDED, trigger: "job:pool.seed", guard: "beacon round value available, or demo seed", effects: [audit, "job:pool.allocate"]}
    - {id: PS-05, from: [SEEDED], to: ALLOCATED, trigger: "job:pool.allocate", guard: "ordering computed; lots created", effects: [audit, "job:lot.bid_open"]}
    - {id: PS-06, from: [ALLOCATED], to: RUNNING, trigger: "job:lot.bid_open", guard: "first lot enters BIDDING", effects: [audit]}
    - {id: PS-07, from: [RUNNING], to: COMPLETED, trigger: system.lots_terminal, guard: "every lot is CLOSED, FAILED_CLOSED or CANCELLED", effects: [audit]}
    - {id: PS-08, from: [DRAFT, PUBLISHED, OPEN, CLOSED, SEEDED, ALLOCATED], to: CANCELLED, trigger: admin.cancel, guard: "no buyer_orders exist for the pool", effects: [audit, notify]}
    - {id: PS-09, from: [ALLOCATED], to: COMPLETED, trigger: "job:pool.allocate", guard: "no lot is PLANNED (all lots CANCELLED or no entries)", effects: [audit]}
```

## Entry

```yaml
entry:
  initial: SUBMITTED
  states: [SUBMITTED, ELIGIBLE, REJECTED, WITHDRAWN]
  terminal: [REJECTED, WITHDRAWN]
  transitions:
    - {id: ES-01, from: [SUBMITTED], to: ELIGIBLE, trigger: "job:pool.close", guard: "link still active when required; request still valid", effects: [audit]}
    - {id: ES-02, from: [SUBMITTED], to: REJECTED, trigger: "job:pool.close", guard: "link inactive or request invalid; reject_reason set", effects: [audit, notify]}
    - {id: ES-03, from: [SUBMITTED], to: WITHDRAWN, trigger: buyer.withdraw, guard: "pool status OPEN and now < close_at", effects: [audit]}
```

ELIGIBLE is not terminal: eligible entries become allocations (SEATED, WAITLISTED or PRICED_OUT) which have their own status in `allocation_status`.

## Lot

```yaml
lot:
  initial: PLANNED
  states: [PLANNED, BIDDING, BID_CLOSED, AWARDED, CHECKOUT_OPEN, FUNDING, FUNDED, CLOSED, FAILING, FAILED_CLOSED, CANCELLED]
  terminal: [CLOSED, FAILED_CLOSED, CANCELLED]
  transitions:
    - {id: LS-01, from: [PLANNED], to: BIDDING, trigger: "job:lot.bid_open", guard: "now >= bid_open_at", effects: [audit, "job:lot.bid_close"]}
    - {id: LS-02, from: [BIDDING], to: BID_CLOSED, trigger: "job:lot.bid_close", guard: "now >= bid_close_at; late bids already rejected", effects: [audit, "job:lot.award"]}
    - {id: LS-03, from: [BID_CLOSED], to: AWARDED, trigger: "job:lot.award", guard: "all lower lot_order lots are past BID_CLOSED; a bid passes R1 to R9; award snapshot written; router and mode stamped (N8)", effects: [audit, "job:lot.open_checkout", notify]}
    - {id: LS-04, from: [BID_CLOSED], to: CANCELLED, trigger: "job:lot.award", guard: "no feasible bid; no money exists", effects: [audit, notify]}
    - {id: LS-05, from: [AWARDED], to: CHECKOUT_OPEN, trigger: "job:lot.open_checkout", guard: "award exists; priced-out seats released; offers created within seats (I8)", effects: [audit, "job:offer.expire", "job:lot.try_fund", notify]}
    - {id: LS-06, from: [CHECKOUT_OPEN], to: FUNDING, trigger: "job:lot.try_fund", guard: "authorized count A >= min(seats, moq + CAPTURE_BUFFER), or fund_deadline_at passed and A >= moq", effects: [audit, "job:order.capture"]}
    - {id: LS-07, from: [FUNDING], to: FUNDED, trigger: "job:lot.try_fund", guard: "completed captures from distinct buyers >= moq, read from the ledger (I5)", effects: [audit, notify, "job:lot.finalize_close"]}
    - {id: LS-08, from: [CHECKOUT_OPEN], to: FAILING, trigger: "job:lot.try_fund", guard: "fund_deadline_at passed with A < moq, or winning offer expired, or ops abort", effects: [audit, "job:lot.finalize_fail", notify]}
    - {id: LS-09, from: [FUNDING], to: FAILING, trigger: "job:lot.try_fund", guard: "sweep resolved with completed < moq and no refill possible, or winning offer expired, or ops abort", effects: [audit, "job:lot.finalize_fail", notify]}
    - {id: LS-10, from: [FAILING], to: FAILED_CLOSED, trigger: "job:lot.finalize_fail", guard: "every authorization VOIDED or expired; every completed capture has a COMPLETED refund; no capture PENDING; net paid is zero", effects: [audit, notify]}
    - {id: LS-11, from: [FUNDED], to: CLOSED, trigger: "job:lot.finalize_close", guard: "capture window over; ledger balanced; merchant notified", effects: [audit]}
    - {id: LS-12, from: [PLANNED], to: CANCELLED, trigger: "job:pool.allocate", guard: "entries available below min_seats (N2)", effects: [audit]}
    - {id: LS-13, from: [AWARDED], to: CANCELLED, trigger: admin.abort, guard: "checkout not yet open; no money exists (N3)", effects: [audit, notify]}
```

## Buyer order (seat)

```yaml
buyer_order:
  initial: OFFERED
  states: [OFFERED, ORDER_CREATED, APPROVED, AUTHORIZING, AUTHORIZED, CAPTURING, CAPTURE_PENDING, CAPTURED, REFUNDING, EXPIRED, REJECTED, AUTH_FAILED, CAPTURE_FAILED, VOIDED, REFUNDED, DECLINED]
  active: [OFFERED, ORDER_CREATED, APPROVED, AUTHORIZING, AUTHORIZED, CAPTURING, CAPTURE_PENDING, CAPTURED, REFUNDING]
  terminal: [EXPIRED, REJECTED, AUTH_FAILED, CAPTURE_FAILED, VOIDED, REFUNDED, DECLINED]
  transitions:
    - {id: BO-01, from: [OFFERED], to: ORDER_CREATED, trigger: buyer.continue, guard: "seat valid; now < offer_expires_at; lot CHECKOUT_OPEN; award valid; total <= cap", paypal: create_order, key: "create:{buyer_order_id}:{attempt}", effects: [audit]}
    - {id: BO-02, from: [ORDER_CREATED], to: APPROVED, trigger: "buyer.return | buyer.approved_callback | webhook | poll", guard: "GET order shows APPROVED; amount, currency, payee, country and payer-key checks pass (FR-CK-05)", paypal: get_order, effects: [audit, "job:order.authorize"]}
    - {id: BO-03, from: [APPROVED], to: AUTHORIZING, trigger: "job:order.authorize", guard: "row lock taken; seat still valid; lot CHECKOUT_OPEN; sets seat_locked_until (I7)", effects: [audit]}
    - {id: BO-04, from: [AUTHORIZING], to: AUTHORIZED, trigger: "job:order.authorize", guard: "authorization status CREATED; amount equals expected (I3)", paypal: authorize_order, key: "auth:{buyer_order_id}", effects: [audit, "ledger:AUTH_CREATED", "job:lot.try_fund"]}
    - {id: BO-05, from: [AUTHORIZING], to: AUTH_FAILED, trigger: "job:order.authorize", guard: "definitive denial (status DENIED or definitive 4xx other than ORDER_NOT_APPROVED)", effects: [audit, "job:lot.refill"]}
    - {id: BO-06, from: [AUTHORIZED], to: CAPTURING, trigger: "job:order.capture", guard: "lot FUNDING or FUNDED", paypal: capture_authorization, key: "cap:{paypal_auth_id}", effects: [audit]}
    - {id: BO-07, from: [CAPTURING], to: CAPTURED, trigger: "job:order.capture", guard: "capture status COMPLETED", paypal: get_capture, effects: [audit, "ledger:CAPTURE_COMPLETED", "job:lot.try_fund"]}
    - {id: BO-08, from: [CAPTURING], to: CAPTURE_PENDING, trigger: "job:order.capture", guard: "capture status PENDING (P3)", effects: [audit, "ledger:CAPTURE_PENDING", "job:capture.poll"]}
    - {id: BO-09, from: [CAPTURE_PENDING], to: CAPTURED, trigger: "job:capture.poll", guard: "capture status COMPLETED", effects: [audit, "ledger:CAPTURE_COMPLETED", "job:lot.try_fund"]}
    - {id: BO-10, from: [CAPTURE_PENDING], to: CAPTURE_FAILED, trigger: "job:capture.poll", guard: "capture DECLINED or FAILED, or pending_wait exceeded", effects: [audit, "ledger:CAPTURE_DECLINED", "job:lot.refill"]}
    - {id: BO-11, from: [CAPTURING], to: CAPTURE_FAILED, trigger: "job:order.capture", guard: "capture DECLINED or FAILED", effects: [audit, "ledger:CAPTURE_DECLINED", "job:lot.refill"]}
    - {id: BO-12, from: [AUTHORIZED], to: VOIDED, trigger: "job:void.run", guard: "not yet captured; reason in void_source", paypal: void_authorization, key: "void:{paypal_auth_id}", effects: [audit, "ledger:AUTH_VOIDED", "job:lot.refill"]}
    - {id: BO-13, from: [CAPTURED], to: REFUNDING, trigger: "job:refund.run", guard: "lot FAILING or ops refund", paypal: refund_capture, key: "refund:{paypal_capture_id}:{seq}", effects: [audit, "ledger:REFUND_PENDING"]}
    - {id: BO-14, from: [REFUNDING], to: REFUNDED, trigger: "job:refund.run", guard: "refund status COMPLETED", paypal: get_refund, effects: [audit, "ledger:REFUND_COMPLETED"]}
    - {id: BO-15, from: [OFFERED], to: EXPIRED, trigger: "job:offer.expire", guard: "now >= offer_expires_at; not AUTHORIZING (I7, I15)", effects: [audit, "job:lot.refill"]}
    - {id: BO-16, from: [ORDER_CREATED], to: EXPIRED, trigger: "job:offer.expire", guard: "now >= offer_expires_at; not AUTHORIZING (I7, I15)", effects: [audit, "job:lot.refill"]}
    - {id: BO-17, from: [APPROVED], to: EXPIRED, trigger: "job:offer.expire", guard: "now >= offer_expires_at; not AUTHORIZING (N4, F5)", effects: [audit, "job:lot.refill"]}
    - {id: BO-18, from: [ORDER_CREATED], to: REJECTED, trigger: "buyer.return | buyer.approved_callback | poll", guard: "policy failure: duplicate payer, wrong country, amount or payee mismatch; never authorize", effects: [audit, "job:lot.refill", notify]}
    - {id: BO-19, from: [APPROVED], to: REJECTED, trigger: "job:order.authorize", guard: "policy failure found before authorizing", effects: [audit, "job:lot.refill", notify]}
    - {id: BO-20, from: [AUTHORIZING], to: REJECTED, trigger: "job:order.authorize", guard: "authorization amount differs from expected; authorization voided at once (N5)", paypal: void_authorization, key: "void:{paypal_auth_id}", effects: [audit, "ledger:AUTH_VOIDED", "job:lot.refill", notify]}
    - {id: BO-21, from: [OFFERED], to: DECLINED, trigger: buyer.decline, guard: "seat valid", effects: [audit, "job:lot.refill"]}
    - {id: BO-22, from: [ORDER_CREATED], to: DECLINED, trigger: "buyer.cancel | buyer.cancelled_callback | buyer.decline", guard: "not AUTHORIZING", effects: [audit, "job:lot.refill"]}
    - {id: BO-23, from: [OFFERED], to: CAPTURING, trigger: "job:order.vault_charge", guard: "payment_mode vault_charge; seat valid; lot CHECKOUT_OPEN; award valid; vault token ACTIVE; total <= cap by integer compare; row lock taken", paypal: charge_vault, key: "vc:{buyer_order_id}", effects: [audit]}
    - {id: BO-24, from: [CAPTURING], to: CAPTURED, trigger: "job:order.vault_charge", guard: "capture status COMPLETED; amount equals the award total; payee equals the seller (I3)", paypal: get_capture, effects: [audit, "ledger:CAPTURE_COMPLETED", "job:lot.try_fund"]}
    - {id: BO-25, from: [CAPTURING], to: CAPTURE_PENDING, trigger: "job:order.vault_charge", guard: "capture status PENDING (P3)", effects: [audit, "ledger:CAPTURE_PENDING", "job:capture.poll"]}
    - {id: BO-26, from: [CAPTURING], to: CAPTURE_FAILED, trigger: "job:order.vault_charge", guard: "definitive decline: INSTRUMENT_DECLINED, status DENIED or 403 PERMISSION_DENIED (token then marked DELETED); unknown outcomes stay CAPTURING", effects: [audit, "job:lot.refill"]}
    - {id: BO-27, from: [OFFERED], to: REJECTED, trigger: "job:order.vault_charge", guard: "vault precheck failed: token missing or not ACTIVE, total above cap, lot no longer CHECKOUT_OPEN, or award invalid", effects: [audit, "job:lot.refill"]}
```

Vacancy rule: a transition into EXPIRED, REJECTED, AUTH_FAILED, CAPTURE_FAILED, DECLINED, or VOIDED with `void_source` of `buyer_withdraw`, `age_guard` or `paypal_expired` creates one claimable vacancy, and the `lot.refill` job runs only while the lot is CHECKOUT_OPEN or FUNDING (or FUNDED when the optional top-up is on) and before `refill_cutoff_at`. A VOIDED with `void_source = lot_failing` never creates a vacancy. PRICED_OUT allocations create vacancies at award time.

## Bid

```yaml
bid:
  initial: DRAFT
  states: [DRAFT, PROPOSED, CONFIRMED, FLAGGED, REJECTED, ELIGIBLE, AWARDED, LOST]
  terminal: [REJECTED, AWARDED, LOST]
  transitions:
    - {id: BS-01, from: [DRAFT], to: PROPOSED, trigger: merchant.quote, guard: "AI proposes fields from a pasted quote (DEP-2)", effects: [audit]}
    - {id: BS-02, from: [DRAFT], to: CONFIRMED, trigger: merchant.confirm, guard: "structured form complete and valid", effects: [audit]}
    - {id: BS-03, from: [PROPOSED], to: CONFIRMED, trigger: merchant.confirm, guard: "merchant reviewed and confirmed every field", effects: [audit]}
    - {id: BS-04, from: [CONFIRMED], to: FLAGGED, trigger: ai.reconcile, guard: "a BLOCKING flag was raised (R7)", effects: [audit, notify]}
    - {id: BS-05, from: [FLAGGED], to: CONFIRMED, trigger: merchant.confirm, guard: "merchant saved a corrected revision; new flags none", effects: [audit]}
    - {id: BS-06, from: [CONFIRMED], to: REJECTED, trigger: "job:lot.award", guard: "a rule among R1 to R6, R8 or R9 failed; reject_reason set", effects: [audit, notify]}
    - {id: BS-07, from: [CONFIRMED], to: ELIGIBLE, trigger: "job:lot.award", guard: "all rules pass", effects: [audit]}
    - {id: BS-08, from: [ELIGIBLE], to: AWARDED, trigger: "job:lot.award", guard: "lowest ranking key", effects: [audit, notify]}
    - {id: BS-09, from: [ELIGIBLE], to: LOST, trigger: "job:lot.award", guard: "not the winner", effects: [audit, notify]}
    - {id: BS-10, from: [FLAGGED], to: REJECTED, trigger: "job:lot.award", guard: "still FLAGGED at award (R7)", effects: [audit, notify]}
    - {id: BS-11, from: [PROPOSED, DRAFT], to: REJECTED, trigger: "job:lot.award", guard: "unconfirmed fields at award (R1)", effects: [audit, notify]}
    - {id: BS-12, from: [PROPOSED, CONFIRMED, FLAGGED], to: DRAFT, trigger: merchant.revise, guard: "now < bid_close_at; creates a new revision with a receipt", effects: [audit]}
```

## Allocation status (no separate machine)

`SEATED` and `WAITLISTED` are set at allocation. WAITLISTED to SEATED happens only inside `AllocationReadService.next_candidates` (N12). SEATED to PRICED_OUT happens only inside `lot.award` when the entry's cap is below its total. PRICED_OUT is final and creates a vacancy filled by the same refill rule.

## Test obligations

- Every transition above has a unit test for its success path and one for each guard that can fail.
- A test enumerates all (from, to) pairs for each machine and asserts that every pair not listed raises `IllegalTransition`.
- The YAML parses; every `job:` effect names a kind in `domain-ports.md`; every `ledger:` effect names a `ledger_kind`; every state list equals the corresponding enum in `db-schema.md`.
