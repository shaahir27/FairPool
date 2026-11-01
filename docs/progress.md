# Progress

Living file, updated by both members. Each member edits only their own rows and entries (merge-conflict rule). Agents update the status of the task they are working on in their first commit and at merge.

Status values: `TODO`, `IN PROGRESS`, `IN REVIEW`, `DONE`, `BLOCKED`, `DEFERRED (owner decision)`.

## Project facts

| Item | Value |
|---|---|
| Repository URL | https://github.com/shaahir27/FairPool.git |
| Hosted URL (Render) | not yet recorded |
| Daily sync time (IST) | not applicable (solo operator) |
| Member A name and handle | solo operator @shaahir27 (both workstreams) |
| Member B name and handle | second member's name and GitHub handle not yet recorded; @shaahir27 previously operated both workstreams |
| ContextMatic plugin version (A, B) | Qoder: remote MCP ready (5 tools, 2026-10-30); Codex: .codex/config.toml staged; Antigravity: mcp_config.json present; no local version string |
| PayPal AI Toolkit plugin version (A, B) | Codex: paypal@paypal-ai-toolkit 1.2.0, installed and enabled (2026-10-30); Qoder/Antigravity: not supported — do not add the write-capable MCP |
| Current phase and gate | PH4 implemented on branch `phase-4` (three commits, unpushed); IG-4 NOT passed: independent review and remote CI are pending. PH3/IG-3 closed and tagged. |

## Gates

| Gate | Status | Tagged by | Notes |
|---|---|---|---|
| IG-0 | DONE | owner | tagged `ig-0`; CI green (run 41086853451); T00A02 complete; Codex PayPal 1.2.0 skills loaded (SSE MCP unavailable in Codex 0.164.0); public visibility deferred to T10A02/T11X01 |
| IG-1 | DONE | owner | tagged `ig-1`; IT-1 green locally and hosted: API https://fairpool-api.onrender.com, frontend https://fairpool-frontend.onrender.com; `/health` and `/ready` 200; webhook 200 with the raw body stored; Supabase free Postgres; Render Postgres deleted |
| IG-2 | DONE | owner | Closed on evidence, not by exception. `make gate-check GATE=ig-2` passes its automated chain and its whole evidence set; tagged `ig-2` with `contracts-v1.3`. The 95% threshold is met by recomputed fields (439 matched, 41 in review of 480 rows), the guard is proved by deterministic tests for every published variant, and the disclosures that keep this honest are in the evidence: 479 distinct live calls, 19 demo rows in review, and the owner's decision that contradictory demo cases may resolve to review. The earlier 2026-10-31 owner-exception closure is superseded. |
| IG-3 | DONE | owner | Phase 3 merged to `main`; `make gate-check GATE=ig-3` passes the full automated chain and the evidence set; tagged `ig-3`. Two items pass on recorded owner decisions rather than executed work and say so in the file: `s11` on the APIMatic waiver (OD-P3-2, rescheduled to T10A04) and `s5` as a spike record. |
| IG-4 | IN PROGRESS | not tagged | Phase 4 is implemented on `main` at `03a1483` with CI green (run 41307137778) and IT-4 passing, but the independent review returned NO: three blockers - vault PENDING can never resolve because the poll guard refuses BO-09/10 in vault mode; an unknown or timed-out outcome dead-ends because CAPTURING is never swept; a create-time 403 leaves a stuck seat with a deleted token - plus nine majors (try_fund dedupe swallowing events, close with a PENDING capture, capture status never updated, refill during FUNDING, mode guard after the provider call, authorize without the row lock, false hold notices, self-referential BO-24 checks, 500 on an approval/expiry race). Recorded in `docs/evidence/phase4/independent_review.json`. |
| IG-5 | TODO | not yet | |
| IG-6 | TODO | not yet | |
| IG-7 | TODO | not yet | |
| IG-8 | TODO | not yet | |
| IG-9 | TODO | not yet | |
| IG-10 | TODO | not yet | |
| IG-11 | TODO | not yet | |

## Tasks

### PH0: Bootstrap and contract freeze

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T00A01 | A | S | DONE | phase-0 | Repository bootstrap |
| T00A02 | A | S | DONE | phase-0 | Secrets hygiene (REST secret rotated twice; buyer password changed; NVP/SOAP disabled/none present; exposed dev-time token removed 2026-10-30) |
| T00A03 | A | S | DONE | phase-0 | API and worker skeleton, settings, host guard |
| T00A04 | A | S | DONE | phase-0 | Containers, CI and repo tools (CI and local Docker compose green) |
| T00B01 | B | L | DONE | phase-0 | Pure domain library with shared vectors |
| T00B02 | B | S | DONE | phase-0 | Spike S1 Log in with PayPal |
| T00B03 | B | S | DONE | phase-0 | Spike S7 payee-email routing |
| T00X01 | AB | M | DONE | phase-0 | Contract review and freeze (contracts-v1 tagged) |

### PH1: Data, platform and shell foundations

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T01A01 | A | L | DONE | phase-1 | Database foundation and migration 0001 (32 tables, 21 enums, 9 triggers, active-order partial index; `alembic check` green; 239 tests) |
| T01A02 | A | M | DONE | phase-1 | Platform services (DbClock, PostgresJobQueue, audit chain, idempotency; fakes; worker runner; 10 integration tests) |
| T01A03 | A | S | DONE | phase-1 | Hosted skeleton live: API https://fairpool-api.onrender.com, frontend https://fairpool-frontend.onrender.com; Render project fairpool; DB moved to free Supabase (session pooler), Render Postgres deleted; `/health`, `/ready`, webhook 200 + raw body; IT-1 green |
| T01A04 | A | S | DONE | phase-1 | Corrected S2 run 2026-10-31: 0 FAIL; O2 `PREVIOUSLY_VOIDED`; replay authorize 200 both; refund completed; four captures from failed attempts need manual refund. The Oct 20 RECORDED S2 result is unchanged. |
| T01B01 | B | M | DONE | phase-1 | API schemas, route-table test and Merchant API OpenAPI (80 parent + 10 merchant operations) |
| T01B02 | B | M | DONE | phase-1 | Port fakes and award fixture (17 tests; every port fake checked) |
| T01B03 | B | M | DONE | phase-1 | Frontend scaffold (17 routes, 14 tests, boundary rule, generated typed client) |
| T01B04 | B | S | DONE | | Spike S6 beacon and sandbox buyers (recorded Oct 29; see spike-results.md) |

### PH2: Core engines I: PayPal gateway, ledger, identity, catalog, AI adapter

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T02A01 | A | L | DONE | phase-2 | Raw REST gateway; offline retry/identity/tracker tests; real C-01 to C-07 7/7 passed on Sandbox with app-owning seller; S4 payload ladder remains T02A04 |
| T02A02 | A | M | DONE | phase-2 | Single-seller disclosure and simulation-first fake; denial/pending/revoked/timeout outcomes covered |
| T02A03 | A | S | DONE | phase-2 | Transactional ledger, exact net and distinct buyers; PostgreSQL replay/concurrency/rollback tests pass; PT-09's funding half needs the T04A03 engine (Q-2026-10-31-07) |
| T02A04 | A | S | DONE | phase-2 | C-01 to C-07 passed; S4 levels 1-2 passed, highest verified 2; level 3 (address lock) unverified; PAYPAL_PAYLOAD_LEVEL remains 0 |
| T02B01 | B | M | DONE | phase-2 | Buyer auth, Argon2id, signed 24-hour sessions, CSRF, revocation, auth limiter and unread notifications tested |
| T02B02 | B | M | DONE | phase-2 | Nested templates/zones/timelines; create/publish/cancel, frozen rules and pool.open; later handlers remain pending |
| T02B03 | B | M | IN REVIEW | phase-2 | Gemini adapter and 160 labelled cases; earlier v2 evaluation failed 154/480, and a later resumed v4 evaluation recorded 479/480 case checks meeting expectations. One consistent offer was routed to review; earlier capacity mismatches and automated acceptance/CI evidence remain open |
| T02B04 | B | S | DONE | phase-2 | PostgreSQL baseline recall@5 10/10; live Elastic hybrid passed with managed `.jina-embeddings-v5-text-small`: 20 docs/10 queries, recall@5 1.0, 205-387ms; temp index deleted; Elastic selected; `SEARCH_BACKEND=elastic`/`ELASTIC_INFERENCE_ID` applied in `.env`, `deploy/render.yaml` and live Render (`/ready` 200) |
| T02B05 | B | S | DONE | | Spike S13 JavaScript SDK v6 (recorded Oct 29; see spike-results.md) |

### PH3: Core engines II: buyer-order engine, seat control, join, search, PayPal Login, pool close

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T03A01 | A | L | DONE | | Buyer-order transition engine (CR-3 merged first); PT-07 runtime, PT-10, illegal-transition alert, effects rollback green |
| T03A02 | A | M | DONE | | Offer expiry and seat control; PT-12 model-based and F5 pass. `lot.refill` handler deliberately not implemented |
| T03A03 | A | S | IN PROGRESS | | Spike S5 webhooks (partly recorded Oct 28; CR-3 split stored/verified/processed. Four event types unreachable until Phase 4-5; `docs/evidence/phase3/s5.json` stays pending) |
| T03A04 | A | S | DONE | | Spike S10 PayPal MCP read-only verification (Oct 28-29 evidence reused, limits recorded) |
| T03A05 | A | S | DONE | | Spike S12 shipment tracking (Oct 28 evidence reused; no proof-of-delivery claim) |
| T03B01 | B | M | DONE | | Pool join, receipts and events, plus the CR-3 pull-forward of the deterministic manual confirmation and the public signing key |
| T03B02 | B | M | DONE | | Search service and indexer (Postgres live; Elastic implemented, never executed here — `OD-P3-3`) |
| T03B03 | B | M | DONE | | PayPal Login link flow (port + fake provider; no real PayPal identity client exists yet) |
| T03B04 | B | S | DONE | | Pool close, plus the close-time public audit fields |
| T03B05 | B | S | DONE | | Spike S11 closed on the owner waiver recorded in OD-P3-2 (2026-11-01): no trial, no generation. The ten-operation OpenAPI document is validated; trial, generation and licensing move to T10A04 |

### PH4: Core engines III and the first integration

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T04A01 | A | M | DONE | phase-4 | lot.open_checkout creates one OFFERED order per seated entry under the lot lock, refills vacancies from the waitlist without overselling (I8, PT-08), and sets deadlines per mode: offer timer in authorize mode, funding deadline in vault mode |
| T04A02 | A | L | DONE | phase-4 | FR-CK-05 approval checks (payee email, amount, currency, payer country, payer key) and order.authorize under the buyer-order lock; an unknown outcome stays AUTHORIZING and is never retried under a new key; rejected orders never authorize (F5) |
| T04A03 | A | L | DONE | phase-4 | Funding trigger with CAPTURE_BUFFER, slot-limited capture sweep, PENDING never counted as paid; FUNDED only when completed captures from distinct buyers reach the MOQ (I5, PT-09, F7, F8) |
| T04B01 | B | L | DONE | phase-4 | Intake: candidate search over public documents only, closed-schema AI parse, deterministic validation, one question per turn then the manual form, server-rendered card, and confirm that delegates to ManualIntakeService; CR-4 `intake_proposals` keeps a proposal owner-bound (F19) |
| T04A04 | A | M | DONE | phase-4 | Beacon adapter and pool.seed: a demo pool takes the labelled demo seed, a live pool announces a drand round and re-queues instead of inventing a value (F27); fetch and signature verification remain `NotImplementedError`, which the S6 check records |
| T04A05 | A | L | DONE | phase-4 | Allocation over the existing pure fairness code: zone order, lots with lot_order, undersized lots cancelled through LS-12, ordered waitlist, and the real AllocationReadService with next_candidates (PT-01, PT-02) |
| T04A06 | A | S | DONE | phase-4 | Public audit now carries lots, beacon, seed_hex, seed_is_demo and the award summary with no personal data, salts, caps or entry ids. Edited `api/routers/public.py`, a B-owned file, under solo operation - recorded in Requests |
| T04X01 | AB | L | DONE | phase-4 | The real AllocationReadService and MerchantDirectory are wired into checkout through `wiring.py`; force-award applies the CR-4 admin.force_award transition; IT-4 passes (1 passed) |

### PH5: Real PayPal path, auction core and merchant foundation

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T05A01 | A | L | TODO | | Real PayPal path for one buyer (redirect) |
| T05A02 | A | L | TODO | | Checkout UI |
| T05A03 | A | M | TODO | | Failure path and compensating refund (fake router) |
| T05A06 | A | M | TODO | | Merchant profile and onboarding states |
| T05A04 | A | L | TODO | | Bid API with receipts and sealing |
| T05A05 | A | L | TODO | | Auction rules engine |

### PH6: Money completion and auction to checkout

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T06A01 | A | L | TODO | | Funding sweep and failure path on the real Sandbox |
| T06A02 | A | M | TODO | | Webhooks |
| T06A03 | A | L | TODO | | Reconciler and unknown-outcome resolution |
| T06A04 | A | M | TODO | | Payload ladder levels and shipping address |
| T06B01 | B | M | TODO | | Quote parsing and confirmation |
| T06A05 | A | M | TODO | | AI offer reconciliation and flags |
| T06A06 | A | L | TODO | | Lot handlers: bid_open, bid_close, award |
| T06A07 | A | M | TODO | | Merchant API keys and MerchantAuth |
| T06B05 | B | L | TODO | | Buyer UI v1: Discover and Join |

### PH7: Live end to end and the agent and merchant lanes

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T07A01 | A | L | TODO | | JavaScript SDK v6 approval |
| T07A02 | A | M | TODO | | Refill orchestration |
| T07A03 | A | S | TODO | | Routers per S3 and S7 |
| T07A04 | A | L | TODO | | Ops console v1 |
| T07B01 | B | L | TODO | | Buyer UI v2: My Pools and Orders |
| T07A05 | A | L | TODO | | Agent API and delegations |
| T07B03 | B | M | TODO | | FairPool MCP server |
| T07A06 | A | M | TODO | | Merchant Agent API sub-app: lots and bids |
| T07B05 | B | M | TODO | | Search in the merchant lane and advisory similarity |
| T07X01 | AB | L | TODO | | Live end-to-end integration |

### PH8: Fulfillment, verification, merchant console and simulation

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T08A01 | A | L | TODO | | Fulfillment backend: progress, fulfillment, shipments, manifest, verification |
| T08A02 | A | M | TODO | | Fulfillment tab UI |
| T08A03 | A | M | TODO | | Merchant Agent API: fulfillment, shipments, manifest and verification routes |
| T08A04 | A | M | TODO | | PayPal MCP verification copilot |
| T08A05 | A | M | TODO | | Observability |
| T08A06 | A | M | TODO | | Security pass |
| T08B01 | B | L | TODO | | Merchant console UI I: Demand Board and bid submission |
| T08B02 | B | L | TODO | | Merchant console UI II: Active Bids and Developer API |
| T08B03 | B | S | TODO | | Spike S9 Zapier MCP managed mode |
| T08B04 | B | L | TODO | | Simulation engine |
| T08B05 | B | S | TODO | | Zapier bridge setup and documentation |

### PH9: Hardening, evaluation and feature freeze

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T09A01 | A | L | TODO | | Fault-injection suite |
| T09A02 | A | M | TODO | | Sandbox contract suite complete |
| T09A03 | A | M | TODO | | Deployment hardening and demo tooling |
| T09A04 | A | S | TODO | | STRETCH: top-up after FUNDED |
| T09B01 | B | L | TODO | | Public audit page and verify-my-place |
| T09B02 | B | L | TODO | | AI evaluation sets and runner |
| T09B03 | B | M | TODO | | Concurrency and property suites for pools, allocation and auction |
| T09B04 | B | M | TODO | | UI polish and honesty copy |
| T09X01 | AB | L | TODO | | README full draft |
| T09X02 | AB | M | TODO | | Feature freeze and IT-3 |

### PH10: Rehearsals and release candidate

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T10A01 | A | M | TODO | | Fixes from rehearsal 1 (payments, ops, fulfillment) |
| T10A02 | A | M | TODO | | Repository cleanup and compliance |
| T10A03 | A | M | TODO | | Devpost text |
| T10A04 | A | M | TODO | | Merchant SDKs and developer portal |
| T10B01 | B | M | TODO | | Fixes from rehearsal 1 (product, UI, agent lane) |
| T10B02 | B | L | TODO | | Demo video |
| T10X01 | AB | M | TODO | | Rehearsal 1 |
| T10X02 | AB | M | TODO | | Rehearsal 2 clean run |

### PH11: Submission

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T11X01 | AB | M | TODO | | Final checks and submit |
| T11X02 | AB | S | TODO | | Post-submit verification |

## Velocity log

Record planned versus actual days per phase and member at each gate. The plan is re-estimated at IG-4 (`docs/implementation-plan.md` section 4).

| Phase | Member A planned | Member A actual | Member B planned | Member B actual |
|---|---|---|---|---|
| PH0 | 1.25 | not yet recorded | 1.75 | not yet recorded |
| PH1 | 2.00 | not yet recorded | 1.75 | not yet recorded |
| PH2 | 2.00 | not yet recorded | 2.00 | not yet recorded |
| PH3 | 2.25 | not yet recorded | 2.00 | not yet recorded |
| PH4 | 3.00 | not yet recorded | 3.25 | not yet recorded |
| PH5 | 2.50 | not yet recorded | 2.50 | not yet recorded |
| PH6 | 3.00 | not yet recorded | 3.50 | not yet recorded |
| PH7 | 3.25 | not yet recorded | 4.00 | not yet recorded |
| PH8 | 3.50 | not yet recorded | 3.50 | not yet recorded |
| PH9 | 3.00 | not yet recorded | 3.75 | not yet recorded |
| PH10 | 2.50 | not yet recorded | 2.00 | not yet recorded |
| PH11 | 0.38 | not yet recorded | 0.38 | not yet recorded |

## Open questions

| ID | Raised by | Question and the two readings | Source of each reading | Status |
|---|---|---|---|---|
| Q-O1 | owner | Spike S2 result lists authorize as COMPLETED: is that the order status or the authorization object's status? Contract expects the authorization status CREATED | `docs/spike-results.md` S2 | answered Oct 27 from checklist 2.2 and 2.3 (authorization CREATED, order COMPLETED); T01A04 re-confirms in code |
| Q-O2 | owner | Exact issue name in the void-replay 422 body | `docs/spike-results.md` S2 | answered 2026-10-31: `PREVIOUSLY_VOIDED` (HTTP 422); capture after void `AUTHORIZATION_VOIDED` |
| Q-2026-10-30-06 | implementation | Replay authorize with the same `PayPal-Request-Id`: the earlier runs returned 201; the corrected 2026-10-31 run returned 200 on both orders. Does `AUTHORIZE_USE_REQUEST_ID=true` still hold? | `docs/spike-results.md` S2, `docs/decisions.md` §4 | answered 2026-10-31: 200 on both after the app-owner fix; the 201s were under the wrong app owner; switch stays `true` |
| Q-S7 | owner | Does an order addressed to a second sandbox business account by payee email approve and authorize (S7)? Owner decides whether the demo uses `payee_email` | `docs/spikes.md` S7 | answered Oct 28: no. Separate seller captures arrive but void and refund are denied; `payee_email` rejected, `single_seller` final |
| Q-D1 | owner | Confirm the assumed design decisions D1 to D11 in `docs/decisions.md` section 2 (stack, operator-defined pools, and the rest) | `docs/decisions.md` | answered at T00X01 |
| Q-2026-10-30-01 | implementation | `lot_index` numbering base: `db-schema.md` says "position within the zone"; `fairness-and-hashing.md` section 5 and N7 do not state 0- or 1-based. T00B01 uses 0-based index and 1-based `lot_order`. | `docs/contracts/db-schema.md`, `docs/contracts/fairness-and-hashing.md` | open; T04A04 confirms before persistence |
| Q-2026-10-30-02 | implementation | Semantic graph refresh needs a valid LLM key; the AST-only graph is committed and usable for code queries. | `graphify-out/GRAPH_REPORT.md` | open; not a PH0 gate blocker |
| Q-2026-10-30-03 | implementation | `db/models/*` (per area) versus per-module `models.py`: chosen per-area for one metadata and no cross-lane imports; schema content is unchanged. | `docs/implementation-plan.md` T01A01, `docs/contracts/db-schema.md` | answered by plan approval |
| Q-2026-10-30-04 | implementation | `chk_usd_only` has no currency column to check; implemented as a null-safe JSON check on pool templates and canonical requests. | `docs/contracts/db-schema.md` | answered by plan approval |
| Q-2026-10-30-05 | implementation | `vault_tokens` has no named index for "one active token per entry"; added a partial unique on `entry_id WHERE deleted_at IS NULL`. | `docs/contracts/db-schema.md` | answered by plan approval |
| Q-2026-10-31-07 | implementation | T02A03/IT-2 say "PT-09 passes for the ledger", but PT-09 is a lot-funding property and the funding engine is T04A03 (PH4). Reading (a): only the ledger half (completed captures from distinct buyers, PENDING excluded) is required now; reading (b): the whole property waits for T04A03. The ledger query and its completed/distinct-buyer tests exist; no funding transition exists yet. | `docs/implementation-plan.md` T02A03 and T04A03; `docs/testing-strategy.md` PT-09 | open; PT-09 lands with T04A03 |

| Q-2026-10-31-08 | implementation planning | Phase 3 join accepts confirmed_request_id, but no persisted confirmed request exists and full intake is T04B01. Recommend pulling forward only deterministic manual confirmation plus a private confirmed_requests record in migration 0003. | api.md Entry/Intake; db-schema.md; T03B01/T04B01 | resolved by CR-3 (contracts-v1.2): deterministic manual confirmation plus a private confirmed_requests record in migration 0003 |
| Q-2026-10-31-09 | implementation planning | Vault permission needs entry_id, so ACTIVE-before-entry is circular. Recommend SUBMITTED entry then consent/save and close-time eligibility; specify durable setup attempts, safe restart identities, callback fencing and fake-only Phase 3 lifecycle while real saving remains T05A01 onward. | vault-charge.md sections 2-5; db-schema.md vault_tokens; implementation-plan.md change set C1 | resolved by CR-3: SUBMITTED entry and receipt, then consent/save, then ACTIVE permission, eligibility at close; attempt-scoped keys, callback fencing, quarantine, fake-only in Phase 3 (DEP-5) |
| Q-2026-10-31-10 | implementation planning | Clock.db_now and entry-window trigger use transaction-start now(); a transaction that waits across close_at can admit late while pool.close is delayed. Recommend fresh database wall-clock checks after locks and a new trigger-function migration, retaining canonical/audit timestamp formats. | domain-ports.md Clock; db-schema.md admission trigger; infra/clock.py; migration 0001 | resolved by CR-3: Clock.db_wall_now after locks, entry-window trigger replaced in migration 0003, lock-wait regression required before the change |
| Q-2026-10-31-11 | implementation planning | Phase 3 close must publish commitments, but audit/key routes are stubs; overdue pool.open can leave PUBLISHED unable to follow PS-03. Recommend bringing forward close-time public reads and an atomic whitelisted OPEN/CLOSED catch-up with no late admission. | T03B04/T04A06; api.md public audit/keys; state-machines.md PS-02/PS-03 | resolved by CR-3: signing-key route and close-time audit fields move to T03B01/T03B04; overdue pools catch up through PS-02 then PS-03 under the pool lock with no late admission |
| Q-2026-10-31-12 | gate planning | The owner closed IG-2 by exception on 2026-10-31. Gemini acceptance and CI evidence remain pending; PT-14's full award comparison also needs a later award engine. | implementation-plan.md PH3 entry; testing-strategy.md PT-14/IT-3; Phase 2 evidence | resolved 2026-11-01: IG-2 closed on automated evidence with contracts-v1.3; PT-14 split by OD-P3-1 |
| Q-2026-10-31-13 | implementation planning | OAuth states lack session binding and S1 does not establish arbitrary ID-token nonce validation. S5 requires verified receipts, but the current receiver stores unverified bodies and processing is scheduled later. Specify session/nonce verification and receipt-only scope without enabling absent money handlers. | T03B03/T03A03; db-schema.md oauth_states; api.md; PayPal S1/S5 evidence | resolved by CR-3: session-bound single-use state with OAUTH_STATE_TTL_S, PayPalIdentity port, nonce claimed only as far as S1 evidence supports; webhook ingest stores always and processes only when verified, no money handler enabled in Phase 3 |
| Q-2026-10-31-14 | integration planning | S11 asks for live submit_bid/progress SDK smoke tests before those handlers exist. Recommend labelled contract-stub serialization smoke now, with real workflow smoke explicitly pending for its implementation phase; do not start a trial without owner approval. | spikes.md S11; T03B05 and later merchant/bid tasks | acceptance split recorded by OD-P3-2: offline generation and licence notes may be recorded; resolved by the owner on 2026-11-01: the trial is waived for IG-3 and rescheduled to T10A04 (OD-P3-2); no generation or licence claim is made |

| Q-2026-11-01-15 | implementation planning | `docs/spike-results.md` S5's neighbour S6 is headed "RECORDED Oct 29" but its body is only the "Record:" template: no chain hash, round period, round number or verified round value. `decisions.md` section 4 records `BEACON_MODE=drand` and says signature checks succeeded. Reading (a): the values exist somewhere and were not pasted; reading (b): the spike was never completed. Phase 4 does not decide it: `pool.seed` uses the demo seed unless `DRAND_BASE_URL` and `DRAND_CHAIN_HASH` are configured, and a read-only drand check is attempted at IG-4. | `docs/spike-results.md` S6; `docs/decisions.md` section 4; `modules/pools/seed.py` | open, narrowed 2026-11-01: the read-only check found `DRAND_BASE_URL`/`DRAND_CHAIN_HASH` absent from `.env` (commented placeholders only) and from the environment, so S6 records `not configured` and no round was fetched or invented. It also found that `cryptography` 50.0.2 has no BLS12-381 verify primitive and `BeaconAnnouncement.fetch` raises `NotImplementedError`, so a configured chain would still need a BLS library and the fetch path before any signature claim is possible. `BEACON_MODE=drand` stays unexecutable here; record a real round before claiming a live beacon |

## Requests to the owner

| Date | From | Request | Status |
|---|---|---|---|
| 2026-10-30 | owner | REST secret rotated again after the dev-time token exposure; buyer password changed; NVP/SOAP disabled or none present; Codex chat deleted. Recorded as complete 2026-10-30 without values. | DONE |
| 2026-10-30 | owner | GitHub CLI is installed and authenticated; Docker Desktop is still absent locally, but the CI compose job passed. Install Docker only for local compose. | DONE |
| 2026-10-30 | owner | Keep the repository private until the final submission QA (T10A02/T11X01); make it public before the Nov 12 deadline and verify logged-out access (FR-HK-01). | DEFERRED to T10A02/T11X01 |
| 2026-10-30 | owner | Qoder ContextMatic ready; Codex PayPal AI Toolkit 1.2.0 installed with skills loaded; live SSE MCP unavailable in Codex 0.164.0 (recorded, not a gate blocker); Antigravity ContextMatic config present. | DONE |
| 2026-10-30 | owner | **IG-1 deployment:** live on Render free (API + static, project `fairpool`); services created via the Render API because Blueprint creation is dashboard-only; Supabase free Postgres; Render Postgres deleted after the switch; IT-1 green. Free web sleeps, no free worker. | DONE |
| 2026-10-30 | owner | S2 app-owner fix: new REST app under the business seller; `SINGLE_SELLER_EMAIL` aligned; corrected run 0 FAIL; O2 `PREVIOUSLY_VOIDED`. | DONE |
| 2026-10-31 | owner | Refund the four USD 1.00 captures from the two failed S2 attempts in the previous seller account; details in `spike_out/spike_report.md` and `spike_out/s2_rerun/spike_report.md`; do not resubmit through the harness. | OPEN |
| 2026-10-31 | owner | Disable or regenerate the NVP/SOAP password/signature visible in the app screenshot; FairPool does not use NVP/SOAP and they are not the REST client secret. | OPEN |
| 2026-10-31 | owner | Supabase free Postgres chosen; schema applied, Render API `DATABASE_URL` switched, Render Postgres deleted. Free project pauses after about 7 days of inactivity. | DONE |
| 2026-10-31 | owner | Decide the judging database: `docs/demo-and-submission.md` says paid Render Postgres for judging; free Supabase conflicts. Either update that rule and add a keep-alive, or move to a paid DB before Dec 1. | OPEN |
| 2026-10-31 | owner | Revoke the temporary Render API key in Account Settings after the deployment work is finished. | OPEN |
| 2026-10-31 | owner | Gemini API key: full live run failed 154/480 (48.3%); the free-tier daily limit of 500 requests is exhausted (429, retry ~21h). Prompt v3 and diagnostics are ready; provide a quota-enabled key or wait for reset. | OPEN |
| 2026-10-31 | owner | S4 payload ladder: highest verified level 2; level 3 (address lock) unverified, no further approval requested. | DONE |
| 2026-10-31 | owner | S8: Elastic hybrid passed (recall@5 1.0 vs PostgreSQL 1.0, 205-387ms) with managed `.jina-embeddings-v5-text-small`; temporary index deleted; Elastic selected. | DONE |
| 2026-10-31 | owner | Set `SEARCH_BACKEND=elastic` and `ELASTIC_INFERENCE_ID=.jina-embeddings-v5-text-small` in `.env`, `deploy/render.yaml` and live Render; env group and service verified via API; deploy live; `/health` and `/ready` 200. | DONE |
| 2026-10-31 | owner | Push the contract CR, `phase-2` and the tags to GitHub and run remote CI. | OPEN |

## Requests between members

| Date | From | To | Request | Status |
|---|---|---|---|---|
| 2026-11-01 | A | B | `T04A06` now ships only the lot, beacon, seed and award content of the public audit payload; the route file `api/routers/public.py` stays B-owned and already carries the keys and close-time fields from Phase 3. Add the fields through the B-owned router rather than editing it from A. | SUPERSEDED by the row below: the content landed, but by editing B's file under solo operation |
| 2026-11-01 | A | B | `db/safety.py` requires a loopback `*_test` database; the local stack has no `fairpool_test`, so `make test` errors on 36 tests unless it is created. Created locally on 2026-11-01; `make setup` should provision it so a clean clone is green. | OPEN |
| 2026-11-01 | A (solo operator) | B | `api/routers/public.py` is B-owned in `api.md` section 2, and `T04A06` edited it in Phase 4 to add the `lots`, `beacon`, `seed_hex`, `seed_is_demo` and `award` content. The edit happened under solo operation (`@shaahir27` holds both lanes), so no other member's unmerged code was touched, but the file is still B's: when B returns as a separate owner, those changes need B's review rather than being treated as pre-approved. This supersedes the open Phase 4 row above. | RECORDED (solo operation) |

## Blockers

| Date | Member | Task | Blocker | Resolution |
|---|---|---|---|---|
| 2026-10-30 | owner | T00A02 / IG-0 | Closed 2026-10-30: security steps complete; IG-0 tagged; Codex PayPal 1.2.0 skills recorded; live MCP unavailable in Codex 0.164.0; public visibility deferred to submission QA. | closed |
| 2026-11-01 | owner | T03B05 / S11 / IG-3 | `IT-3` requires the APIMatic trial to start in Phase 3, and `Q-2026-10-31-14` forbids starting it without the owner. Generation and licence notes can be recorded offline; the trial and any live SDK smoke cannot. | OPEN — owner action: authorise or defer in writing (OD-P3-2). IG-3 must not be tagged while this is unresolved. |
| 2026-11-01 | A | T03A03 / S5 | Three of the seven contracted webhook event types (`CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.PENDING`/`DENIED`) cannot be produced before authorize, capture and void handlers exist in Phase 4-5. | OPEN — recorded per event type, which `spikes.md` S5 explicitly allows; not a Phase 3 failure. |
| 2026-11-01 | B | T03B02 / OD-P3-3 | The Elastic half of the search parity test needs a cluster; the S8 cluster's provenance, credentials and trial dates are not recorded, and the plan says spend nothing without the owner. | OPEN — Postgres path is the CI proof; the Elastic half runs only where credentials exist and is labelled when it does not. |

## Decisions log

| Date | Decision | By | Recorded in |
|---|---|---|---|
| 2026-10-30 | Single `phase-0` branch from an empty `main` base; one pull request; all PH0 tasks are sequential commits on the branch. | owner | progress.md, plan |
| 2026-10-30 | Ruff excludes legacy spike/validation scripts; backend and the new repository tools are linted. | owner | progress.md |
| 2026-10-30 | pip-compile 7.6.2 lacks `--universal`; hashed locks are generated on Windows and verified by the Linux CI install. | owner | progress.md |
| 2026-10-30 | `cryptography` is allowed only in `domain/hashing.py`; `check_imports.py` enforces the module-scoped exception. | owner | progress.md, scaffold section 5 |
| 2026-10-30 | gitleaks allowlists the fairness vectors and three mock-fixture spike test files by exact path; no broad allowlist. | owner | .gitleaks.toml, progress.md |
| 2026-10-30 | Codex is the agent platform: `AGENTS.md` plus `.codex/skills/graphify`; no `CLAUDE.md`. The graph is rebuilt with `graphify extract .` and committed. | owner | progress.md, scaffold section 9 |
| 2026-10-30 | The host guard lives in `config.py` so PH0 has no adapter dependency; T02A01 reuses it. | owner | progress.md |
| 2026-10-30 | CI fixes: build tools pinned in the hashed locks, CSV tuple envs decoded by a validator, gitleaks CLI in CI, and compose `--env-file .env`. All nine checks pass. | owner | progress.md, .github/workflows/ci.yml |
| 2026-10-30 | Graphify semantic extraction failed with the configured Gemini key; the committed graph is the AST-only update (1487 nodes / 2447 edges) and excludes `.env`. A later `graphify label` refreshes names when a valid key is set. | owner | progress.md, graphify-out/GRAPH_REPORT.md |

| 2026-10-30 | Qoder ContextMatic uses HTTP transport (SSE failed at runtime); status ready with 5 tools. | owner | progress.md, .mcp.json |
| 2026-10-30 | Local Docker stack verified (API health 200, DB extensions, worker, frontend); containers run from source with PYTHONPATH and pip retries. | owner | progress.md, deploy/Dockerfile.api, deploy/Dockerfile.worker |

| 2026-10-30 | Local `.env` `DATABASE_URL` uses `127.0.0.1` for host-side Alembic/tests; compose overrides it to the `db` service for api/worker. | owner | progress.md, deploy/docker-compose.yml |
| 2026-10-30 | Models live in `db/models/*` grouped by area (one metadata, no cross-lane imports); `chk_usd_only` is a null-safe JSON check on `pools.template` and `pool_entries.canonical_request`; `vault_tokens` has a partial unique on `entry_id WHERE deleted_at IS NULL`; `asyncpg` added and locks regenerated. | owner | progress.md |
| 2026-10-30 | The Merchant Agent sub-app declares routes relative to its `/merchant-api/v1` mount; `tools/export_merchant_openapi.py` prefixes the paths for the APIMatic document (`sdk/merchant-openapi.json`). | owner | progress.md, tools/export_merchant_openapi.py |
| 2026-10-30 | Commit strategy per owner: two commits only, one meaningful commit for the A workstream and one for the B workstream; task IDs stay in the bodies. The branch is not pushed until both are assembled. | owner | progress.md |
| 2026-10-30 | Frontend uses React Router 6.28; `npm audit` reports two moderate production advisories whose fix is Router 7. The scaffold has no live data; revisit Router 7 at T09B04. | owner | progress.md, frontend/package.json |
| 2026-10-30 | Graph output is local-only: `graphify-out/` is git-ignored and removed from the repository per owner. The local AST graph has 2,591 nodes / 5,139 edges / 177 communities; `.graphifyignore` excludes `.env`; the three value matches were the shared project word `fairpool`, not secrets. | owner | progress.md, .gitignore |
| 2026-10-30 | Render free tier chosen for the PH1 skeleton: free API web service, free Postgres, free static site, no worker. Free web sleeps after 15 minutes, free Postgres expires after about 30 days, and there is no free worker; the worker and paid instances must return by 2026-11-20 (BD-05) for the live demo. | owner | progress.md, deploy/render.yaml, README.md |
| 2026-10-30 | Codex 0.164.0 loads the PayPal plugin skills but not its SSE MCP tools; the plugin version is recorded and live MCP is optional, not a PH0 blocker. | owner | progress.md, AGENTS.md |
| 2026-10-30 | Exposed dev-time PayPal access token removed from Codex config; Sandbox client secret rotated again; no value recorded. | owner | progress.md |
| 2026-10-31 | Hosted skeleton uses free Supabase Postgres (session pooler); Render API `DATABASE_URL` switched and Render Postgres deleted. Data API, automatic table exposure and automatic RLS are off. Paid DB decision for judging remains open. | owner | progress.md, README.md |
| 2026-10-31 | Owner approved one additional evidence commit after the two PH1 implementation commits (hosted IT-1 + Supabase); `ig-1` tags that commit. | owner | progress.md |

## Defects from rehearsals

| ID | Found in | Description | Owner | Status |
|---|---|---|---|---|
| D-P3-01 | PH3 | Some Phase 3 tests commit rows into the shared `fairpool_test` database (the 200-parallel join race and the PT-07 walk must commit for the race to be real). Count-based assertions in other files then depend on execution order. Fix: derive every expected count from the rows the test itself created, or give the committing tests their own database. | B | OPEN |
| D-P3-02 | PH3 | The `elasticsearch` client is not installed, so the live Elastic parity path cannot execute even where `ELASTICSEARCH_URL` is set. The skip now gates on the URL and on the client being importable, and prints which reason applied. Installing the pinned client remains a deliberate, lockfile-level decision. | B | CLOSED |
| D-P3-03 | PH3 | `GET /api/v1/pools/{id}/entries/me` reports `vault_status` and `vault_label` as null when `VAULT_TOKEN_KEY` is unset rather than failing. Deliberate: a buyer's own page must not break over an operator setting. Recorded so it is not later read as "no permission exists". | B | RECORDED |
| D-P3-04 | PH3 | The contracted 10-per-minute-per-user join limit is enforced per worker process (the pre-existing `AuthRateLimiter` shape, widened to sessions). Multi-process deployments see up to n times the rate. Disclosed limit, needs shared-store enforcement before it is claimed. | A | OPEN |
| D-P3-05 | PH3 | `make setup` does not create the loopback `fairpool_test` database `db/safety.py` requires, so a clean clone cannot run `make test` until someone creates it. Fix: add it to `setup` or to `deploy/db-init.sql`. | A | OPEN |
| D-P3-06 | PH3 | `.gitignore` lists `docs/evidence/` as disposable local output, yet the Phase 2 evidence files are tracked. `make gate-check` therefore reads a directory a clean clone does not have. Fix: drop the ignore rule and keep evidence committed (it is a gate record, not build output), or move the checks onto committed artifacts. Phase 3 evidence was force-added to follow the Phase 2 precedent. | A | OPEN |
| D-P3-07 | PH3 | `/api/v1/pools?q=` reached the search service only after the review pass: T03B02 shipped the service, indexer and reindex route while the public listing still ran a keyword `ilike`. Now routed through `SearchService` with one route-level test. | B | CLOSED |
| D-P2-01 | PH2 | Quote-capacity parsing can return a definite capacity from conflicting values; regression coverage still owed before unqualified AI demo acceptance. | B | OPEN |

## Submission notes

Devpost text draft, video link and the final checklist result are recorded here by T10A03, T10B02 and T11X01.

## Daily log

One line per member per day: date, member, what merged, what is next.

- 2026-10-30, owner: T00A02 complete; all PH0 tasks DONE; IG-0 tagged; Codex PayPal 1.2.0 skills recorded; Docker stack healthy; repo stays private until T10A02/T11X01. Next: PH1.
- 2026-10-30, owner: `phase-1` created; T01A01 complete (migration 0001: 32 tables, 21 enums, 9 triggers; `alembic check` green; 239 tests). Next: T01B01 and T01B02.
- 2026-10-30, owner: T01B01 complete (schemas, 80 parent + 10 merchant route stubs, route/OpenAPI contract tests; merchant artifact written). Next: T01B02/T01A02.
- 2026-10-30, owner: T01A02, T01B02 and T01B03 complete (platform services, ports/fakes, frontend shell; `make verify` and `gate-check GATE=ig-1` green locally). Next: owner Render deploy and S2 O2, then IT-1 and `ig-1`.
- 2026-10-31, owner: S2 corrected run 0 FAIL; O2 `PREVIOUSLY_VOIDED`; replay authorize 200 both; app-owner fix confirmed; four old captures refund pending; NVP/SOAP exposed credentials must be disabled; next hosted Render.
- 2026-10-31, owner: Render free deployment live (API + static, project `fairpool`); IT-1 green; DB switched to free Supabase and the Render Postgres deleted; docs updated; `ig-1` tagged. Next: PH2.
- 2026-10-31, owner: Real Sandbox C-01–C-07 7/7 passed after correcting the invalid C-04 capture expectation; S4 levels 1-2 passed (highest verified 2; level 3 unverified); Gemini key model lookup passes but live generation is blocked by 402 prepayment credits; S8 Elastic and remote CI remain pending.
- 2026-10-31, owner: Full Gemini run 480/480 with 154 errors and 48.3% field accuracy; free-tier daily 500 exhausted (429); prompt v3 and raw-output/subset diagnostics implemented; live Gemini rerun awaits quota.
- 2026-10-31, owner: Elastic endpoint tested live; local `.multilingual-e5-small` lacked ML capacity, but managed `.jina-embeddings-v5-text-small` hybrid RRF reached recall@5 10/10 at 205-387ms; temp index deleted; Elastic selected; `SEARCH_BACKEND=elastic`/`ELASTIC_INFERENCE_ID` applied to `.env`, `deploy/render.yaml` and live Render (`/ready` 200).

## Phase 2 execution record (2026-10-31)

The owner approved the Gemini/validation plan and exactly three phase commits,
including exactly one intermediate instructions/contracts commit (`e830966`).
The remaining two group payment/platform and identity/catalog/Gemini/evidence.
Contract amendments were independently reviewed in the working tree; no remote
merge or CI result is represented as completed before it occurs.

Foundation regressions found in PH1 were reproduced and repaired: handler writes
survived exceptions, unsupported jobs were consumed, expired claims lacked owner
fencing, cross-lot shipments were accepted, application errors lost their codes,
and gate tooling accepted unknown gates/failed to propagate failures reliably.
Migration 0001 and original product idea/historical spike results are unchanged.

Local verification: 352 backend tests passed with 98.60% domain coverage; 14
frontend tests, lint, types and production build passed. Fresh migration,
upgrade-from-0001 and both drift checks passed in a newly created disposable
database. Docs/imports/OpenAPI/types checks passed. Independent review repaired
hypothetical/negated flag false positives and stale-evaluation handling; final
focused rereview passed 38 tests. The later local run also covers evaluator
failure retention and exact field metrics. Evidence: `docs/evidence/phase2/README.md`.

C-01 to C-07 passed against Sandbox with the app-owning seller on 2026-10-31
(7/7); C-06 uses the documented PayPal-Mock-Response test header; no captures
or refunds. S4 verified levels 1-2; highest level 2, level 3 unverified. S8's
live Elastic hybrid test passed recall@5 10/10 (205-387 ms) with managed
`.jina-embeddings-v5-text-small`; the temporary index was deleted and Elastic is
selected; `SEARCH_BACKEND=elastic` and `ELASTIC_INFERENCE_ID` are set in `.env`,
`deploy/render.yaml` and live Render (`/ready` 200). The full Gemini live run failed 154/480 cases at 48.3% field
accuracy; the free-tier daily 500 limit is exhausted, so the prompt-v3 rerun
awaited a quota-enabled key at that time. The owner subsequently closed IG-2
by exception on 2026-10-31; it is not tagged and the automated acceptance
checks still report pending evidence. See the current gate row and Phase 2
verification record for the later Gemini evaluation. No paid deployment was
performed.

## IG-3 closure attempt (2026-11-01, second pass)

Asked to close the gate. What got done, and the two things that stopped it:

1. **Search dependencies are now real.** `elasticsearch` 9.5.1 and `aiohttp` 3.14.5 (with
   their transitive pins) went into `requirements.in` and both hash-locked files via
   `pip-compile`. No pre-existing pin moved - the diff is 791 added and 14 removed lines,
   all of them new packages - and `pip install --require-hashes --dry-run` resolves, so CI
   installs the official client. The live Elastic parity test still skips there because CI
   holds no cluster credentials, which is the honest outcome.
2. **Webhook listener: registered and verified, and two of my earlier claims were wrong.**
   `PAYPAL_WEBHOOK_ID` in `.env` is **empty**, not holding a stale October value as I first
   wrote, and the listener is not untraceable. What is actually true: PayPal's
   `GET /v1/notifications/webhooks` returns HTTP 200 with zero links on this app even for a
   listener that `GET` and `DELETE` by id handle normally, so only the list call is
   unreliable. Registering the seven contracted event types at
   `https://fairpool-api.onrender.com/webhooks/paypal?s5=live` returned 201 and the direct
   GET confirms all seven types on id `1UT33484SD059942U`. The plain URL answers
   `WEBHOOK_URL_ALREADY_EXISTS` because two orphan listeners hold it - the October one and
   a `?s5=1` created during this check - and their ids are not recoverable through the API,
   so clearing them is a dashboard action. Nothing was written to `.env` or Render: the
   owner sets the verified id. Signature verification therefore still has not been executed
   against a delivered event, and `s5` stays pending for that reason plus the four event
   types that cannot exist before Phase 4-5.

3. **APIMatic trial: cannot be delegated.** The 14-day trial is an account signup at
   apimatic.io (email, terms, per-language pricing afterwards) and no APIMatic credential
   exists locally. I will not create an account on your identity, and I will not present a
   simulated generation as a trial result. Either start it and hand me the token in `.env`,
   or waive it in one line and I amend `IT-3`.
4. **Nothing was tagged.** `make gate-check GATE=ig-3` runs the whole automated chain green
   and still exits 2 on `s5` and `s11`. `contracts-v1.2` also remains untagged: it is due
   under `contracts/README.md` section 0.2, but tagging was reserved until the gate
   requirements were met, and they are not.


## IG-3 evidence verification (2026-11-01)

Ordered work on the gate, executed rather than assumed:

1. **Pushed and verified CI.** `main` advanced `88105a0..a57804a`; remote CI runs
   41271936679 and 41272459105 finished with all nine jobs green, including Test (with the
   Alembic migration and drift check on a fresh `fairpool_test`). `ci.json` is now
   passed. No D-P3-01 flakiness appeared in CI.
2. **Webhook listener verified read-only, no secret printed.** Sandbox client
   credentials work (token obtained from `api-m.sandbox.paypal.com`).
   `GET /v1/notifications/webhooks` returns HTTP 200 with **zero listeners**, and the
   `PAYPAL_WEBHOOK_ID` held in `.env` matches nothing - it points at the temporary
   listener deleted in October. So signature verification cannot be executed until a
   listener is registered, which is a write to the owner's app and needs an explicit
   go-ahead. `s5.json` stays pending with that recorded precisely; the October partial
   record is untouched.
3. **Elastic checked per `OD-P3-3`.** Credentials exist and the cluster answers
   (version 9.5.5), so the live parity test ran for real and passed: the hybrid
   retrieval returned its own document and the `SearchHit` shape matched Postgres.
   Two findings came out of running it. The adapter indexes without an explicit refresh
   and Elastic is near-real-time, so the test now polls for visibility - the contract
   promises at-least-once indexing, never same-millisecond visibility. And `elasticsearch`
   plus `aiohttp` are **not** in the committed requirements: they are installed in this
   local venv only, so CI still skips that test with its printed reason. Putting them in
   the lockfile is an owner decision, not something to fold into a phase commit. The run
   created `fairpool-search-v1` on the cluster and deleted its test document, as S8 did.
4. **APIMatic checked against `OD-P3-2`, which says do not start without the owner.**
   No trial was started and no account was touched. What can be stated is unchanged:
   `sdk/merchant-openapi.json` validates at exactly ten operations, so the original
   October blocker ("no OpenAPI file exists") is gone, and generation plus licence terms
   remain unrecorded. `s11.json` stays pending.
5. **Suite re-run after the push:** 691 tests pass including the 8 fault tests, with the
   live Elastic parity test now executing locally.
6. **Deploy consequence recorded, nothing executed.** Pushing `main` leaves the hosted
   API running its own image; `render.yaml` has no pre-deploy command and
   `Dockerfile.api` runs uvicorn only, so nothing migrated the hosted Supabase schema.
   The hosted database is still at revision 0002 while the code now says 0003, so the
   deployed `/ready` probe will report migrations pending after its next rebuild, and no
   Phase 3 endpoint should be exercised on the hosted URL before a deliberate, authorised
   hosted migration. `healthCheckPath` is `/health`, so this does not break the container.

**`ig-3` is not tagged.** The documented gate rule is integration test green +
`make gate-check GATE=ig-3` green + tag pushed; the checker still refuses, on `s5` and
`s11`, both owner-gated. `contracts-v1.2` is separately due - `contracts/README.md`
section 0.2 requires tagging after a CR merges, and CR-3 has merged - and it has not been
created because tagging was explicitly reserved until the gate requirements are met.


## Phase 3 independent review (2026-11-01)

A read-only reviewer agent audited the `phase-3` diff against `AGENTS.md`, the
CR-3 contracts and the tests. It found 1 BLOCKER, 4 MAJOR and 8 MINOR issues, all
dispositioned below. None touched a money or safety invariant.

| ID | Finding | Disposition | Proof |
|---|---|---|---|
| B1 | `POST /api/v1/intake/manual` returned 500 - a raw `uuid.UUID` reached Starlette's `json.dumps`, and no test had ever posted to the route | Fixed: ids stringified as `join.py` already does; every other `JSONResponse(content=...)` on the branch audited | `tests/integration/test_intake_manual_route.py`, which fails on the unfixed code and passes after |
| M2 | The withdraw route ran provider I/O while still holding the `users` and `pools` row locks, because a savepoint release does not free them | Fixed as two phases: commit the entry withdrawal, then delete the permission on a fresh short transaction | ordering test in `tests/integration/test_vault_lifecycle.py` |
| M3 | uvicorn's access logger prints the full request target, so `?code=`, `?state=` and `?token=` could reach an unredacted log; our filter only covered the root handler | Fixed both ways: filter attached to `uvicorn.access`/`uvicorn.error`, `--no-access-log` in `deploy/Dockerfile.api`. While fixing it a second latent bug surfaced: `_OAUTH_PARAM` required a literal quote, so `code=`/`state=` were never masked anywhere | `tests/unit/test_log_redaction.py` |
| M4 | CR-3 text invented `PaymentRouter.charge_vault -> CaptureResult`; that type does not exist and the router has no such method | Contract corrected to reality (`ChargeResult` on the gateway, called by the `order.vault_charge` handler); no method added to satisfy a doc line | `docs/contracts/domain-ports.md` section 4.4 |
| M1 | The attempt-scoped keys CR-3 requires (`vs:{entry}:{attempt}`, `vp:{entry}:{attempt}`) could not reach the provider, so two save attempts of one entry collided on one idempotency key | Fixed: attempt identity threaded through `PaymentVaultProvider`, its fake, the gateway and `fakes/payments.py`, using the identity the attempt row already stores | two-attempts and retry-reuses-identity tests in `test_vault_lifecycle.py` |
| m1 | `has_active_permission` claimed in its docstring to mirror BO-27 while being stricter | Docstring corrected to the close-time rule and why it differs; charge behaviour untouched | - |
| m2 | `pool.open` decided on `db_now` after the lock while CR-3 note 1 requires `db_wall_now` | Fixed; the audit row keeps `db_now` | extended `tests/integration/test_pools.py` |
| m3 | `pool.seed` was enqueued with a dedupe key the job table says it does not have | Removed; the concurrency key kept | `test_close_commitments.py` |
| m4 | Public audit published `audit_checkpoints` before closure | Gated on CLOSED or later | the `test_public_audit_*` tests |
| m5 | A stale local error override in `entries.py` duplicated the shared map under a comment claiming the codes were missing from it | Deleted; the shared handler is used | join tests unchanged status codes |
| m6 | `enums.py` header claimed migration 0001 creates every enum type | Qualified for `vault_setup_status` (0003) | - |
| m7 | Docs named tests that did not exist: `test_illegal_transitions.py`, the F14/F15 function names, `test_f26_clock_skew_database_clock_only` | Real tests added or renamed so every documented name resolves | `tests/unit/test_illegal_transitions.py`, `test_f14_*`, `test_f15_*`, the F26 function |
| m8 | F15's stated "delegations row" half was not exercised - only a second human request | Made real: a `delegations` row drives the same entry service | `test_f15_agent_and_human_same_account_one_entry` |

Checked and found clean: integer-cent money everywhere (the only float is the
contract-permitted search score); no module outside `adapters/paypal/` calls
authorize/capture/void/refund; the engine makes no network call and treats a `paypal:`
field as metadata; "paid" only ever from a validated COMPLETED capture, never
`order.status` (V8); every whitelisted status change goes through `assert_transition`
with raise-and-alert and no direct `UPDATE ... SET status`; the wall clock is read after
the lock in engine, join, withdraw and close while receipts keep `db_now`; no seat is
released while AUTHORIZING, CAPTURING or CAPTURE_PENDING (PT-12); replay is distinguished
from illegal and conflicting with no duplicated effect (PT-10); vacancies come from rows
with one deduplicated refill and `lot_failing` excluded (I8); synthetic data never reaches
PayPal and the fakes build no HTTP client (I12); search is retrieval-only, drops stale or
private hits and never gates (PT-14); DEP-5 refuses before any half-write; and no Phase
4+ surface crept in.

Both failures this review caught were mine in origin: a route wired without a
route-level test, and a contract sentence the code could not carry. That is the argument
for the gate demanding an independent pass instead of trusting the implementing agent.

## Phase 3 execution record (2026-11-01)

Executed solo on branch `phase-3` in three authored commits, after the plan
review that produced CR-3. Skills applied: `ponytail` (scope and the smallest
complete change), `ponytail-review` and `verification-before-completion`
(everything claimed below was run, and CI/git state was checked live rather
than taken from the plan), `test-driven-development` (acceptance bullet to named
test), `graphify` (navigation; it needed grep fallback for line-level facts).

1. `89cc31f CR-3` — contracts and plan only. Fixes the five contradictions that
   made IG-3 unreachable as written: no durable confirmed request, the vault
   ACTIVE-before-entry circularity, `now()` at the deadline boundary, the
   `int` vault cap, and the join/idempotency/rate-limit mechanisms being three
   names for one undefined rule. Records `DEP-5`, `OD-P3-1` to `OD-P3-5`, the
   PT-14 split, and the trial, Elastic and webhook blockers.
2. `6d915c6` — migration 0003, `Clock.db_wall_now`, the `PaymentVault` /
   `PayPalIdentity` ports, the pure guard module, the buyer-order engine and
   offer expiry with their tests (PT-07 runtime, PT-10, PT-12, F5).
3. `66eaefa` — join with signed receipts, withdrawal, SSE, public signing key,
   pool close with the vector-checked Merkle snapshot, PayPal Login linking,
   the fake vault lifecycle, search with Postgres fallback and admin reindex,
   the worker registry for exactly the four implemented kinds, plus PT-13,
   PT-14 (Phase 3 form), F14, F15, F16 and the privacy tests.

Measured, not asserted: 682 offline tests and 8 fault tests pass, one test is
skipped with a printed reason (no Elastic credentials), `ruff check`,
`ruff format --check`, `mypy --strict` over `domain/` and `modules/`,
`tools/check_imports.py`, `tools/validate_docs.py`, frontend lint, 14 frontend
tests and the frontend build are all clean, and `tools/check_migrations.py`
passes the full round trip on a disposable database.

`make gate-check GATE=ig-3` now exists, runs the whole automated chain green
(lint, strict typing, 682 offline tests, import boundaries, docs, OpenAPI,
frontend lint/tests/build, Alembic round trip, migration verification, the fault
suite, generated artifacts and gitleaks) and then exits 2 on s5 and s11 only.
ci is now passed: run 41271936679, nine jobs green on `a57804a`. That is the correct state: `ig-3`
may not be tagged until those are real, and no evidence file was marked passed to
make it look otherwise.

Owner actions IG-3 cannot pass without:
- decide `OD-P3-2` (start the APIMatic trial, or move the requirement);
- provide or waive Elastic credentials and record the cluster provenance and
  trial dates that `spikes.md` S8 asks for;
- confirm the sandbox webhook listener and URL for `T03A03`, and accept that
  four event types are physically unobservable until Phase 4-5;
- push `phase-3` and run remote CI before any tag; the branch is local.

## IG-3 closed (2026-11-01)

Hosted database first, then the gate. Supabase went 0002 to 0003 after a data snapshot of
all 33 tables (5 rows) and a pre-check showing `oauth_states`, `vault_tokens`,
`pool_entries` and `buyer_orders` were empty - which is what makes the `session_id NOT
NULL` addition safe. `pg_dump` 16 could not dump a server running 17.11, so the snapshot
went through the app's own connection helper instead. Verified after: revision 0003, 35
tables, `vault_tokens.cap_cents` bigint, the entry-window trigger on `clock_timestamp()`,
`alembic check` clean, and the live `/ready` probe back to `migrations: ok`.

`make gate-check GATE=ig-3` then passed its automated chain and evidence set, so `ig-3` and
`contracts-v1.2` are tagged. `ig-2` stays untagged with its Gemini evidence pending, and the
uncommitted `phase2-gemini-v5` prompt bump in the tree still invalidates that stored
fingerprint until the evaluation is re-run.

## Phase 4 execution record (2026-11-01)

Executed solo on branch `phase-4` in three authored commits, after the plan review that
produced CR-4. Commit 4 (this record) is the gate, the evidence set and the docs. The work
followed `verification-before-completion` (every number below was produced by a command run
in this session, then written down) and `ponytail` (the diff is one tool plus documents, no
production code). Neither `SKILL.md` was loaded through the skill tool and `graphify` was not
queried, because the task named its files and the change touches no module logic; claiming a
loaded skill the session cannot show is the kind of claim this file exists to prevent.

1. `e11a801 CR-4` - contracts, plan and migration 0004 first, alone, so no dependent code
   followed a shape the contracts did not allow. It records LS-14 (`admin.force_award`, demo
   and test only), the mode-aware LS-06 without which a vault-mode lot could never reach
   FUNDED, a nullable `awards.bid_revision_id` for a forced award with no bid behind it,
   `intake_proposals` so a proposal is owner-bound before it can be confirmed, and
   `lots.refill_waves` so "bounded by max_refill_waves" has a counter to read.
2. `9b6f452` - seed, allocation, `lot.open_checkout`, approval/authorize, the vault charge,
   the funding trigger and capture sweep, and the forced-award helper, all against the fake
   router: its message records 794 tests at that point, F7 and F8 among them.
3. `ad656fb` - intake with its closed schemas and deterministic validation, the Phase 4 HTTP
   surface, the sixteen registered worker kinds with a registry test that compares the map
   with the implemented set, the public audit content, and IT-4: its message records 834
   tests. This session measures 836 on the same tree, so the two figures differ by two; the
   measured 836 is what the README and `local_checks.json` use, and the discrepancy is noted
   rather than smoothed over.

Measured, not asserted: 836 backend tests pass with no skips (828 offline plus the 8 fault
tests, which the gate also runs on their own; the live Elastic parity test executes locally
because `ELASTICSEARCH_URL` and the client are present);
`ruff check`, `ruff format --check` over 248 files, `mypy --strict` over 58 modules,
`tools/check_imports.py`, `tools/validate_docs.py`, the ten-operation merchant OpenAPI,
`tools/check_generated.py` and gitleaks (50 commits, no leaks) are clean; frontend lint, 14
tests and the production build pass; `tools/check_migrations.py` passes the full round trip
and `fairpool_test` reports revision 0004 with 35 application tables plus `alembic_version`.
IT-4 re-run on its own: 1 passed in 4.67s.

`tools/gate_check.py ig-4` now exists and reads `docs/evidence/phase4`; it runs the same
migration verification and fault suite as ig-3 without changing ig-2 or ig-3. It exits 2 on
`independent_review` and `ci` only, which is the true state: no independent review has run on
this diff, and the branch is unpushed. `migrations`, `local_checks` and `pipeline` are passed
because their output was captured here.

**`ig-4` is not tagged.** A gate needs the integration test, `make gate-check` green, the tag
pushed, and both lanes merged. Two items are missing and neither can be produced by the
implementing agent: an independent read-only review of `main..phase-4`, and a remote CI run.
`contracts-v1.4` is in the same position: `docs/contracts/README.md` line 5 already says it
was "tagged after the Phase 4 change request", but no such tag exists and none was created,
because tagging is owner-gated and was out of scope here. That sentence is inaccurate until
the owner tags the CR-4 commit.

Owner actions Phase 4 cannot close without:
- push `phase-4` and run remote CI, then record the run id in `docs/evidence/phase4/ci.json`;
- have an independent agent review the three commits and record its findings, or accept that
  IG-4 stays open;
- decide whether `contracts-v1.4` is tagged at the CR-4 commit or after the merge;
- migrate the hosted Supabase database 0003 to 0004 and redeploy, since the hosted service
  still runs the Phase 3 image and its `/ready` probe reports the revision it expects, not
  this branch;
- set `DRAND_BASE_URL` and `DRAND_CHAIN_HASH` (or keep the demo seed) and record a real S6
  round; the 2026-11-01 check found them absent and recorded `not configured`.
