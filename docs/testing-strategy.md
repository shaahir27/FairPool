# Testing strategy

Tests are the proof that the invariants hold. Every task's acceptance bullets map to named tests (`AGENTS.md` section 6). This file defines the layers, the property tests (PT-xx), the integration acceptance test for each gate (IT-x), the fault matrix for F1 to F30, and how the checklist maps to tests.

## 1. Layers

| Layer | Location | Marker | Runs in CI | What it covers |
|---|---|---|---|---|
| Unit and contract | `backend/tests/unit/` | none | yes | Domain logic, schema and route contracts, state-machine YAML, enum equality, vectors |
| Property | `backend/tests/property/` | `property` | yes | Hypothesis tests PT-01 to PT-16 |
| Integration | `backend/tests/integration/` | `integration` | yes | Postgres-backed flows with fakes (`FakePaymentRouter`, `FakeAI`, `FakeBeacon`, `FakeSearch`) |
| Sandbox contract | `backend/tests/contract_sandbox/` | `sandbox` | no | Real PayPal Sandbox calls C-01 to C-07 (non-interactive) |
| Sandbox interactive | same | `sandbox_interactive` | no | Real calls needing a human approval C-08 to C-18 |
| Fault injection | `backend/tests/faults/` | `faults` | no (run by gate-check) | F1 to F30, crashes, restarts |
| Concurrency | `backend/tests/concurrency/` | `concurrency` | yes | Races on join, offers, seats |
| AI evaluation | `backend/tests/ai_eval/` | `ai_eval` | no | Real model, labelled sets, retrieval quality |
| Frontend | `frontend/` | none | yes | `tsc`, eslint, unit tests, the verify-my-place vectors |
| End to end | manual with scripts | none | no | Rehearsals (IT-10) |

Contract tests must exist from the gate that creates their subject: `test_state_machines_contract` (YAML equals code, illegal pairs raise) and `test_fairness_vectors` (Python) at IG-0; `test_schema_contract` (enums and `alembic check`), `test_api_contract` (routes equal the endpoint table) and `test_merchant_openapi_contract` (exactly the operations and operationIds in `api.md` section 4.3, at most 20) at IG-1; `test_mcp_contract` (exactly the four tools, no payment tools) and `test_no_payment_surface` (PT-16) at IG-7. The frontend half of the fairness vectors arrives with the frontend tests.

Coverage gates (line coverage): `domain/` 90 percent, `checkout` and `ledger` 85 percent, everything else 70 percent. Coverage never replaces the named acceptance tests.

## 2. Property tests

| ID | Property |
|---|---|
| PT-01 | Allocation is deterministic for the same inputs and is a permutation: every eligible entry appears exactly once (I11) |
| PT-02 | Lots follow the lot plan per zone; undersized lots are CANCELLED; waitlist is the ordered remainder |
| PT-03 | Commitments, Merkle root, inclusion proofs and the receipt signature reproduce `vectors/fairness_v1.json` (Python and browser) |
| PT-04 | Money arithmetic is exact in cents; tax rounding and mean rounding match the vectors; PayPal string round-trips |
| PT-05 | Tier resolution, feasibility and bid ranking match the vectors; the tie-break is deterministic |
| PT-06 | Capacity across lots never exceeds a merchant's total capacity (R9) |
| PT-07 | Every transition not in the YAML raises; every listed transition passes its guard tests (I10) |
| PT-08 | Under random event sequences, offers in flight plus committed never exceed seats (I8) |
| PT-09 | A lot is FUNDED exactly when completed captures from distinct buyers reach the MOQ; PENDING never counts (I4, I5) |
| PT-10 | Replaying any job or handler twice leaves the same final state and one ledger row per idempotency key (I9) |
| PT-11 | After FAILING completes, net paid is zero for any mix of capture and refund outcomes |
| PT-12 | No sequence releases a seat while its order is AUTHORIZING (I7), model-based |
| PT-13 | Unique constraints hold under concurrent joins: one entry per user and per account key per pool (I6) |
| PT-14 | Search never gates: for any set of bids, the award is identical with the search backend on, off or failing (INT-1) |
| PT-15 | A merchant API key or session can never read another merchant's bids, lots they did not win, or fulfillment rows (sealing, INT-9) |
| PT-16 | No HTTP route and no MCP tool in the agent, MCP or Merchant Agent surfaces creates orders, authorizes, captures, voids or refunds, and `fairpool.modules.mcp` and `agentapi` import nothing from payments (I1, I2, INT-5) |

## 3. Integration acceptance tests (one per gate)

A gate passes only when its IT passes, `make gate-check GATE=<gate>` is green and the tag is pushed. Dates are in `docs/implementation-plan.md`.

| ID | Gate | Acceptance |
|---|---|---|
| IT-0 | IG-0 | On a clean clone `make setup` and `make verify` are green and `tools/validate_docs.py` and `tools/check_imports.py` run in CI; tag `contracts-v1` exists with its change-log row; secrets are rotated (T00A02); the two dev-time plugins are installed in both members' coding agents with versions recorded; spike results S1 and S7 are recorded and the matching switches in `docs/decisions.md` are filled (S3 is already recorded) |
| IT-1 | IG-1 | `alembic upgrade head` and `alembic check` pass and every trigger and unique index in `db-schema.md` has a test; Clock, JobQueue, AuditLog (chain equals the vectors) and IdempotencyStore pass; the hosted URL serves `/health` and the webhook stub returns 200 and stores the raw body; the route-table and Merchant OpenAPI contract tests pass; every port has a fake with a behaviour test; the frontend builds and its boundary lint passes; S2 follow-up (O1, O2) and S6 are recorded |
| IT-2 | IG-2 | Gateway Sandbox tests C-01 to C-07 pass and the request-ID examples reproduce; the fake router's failure injection works; PT-09 passes for the ledger; register, login and roles work; publishing a pool computes the rules hash from the vectors and enqueues its jobs; the AI adapter validates, retries once and imports nothing from payments; S4, S8 and S13 are recorded |
| IT-3 | IG-3 | PT-07, PT-10 and PT-12 pass for the buyer-order engine and seat control; 200 parallel joins by one account give one entry and receipts verify; search returns the same shape from the Postgres backend (and Elastic if S8 passed) and PT-14 passes; PayPal Login behaves per `DEDUPE_MODE`; pool close publishes commitments and the root and late joins are impossible; S5, S10, S11 and S12 are recorded and the APIMatic trial started in PH3 |
| IT-4 | IG-4 | Pipeline test with `FakePaymentRouter` and `FakeAI`: create and publish a pool; 12 users join through intake (some caps low enough to be priced out); close; demo seed; allocate two lots and a waitlist; force-award; `lot.open_checkout` creates offers and refills priced-out seats from the waitlist; all authorizations are captured by the sweep (in vault mode all seated charges complete through `charge_vault` of the fake router) and the lot is FUNDED; the audit chain verifies; the public audit payload recomputes with the vectors; the real `AllocationReadService` and `MerchantDirectory` are wired through `wiring.py` |
| IT-5 | IG-5 | One real Sandbox buyer through the app on the redirect path (in vault mode: saving PayPal at join, then a server-side charge and a refund, with VC-01 to VC-06; in fallback mode: offer, approval, server-side authorize, then void, and capture then refund in a second run) with the ledger equal to PayPal GETs; the checkout UI shows notices and labels; the failure path with the fake router ends at net zero (PT-11); the auction rules engine reproduces the vectors; merchant profile and sealed bids with receipts pass their tests |
| IT-6 | IG-6 | Real Sandbox: authorizations are captured by the sweep and the lot is FUNDED; a second lot misses its minimum and ends with void then refund at net zero; webhooks are verified (if S5 passed) or the reconciler is the only path; payload ladder at the S4 level; bids go through quote parsing with merchant confirmation and reconciliation flags; lot handlers award and open checkout from real bids; merchant API keys and MerchantAuth pass PT-15; Buyer UI v1 completes an entry through the receipt |
| IT-7 | IG-7 | Full live flow with at least three real Sandbox buyers: entries, close, seed, allocation, two lots; a merchant bids through the console with a pasted quote and a second merchant through an API key; award; checkout with the SDK popup (if S13 passed) or redirect; one offer expires and refills; lot 1 is FUNDED; lot 2 ends with void then refund at net zero; the agent API and the FairPool MCP server join, list and withdraw an entry; the merchant-lane search and the LOW_SIMILARITY flag work; the ops console shows both lots; no manual database edits |
| IT-8 | IG-8 | Fulfillment CSV, shipments (tracker submitted if S12 passed), the verification manifest and the live verification endpoint work for a FUNDED lot; the PayPal MCP read-only verification (or the endpoint) confirms totals; the merchant console tabs work against the real backend; the Merchant Agent API has ten operations; observability, security and rate limits pass; a simulation pool of 10,000 entries allocates in under 10 seconds; S9 is recorded |
| IT-9 | IG-9 | All test layers are green: the fault suite F1 to F30 (F17 and F18 as disclosed limits), the Sandbox contract suite C-01 to C-18, concurrency and property suites and the AI evaluation baseline; the public audit page and verify-my-place reproduce the vectors; the README draft is complete; feature freeze, after which only fixes merge |
| IT-10 | IG-10 | Two consecutive clean end-to-end rehearsals from `make demo-reset` with no manual database intervention; SDKs generated and smoke-tested; Devpost text drafted; the demo video recorded; tag `rc1` |
| IT-11 | IG-11 | Submission verified: repository, license, video and links open while logged out; Devpost fields complete; no edits after the deadline |

## 4. Fault matrix (F1 to F30)

Each failure has a named test under `backend/tests/faults/` (or the layer shown). A test fails if the invariant in the last column is violated.

| ID | Test | Layer | Protects |
|---|---|---|---|
| F1 | `test_f01_authorize_timeout_unknown_outcome` | faults | I7, I9 |
| F2 | `test_f02_webhook_lost_reconciler_heals` | faults | I4 |
| F3 | `test_f03_duplicate_webhook_ignored` | faults | I9 |
| F4 | `test_f04_webhooks_out_of_order_monotonic` | faults | I10 |
| F5 | `test_f05_approval_after_seat_expired_never_authorizes` | faults | I1, I7 |
| F6 | `test_f06_approved_tab_closed_reconciler_continues` | faults | I1 |
| F7 | `test_f07_capture_pending_not_paid` | faults | I4 |
| F8 | `test_f08_captures_decline_refill_or_fail` | faults | I5 |
| F9 | `test_f09_late_capture_after_failure_refunded` | faults | I4, I5 |
| F10 | `test_f10_authorization_expired_vacancy` | faults | I8 |
| F11 | `test_f11_offer_expires_mid_checkout_fails_lot` | faults | I3 |
| F12 | `test_f12_merchant_withdraw_ops_abort` | integration | none |
| F13 | `test_f13_requote_new_attempt_old_order_abandoned` | faults | I3, I9 |
| F14 | `test_f14_concurrent_joins_one_entry` | concurrency | I6 |
| F15 | `test_f15_agent_and_human_same_account_one_entry` | concurrency | I6 |
| F16 | `test_f16_relink_blocked` | integration | I6 |
| F17 | `test_f17_disclosed_limit_multiple_accounts` | unit (README and UI copy) | I13 |
| F18 | `test_f18_disclosed_limit_omitted_entry` | unit (README and UI copy) | I13 |
| F19 | `test_f19_ai_misparse_caught_by_confirmation` | integration | I3 |
| F20 | `test_f20_prompt_injection_no_effect` | ai_eval and integration | I2 |
| F21 | `test_f21_token_expiry_refresh_once` | faults | none |
| F22 | `test_f22_paypal_429_5xx_backoff_same_key` | faults | I9 |
| F23 | `test_f23_worker_killed_mid_sweep` | faults | I9, I10 |
| F24 | `test_f24_refund_fails_lot_stays_failing` | faults | I5 |
| F25 | `test_f25_wrong_currency_or_country_rejected` | integration | I3 |
| F26 | `test_f26_clock_skew_database_clock_only` | integration | I15 |
| F27 | `test_f27_beacon_down_selection_waits` | integration | I11 |
| F28 | `test_f28_payee_mismatch_rejected` | integration | I1 |
| F29 | `test_f29_double_click_two_tabs_one_order` | concurrency | I9 |
| F30 | `test_f30_funding_source_denied_vacancy` | faults | I8 |

## 5. Checklist mapping

| Checklist item | Covered by |
|---|---|
| 0.1, 0.2 credentials | T00A02; secret scan in CI; log redaction test |
| 1.1 Sandbox only | Host guard unit test (`ForbiddenHost`) |
| 1.2 scopes | Startup self-check test logs names, never values |
| 1.3, 1.4 NVP/SOAP balance and Express Checkout setup | Not used: legacy API unrelated to Orders v2 (`docs/system-design.md` section 3.1) |
| 2.1 to 2.6 approve, authorize, void, capture, refund | C-08, C-09, C-10, C-11 |
| 2.7 decline or cancel | C-17 cancel path and F-tests; state machine does not depend on it |
| 2.8 minimum counts completed captures only | PT-09, IT-4, IT-6 |
| 3.1 to 3.4, 3.8 second seller | S3 recorded (failed); C-16 (S7) |
| 3.5 separate buyer orders | C-05 and IT-7 |
| 3.6 Payouts | Not used; static test that no Payouts endpoint appears in the adapter |
| 3.7 India domestic | F25 and C-13 |
| 4.1 to 4.3 Login and payer_id | S1 results; integration tests per `DEDUPE_MODE` |
| 5.1, 5.2 webhooks | C-15, F2, F3, F4 |
| 6.1 negative tests | C-06 and mock-response tests |
| 6.2 idempotent retries | C-03, C-10, PT-10 |
| 6.3 pool failure handling | IT-6 and IT-7 (void then refund then net zero) |
| FairPool rows: price cap, batching, allocation | PT-01, PT-02, PT-05, IT-4 |
| FairPool rows: AI extraction | AI evaluation sets and F19, F20 |
| FairPool rows: waitlist, concurrency, bots | PT-08, PT-12, PT-13, F14, F15, F29; bots remain a disclosed limit (F17) |
| FairPool rows: fairness audit | PT-03 and the audit page test |
| FairPool rows: MAP and inventory | Attestations only; outside the Sandbox |
| Integrations: search, MCP, Merchant API, SDK, Zapier, PayPal MCP, tracking | PT-14, PT-15, PT-16, C-17, C-18, IT-7, IT-8 |

## 6. Rules for writing tests

- Name the acceptance bullet in the test docstring (`# T04A02 acceptance 3`).
- Sandbox contract tests never mock PayPal, use USD 1.00, print no secrets, and clean up (void or refund) what they create.
- Unit tests that mock PayPal name the mock explicitly and are never used as evidence of PayPal behaviour.
- A test that needs the real model is marked `ai_eval`; everything else uses `FakeAI`.
- A bug fix lands with the failing test first.


## Vault-mode additions (`PAYMENT_MODE=vault_charge`, Oct 29)

The property and fault tests above keep their meaning; in vault mode the following also hold and are tested with the fake router and, where marked, real Sandbox:

- A charge never exceeds the awarded total and the awarded total never exceeds the buyer's cap, over random caps and prices (model-based).
- An unknown charge outcome is never retried under a new key; reconciliation by GET decides (fault test with a timeout after the order is created).
- A deleted or revoked permission yields a clean rejection and one vacancy refilled from the waitlist; a simulated decline does the same.
- The payment token never appears in logs, API bodies, audit rows, prompts or reports (VC-05).
- A lot that misses its minimum refunds every completed capture and deletes the saved permissions; the ledger nets to zero.
- Real Sandbox: VC-01 to VC-04 (`contracts/vault-charge.md` section 9).
