# Progress

Living file, updated by both members. Each member edits only their own rows and entries (merge-conflict rule). Agents update the status of the task they are working on in their first commit and at merge.

Status values: `TODO`, `IN PROGRESS`, `IN REVIEW`, `DONE`, `BLOCKED`, `DEFERRED (owner decision)`.

## Project facts

### Owner authentication follow-up — IN REVIEW (2026-11-02)

Redirect follow-up: the user's PayPal rejection exposed the incorrect internal `/signin/authorize` entry point inherited by signup and linking. Both now use the S1 harness and official guide's `/connect?flowEntry=static`; regression assertions first failed on the old path. Running-app inspection confirmed its client ID matches `.env`, scope is only `openid`, and the callback is exactly `http://localhost:8000/api/v1/auth/paypal/callback`. This does not prove the same client ID is selected in the PayPal dashboard or that the live consent flow has succeeded.

Owner-authorized CR-6 follow-up after IG-5: PayPal-first enrollment (FR-ID-06, T03B03 and authentication slice of T06B05), real Sandbox identity adapter, migration 0005, and three signup screens in the existing palette. The owner authorized commit and push for hosted testing. No future agent participation features or gate/tag changes are included. Validation and live Sandbox signup status are recorded separately from historical IG-5 evidence.

Verification: 933 offline backend tests passed (94.50% domain coverage), 45 frontend tests passed, lint/type/import/docs/OpenAPI checks and production frontend build passed. `make verify` reached its final secrets step but could not execute the WinGet Gitleaks binary inside the sandbox; the same binary ran separately with elevated execution and found no leaks in history or the uncommitted diff/new source files. Graphify AST update completed (SQL parser unavailable; Markdown semantics not refreshed). Migration 0005 and signup-table RLS verified on local, test and Supabase databases; Supabase `alembic check` reports no pending operations. Local running API returns signup status enabled and starts the Sandbox redirect with an HttpOnly cookie and no-store response. Real PayPal signup remains pending exact callback registration: PayPal currently returns invalid client_id or redirect_uri. Browser automation unavailable, so no screenshot-based visual verification or provider-dashboard change is claimed. Owner authorized commit and push; live signup verification remains pending.

| Item | Value |
|---|---|
| Repository URL | https://github.com/shaahir27/FairPool.git |
| Hosted URL (Render) | not yet recorded |
| Daily sync time (IST) | not applicable (solo operator) |
| Member A name and handle | solo operator @shaahir27 (both workstreams) |
| Member B name and handle | second member's name and GitHub handle not yet recorded; @shaahir27 previously operated both workstreams |
| ContextMatic plugin version (A, B) | Qoder: remote MCP ready (5 tools, 2026-10-30); Codex: .codex/config.toml staged; Antigravity: mcp_config.json present; no local version string |
| PayPal AI Toolkit plugin version (A, B) | Codex: paypal@paypal-ai-toolkit 1.2.0, installed and enabled (2026-10-30); Qoder/Antigravity: not supported — do not add the write-capable MCP |
| Current phase and gate | PH6 complete and merged to `main`; CI green; deployed; IT-6 ran live against PayPal Sandbox. **IG-6 closed** on this commit with tags `ig-6` and `contracts-v1.6`. PH5/IG-5 and PH4/IG-4 are closed and tagged. |

## Gates

| Gate | Status | Tagged by | Notes |
|---|---|---|---|
| IG-0 | DONE | owner | tagged `ig-0`; CI green (run 41086853451); T00A02 complete; Codex PayPal 1.2.0 skills loaded (SSE MCP unavailable in Codex 0.164.0); public visibility deferred to T10A02/T11X01 |
| IG-1 | DONE | owner | tagged `ig-1`; IT-1 green locally and hosted: API https://fairpool-api.onrender.com, frontend https://fairpool-frontend.onrender.com; `/health` and `/ready` 200; webhook 200 with the raw body stored; Supabase free Postgres; Render Postgres deleted |
| IG-2 | DONE | owner | Closed on evidence, not by exception. `make gate-check GATE=ig-2` passes its automated chain and its whole evidence set; tagged `ig-2` with `contracts-v1.3`. The 95% threshold is met by recomputed fields (439 matched, 41 in review of 480 rows), the guard is proved by deterministic tests for every published variant, and the disclosures that keep this honest are in the evidence: 479 distinct live calls, 19 demo rows in review, and the owner's decision that contradictory demo cases may resolve to review. The earlier 2026-10-31 owner-exception closure is superseded. |
| IG-3 | DONE | owner | Phase 3 merged to `main`; `make gate-check GATE=ig-3` passes the full automated chain and the evidence set; tagged `ig-3`. Two items pass on recorded owner decisions rather than executed work and say so in the file: `s11` on the APIMatic waiver (OD-P3-2, rescheduled to T10A04) and `s5` as a spike record. |
| IG-4 | DONE | owner | Phase 4 is on `main` at `babb4fd`, CI green (run 41315766795) and `make gate-check GATE=ig-4` passes its automated chain and its evidence set; tagged `ig-4` with `contracts-v1.4`. Two independent reviews ran and their findings were closed, the second one's two money-path regressions included; the owner waived a third full review explicitly, and `docs/evidence/phase4/independent_review.json` states that provenance rather than implying a clean independent pass on the last commit. Known limits stay recorded: Q-16, Q-18, Q-20. |
| IG-5 | DONE | owner | Closed 2026-11-02 on evidence. `make gate-check GATE=ig-5` exits 0 across all nine required files. Code and tests on `main` at `f01c783`, CI green (run 41425822470: 913 backend, 10 fault, 39 frontend, ruff, `mypy --strict`, eslint, tsc, build, imports, docs, merchant OpenAPI, gitleaks, compose); the tag sits on the following evidence commit, as with IG-4. IT-5 ran live on the Sandbox (C-08 authorize-then-void and C-09 capture-then-refund, both ending at a zero ledger). Five independent read-only review passes: four FAIL with findings (all fixed and named by tests), the fifth PASS with no blocker and no major and three follow-ups carried to T08B01 and IG-6. Tagged `ig-5` and `contracts-v1.5` |
| IG-6 | TODO | not yet | |
| IG-7 | DONE | `phase-7` / PR #5 | Closed 2026-11-04 on evidence. CI run 41861568532 is green across all nine jobs on 6d18525; `docs/evidence/phase7/` carries migrations, local checks, IT-7, C-17, three independent review passes and CI, all passed. IT-7 ran live: the agent/MCP/merchant-key lanes, both lots awarded from real bids, lot 1 FUNDED on capture 67454261HL110735P, lot 2 FAILED_CLOSED with authorization 98034989X7549701W VOIDED at a zero ledger, and one refill wave. C-17 passed live (popup approval, server authorize 01H970211Y409711B). One owner waiver is recorded: the in-run refund of a lot-2 capture, because the refill approval missed its offer window and IT-6 already proved capture-to-refund-at-zero live on this code. Tagged `ig-7` |
| IG-8 | DONE | `main` | Closed 2026-11-05 on evidence. `docs/evidence/phase8/` carries migrations, local checks, IT-8, the 10k simulation (5,386 ms), the Sandbox contract set with C-18, three independent reviews and CI, all passed; `make gate-check GATE=ig-8` exits 0 across all eight files. S9 ran on the owner's Zapier Pro trial and is recorded **read-only**: the managed GET tool returned live data with its URL and Authorization locked, but both write tools could not send a schema-valid body (Zapier returns a summary only and exposes its preset body as `[object Object]`), so `ZAPIER_BRIDGE` stays off and `/mcp` remains the agent path. The trial token was revoked after recording. Tagged `ig-8`. |
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
| T05A01 | A | L | DONE | main | Real PayPal path for one buyer (redirect) plus the shipping seal. Live on 2026-11-02: one Sandbox buyer through offer, approval, server-side authorize and void (`FAILED_CLOSED`, ledger zero) and a second run through capture, funding and refund (`COMPLETED`, ledger zero); C-08 and C-09 pass. Address sealing follows BD-11 as a Fernet token. See `docs/evidence/phase5/it5_sandbox.json` |
| T05A02 | A | L | DONE | main | Batch-one UI redesign (2026-11-02, owner-steered): enclosed checkout, account sidebar, buyer-friendly progress, expandable payment/activity details, receipt drawer, Motion transitions and one cobalt/coral/marigold palette across the app. Login/register layout retained after approval. An app-wide session gate now sends a signed-out visit to `/login` and returns the buyer to the path they came from. 39 frontend tests, typecheck, eslint and the build green |
| T05A03 | A | M | DONE | phase-5 | Failure path and compensating refund (fake router); PT-11, F9 and F24 pass |
| T05A06 | A | M | DONE | phase-5 | Merchant profile and onboarding states; `require_merchant` now loads the merchant row |
| T05A04 | A | L | DONE | phase-5 | Bid API with receipts and sealing; `test_bid_sealing.py` passes |
| T05A05 | A | L | DONE | phase-5 | Auction rules engine; R1-R7 guards, R9 cross-lot selection, the two new vectors and PT-06 pass. The DB loader stays a T06A06 dependency |

### PH6: Money completion and auction to checkout

Started 2026-11-03 on branch `phase-6` (solo operation, both lanes, CR-8 first).

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T06A01 | A | L | DONE | phase-6 | IT-6 ran end to end against PayPal Sandbox on 2026-11-03: a two-lot pool, four real sealed bids, `lot.award` deciding both lots in `lot_order` with lot 2's cheaper bid `REJECTED R9_CAPACITY_EXHAUSTED`, a buyer approving a real order, authorization `1C716592GL014192L` captured to `8J691800FS7606033` (COMPLETED 470.00 USD on a direct PayPal GET), lot 1 `FUNDED` then that capture refunded to COMPLETED, and lot 2 voided to `FAILED_CLOSED` at net zero with `void_source lot_failing`. Seven real webhook deliveries arrived and C-15 passed on one of them. `docs/evidence/phase6/it6_sandbox.json`, `failure_net_zero.json` and `webhook_delivery.json` carry the references; the deadline stall is `Q-2026-11-03-32` and the fee-on-refund question is left open |
| T06A02 | A | M | DONE | phase-6 | Webhook ingest verifies through the adapter when `PAYPAL_WEBHOOK_ID` is configured, stores the raw body first either way, answers 200 for verified/duplicate and 400 for a configured refusal, and enqueues `webhook.process`; the processor maps an event to its stored resource, GETs it and applies it through the state machine, and unmappable events reach the dead letter with a working retry route. F2, F3 and F4 pass. Review found the "stored first" claim was not true on one path -- the ingest row was not committed before verification, so a delivery the adapter could not parse raised inside the verify call, the request died as a 500 and the rollback took the body with it (`paypal-adapter.md` section 8). Both halves fixed: the row is committed straight after the insert, and an unparseable body is an unverified delivery rather than a 500. That early commit narrows one guarantee, and it is recorded rather than hidden: a delivery whose process died between the commit and the enqueue is absorbed as a duplicate on redelivery, so that one acceleration hint is lost -- webhooks accelerate and a GET confirms (P4), so the reconciler still settles the money. Live delivery is a hosted item (`webhook_delivery.json`) |
| T06A03 | A | L | DONE | phase-6 | The authorization age guard settles a hung `AUTHORIZING` seat by provider evidence through BO-04/BO-05/BO-20 only, and an aged `AUTHORIZED` seat voids with `void_source="age_guard"`. F10 covers the expired seat, the vacancy, the sweep stopping and the half review added: a seat the provider never saw is settled by a read and never by a replayed write. `authorization_age_guard_s` is no longer dead config |
| T06A04 | A | M | DONE | phase-6 | Payload levels proven per level (`tests/unit/test_payload_levels.py`) and the sealed shipping address is read back when a provider order is re-created, so a retry does not lose it. Shipped default stays `PAYPAL_PAYLOAD_LEVEL=0`; the flip is hosted config and is handed back |
| T06B01 | B | M | DONE | phase-6 | `POST /api/v1/merchant/lots/{lot_id}/quote` parses a pasted quote into a PROPOSED revision with unresolved fields left empty for the merchant, prefills `product_key` server-side, enforces flat-delivered at the write, and D-P2-01 is closed: a conflicting capacity returns null plus an ambiguity instead of a definite number |
| T06A05 | A | M | DONE | phase-6 | `modules/auction/reconcile.py` runs inline after confirm, writes `bid_flags`, moves a BLOCKING flag to FLAGGED (BS-04) which award rejects as R7, and holds a free-text bid for ops review when the model is unavailable. No path in the file can produce ELIGIBLE or AWARDED; F20's injection half passes locally, the Gemini half needs a quota key |
| T06A06 | A | L | DONE | phase-6 | `lot.bid_open`, `lot.bid_close` and `lot.award` with the DB loader over `domain/auction_rules.py` (the T05A05 carry-in) and the R5 rate-table gap. Award walks every lot in `lot_order` through one `select_across_lots`, stamps router and mode (N8), marks priced-out seats, enqueues `lot.open_checkout`, and returns without a transition when a job arrives for a lot that has already decided. `pool.allocate` now emits its declared `job:lot.bid_open`. Independent review found three, all fixed: LS-03 counted only `AWARDED`/`CANCELLED` as decided, so every lot behind one that had reached checkout requeued for ever; the ranking tie-break was derived from the pool seed instead of the lot seed the audit page republishes; and a bid that failed R8 or R9 was moved to `ELIGIBLE` (BS-07, "all rules pass") and then `LOST` instead of `REJECTED` with its reason (BS-06) |
| T06A07 | A | M | DONE | phase-6 | Keys create (secret shown once, HMAC stored, prefix only thereafter), list and revoke; `PostgresMerchantAuth` resolves a `fpm_` bearer to the same principal a session gets, refuses every bad key with one answer, and `require_merchant_key` is live. PT-15 is proved through a key's own principal on a real merchant-scoped read. `require_scope` delivers the contracted `403 API_KEY_SCOPE` for the routes that call it (T07A06) |
| T06B05 | B | L | DONE | phase-6 | Discover (prompt bar, server-built confirmation card with its notices verbatim, trending grid with the exact FR-UI-01 badge), the pool lobby (stage strip, server-clocked countdown from the SSE `tick`, lot plan, rules with its hash, join and withdraw), and the entry receipt as a page with copy, **download** and print. A workspace rail in the brand field, a measured tonal ramp, and sign-out in every shell came with it. CR-9 gives the lobby the durable receipt read-back. Live-rendered against the local API at 390 and desktop widths |

IG-6 is **not** claimed by these rows. The items that need a human, a PayPal dashboard, a Gemini quota or hosted config are listed in `docs/evidence/phase6/` with `status: "pending"` and the command that would close each one.

### PH7: Live end to end and the agent and merchant lanes

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T07A01 | A | L | DONE | phase-7 | Client-token grant in the adapter, cached to a minute before expiry; `/checkout/config` returns the exact api.md object; the SDK callback stamps `approval_channel=sdk_popup`; `PayPalButton` runs the v6 sequence and falls back to redirect. C-17 is the live popup row in `sandbox_contracts.json` |
| T07A02 | A | M | DONE | phase-7 | Already complete from Phase 6: `modules/checkout/refill.py`, `lot.refill` registered and emitted, PT-08 and the wave/cutoff tests. Phase 7 changed nothing |
| T07A03 | A | S | DONE | phase-7 | `adapters/paypal/routers.py` is the single source of the label; `payee_email` and `platform` raise `NotEnabled`; the fallback notice reaches the checkout config and order labels. `test_router_labels` proves all three |
| T07A04 | A | L | DONE | phase-7 | `modules/checkout/ops.py` and the five admin routes: lot view, abort only through LS-13/LS-08/LS-09, derived alerts, TTL-bounded mock toggles gated by `MOCK_TOGGLES_ENABLED` and labelled MOCK, audit export. The console reads every surface |
| T07B01 | B | L | DONE | phase-7 | My Pools groups entries into Pending, Waitlist and Action Required with the checkout inline; Orders groups by the API's own labels. Both have loading, empty and error states; 12 frontend tests |
| T07A05 | A | L | DONE | phase-7 | Delegation tokens are HMAC-stored and shown once; `require_agent` resolves a principal; nine routes reuse the browser's intake validator and join service; header/body idempotency, cap and scope; sample script; F15 and PT-16 tests |
| T07B03 | B | M | DONE | phase-7 | `/mcp` with exactly four tools proxying the Agent API. The official Python SDK could not mount on the pinned Starlette (a mount needs a trailing slash, and a mounted app's lifespan never runs), so a dependency-free JSON-RPC/SSE shim ships at exactly `/mcp`; the deviation is recorded in `Q-2026-11-04-35` |
| T07A06 | A | M | DONE | phase-7 | Five lot/bid routes over the same confirm-and-reconcile path as the console, scopes enforced, idempotent PUT returning the contract receipt. The 120 rpm key limit is contract text with no store and is deferred to `T08A06` |
| T07B05 | B | M | DONE | phase-7 | `modules/search/similarity.py` writes a LOW_SIMILARITY WARNING after the confirmed-bid commit, never inside it and never changing status; console `GET /merchant/lots?q=` implemented; tests cover the rule, the skip cases and a search outage |
| T07X01 | AB | L | DONE | phase-7 | `tools/it7_live.py` (`--dry-run`, `--live`, loopback approval redirector, its own job drainer) ran live on 2026-11-04: four joined buyers with receipts, the agent and MCP lanes, both merchant lanes, the similarity warning, both lots awarded, lot 1 FUNDED on a completed capture and lot 2 voided at the deadline to a zero ledger, plus one refill wave. C-17 passed live on a separate offer. The one waiver and why are in `docs/evidence/phase7/it7_sandbox.json` |

**Independent review, three lanes (2026-11-04).** Money/ops, agent/merchant/MCP and frontend were reviewed read-only. Every finding was checked against the contract first, then fixed or recorded: the client-token lock and the discarded lot money queries, the missing abort guards, the approval-channel row, the duplicated SANDBOX label, the unbounded merchant bid list, the MCP engine leak and body cap, the delegation scope that only applied at create, the in-request similarity check, the flag race, the agent lane deleting a saved PayPal permission, and ten frontend defects (paid entries under Action required, Cancel declining without asking, a lot-lookup race, honest MOCK copy, ignored approve results, a hanging SDK, a cache that survived sign-out, MOCK state lost on reload, duplicate accessible names and focus loss). The one limitation left is `Q-2026-11-04-37`; the real capture path is unaffected.

**IT-7 and C-17 ran live (2026-11-04).** The Phase 7 scenario ran on loopback against PayPal Sandbox: four buyers joined through the browser routes with signed receipts; the agent API and the MCP endpoint joined, listed and withdrew; a console merchant and a key merchant bid through the two documented lanes; the off-product bid produced a LOW_SIMILARITY warning without changing its status; both lots awarded. The owner approved two real orders; lot 1 reached FUNDED on capture 67454261HL110735P (47000 cents, COMPLETED on a direct GET), and lot 2 failed at its fund deadline with authorization 98034989X7549701W VOIDED and a zero money ledger. One lot-2 offer expired and `lot.refill` offered the seat to the waitlist; that refill approval arrived after its offer window and was refused, so lot 2 failed with a void and no capture to refund. The owner recorded a waiver for that one leg on 2026-11-04: IT-6 already proved the live capture-to-refund-at-zero path on this code. C-17 was then proven on a separate offer: the SDK popup approved, the browser sent only the order id, the server re-checked and authorized (01H970211Y409711B, `approval_channel=sdk_popup`). The pool staying RUNNING after both lots are terminal is the existing `Q-2026-11-03-26`, measured rather than introduced.

**Phase 8 (2026-11-05).** The merchant journey is real: Demand Board, Active Bids with the holds-then-captures tracker, Developer keys and the fulfilment tab all talk to the backend; fulfilment ships the CAPTURED list, CSV, shipments, a no-PII manifest and a live read-only verification; metrics and the four alert rules are exposed; and the seeded simulation allocates 10,000 entries in 5.4 seconds without touching a public list. Two independent backend reviews and one frontend review found real defects — the webhook cap was applied after the body was buffered, masking was shallow, tracking was terminal on a transient failure, the key rate limit did not exist, agent pool search ignored scope, the profile save wiped payee data and the merchant API key read serialized requests — all fixed with tests. `tools/demo_seed.py` now seeds a coherent five-pool demo (BIDDING demand, an awarded checkout, a funded lot with shipments, a failed lot at zero ledger, and a 10k simulation) with merchant accounts that carry the merchant role and the three attestations.

**Owner work parked (2026-11-04).** Uncommitted landing-page edits (copy rewrite, a `Count`
component and mobile work) arrived in the working tree. They did not compile (`entry` possibly
undefined, an unused `Count`) and broke two landing tests, so `make verify` could not run. The two
files were copied to `.tmp/owner-landing-2026-11-04/` (outside git) and the committed versions
restored. The mobile story swipe and the ghost-letter removal the owner asked for remain open under
`T09B04`.

### PH8: Fulfillment, verification, merchant console and simulation

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T08A01 | A | L | DONE | phase-8 | `modules/fulfillment/**` and both route tables: progress, the CAPTURED shipping list in JSON and CSV, shipments with the tracker call behind a job, the no-PII manifest and the read-only verification. The DB trigger and the service both refuse an unfunded lot (`LOT_NOT_FUNDED`). |
| T08A02 | A | M | DONE | phase-8 | The fulfilment tab downloads the funded CSV, records shipments with a two-step confirmation, downloads the manifest and runs the live verification, and says when the tracker was not submitted. |
| T08A03 | A | M | DONE | phase-8 | The five fulfilment operations are live on `/merchant-api/v1` with `fulfillment:read`, `shipments:write` and `manifest:read`; the sub-app still declares exactly ten operations and the frozen document did not move. |
| T08A04 | A | M | DONE | phase-8 | The verification endpoint is the primary documented path and it reads each capture back from PayPal; the read-only MCP route (S10) is documented in the README. A real AI client run is the owner's live check. |
| T08A05 | A | M | DONE | phase-8 | `/metrics` exposes refused transitions, amount mismatches, unknown outcomes, dead letters and funnel gauges as a raw route; `deploy/alerts.yml` has the four rules and a test checks every metric name and threshold. |
| T08A06 | A | M | DONE | phase-8 | Buyer/merchant/operator roles are enforced server-side, a merchant cannot bid on its own pool, cookies are Secure and `__Host-`prefixed, the proxy is trusted explicitly, login has origin + per-account limits, the webhook body is capped and masked, security headers are on, and `APP_ENV` fails closed. Two reviews' findings are fixed. |
| T08B01 | B | L | DONE | phase-8 | Demand Board: search, lot terms, SSE refresh, quote paste with the manual fallback, an editable bid and a confirmation card before anything is saved. |
| T08B02 | B | L | DONE | phase-8 | Active Bids groups Pending / In Checkout / Lost or Failed with the MOQ tracker, refills and fund countdown; Developer creates scoped keys shown once; Profile writes only edited fields. |
| T08B03 | B | S | DONE | phase-8 | S9 recorded 2026-11-05 as **read-only** (`docs/spike-results.md` S9, `docs/evidence/phase8/s9.json`). Claude connected to the managed server; the locked GET tool returned live data (2 tasks/call); one action per event type means at most three Webhooks tools; the POST join (flat Data rows) and the Custom Request join (raw `data`) both failed with a summary-only "Request validation failed." while the same body answers 200 by direct call and through `/mcp`. Trial ends 2026-11-11; `ZAPIER_BRIDGE` stays off. |
| T08B04 | B | L | DONE | phase-8 | `modules/sim/**` seeds a SIMULATION pool, writes 10,000 entries in bulk, ranks in process and seats them in 5.4 s locally; the pool never appears in public lists and is labelled. |
| T08B05 | B | S | DONE | phase-8 | Setup notes in `docs/spike-results.md` now describe the recorded read-only result: one action per event (three usable tools), locked URL + Authorization, 2 tasks per successful call, trial dates, and why writes fail. The README states the bridge was not demonstrated for writes and names `/mcp` as the agent path; no setup note claims a working Zapier write bridge. |

### PH9: Hardening, evaluation and feature freeze

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T09A01 | A | L | DONE | | Fault-injection suite. F1 to F30 now have a test at the layer the matrix assigns; 15 cases were added in 3c3fdfa. Verified: pytest faults + concurrency 33 passed (58.56 s), the integration/unit/concurrency extras 7 passed (13.59 s). F21/F22 exercise the adapter retry table through an httpx.MockTransport and are labelled plumbing, not Sandbox evidence; F17/F18 assert the disclosed limits in the README and UI copy. Evidence: `docs/evidence/phase9/faults.json`. |
| T09A02 | A | M | DONE | | Sandbox contract suite complete. C-11, C-12, C-13, C-17 and C-18 added as interactive real-provider tests behind `FAIRPOOL_SANDBOX_APPROVAL`; C-16 runs in the default suite. Default run: 9 passed, 9 skipped with named reasons; C-13 verified live (INR rejected). No PayPal mock exists under contract_sandbox. Evidence: `docs/evidence/phase9/sandbox_contracts.json`; run instructions in `backend/tests/contract_sandbox/README.md`. |
| T09A03 | A | M | IN PROGRESS | | Deployment hardening and demo tooling. Blueprint pins `PAYMENT_MODE=authorize_capture`; `make demo-reset` is implemented and proven locally (61,931 rows to 0, clean re-seed). Hosted demo reseeded 2026-11-05 (merchant console now shows the funded/checkout lots). Owed: a hosted smoke after the Phase 9 deploy. |
| T09A04 | A | S | DEFERRED (stretch not taken) | | STRETCH: top-up after FUNDED. Not taken: the stretch is outside the IG-9 exit list and no evidence is claimed for it. Recorded here rather than left as an unowned TODO. |
| T09A05 | A | M | DONE | | Funding and ledger integrity (audit F5). `ops.alerts()` compares PayPal's completed captures less refunds against the ledger's CAPTURE_COMPLETED less REFUND_COMPLETED for FUNDED/CLOSED/FAILED_CLOSED lots and reports `ledger_imbalance`. Verified this session: `test_alerts_ledger_imbalance.py` 2 passed. Evidence: `docs/evidence/phase9/f5_funding_balance.json`. |
| T09A06 | A | M | IN PROGRESS | | CR-14 agent-populated market run. The self-check boundary report passes (`tools/agent_market.py --self-check`): four MCP tools, a sealed bid at revision 1 with a 64-hex receipt, six adversary attempts refused, zero provider-write orders from delegated entries (query restricted to provider-write statuses; awards are now deleted before their revisions so cleanup completes). The live model bid (acceptance bullet 1) runs through `tools/live_gates.py bid` after the free-tier quota resets; evidence `agent_market.json` states it separately. |
| T09B01 | B | L | DONE | | Public audit page and verify-my-place. `frontend/src/audit/verify.ts` (named by `fairness-and-hashing.md` sections 1 and 5) reimplements canonical JSON, SHA-256, the Merkle tree, rank hash, demo seed, rules hash and Ed25519 verification on Web Crypto with no new dependency; `AuditPage.tsx` replaces the placeholder with three recomputed verdicts, the lot and bid-set-root table, the DEMO SEED label and a receipt-driven place check. Parity is pinned against `docs/contracts/vectors/fairness_v1.json` in both languages (10 frontend vector tests, `tests/unit/test_rules_hash_vectors.py` — the file implementation-plan.md section 4.1 already named), and `tests/integration/test_public_audit_rules_hash.py` proves the served rules document still hashes to the frozen hash after seeding. Local evidence: 290 frontend tests and 30 files green, strict typecheck and eslint clean, backend suite green; remote CI on this push not yet observed. Browser visual QA not performed. |
| T09B02 | B | L | IN PROGRESS | | AI evaluation sets and runner. Datasets hold 50 intake, 30 quote, 60 reconcile and 20 simulation cases; the runner and metrics exist. Baseline pending: the first run at 30 RPM hit per-minute 429s, the rerun at 10 RPM was cut by the free-tier 500-request daily cap after 379 of 480 results. Runs again after the reset; README table and `ai_evaluation.json` follow the completed run. |
| T09B03 | B | M | DONE | | Concurrency and property suites. Verified this session: pytest property + concurrency 83 passed (90.25 s), including PT-01..PT-16 and the 200-join race. Evidence: `docs/evidence/phase9/property_concurrency.json`. |
| T09B04 | B | M | DONE | #8 | Workspace redesign; CR-10 read models; see workspace-ui-plan.md. make verify green (1207 backend / 253 frontend); build and independent source review pass. Browser visual QA blocked by URL policy; pending visual acceptance. Navigation performance follow-up: navigation-performance.md, shared query cache and role-safe preloading implemented; make verify green (1207 backend / 269 frontend), final frontend suite 272 passed; independent source review and build pass. |
| T09B05 | B | M | DONE | | In-app notifications inbox (FR-UI-09, CR-13). CR-13 adds the two owner-scoped routes; backend 7 passed (owner scope, 401, newest first, 50 cap, idempotent mark-read, `/me` parity, CSRF), frontend 19 passed after the review fixes (badge seeded before opening, stale-token note, every kind rendered). Evidence: `docs/evidence/phase9/notifications.json`. |
| T09B06 | B | M | DONE | | MANDATE task and buyer ratification card (CR-14). Backend `94ab594` + the binding fix `8f58fe2`: the mint path recomputes the canonical mandate hash and refuses a mismatch, so a token cannot carry a wider cap or unratified scope/conditions. Card hashes the canonical fields and requires explicit ratification. Recorded gap: conditions are advisory, not enforced (Q-2026-11-08-39); the live-model proposal gate runs via `tools/live_gates.py mandate` after quota reset. Evidence: `docs/evidence/phase9/mandate_gate.json`. |
| T09X01 | AB | L | IN PROGRESS | | README full draft. Required sections exist (product, how it works, PayPal, AI, sponsor tools, honest limits, run, tests, architecture, roadmap); the measured AI-evaluation table and the live-gate paragraphs land after the quota reset. `docs/evidence/phase9/readme_draft.json` follows that. |
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
| PH6 | 3.00 | not measured (see the note below the table) | 3.50 | not measured (see the note below the table) |
| PH7 | 3.25 | not yet recorded | 4.00 | not yet recorded |
| PH8 | 3.50 | not yet recorded | 3.50 | not yet recorded |
| PH9 | 3.00 | not yet recorded | 3.75 | not yet recorded |
| PH10 | 2.50 | not yet recorded | 2.00 | not yet recorded |
| PH11 | 0.38 | not yet recorded | 0.38 | not yet recorded |

**PH6 actuals, and why they are not day counts.** One operator ran both lanes in a
single session with no time tracking, so an honest day figure does not exist for either
lane and the cells stay empty rather than carry an invented one. What is measurable is
recorded here: the branch is 80 files, +8119/-243 against `fbaf6e8` - backend
+4821/-130, frontend +2830/-69 of hand-written screens and tests, generated API types
+59/-10, docs +281/-27.

The planned column also disagrees with itself. The PH6 task sizes sum to **5.00 days for
Member A and 1.50 for Member B** (T06A01 L, A02 M, A03 L, A04 M, A05 M, A06 L, A07 M;
T06B01 M, B05 L), while this table's PH6 row says 3.00 and 3.50. `implementation-plan.md`
is not edited here, because AGENTS.md section 2 ranks it above a re-estimate note; both
figures are recorded so the IG-6 review sees the discrepancy instead of inheriting one
of them silently.

## Open questions

| ID | Raised by | Question and the two readings | Source of each reading | Status |
|---|---|---|---|---|
| Q-2026-11-06-38 | agent (hosted verification after F2) | On the deployed app the signed `checkpoint` verifies against the served public key for all four pools tested, but `rules_hash(served rules_document) == stored rules_hash` is FALSE for all four. No plausible beacon shape reproduces the stored hash, so the document the route rebuilds at read time is not the one publish hashed. Reading (a): the live columns (`template`, `lot_plan`, `timeline`) were written after publish by a later build or seeder, so the rows are stale and a re-seed turns the verdict green; reading (b): `rules_document(pool)` is not a stable function of the row, and the only correct fix is to freeze the document itself at publish into its own JSONB column (numbered migration plus a CR to `api.md` and `fairness-and-hashing.md` section 7). Either way the new audit page shows a red verdict on existing hosted demo pools, so the audit beat cannot be recorded until this is settled | `api/routers/public.py` (rules_document at read time), `modules/pools/service.py` (hash at publish), `docs/contracts/fairness-and-hashing.md` section 7, live `GET /api/v1/public/pools/{id}/audit` on `fairpool-api.onrender.com` | RESOLVED 2026-11-06. Neither reading was right: the demo **seeder** moves each pool's `open_at`/`close_at` after publish (`tools/demo_seed.py` calls `move_timeline`), and `timeline` is an input to `rules_document`, so the frozen hash no longer described the row. Freshly seeded pools mismatched too, which is how it was isolated from stale data. Fixed in the shared helper: a pre-close shift re-freezes `rules_hash`, a post-close shift is refused, and the read uses `populate_existing` so a stale identity map cannot bypass the guard. Two tests added (`test_public_audit_rules_hash.py`), plus the live check that the hosted audit page now recomputes clean. The audit-page beat is unblocked once the hosted demo database is re-seeded. |
| Q-2026-11-08-39 | Phase 9 mandate review | A ratified mandate's conditions are validated, hashed with the cap/scope/expiry and returned with the token, and each predicate resolves from stored rows only. No agent surface evaluates them yet, so a stop-and-ask condition is advisory: an agent that ignores it is bounded only by the cap and scope. Reading (a): evaluate conditions inside the agent entry/read paths and refuse or flag with a production code, which needs an additive response field and a CR; reading (b): keep them advisory for this submission and state it in the README. The cap, scope and expiry are enforced either way | `modules/identity/mandate.py`, `modules/agentapi/service.py`, `docs/contracts/api.md` section 4.4 | OPEN, recorded |
| Q-2026-11-04-37 | independent review | Mock toggles are stored in process memory, but the deployed topology runs the API and the worker as separate processes. `force_capture_failure` armed through the API therefore cannot reach a capture run by the worker; the console now says the toggle applies to the process serving the request, and the MOCK label stays honest. Reading (a): move the toggle state to a database row (a migration or the audit chain as a KV) so both processes see it; reading (b): treat mocks as a single-process demo tool and keep them out of deployed evidence. The real capture path is unaffected — only the simulated failure is | `modules/checkout/mock_gateway.py`; `modules/checkout/ops.py`; `deploy/docker-compose.yml` | OPEN, carried to T10A01. The gate evidence uses the single-process run and says so |
| Q-2026-11-04-33 | T07A05 | A delegation carries `scope.category`, and nothing in a pool template defines `category`, so a category-scoped delegation matches no pool. Reading (a): templates gain a category and the check is literal; reading (b): `category` means the template `product_key`; reading (c): the field is dropped from the scope. Phase 7 compares literally and answers 404 like an unknown pool, so the field is safe but currently unusable | `modules/agentapi/service.py` `_check_scope`; `docs/contracts/api.md` 4.4; `docs/contracts/db-schema.md` delegations | OPEN. Needs a contract decision before a delegation is documented as category-scoped |
| Q-2026-11-04-34 | T07A05 | `api.md` section 4.4 says a header/body idempotency-key mismatch answers 400, and section 1 says the same key with a different body answers `409 IDEMPOTENCY_CONFLICT`. The agent route answers 409 and its tests assert that; the contract text disagrees with itself | `docs/contracts/api.md` 1 and 4.4; `api/routers/agent.py` | OPEN. One sentence in the contract needs correcting; no code change is pending |
| Q-2026-11-04-35 | T07B03 | `api.md` names the official MCP Python SDK for `/mcp`. It installs, but under the pinned FastAPI/Starlette a `Mount` answers 307 at `/mcp` and the mounted app's lifespan never runs (`Task group is not initialized`), so the session manager cannot start. A dependency-free JSON-RPC/SSE ASGI app at exactly `/mcp` implements initialize, tools/list and tools/call for the same four tools. The acceptance bullets (four tools, delegation auth, no payment tool, a real client round trip) are met; the SDK choice is not | `api/app.py` `/mcp`; `modules/mcp/**`; `tests/unit/test_mcp_contract.py` | OPEN. Either the contract names the shim or the Starlette pin moves in a later phase |
| Q-2026-11-04-36 | T07B01 | `allocation.waitlist_position` is SILENT in api.md beyond a null example for SEATED. The implementation derives it as `rank - seats` (minimum 1) for a WAITLISTED entry, where seats are the zone's lot seats, and the UI prints "Waitlisted, position #N" | `modules/agentapi/views.py`; api.md "Entry" | OPEN. Recorded so the derivation is a decision rather than an accident |

| Q-2026-11-03-32 | IT-6 live run | A lot that misses its minimum did not fail at its own fund deadline. Lot 2 (2 seats, minimum 2, one authorization) had `fund_deadline_at` 15:22:49Z and was still `CHECKOUT_OPEN` at 15:24; `LS-08` applied only at 15:25:10Z, after a `lot.try_fund` job was enqueued by hand, and `FAILED_CLOSED` followed at 15:25:21Z. Reading (a): the `lot.try_fund` armed at the deadline evaluates the deadline before the database clock has passed it, returns without deciding, and nothing re-arms it -- `domain-ports.md` section 5 gives `try_fund` no self-requeue on that path, and with `max_refill_waves=0` there is no refill to enqueue one either, so the lot parks until a human or the ops console acts. Reading (b): the deadline job ran for lot 1 only and lot 2's never fired, which would be a scheduling gap rather than a decision gap. Both readings end in the same place -- a funded-or-failed decision that did not happen on time -- and neither was reproduced in tests, because every offline test drives the handler directly instead of waiting on the armed job. | `modules/checkout/funding.py` `_fail_if_deadline_passed` and `open_checkout.py`'s deadline job; `docs/contracts/state-machines.md` LS-08/LS-10; the live audit trail 15:22:49Z deadline, 15:25:10Z `lot.failing` | OPEN. Observed once against the real Sandbox and not yet pinned to a line of code; the fix is a re-arm on the not-yet-passed path, but the mechanism needs confirming before changing a money-timer. |
| Q-2026-11-03-31 | T06A03 (review round) | The aged path settles a hung `AUTHORIZING` seat by reading the provider, and a read can legitimately return nothing: the order exists, it carries no authorization at all because the send died before PayPal saw it, and the seat's own BO-03 re-check has already failed. The row then stays `AUTHORIZING` and logs `checkout.authorize.aged_without_evidence` on every sweep, for as long as anyone runs the job. Reading (a): that is what I7 demands, money may be in flight in a form we cannot see, so the seat stays locked, ops settles it and the log is the alert. Reading (b): CR-8 note 1 exists precisely so a seat is not locked for ever, so a definitive read that shows nothing is itself the evidence to end it. | (a) `docs/contracts/state-machines.md` BO-03 with I7, and `paypal-adapter.md` section 4: an unknown outcome is never a success. (b) `state-machines.md` CR-8 note 1 and `Q-2026-11-01-18`, which speak of a seat whose authorization GET *reports* EXPIRED, VOIDED or CREATED -- the contract names no zero-evidence case at all. | OPEN. The code takes reading (a), because the other reading settles a seat by the absence of evidence and would be the write this round just removed wearing a different hat. The consequence is recorded rather than argued: a lot whose only live seat is in this state counts as holding a live authorization in `failure.py`'s `LIVE_AUTH_STATES`, so `lot.finalize_fail` (LS-10) can never close it at net zero -- the sweep re-drives the authorize and raises one stuck alert. Closing this needs a human reading or a CR, not a code change on this branch. |
| Q-2026-11-03-30 | T06B05 | `Notifier.notify` writes `notifications` rows and `GET /api/v1/me` reports `unread_notifications`, but no route lets a buyer read them, so the buyer shell shows no bell: a count with nothing behind it is a promise the app cannot keep. Reading (a): add a notifications list route (a new row in the frozen endpoint table, so a change request); reading (b): leave it to T07B01, whose My Pools screen is where an entry's outcome belongs anyway. Phase 6 takes (b) and states the count nowhere. | `docs/contracts/domain-ports.md` section 6 (Notifications); `docs/contracts/api.md` section 2 route table; `modules/notify/service.py` | OPEN: owed by T07B01. If a list is wanted before then, it is a change request |
| Q-2026-11-03-29 | T06B05 | `api.md` says `POST /api/v1/intake/confirm` returns `201`, and the route returns `200`. Reading (a): set `status_code=201` on the route, which changes the committed OpenAPI snapshot and its generated types; reading (b): leave it, because no client branches on it (openapi-fetch returns the parsed body for either) and the merchant-key routes were the Phase 6 surface that needed the contracted code. Phase 6 takes (b) for intake and takes (a) for `POST /api/v1/merchant/api-keys`, which is the route this phase ships. | `docs/contracts/api.md` section "Intake"; `api/routers/intake.py:122-125`; `docs/contracts/api.md` section 4.2 | OPEN (record): a follow-up should align intake/confirm with the contract in one small commit |
| Q-2026-11-03-28 | T06A06 | `BID_PRICING_MODE=itemised` has no award path. `select_across_lots` ranks every offer with one lot-level seat list, so shipping and tax are the same for all bids on the lot -- exact while every bid is one flat delivered price, wrong the moment each merchant brings their own shipping table and rate table. Reading (a): give each `BidOffer` its own seated list, which changes the pure function's shape and its vectors; reading (b): refuse. `modules/auction/handlers.py` takes (b) and raises `FEATURE_DISABLED` at award when the mode is not `flat_delivered`, so an itemised deployment cannot silently award on the wrong totals. The shipped default is `flat_delivered` (`config.py:89`), so no path anyone runs today reaches the refusal. | `docs/contracts/flat-delivered-bids.md`; `docs/contracts/fairness-and-hashing.md` section 10; `domain/auction_rules.py` `select_across_lots`; `docs/contracts/config-and-errors.md` `BID_PRICING_MODE` | OPEN (record): reading (a) is owed before `itemised` is ever enabled; CR-8's R5 row describes the itemised rule that award does not yet evaluate |
| Q-2026-11-03-26 | Phase 6 planning | PS-07 closes a pool when `system.lots_terminal` finds every lot CLOSED, FAILED_CLOSED or CANCELLED, but `system.lots_terminal` is not a job kind in `domain-ports.md` section 5 and no handler emits it, so a pool whose last lot ends stays RUNNING until something else moves it. Reading (a): add a `pool.complete` kind, which is a contract change and a new registered handler; reading (b): evaluate PS-07 inline inside `lot.finalize_close` and `lot.finalize_fail`, which already hold the lot and its pool in a transaction, so no kind and no new job is needed. Neither is implemented today and no Phase 6 task names it, so Phase 6 does not decide it. | `docs/contracts/state-machines.md` PS-07; `docs/contracts/domain-ports.md` section 5; `modules/checkout/funding.py` finalize_close, `modules/checkout/failure.py` finalize_fail | OPEN: owed by Phase 7 or Phase 8. T06A06 deliberately does not add a job kind to work around it |
| Q-2026-11-03-27 | T06A06 planning | `lot_advisory_lock_key` and `apply_lot_transition` live in Member A's `modules/checkout/engine.py` and `modules/checkout/funding.py`, but the Phase 6 lot handlers belong to Member B's `modules/auction/`, and `tools/check_imports.py` rule 5 forbids the import. The per-lot advisory key must be **identical on both sides** or `lot.award` and `lot.try_fund` do not contend and I8 breaks silently. Reading (a): Member B duplicates the key derivation with a unit test asserting both sides produce the same int for the same UUID; reading (b): relocate the key and the lot-transition helper to a lane-neutral home, which edits Member A's engine and every caller. T06A06 takes reading (a) because it is the smaller change and the test makes the drift loud. | `tools/check_imports.py` rule 5; `modules/checkout/engine.py` LOT_LOCK_NAMESPACE; `docs/contracts/domain-ports.md` section 6 | OPEN (record): a follow-up should perform reading (b); the equality test guards it until then |
| Q-2026-11-02-23 | T05A06 review | `POST /api/v1/merchant/profile`'s response shape is not written down anywhere in `api.md`; the code returns `merchant_id`, `display_name`, `onboarding_status` and `attestations`. Reading (a): the route returns what the row holds and api.md needs a write-up (a contract edit); reading (b): pick another shape from a similar route. Code takes the first and does not edit the contract silently | `docs/contracts/api.md` merchant section; `api/routers/merchant.py` | RESOLVED by CR-8: api.md section 4.2 now carries the shape the route returns |
| Q-2026-11-02-24 | T05A03 review | `domain-ports.md` section 5 lists `void.run` payload as `{buyer_order_id, reason}`, `refund.run` as `{buyer_order_id, seq}` and dedupe `none` for all three Phase 5 kinds; the code sends `void_source`, derives `seq` at run time and adds `finalize_fail:{lot_id}` / `void:{bo}` / `refund:{bo}` dedupe keys. Reading (a): the payload names follow the doc and the dedupe keys are an implementation hardening the doc neither requires nor forbids; reading (b): the doc is the exact wire format and the code must match it, including a `seq` the enqueue cannot know yet. Code keeps reading (a)'s behaviour because the keys are what stop a double void or refund, and records the naming drift instead of editing the contract | `docs/contracts/domain-ports.md` section 5; `modules/checkout/failure.py` | RESOLVED by CR-8: the doc follows the code. `void.run` carries `void_source`, `refund.run` carries only `buyer_order_id`, `lot.finalize_fail` carries `passes`, and the three dedupe keys are documented, because they are what stops a second void or refund of the same resource |
| Q-2026-11-02-25 | T05A05 review | R4 and R6 have no text in `fairness-and-hashing.md` sections 10 and 11, only in `docs/registry.md`: R4 "capacity covers the lot seats", R6 "valid_until at least fund deadline plus capture grace". `Q-2026-11-02-21` recorded narrower readings (R4 against MOQ, R6 against `bid_close_at`), and the code followed them. Reading (a): `registry.md` is the rule list and the engine must compare seats and the funding horizon; reading (b): the contracts directory is the only source and the registry lines stay notes. Code now takes reading (a) because (b) lets a bid that cannot supply its own lot win, and because the `bid_close_at` test made R6 pass a validity that expires before the money is due. The frozen vectors do not exercise either rule, so no vector changed | `docs/registry.md` R4 and R6; `docs/contracts/fairness-and-hashing.md` sections 10-11; `domain/auction_rules.py` | RESOLVED by CR-8, which confirms reading (a): `config-and-errors.md` section 5 now states that R4 compares the declared capacity against the **lot's seats** and R6 measures validity against `fund_deadline_at` plus `capture_grace_s`. Reading (b) would let a bid that cannot supply its own lot win, so no code change follows |
| Q-2026-11-02-22 | T05A02 PDF fidelity | PDF pages 7-9 require lot-history timestamps, provider references and a verified net result; OrderStatusResponse has none. Reading (a): extend the contract to return verified fields; reading (b): copy sample values or infer them in the browser. I4 and I13 forbid (b); these exact details await a contract change. Buyer, merchant and item details are available through existing me and offer endpoints and are implemented. Auth illustration uses One voice / One seat instead of unsupported sample counts. | `FairPool finalised screens.pdf` pages 2, 7-9; `docs/contracts/api.md`; I4, I13 | RESOLVED by CR-8: `history[].at` and the three `paypal.*_status` fields are already returned and are now written into api.md; a per-order verified net result is **deferred** to the merchant fulfillment path rather than invented, because it needs a ledger aggregate no Phase 6 task names. The design PDF this row cites was removed from the repository on 2026-11-03; the implemented screens and `frontend/src/index.css` plus `frontend/src/shared/commerce.css` are the design reference for new screens |
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
| Q-2026-11-01-16 | implementation | The vacancy rule after the `buyer_order` table says the `lot.refill` job runs while the lot is `CHECKOUT_OPEN` **or** `FUNDING`, but the only transition that continues a refilled offer, BO-01, requires `lot CHECKOUT_OPEN`, and BO-03 re-checks the same status. A refill that runs in `FUNDING` therefore creates an `OFFERED` order the whitelist can never move, and the seat stays stuck. Reading (a): the vacancy rule is the intent and BO-01/BO-03 are too narrow; reading (b): a FUNDING refill is not fundable and the vacancy sentence lists FUNDING for a top-up that no task delivers. Phase 4 code takes reading (b) and refuses a refill outside `CHECKOUT_OPEN` (`modules/checkout/refill.py`), so no unpayable offer exists; F8 proves vacancy to refill while the lot is `CHECKOUT_OPEN`. Aligning the contract needs a change request: either BO-01/BO-03 admit a refilled offer in `FUNDING`, or the vacancy sentence drops `FUNDING`. | `docs/contracts/state-machines.md` (vacancy rule, BO-01, BO-03), `docs/contracts/domain-ports.md` section 6 | RESOLVED by CR-8 note 4: reading (b) is the contract now. `lot.refill` runs only while the lot is `CHECKOUT_OPEN`, which `modules/checkout/refill.py` already enforces, so no `OFFERED` seat can exist that the whitelist cannot move |
| Q-2026-11-01-17 | implementation | `docs/contracts/api.md` section 3 fixes the offer notice `hold` as "PayPal places a hold for the total shown only after you approve", which is false under `PAYMENT_MODE=vault_charge`: `vault-charge.md` section 1 says no funds are reserved and PayPal's approval screen shows no purchase amount. Reading (a): api.md's notice is the authorize_capture wording and must be mode-aware; reading (b): api.md overrides and the vault text is wrong. Phase 4 code takes reading (a): `GET /offers/{id}` returns the vault wording (`VAULT_NOTICE` in `api/routers/checkout.py`) when the lot is stamped `vault_charge` and the api.md sentence otherwise. api.md needs a change request to carry both sentences. | `docs/contracts/api.md` section 3; `docs/contracts/vault-charge.md` sections 1 and 3 | RESOLVED by CR-8: api.md's offer `hold` notice is now explicitly the stamped mode's sentence, and it carries `VAULT_NOTICE`'s exact text beside the `authorize_capture` one. No code change |
| Q-2026-11-01-18 | implementation planning | If a lot leaves CHECKOUT_OPEN while one of its orders is AUTHORIZING, the authorize retry is now refused (authorizing after close would be wrong) and the whitelist offers no exit from AUTHORIZING except BO-04, BO-05 and BO-20, all driven by the same job; `void.run` is Phase 5. The seat therefore stays locked until then. Reading (a): accept it, because money is already in flight and the Phase 5 void path is what settles it; reading (b): a CR allowing an age-guarded AUTHORIZING to AUTH_FAILED/REJECTED. Phase 4 records it and does not decide. | `docs/contracts/state-machines.md` BO-03/04/05/20 and BO-12; `modules/checkout/authorize.py`; `docs/implementation-plan.md` T05A03 | RESOLVED by CR-8 as **neither reading whole**. An aged seat is settled by provider evidence, not by the clock alone: `get_authorization`, or `get_order` where no authorization id was ever stored, produces the observation BO-04/BO-05/BO-20 already require, and CR-8 widens BO-05 to the statuses `paypal-adapter.md` section 4 already names. No transition is invented. A seat that lands `AUTHORIZED` after its lot left `CHECKOUT_OPEN` is voided with `void_source` `age_guard`. The implementation is T06A03, which also reads `authorization_age_guard_s` (dead config until now) and settles the row through `_observe_authorization`: a stored authorization is read with a GET, and a seat with nothing stored is settled by reading the order. The authorize replay this note first described was dropped in review, because when the send died before it arrived `auth:{buyer_order_id}` is a key PayPal has never seen and the replay would be a fresh write on a seat the BO-03 re-check had just refused (I7, I9). No `age_guard` void was needed, and CR-8 note 2 was rewritten to say so rather than describe code that does not exist. `tests/faults/test_f10_authorization_expired_vacancy.py` proves three halves: aged settles and leaves the reconciler's sweep with nothing to re-drive, aged-with-nothing-at-the-provider stays locked without a second write, un-aged waits |
| Q-2026-11-01-19 | implementation | `docs/contracts/api.md` line 133 fixes the intake card's `no_charge` notice as "Nothing is charged now. PayPal places a hold only after a merchant and exact price are known and you approve." That sentence is false in the primary mode: `vault-charge.md` section 1 says `PAYMENT_MODE=vault_charge` reserves nothing and places no hold, and the card cannot know a lot's stamped mode because the mode is stamped on the lot at award (N8). Reading (a): the contract sentence describes `authorize_capture` only and must become mode-aware or hold-neutral; reading (b): the card must keep the contracted sentence and vault mode is out of scope. The code takes reading (a): `NO_CHARGE_NOTICE` in `modules/intake/pipeline.py` promises no charge and no hold at all, and `test_the_intake_card_notice_does_not_promise_a_hold` asserts it. api.md needs a change request to carry the mode-neutral wording. | `docs/contracts/api.md` section 3 line 133; `docs/contracts/vault-charge.md` section 1 | RESOLVED by CR-8: api.md's intake `no_charge` sentence is now the mode-neutral one the card ships, because the card is read before any lot exists and cannot know the mode N8 stamps later. No code change |
| Q-2026-11-02-21 | auction rules (T05A05) | R1 to R7 are named in `config-and-errors.md` section 5 but their parameter readings are not written down: which comparison R4 makes, what R6 measures validity against, and whether R5 tax coverage is the flat-delivered rule. Reading (a): implement the narrowest deterministic comparison for each name and record it; reading (b): stop until a CR specifies each rule. Code takes reading (a) and records it here: R1 is shape plus `submitted_at > bid_close_at` on the frozen close time plus `confirmed`; R2 is the merchant's onboarding state and attestations; R3 compares product key, condition and the lot's bundle key; R4 requires a declared capacity of at least the lot MOQ; R5 compares delivery days against the lot maximum, returns days against the lot minimum, and in flat-delivered mode requires tax INCLUDED with no per-zone shipping; R6 requires `validity_end` strictly after `bid_close_at`; R7 rejects any remaining BLOCKING AI flag and never a LOW_SIMILARITY warning. Rules apply in that order and the first failure is stored. A CR can tighten any reading without changing the code's shape. | `docs/contracts/config-and-errors.md` section 5; `domain/auction_rules.py` `bid_rejection`; `tests/unit/test_auction_guards.py` | RESOLVED by CR-8: the recorded readings are now the contract text (see the R1 to R7 table in `config-and-errors.md` section 5). No code change |
| Q-2026-11-01-20 | implementation | BO-24's guard needs the provider's amount and payee, and BO-26 lists only definitive declines (`INSTRUMENT_DECLINED`, `DENIED`, 403 `PERMISSION_DENIED`). A read-back that says COMPLETED for another amount or payee, or that omits `payee.email_address` altogether, therefore satisfies neither edge: `order.resolve` refused on every sweep and the row looped in CAPTURING forever. Reading (a): such a capture is a definitive failure of this seat and must terminate; reading (b): it stays CAPTURING until a human or a later phase decides. Code takes reading (a) without inventing a whitelisted pair: the same BO-26 edge is applied with `status DENIED`, `reject_reason` `AMOUNT_MISMATCH`/`PAYEE_MISMATCH` (both contracted) or an `error_code` of `UNVERIFIABLE` in the audit evidence, the unverifiable case only after three `capture_grace_s` windows from the order's CAPTURING timestamp (a bound on the order rather than `current_attempt`, which is the re-quote counter, N9). The refused capture is not recorded as a `paypal_captures` row, so `lot.finalize_close` never sees a completed capture the ledger cannot balance; the provider's capture id is logged for the Phase 5 refund path. BO-26's guard text needs a change request to name this case. | `docs/contracts/state-machines.md` BO-24/BO-26; `docs/contracts/vault-charge.md` section 7; `modules/checkout/vault_charge.py` | RESOLVED by CR-8: reading (a) is now written into `vault-charge.md` section 7 as a named outcome row. `vault_charge.py` already implements it, including the three-window bound on the order's `CAPTURING` timestamp; BO-26's guard text in `state-machines.md` did not need to change because the code satisfies it with a `DENIED` observation |

## Requests to the owner

Batch-one visual review, 2026-11-02 (T05A02): the owner superseded exact PDF replication with a familiar commerce layout, retained authentication layout, and explicitly replaced the palette for the entire app. Buyer, merchant, product and terms use the existing me and offer endpoints. Q-2026-11-02-22 records only optional reference-data gaps: lot history, provider references and a verified net result. T05A01 interactive C-08/C-09 and live IT-5, plus IG-5 evidence, remain outstanding independently of this UI pass.

Verification (2026-11-02): frontend lint, strict typecheck, production build and 33 tests pass; docs validation, imports and merchant OpenAPI checks pass. `make verify` first hit the Windows default-shell mismatch; with Git Bash and a loopback `fairpool_test` database it ran 897 backend tests: 892 passed and five failed in `backend/tests/integration/test_checkout_routes.py` (`test_continue_creates_the_provider_order_once_and_moves_the_seat`, `test_approved_runs_the_checks_and_is_idempotent`, `test_checkout_return_never_trusts_the_token`, `test_checkout_cancel_declines_and_redirects`, `test_the_order_page_lists_the_history_and_the_fallback_label`). The first returns 500 on continue; the others lack the provider order id. No backend files were changed in this UI pass. The gate is not claimed green and no PR is opened against a failing verification. NPM audit reports 22 existing development-tool advisories (19 moderate, one high, two critical); none names the added Motion package. Major Vite/Vitest upgrades are outside this UI task.

Design evidence: research used W3C contrast/use-of-color guidance, Adobe Spectrum's semantic color roles, Baymard checkout research, and official Motion/Radix/React Aria documentation. Three palettes were compared on rendered authentication screens before the final cobalt/coral/marigold system was applied through global tokens. Native dialog handles the private receipt; Motion 14.9.0 handles state transitions and expandable order sections, respecting reduced motion. Graphify AST update completed after moving disposable QA files into the existing ignored `.test-tmp-*` area; Markdown semantics were not rebuilt. The native browser inspector script timed out; Playwright is the fallback. Final browser QA covers login, registration, checkout, order status and the receipt at 1440, 768 and 390 pixels: no overflow, no page errors and zero axe WCAG A/AA violations in 15 scans; Escape, receipt focus restoration, mobile navigation and reduced motion are checked. Authentication layout is retained; only its palette was changed after the owner requested one system across the entire app.

| Date | From | Request | Status |
|---|---|---|---|
| 2026-10-30 | owner | REST secret rotated again after the dev-time token exposure; buyer password changed; NVP/SOAP disabled or none present; Codex chat deleted. Recorded as complete 2026-10-30 without values. | DONE |
| 2026-10-30 | owner | GitHub CLI is installed and authenticated; Docker Desktop is still absent locally, but the CI compose job passed. Install Docker only for local compose. | DONE |
| 2026-10-30 | owner | Keep the repository private until the final submission QA (T10A02/T11X01); make it public before the Nov 12 deadline and verify logged-out access (FR-HK-01). Enable the Keep warm workflow (`gh workflow enable keep-warm.yml`) in the same change, because scheduled jobs are free only once the repository is public. | DEFERRED to T10A02/T11X01 |
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

| 2026-11-01 | owner | Render free plan has no background worker, so the hosted demo never runs the `reconciler.sweep` cron: the sweep runs only where a worker is deployed, and the demo relies on the admin-triggered sweep. `deploy/render.yaml` therefore still declares no worker service and no paid instance is added (spend nothing on Render). IG-4 is unaffected because the cron is proven locally by `test_the_reconciler_thread_enqueues_one_coalesced_sweep` and `test_the_sweep_cron_enqueues_one_coalescing_job_per_tick`. | OPEN |

| 2026-11-05 | owner | Keep the free Render service awake for the judges: request `/health` and `/ready` every 10 minutes, because Render spins a free web service down after 15 minutes without inbound traffic and needs about a minute to wake. `.github/workflows/keep-warm.yml` carries the schedule and a manual wake button; it runs `*/10 3-22 * * *` (20 hours a day, about 600 of the 750 free instance hours a month) and stays disabled until the repository is public, because a 10-minute schedule on a private repository would use about 4,320 of the 2,000 free Actions minutes a month and block CI. A Windows scheduled task on the owner's machine was tried first and removed: the owner only needs warmth from the public flip, and a laptop task flashes a PowerShell window every cycle. Cadence, hour arithmetic, Supabase pause rule and limits recorded in `navigation-performance.md`. | DONE |
| 2026-11-06 | agent | Render `ai` env group (`evg-dbino28u01pc73dfacrg`) is read-only verified and needs owner action before hosted AI can work: it declares `AI_MODEL_PARSE=claude-sonnet-5-5` and `AI_MODEL_SIM=claude-haiku-5-5`, but `adapters/ai` implements `google-genai` only and no code path reads `ANTHROPIC_API_KEY` (present on the service). `GEMINI_API_KEY` is declared as a `sync: false` slot in `deploy/render.yaml` and is **absent** from both the group and the service env list, so `AI_ENABLED=true` would hit the `config.py` start-up rule and take the judges' URL down. Fix = set the Gemini key and change both model names to the current Gemini identifiers, then flip `AI_ENABLED` and redeploy. `deploy/render.yaml` keeps `AI_ENABLED=false` until this is done. | DONE 2026-11-06: owner set the Gemini key and Gemini model names and flipped `AI_ENABLED=true`; service healthy with AI on. The first live smoke then failed inside the adapter's own guards, not the provider — tracked under CR-12 below. |

## Requests between members

T05A02 batch-one pass (2026-11-02): the owner explicitly requested authentication and checkout screens, then an original commerce layout and a new app-wide palette, including shared branding, shell and visual tokens. This authorizes the necessary B-owned frontend/shared and buyer authentication edits for this A-owned task under solo operation; no later-phase buyer/merchant features are pulled forward.

| Date | From | To | Request | Status |
|---|---|---|---|---|
| 2026-11-03 | A | B | `T06A06` puts `lot.bid_open`, `lot.bid_close` and `lot.award` in Member B's `modules/auction/handlers.py`, which `tools/check_imports.py` rule 5 forbids from importing Member A's `apply_lot_transition` or `lot_advisory_lock_key`. Phase 6 therefore re-derives the advisory key in the B lane from the same `"fairpool/lot-lock/v1"` namespace and guards the copy with a unit test that both sides return the same int for the same UUID. A follow-up should move the key and the lot-transition helper to a lane-neutral home so the two lanes cannot drift; until they do, the test is the safety net (`Q-2026-11-03-27`). | OPEN (record) |
| 2026-11-01 | A | B | `T04A06` now ships only the lot, beacon, seed and award content of the public audit payload; the route file `api/routers/public.py` stays B-owned and already carries the keys and close-time fields from Phase 3. Add the fields through the B-owned router rather than editing it from A. | SUPERSEDED by the row below: the content landed, but by editing B's file under solo operation |
| 2026-11-01 | A | B | `db/safety.py` requires a loopback `*_test` database; the local stack has no `fairpool_test`, so `make test` errors on 36 tests unless it is created. Created locally on 2026-11-01; `make setup` should provision it so a clean clone is green. | DONE in Phase 6 (see D-P3-05) |
| 2026-11-02 | A (solo operator) | B | `backend/src/fairpool/domain/**` is B-owned per `docs/team-split.md`, and `T05A05` (A lane) adds R1-R7 guards and `select_across_lots` to `domain/auction_rules.py`. The edit happens under solo operation where `@shaahir27` holds both lanes; recorded so a future separate owner reviews it rather than treating it as pre-approved. | RECORDED (solo operation) |
| 2026-11-02 | A (solo operator) | B | The Phase 5 review pass changed B-owned `domain/auction_rules.py` again (R1 boundary, R4 seats, R6 funding horizon), the B-owned `api/schemas.py` and `api/deps.py` (CR-5 models, `require_merchant`), and everything the T05A02 UI needed (`frontend/src/**`, `frontend/package.json`, two `public/fonts` binaries, the `motion` dependency). Same solo-operation basis; the R4 and R6 readings in particular await the owner's word on `Q-2026-11-02-25` | OPEN (record) |
| 2026-11-01 | A (solo operator) | B | `api/routers/public.py` is B-owned in `api.md` section 2, and `T04A06` edited it in Phase 4 to add the `lots`, `beacon`, `seed_hex`, `seed_is_demo` and `award` content. The edit happened under solo operation (`@shaahir27` holds both lanes), so no other member's unmerged code was touched, but the file is still B's: when B returns as a separate owner, those changes need B's review rather than being treated as pre-approved. This supersedes the open Phase 4 row above. | RECORDED (solo operation) |

## Blockers

| Date | Member | Task | Blocker | Resolution |
|---|---|---|---|---|
| 2026-10-30 | owner | T00A02 / IG-0 | Closed 2026-10-30: security steps complete; IG-0 tagged; Codex PayPal 1.2.0 skills recorded; live MCP unavailable in Codex 0.164.0; public visibility deferred to submission QA. | closed |
| 2026-11-01 | owner | T03B05 / S11 / IG-3 | `IT-3` requires the APIMatic trial to start in Phase 3, and `Q-2026-10-31-14` forbids starting it without the owner. Generation and licence notes can be recorded offline; the trial and any live SDK smoke cannot. | OPEN — owner action: authorise or defer in writing (OD-P3-2). IG-3 must not be tagged while this is unresolved. |
| 2026-11-01 | A | T03A03 / S5 | Three of the seven contracted webhook event types (`CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.PENDING`/`DENIED`) cannot be produced before authorize, capture and void handlers exist in Phase 4-5. | OPEN — recorded per event type, which `spikes.md` S5 explicitly allows; not a Phase 3 failure. |
| 2026-11-01 | B | T03B02 / OD-P3-3 | The Elastic half of the search parity test needs a cluster; the S8 cluster's provenance, credentials and trial dates are not recorded, and the plan says spend nothing without the owner. | OPEN — Postgres path is the CI proof; the Elastic half runs only where credentials exist and is labelled when it does not. |
| 2026-11-03 | A | IG-6 / deployment check | Read-only Render API and HTTP check of the live stack. `fairpool-api` is not suspended and is healthy: `/health` 200, `/ready` 200 with `database` and `migrations` ok, `/` serves the built SPA and `/api/v1/pools` answers, so **`https://fairpool-api.onrender.com` is the working app URL**. `fairpool-frontend` is `suspended` by `user` and answers 503 `Service Suspended`; it is redundant, not broken, because a second `*.onrender.com` subdomain can never hold the session cookie. Two defects were found and fixed in code on this branch: the README named the suspended host as the hosted link, and the served page still carried the Phase 1 meta description saying "no marketplace action works yet". Both services auto-deploy **from `main` only**, so the live build is `daa822c` and shows none of Phase 6. Separately, the ngrok host in `.env` (`PUBLIC_BASE_URL`) now forwards to `127.0.0.1:8000`, which is a local dev API on the compose database, publicly reachable on the internet -- fine for a Sandbox demo, but the owner should know it is open and stop it when the run is done. | OPEN — needs two owner decisions: the pull request or merge that makes CI run and the demo show Phase 6 (`ci.json`), and whether to repoint the PayPal listener at the ngrok host to capture a real webhook delivery (C-15). No hosted write was attempted. |

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
| D-P3-05 | PH3 | `make setup` does not create the loopback `fairpool_test` database `db/safety.py` requires, so a clean clone cannot run `make test` until someone creates it. Fix: add it to `setup` or to `deploy/db-init.sql`. | A | CLOSED 2026-11-03 (Phase 6): `tools/ensure_test_db.py` runs from `make setup`, resolves the URL the conftest way, refuses anything but a loopback `*_test` database through `db/safety.py`, and prints a SKIP rather than failing the bootstrap when the server is not up. `tests/concurrency/test_join_200_parallel.py` also stopped reading `DATABASE_URL` directly, which was the one file that could not run from a plain shell |
| D-P3-06 | PH3 | `.gitignore` lists `docs/evidence/` as disposable local output, yet the Phase 2 evidence files are tracked. `make gate-check` therefore reads a directory a clean clone does not have. Fix: drop the ignore rule and keep evidence committed (it is a gate record, not build output), or move the checks onto committed artifacts. Phase 3 evidence was force-added to follow the Phase 2 precedent. | A | OPEN |
| D-P3-07 | PH3 | `/api/v1/pools?q=` reached the search service only after the review pass: T03B02 shipped the service, indexer and reindex route while the public listing still ran a keyword `ilike`. Now routed through `SearchService` with one route-level test. | B | CLOSED |
| D-P4-01 | PH4 | The Render deploy of the Phase 4 image timed out with "no open ports detected" even though uvicorn logged `0.0.0.0:10000`: the Dockerfile declared `EXPOSE 8000` while Render injects `PORT=10000`, and Render's port scan trusts the declaration. Fixed by declaring 10000 and defaulting the command to it, with compose pinning `PORT=8000` for the port it actually maps. | A | CLOSED |
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
- 2026-11-06, owner (audit follow-up): six verified loopholes opened as buckets F1-F6, delivered on `main` under the section 6 solo note. F1 merged: blueprint moves the hosted demo to `authorize_capture` (the mode IT-5/C-08/C-09 proved and the mode README line 5 describes; `vault_charge` remains the code default and is labelled fake-only per DEP-5), states `VAULT_REAL_SAVE_ENABLED=false`, corrects the Orders v2 payee wording, names where the stand-in-seller fallback is actually labelled, adds the fee-on-refund sentence `vault-charge.md` section 61 requires, and re-stages three storyboard beats that depended on capability that does not exist. `tests/unit/test_render_blueprint_mode.py` pins blueprint-to-README agreement. CR-11 merged (contracts only, `contracts-v1.7`): audit reveal gate, per-lot `bids_root`, signed read-time `checkpoint`, checkpoint coverage over `pool`/`lot`/`bid`, `fetch` round-window rule, `pools.beacon` add→merge, `bid_set_case` vector. F3 merged: `BeaconAnnouncement.fetch` implemented (unresolved round or transport failure is the F27 wait, never a failed job), round schedule recomputed from live chain parameters, announcement merged rather than replaced at seed so `rules_document` keeps hashing to `rules_hash`, and `FakeBeacon` gained the `not_before` key the real adapter returns. Full backend suite 1,225 passed; CI green on F1. Next: F4, F2, F6, then F5. Blocked on owner: live Render `ai` group carries Claude model names with no Gemini key, so `AI_ENABLED` stays false until that is fixed.
- 2026-11-06, owner (audit follow-up, second pass): F4, F6 and F2 merged on `main`. F4: `lot.bid_close` writes `bids_root`/`bids_count` into the LS-02 payload through the existing `merkle_root`; the published checkpoint chain widened from `subject_type='pool'` to `pool`/`lot`/`bid`; a read-time Ed25519 `checkpoint` added (first app-side use of `verify_ed25519`); `total_capacity` made a required bid key with the per-lot capacity fallback deleted (the fallback is what let one merchant claim a lot capacity on every lot); R8/R9 rejection codes coarsened to merchants while staying exact in the column; `seed_hex`/`beacon` withheld until no lot is `PLANNED`/`BIDDING` and the chain until none is `BIDDING`, which is what made `lot_tiebreak_hash` readable pre-bid. F6: LS-04 notifies seated buyers and BS-09 notifies the loser, both already declared in `state-machines.md`; a priced-out buyer now sees the delivered price beside their own confirmed cap. F2: `frontend/src/audit/verify.ts` (canonical JSON, SHA-256, Merkle, rank hash, demo seed, rules hash, Ed25519 on Web Crypto, no new dependency) plus the real audit page replacing the placeholder, with vector parity pinned in both languages and `tests/unit/test_rules_hash_vectors.py` shipped as implementation-plan named it. Local gate: 1,253 backend tests passed (baseline 1,207, +46) at 94.59% domain coverage against the 90% gate, 290 frontend tests in 30 files, strict typecheck, eslint, production build, ruff, import boundaries, docs validation and merchant OpenAPI all clean. Mutation-checked: removing the bids_root payload fails 3 tests, emptying the coarse-reason map fails 2, deleting the seated-buyer notify fails 1, and the restore returns all to green. Remote CI on this push and the hosted re-seed plus live smoke are not yet observed. Four pre-existing local-only mypy reports in `infra/metrics.py` and `adapters/search/projection.py` were left untouched: CI's identical command is green and both files are outside this work.
- 2026-11-06, owner (live AI smoke): hosted AI is on and calling Gemini (`gemini-3.5-flash-lite`), and the first end-to-end intake failed every dated message **inside FairPool's own guard layer**, not at the provider. `ai_runs` and a local replay of the real model showed three distinct faults: the currency marker list had no `$`, so a proposal of USD for "my cap is $650" was rejected as ungrounded; the schema demanded ISO while the model copies what it read, so "by Nov 30, 2026" failed validation, retried, and then failed the guard that wants that ISO string verbatim in the message; and a weekday ("by Friday") can never be an ISO date, so the whole proposal died and the buyer got the manual form. CR-12 (`contracts-v1.8`) records the reading: an explicit calendar date in any written form is canonicalised and grounded against the day the message states, a weekday or relative phrase goes back to null and the existing 2.6 question asks for the date, and a currency symbol grounds its code. A slash date still grounds nothing on purpose. Because the 2.6 answer is its own turn, grounding now also reads the buyer's earlier messages (never the server's own question, which quotes the pool's delivery bound) and the prompt tells the model to carry established fields into the answer — without both halves, "by Friday" ended in the manual form one turn later. `PROMPT_VERSION` is `phase2-gemini-v10`. Live probes: the four message shapes pass (the ISO-date message hit one transient provider error, then passed on both re-runs), and the two-turn path returned a complete card 5/5 with the pool, region and cap carried from turn one. Because the prompt changed, all 50 labelled intake cases were re-measured live at v10 (`v10_intake_spots` in `docs/evidence/phase2/gemini.json`: 100% on their labelled fields; ten provider-unavailable cases were re-run in two follow-up reports, and every raw report is retained); `tools/gate_check.py` now requires that block instead of accepting the v4 baseline only while the prompt literal is v8. Tests: `test_gemini.py` gains 20 guard cases (65 pass in that file), plus a two-turn test in `test_intake_validation.py` and the gate-tooling test for the new block. The local `fairpool_test` database was wiped after it was found to hold 20 pool rows committed by earlier runs, which pushed a fresh pool out of the 20-row public listing page and failed `test_a_simulation_pool_is_invisible_to_public_surfaces`; the test itself is unchanged because the suite's premise is a disposable database.

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

## Phase 5 execution record (2026-11-02)

Built and verified in this phase: the real redirect checkout (`offer -> continue ->
approve -> return -> server-side authorize`), the failure path to net zero (void,
capture, refund, `LS-08` to `LS-10`), the shipping address sealed as a Fernet token
under `ADDRESS_ENCRYPTION_KEY` (BD-11), the merchant profile with the three
attestations, sealed bids with Ed25519 receipts on the bid whitelist, the `ranking_v1`
rules engine with R1 to R9 and two new vectors, CR-5's nine optional response keys,
the checkout and order-status screens, an app-wide session gate, `tools/demo_seed.py`,
and `make api` / `make web` / `dev.ps1` for the no-Docker path.

Live Sandbox evidence (`docs/evidence/phase5/it5_sandbox.json`): one real buyer
through the redirect path; C-08 authorize then void to `FAILED_CLOSED` with a zero
ledger; C-09 capture `COMPLETED` to `FUNDED` then refund `COMPLETED` with a zero
ledger. A third approval was correctly refused (`WRONG_COUNTRY`) for a non-US payer.

Review state: five independent read-only passes ran on this phase. The first four
returned FAIL with findings, and every finding is fixed and named by a test (the list
is in `docs/evidence/phase5/independent_review.json`). The two the later passes caught
inside the fixes themselves were the adapter refusing `attempt 0`, which would have
500'd every first continue, and the gate treating any non-2xx as signed out. The fifth
pass re-read the fixed state and returned PASS with no blocker and no major, so IG-5 is
closed and tagged. Its three follow-ups are recorded in the same file: two belong to the
merchant console (T08B01) and one is the hung-`AUTHORIZING` case of `Q-2026-11-01-18`,
which the Phase 6 reconciler and the authorization age guard settle (IG-6). A re-read by
the implementing agent is not independent and was never recorded as one.

Follow-up raised while closing the gate (unverified, deliberately not shipped): one of
the read-only review agents edited `modules/auction/bids.py`, `modules/checkout/funding.py`
and two test files anyway, adding a lot row lock, switching the bid deadline guard from
`db_now` to `db_wall_now`, parsing `valid_until` at the write, and refreshing the bid
before confirm. All four files were reverted to `f01c783` before tagging: the PASS verdict
was rendered on that state, so an unreviewed mutation cannot ride under it, and AGENTS.md
section 7 keeps a needed change elsewhere a request rather than a silent edit. The
substance is worth a look in Phase 6 - state-machines.md clarification 1 does say a
deadline guard is read on the wall clock after the row lock, and its list names pool, lot
and buyer-order guards rather than the bid window, so whether BS-12's guard owes the same
treatment is the owner's call.

Owner's remaining steps:
- the demo `DEMO_SEED_PASSWORD` is in `.env` only (I14: no repo default, no
  command-line secret). The password an earlier commit carried is still in git history
  as of `4f3ce33`; both databases were re-seeded on 2026-11-02 with the new value, so
  the old string no longer opens anything, but a history rewrite before the repository
  goes public is the owner's call;
- decide `Q-2026-11-02-23`, `-24` and `-25` (contract write-up, job payload naming,
  and the R4 and R6 readings);
- the hosted service ran the Phase 4 image until 3 November 2026, when this work reached
  `main` and Render deployed it; the new checkout screens and the seeded Supabase pool are
  reachable at the API origin now.

Authentication push preparation (2026-11-02): fixed the reported Uvicorn access formatter crash by preserving its five redacted arguments. The regression uses the real AccessFormatter and applies the filter twice; it failed before the fix and all 18 logging tests pass afterward. PayPal Sandbox accepts the configured client credentials, but the user still sees provider-side invalid client_id or redirect_uri. No successful consent callback is claimed.

CR-7 follow-up — IN REVIEW (owner request 2026-11-02): the owner confirmed the
HTTPS ngrok PayPal return works and requested name/email/address prefill, reusable
encrypted delivery addresses and a clean separate delivery step. Screenshots show
Full Name, Email and address attributes selected; a fresh consent round trip is
still needed for expanded scopes. The earlier commit/push authorization is on hold
until the owner tests the tunnel flow. Local-only URL changes are ignored.

CR-7 validation (2026-11-02): `make verify` exits 0: 938 backend tests,
49 frontend tests, 94.50% domain coverage, lint/types/imports/docs/OpenAPI and
Gitleaks history scan pass. Frontend production build and separate redacted
working-diff/new-file secret scan pass. Graphify AST update completes; SQL parser
is unavailable and Markdown semantics are not refreshed. Migration 0006 and
`alembic check` pass on local and Supabase; the test database migrates through
the same revision. Public ngrok pages and signup-start endpoint respond 200 with
the HTTPS callback and expanded standard scopes. Fresh PayPal profile/address
claims and screenshot verification remain for the owner; no commit or push.

PayPal prefill root cause, isolated live on 2026-11-02 with the owner's
sandbox buyer and a Chrome-driven full consent: the exchange succeeds and the token
response carries `access_token expires_in nonce refresh_token scope state token_type`
but **no `id_token`**, and both documented identity endpoints answer with only
`['sub','user_id']` - no name, no email, no address, no payer_id. Adding `nonce` to the
authorization request changed nothing and was reverted. The scope list is delivered
correctly: PayPal re-serialises it as
`openid profile email address https://uri.paypal.com/services/paypalattributes`, so the
`+` encoding is not the fault. A second, never-consented US buyer (created for this
test; its attempts give a distinct account key, so the pair really is two accounts) and
a `nonce` on the authorization request were run as a two-by-two against the first buyer
without a nonce: all four give the same token response with no `id_token` and the same
`['sub','user_id']` from both endpoints, and no consent screen in any of them. The stale
grant is therefore ruled out outright - the never-consented buyer saw no consent screen
on its *first* run minutes after being created, so Sandbox approves silently and never
prompts - as is anything in our request or our parser.
The owner then confirmed the callback is registered in the Login with PayPal **Return
URL** field, so the app's LIWP setup matches the guide. What the guide also states is
`Because Log in with PayPal involves sharing customer data, PayPal must review your app
and approve it`, which is the one remaining candidate and is visible only on the app
page. Nothing in our code can make PayPal send claims it does not send.
One real defect was found and fixed on our side while proving this: the adapter merged
the second endpoint's response only on an exact identifier match, and the two schemas
report the same account as a bare `user_id` and as its identity URL, so the claims
would have been dropped even if PayPal had sent them. `_same_account()` compares the
two documented forms without re-keying the stored identifier (BD-12 holds), with a test
that the claims now arrive and a test that another account is still ignored.

Shared-device rule (owner decision 2026-11-02): duplicate control is the PayPal account,
not the browser. `POST /api/v1/auth/paypal/start` no longer refuses a browser that already
holds a session, and `/register` no longer sends a signed-in visitor home, so a second
person on one device can enroll their own PayPal account. The refusal stays where it
belongs: the same linked PayPal identifier cannot enroll a second user, and the new
integration test walks exactly that family - one buyer signs up, a second buyer signs up
in the same browser, and the first buyer's PayPal account is then refused with
`reason=account_exists`. This reverses a guard that was deliberate and tested; the
superseded test is renamed rather than deleted so the reversal is visible in the suite.

Hosted deployment is single-origin now (owner chose this 2026-11-02). Live browser proof
first: on Render `POST /api/v1/auth/login` answered 200 and `/api/v1/me` immediately
answered 401, and five PayPal signup attempts left five rows with `authenticated_at` NULL -
the browser never carried the cookie. Cause: `onrender.com` is on the Public Suffix List,
so `fairpool-frontend.onrender.com` and `fairpool-api.onrender.com` are cross-site, and a
`SameSite=Lax` cookie set in a cross-site fetch response is dropped. Nothing signed-in
worked there, not just signup. The API image now builds the Vite app in a Node stage and
serves it from `/app/web`, the client falls back to its own origin when
`VITE_API_BASE_URL` is unset, and `FRONTEND_BASE_URL` and `CORS_ORIGINS` on Render point at
the API. Same-origin proof in the built image: `/start` stored the cookie and `/status`
then read `pending`, where the split origin had read `not_started`; `/`, `/register` and
`/assets/*` serve the SPA while `/api/v1/nope` keeps the JSON 404 and `/health` stays 200.
The static frontend remains a page preview only. Also fixed in `.env`:
`PAYPAL_LOGIN_REDIRECT_URI` pointed at `/paypal-login/callback`, a path the app does not
serve, so the signed-in linking flow could never complete; it is now the real
`/api/v1/paypal/login/callback`. That link callback is not yet a registered PayPal return
URL on either host, which is the owner's dashboard step if linking is wanted for the demo -
registration does not need it.

## Phase 6 execution record (2026-11-03, branch `phase-6`)

Verification on this branch, recorded in `docs/evidence/phase6/local_checks.json`:
`make verify` exits 0 - 1027 backend tests pass with the domain coverage floor met at
94.52%, mypy --strict is clean over 70 files, 107 frontend tests pass across 13 files
(with the owner's own restyle in place), `make test-faults` is 18 passed,
`tools/check_imports.py` reports 0 lane violations, `tools/validate_docs.py` reports 0
errors (two warnings, both the illustrative no-such-endpoint path the IT-1 probe uses), the merchant
OpenAPI document still holds exactly ten operations, and gitleaks finds no leak across
82 commits.


**IT-6 ran live, and it found what tests could not.** Between 14:05Z and 15:26Z the whole scenario went through against PayPal Sandbox on loopback: a two-lot pool opened, seeded, allocated and awarded from four real sealed bids; a buyer approved a real order and the server re-checked it with a GET rather than trusting the redirect; authorization 1C716592GL014192L was captured to 8J691800FS7606033, COMPLETED 470.00 USD on a direct PayPal read; lot 1 reached FUNDED on one distinct paid buyer and that capture was then refunded to COMPLETED; and lot 2, one authorization against a minimum of two, was voided to FAILED_CLOSED at net zero with PayPal's own GET reading the authorization VOIDED. Seven real webhook deliveries reached the deployed listener -- including AUTHORIZATION.VOIDED and CAPTURE.REFUNDED, two of the three types S5 had recorded as unproducible -- and C-15 passed over the capture event's bytes. Two lessons only a live run gives: the abort route I had planned to fail lot 2 with is a NotImplementedError stub, so the refund had to come from BO-13's ops branch and is labelled as that; and lot 2 did not fail at its fund deadline, sitting CHECKOUT_OPEN two minutes past it until a try_fund job was enqueued by hand, which is Q-2026-11-03-32. Whether PayPal keeps its fee on a refund is still unanswered: the Sandbox read returned a null fee breakdown, so no claim is made.

Six commits on `main` -- four from this phase, then the CI assertion fix and the evidence close-out -- both lanes run by one operator, pushed and deployed.

**One thing the green run does not cover.** The commit that closes the gate, `8c04761`, went red in CI on `Frontend`: `tests/signup.flow.test.tsx:150` expected the email field to still hold `drafted@example.test` and read an empty value. The tag `ig-6` sits on that commit. The very next commit, `2dc3283`, differs only in a README sentence and CI is green on it with all nine jobs, and the test passes when run on its own here -- so this is an intermittent test in the signup prefill flow, not a Phase 6 regression. It is recorded instead of quietly re-run until it passes. The landing-page commit `1f01be4` reddened the same job with the same message, which made it worth diagnosing rather than retrying: `SignupDetailsPage` renders its heading the moment the status answer flips the page to `ready`, but seeds email, name and address in a passive effect that lands a tick later -- so an assertion written against the heading can read an empty field, and in the tests that type immediately after the heading the seed can land after the keystrokes and erase them. The suite now flushes that effect before it touches the fields. Reproduced before the fix under CPU load (the old pattern failed 2 of 6 runs with CI's exact assertion) and 8 of 8 clean after it, so the race is closed rather than retried away. CR-8
landed first so no later commit had to re-litigate the guard it depends on.

**CR-9, raised and authorized inside this phase.** The owner asked for the buyer receipt
screen to be worth keeping. `POST /api/v1/pools/{pool_id}/entries` issues the signed
receipt once and nothing else returned it, so a reload in another browser left the buyer
with nothing to keep and the screen had to cache the value in `sessionStorage` to look
whole. `entry_receipts` already stores every field and `receipt_for_entry` already
rebuilds the exact body for the join replay, so the fix was one optional field on a
B-owned read route rather than a new endpoint: `GET /api/v1/pools/{pool_id}/entries/me`
now returns `receipt`, as the bytes that were signed (the route answers with a
`JSONResponse` for the same reason the join does — a re-serialised timestamp would no
longer verify). The browser copy went out of `drafts.ts` with it: one source of truth.
Written into `api.md`, the change log, and `tests/integration/test_join_receipts.py`.

**Buyer UI v1 (T06B05) and the design pass the owner asked for.** `frontend/src/buyer/`
gained `discover/DiscoverPage.tsx`, `lobby/PoolPage.tsx`, `lobby/money.ts` and
`receipt/EntryReceiptPage.tsx`; the two placeholders in `pages.tsx` are gone. The
contracted FR-UI-01 badge is one exported constant and is asserted as a literal. The
countdown is fed by the SSE `tick` frame and never by `new Date()`; before the first
sample the screen states the deadline in absolute terms. `usdToCents` parses the
contracted `^\d+(\.\d{1,2})?$` shape with integer arithmetic only (BD-14).

Two things this pass got wrong at first, and both were corrected after the owner
pushed back rather than left in: cards were painted near-white, which is foreign to a
glacier-blue palette, and the workspace rail's logo badge was recoloured to marigold
while `canvas` was deepened - and `PoolMark` draws its glyph *in* `canvas`, so that
edit changed a brand asset. `canvas` is restored to `209 224 248`, the mark renders
exactly as it does on the sign-in panel, and the colour work moved to a token layer.

The flatness the owner described has a number: page-to-panel was **ΔL\* 5.5**, which is
why every surface read as one shade. The new ramp is `page 186 206 236` → `card
238 245 254` (**ΔL\* 13.1**) with `surface` kept for inset wells and two semantic bands,
`tint` for the buyer's own stake and `coral-tint` for the one destructive confirm. The
rail takes `--color-brand-field` (35 67 168) - the sign-in panel's own surface, not a new
hue - with `field-band` for the active row. Every text pair is measured, not assumed:
`ink` on card 13.21, `muted` on card 7.85, `on-field` on the rail 7.44, `field-muted`
5.36, marigold on the rail 5.80, all AA. `--color-canvas` is used inside the logo and as
an in-panel chip, so it was left alone. Coral is unchanged as the single action colour
and gained a 1px `accent-strong` edge because the fill against a card measures 2.89:1
and a control boundary needs 3:1. New tokens live in `index.css` and `tailwind.config.js`
only; no component carries a raw colour. A scoped `@media print` block prints the receipt
without the workspace chrome, and the caret, scrollbars and text selection are now themed
from the palette instead of shipped as platform defaults.

Copy was cut where it had become lawyer-speak: the intake panel's helper paragraph about
what the server owns is gone, the confirmation card says "This is what we understood.
Check it before it goes to the merchants", and the receipt states what it proves in one
line. The FR-UI-01 badge and the two server-built notices are still rendered verbatim,
because those are the API's words, not mine (FR-UI-08, I13).

**Sign-out** exists at last: one control in `shared/components/AreaLayout.tsx`, so the
buyer rail, the mobile menu and the merchant/ops header all get it. It calls the route
that has existed since Phase 1, clears the CSRF token and the session cache, and says
"Still signed in" when the call fails rather than pretending. The shell also greets the
buyer by the name `/api/v1/me` reported and states the PayPal-link fact; `RequireAuth`
caches that one answer instead of the shell asking a second time, and it validates the
payload at the boundary (a stub `/me` without a name is recorded as no account info, not
handed to the shell as something to call `.split()` on - which is how the first version
broke two guard tests).

**Found while rendering, not while writing tests:** the receipt's "Back to the pool" was
a `<Link>` to the same route the lobby already occupied, so clicking it re-mounted the
lobby with the receipt state still set and the buyer could not leave. It is a button that
clears the view now. The same run showed the lobby offering "Confirm and join" while the
server-clock countdown said the window had closed; the panel now reads that from the
feed's own sample and refuses to offer an action the server will reject.

**Deliberately not built:** no notification bell. `Notifier` writes rows and `/api/v1/me`
reports a count, but no route lets a buyer read them, so a bell would promise a screen
that does not exist - recorded as `Q-2026-11-03-30` for T07B01. `intake/confirm` still
answers 200 where `api.md` says 201 (`Q-2026-11-03-29`): no client branches on it and
this phase had no reason to move a Phase 3 route.

**Rendered, not assumed.** Every changed screen was driven in a real browser against a
local API on the compose database (never the hosted demo one): Discover with a live
trending card, the lobby with a countdown ticking from the SSE feed, the join through
`intake/manual` to a real entry, and the receipt read back from the server after a fresh
navigation with no browser copy to fall on. The narrow pass ran in a same-origin 390px
frame: no horizontal scroll on any of the three, and the one overflow it found - a
64-character rules hash - now wraps. Screenshots were not captured: the in-app browser
surface is not visible from here, so the check is the live DOM and computed styles, not
pixels.

**Independent review, and what it found.** Four read-only review agents ran over this
branch - the money lane, the auction lane, the buyer UI and CR-9, then a confirmation
round over the fixes - and their verdicts, the findings that were not acted on and why,
are in `docs/evidence/phase6/independent_review.json`. Nine code defects and one lying test
fake came out of them
and every one is fixed here rather than argued about. Three were bugs a demo would have
shown: the award's lower-lot gate read only AWARDED and CANCELLED as decided where LS-03
says "past BID_CLOSED", so the moment lot 1 reached checkout every later lot requeued for
ever and its seats were never awarded; the ranking tie-break was derived from the pool
seed while the published vectors derive it from the lot seed, so a tie broke in a way no
buyer could reproduce; and a bid that failed R8 or R9 was moved to ELIGIBLE - whose guard
is "all rules pass" - and then to LOST, with no reason code and no notice to the merchant.
One was a money bug: an aged seat with no stored authorization fell through to a replayed
authorize, and when the original send died before PayPal saw it that key is one the
provider has never seen, so the "replay" created a fresh authorization on a seat the BO-03
re-check had just refused (I7, I9). It reads the order now, and a seat with nothing to
read stays locked - which is an open reading, not a settled one, and is written up as
`Q-2026-11-03-31` rather than quietly lived with. The webhook ingest committed nothing
before verifying, so a delivery the adapter could not parse lost its raw body in the
rollback, which is the one thing `paypal-adapter.md` section 8 forbids; the missing CR-9
receipt row answered 500 and took the buyer's own status screen with it; the cancelled-pool
copy promised a hold release that PS-08 makes impossible; and `engine._enqueue` still
carried the pre-CR-8 field name `reason`, in a branch no transition can even reach.

F10's own fake was lying too: it wrote the EXPIRED status *after* its simulated timeout had
already raised, so the expiry never landed and the test passed only through the replay path
the money fix removed. The fake now states the expiry into the order, the authorization
table and the replay before losing the response, which is what its docstring always said,
and the aged seat settles through a read. The confirmation round was asked to treat that
fixture as suspect precisely because it changed in the same round as the code it tests; its
verdict was that the fake is honest rather than shaped to pass, and `Ship` with nothing
in must-fix. Four small items it then raised - the narrowed duplicate-recovery guarantee,
the zero-evidence open question, an over-wide ValueError log and a dead LOST-stamp loop
that bought six deleted lines - are applied after that verdict, and the evidence file says
plainly that no agent has read them since.

### T06B05 usability and loading follow-up (2026-11-03)

The buyer pool page now keeps product information first and places the entry controls below the product and stages, rather than in a narrow side column. Joining stays on the pool page; opening the receipt is an explicit action. The receipt has grouped references/account details, a product row, a separate joining-fee summary, and download/print controls below the document. The PDF is an entry acknowledgement, not evidence of a purchase payment; signed proof remains an unchanged JSON download. Unsupported font characters refuse PDF export and offer Print instead of losing a buyer's name.

Mobile shopping tabs are separate from the labeled Account menu. The desktop rail is compact, request examples are shorter, and shared loading screens use transform-only motion with a reduced-motion alternative. Entry checks now distinguish loading, absence and failure; only a confirmed absence offers joining. Buyer page code downloads during the session check, and versioned static JS/CSS can be cached while HTML revalidates.

Validation: `make verify` passed for the backend/static-serving and initial frontend changes; the latest UI refinements passed all 115 frontend tests, production build/typecheck and lint. Named regression checks are in `lobby.behavior.test.tsx`, `receipt.behavior.test.tsx`, `receipt.pdf.test.ts`, `buyer.shell.test.tsx` and `test_web_serving.py`. The generated sample PDF was rendered and visually inspected. Browser screenshots and authenticated hosted performance profiling were unavailable; public HTTP timing was measured without credentials. Independent review covers correctness and the font fallback; deployment verification is recorded in the pull request.

### Public landing and sign-in navigation (2026-11-03)

The public landing is at `/`; buyer discovery is at `/discover`. Buyer and merchant sign-in share the existing authentication endpoint, open their respective workspaces, and link back to the landing. Protected deep links retain their destination through sign-in. The example walkthrough is opt-in and can be paused or navigated by step.

`landing.flow.test.tsx` covers both sign-in paths, return links, merchant deep links, and walkthrough playback. Chrome checks covered 320–1440 px, including touch navigation and reduced motion. The production frontend build passed.


### Public landing palette and copy review (2026-11-04)

Owner-requested follow-up to the imported landing page: retained its layout, routes and scroll walkthrough. Blue fields now use flat shared palette tokens; the decorative gold uses the shared mark token. Winning-bid text uses the light field foreground (the regression test first failed at 3.44:1 with gold). Selection text explicitly uses dark ink. Copy now distinguishes saved-payment consent and automatic capped charges from checkout approval, explains refund initiation/status and outside-PayPal merchant settlement, and limits the allocation claim to auditable ordering.

Removed an unused counter and fixed strict TypeScript guards in the imported page. Updated the landing tests from the previous playback controls to the scroll walkthrough and supplied browser observer/media stubs. All 123 frontend tests, frontend eslint, production build/typecheck and git diff whitespace checks passed. Browser visual QA could not run: the taste inspector timed out on Page.enable and the browser access host was unavailable. Its source style lint reports existing decorative patterns outside this palette/copy pass; no full design-gate pass is claimed. No payment behavior or contracts changed.

Verification follow-up: Graphify AST refresh succeeded (6,721 nodes). The full backend run passed 1,003 tests with 26 setup errors caused by denied access to the system pytest temp directory; all 76 tests in the affected files then passed using an explicit workspace basetemp. The final frontend rerun passed all 123 tests and the final production build passed. Backend/frontend lint and strict typechecks, import boundaries, documentation validation (two existing warnings), and Merchant OpenAPI validation passed. `make verify` is not reported green: the default temp path failed, and the separate remaining checks could not execute Gitleaks because its installed binary was permission-denied. Browser screenshots and the full taste design gate remain unverified; pre-existing decoration is retained within this scoped review.

### Admin workspace routing and focused ops pages (2026-11-04)

Owner-authorized follow-up to T07A04 and FR-ID-05 across both frontend lanes. Root cause: login trusted the requested workspace rather than the server role, while RequireAuth checked session existence only. Login now reads /me after password verification, selects the role's home and retains only destinations in that role's workspace. Buyer, merchant and admin routes require their matching role before mounting or fetching protected page data. Existing server role and per-user ownership checks remain authoritative; admin does not impersonate a buyer.

The ops workspace reuses the buyer workspace shell and all existing palette tokens. Overview contains the real alert summary, alert queue and links to affected lots; Lots contains the inspector and confirmed abort action; Recovery contains dead-letter retry and reconciliation; Audit contains export; Sandbox controls are a separate utility destination. The old page-level grid that squeezed headings into side columns was removed. No new backend endpoint, dependency, payment behavior or contract was introduced. Research: Atlassian navigation/layout guidance (https://atlassian.design/components/navigation-system/layout) and Carbon's contextual empty-state guidance (https://www.carbondesignsystem.com/building-blocks/core/patterns/empty-states). The owner's existing brand and request for focused pages override the initially dealt framed-sheet direction.

Verification: all 177 frontend tests pass, including 13 role-routing/access regressions; production build (strict TypeScript), eslint, backend ruff/mypy, import boundaries, Merchant OpenAPI and documentation checks pass (two pre-existing documentation warnings). The full backend run passed 1,080 tests with 95% domain coverage and 26 setup errors from Windows temp-directory permissions; all 76 tests in those affected files then passed using a workspace basetemp. Gitleaks passed with elevation (106 commits, no leaks). Thus the original make verify invocation is not claimed green. Real Chrome verified admin form login to /ops, admin redirection away from /discover, and all five admin pages at 1440, 768 and 390 pixels: no page overflow, zero page exceptions. Reviewed screenshots include loaded alert data and each task page; no destructive control was exercised against the shared database. Graphify AST refresh succeeded: 7,402 nodes; Markdown semantics were not rebuilt. Skills used: Graphify, Ponytail, TDD, verification-before-completion, design-taste-frontend, Impeccable and UI/UX Pro Max; missing helper paths were resolved using supplied alternate skill locations, and the design browser helper required elevation.
