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
| Current phase and gate | PH3 planning; IG-2 closed by owner exception (not tagged; automated acceptance pending) |

## Gates

| Gate | Status | Tagged by | Notes |
|---|---|---|---|
| IG-0 | DONE | owner | tagged `ig-0`; CI green (run 41086853451); T00A02 complete; Codex PayPal 1.2.0 skills loaded (SSE MCP unavailable in Codex 0.164.0); public visibility deferred to T10A02/T11X01 |
| IG-1 | DONE | owner | tagged `ig-1`; IT-1 green locally and hosted: API https://fairpool-api.onrender.com, frontend https://fairpool-frontend.onrender.com; `/health` and `/ready` 200; webhook 200 with the raw body stored; Supabase free Postgres; Render Postgres deleted |
| IG-2 | DONE (owner exception) | not tagged | Owner explicitly closed IG-2 on 2026-10-31 despite outstanding acceptance checks. The current Gemini evaluation recorded 479/480 case checks passing across resumed segments; one consistent offer required review. Earlier capacity parsing errors remain unresolved. The gate checker still reports Gemini and CI evidence pending; this closure is not an automated acceptance pass. |
| IG-3 | TODO | not yet | |
| IG-4 | TODO | not yet | |
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
| T03A01 | A | L | TODO | | Buyer-order transition engine |
| T03A02 | A | M | TODO | | Offer expiry and seat control |
| T03A03 | A | S | IN PROGRESS | | Spike S5 webhooks (partly recorded Oct 28; see spike-results.md) |
| T03A04 | A | S | DONE | | Spike S10 PayPal MCP read-only verification |
| T03A05 | A | S | DONE | | Spike S12 shipment tracking |
| T03B01 | B | M | TODO | | Pool join, receipts and events |
| T03B02 | B | M | TODO | | Search service and indexer |
| T03B03 | B | M | TODO | | PayPal Login link flow |
| T03B04 | B | S | TODO | | Pool close |
| T03B05 | B | S | TODO | | Spike S11 APIMatic generation |

### PH4: Core engines III and the first integration

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T04A01 | A | M | TODO | | lot.open_checkout handler |
| T04A02 | A | L | TODO | | Approval checks and authorization flow (fake router) |
| T04A03 | A | L | TODO | | Funding trigger and capture sweep (fake router) |
| T04B01 | B | L | TODO | | Intake pipeline |
| T04A04 | A | M | TODO | | Beacon adapter and pool.seed |
| T04A05 | A | L | TODO | | Allocation and AllocationReadService |
| T04A06 | A | S | TODO | | Public audit endpoint and keys |
| T04X01 | AB | L | TODO | | First integration: pool to checkout |

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

| Q-2026-10-31-08 | implementation planning | Phase 3 join accepts confirmed_request_id, but no persisted confirmed request exists and full intake is T04B01. Recommend pulling forward only deterministic manual confirmation plus a private confirmed_requests record in migration 0003. | api.md Entry/Intake; db-schema.md; T03B01/T04B01 | open; approve narrow CR before dependent code |
| Q-2026-10-31-09 | implementation planning | Vault permission needs entry_id, so ACTIVE-before-entry is circular. Recommend SUBMITTED entry then consent/save and close-time eligibility; specify durable setup attempts, safe restart identities, callback fencing and fake-only Phase 3 lifecycle while real saving remains T05A01 onward. | vault-charge.md sections 2-5; db-schema.md vault_tokens; implementation-plan.md change set C1 | open; approve lifecycle/storage/key amendments before dependent code |
| Q-2026-10-31-10 | implementation planning | Clock.db_now and entry-window trigger use transaction-start now(); a transaction that waits across close_at can admit late while pool.close is delayed. Recommend fresh database wall-clock checks after locks and a new trigger-function migration, retaining canonical/audit timestamp formats. | domain-ports.md Clock; db-schema.md admission trigger; infra/clock.py; migration 0001 | open; approve deadline semantics amendment and lock-wait regression |
| Q-2026-10-31-11 | implementation planning | Phase 3 close must publish commitments, but audit/key routes are stubs; overdue pool.open can leave PUBLISHED unable to follow PS-03. Recommend bringing forward close-time public reads and an atomic whitelisted OPEN/CLOSED catch-up with no late admission. | T03B04/T04A06; api.md public audit/keys; state-machines.md PS-02/PS-03 | open; approve bounded dependency/guard clarification |
| Q-2026-10-31-12 | gate planning | The owner closed IG-2 by exception on 2026-10-31. Gemini acceptance and CI evidence remain pending; PT-14's full award comparison also needs a later award engine. | implementation-plan.md PH3 entry; testing-strategy.md PT-14/IT-3; Phase 2 evidence | owner exception recorded; outstanding checks remain open |
| Q-2026-10-31-13 | implementation planning | OAuth states lack session binding and S1 does not establish arbitrary ID-token nonce validation. S5 requires verified receipts, but the current receiver stores unverified bodies and processing is scheduled later. Specify session/nonce verification and receipt-only scope without enabling absent money handlers. | T03B03/T03A03; db-schema.md oauth_states; api.md; PayPal S1/S5 evidence | open; approve security/phase-boundary clarifications |
| Q-2026-10-31-14 | integration planning | S11 asks for live submit_bid/progress SDK smoke tests before those handlers exist. Recommend labelled contract-stub serialization smoke now, with real workflow smoke explicitly pending for its implementation phase; do not start a trial without owner approval. | spikes.md S11; T03B05 and later merchant/bid tasks | open; record acceptance split before counting S11 complete |

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

## Blockers

| Date | Member | Task | Blocker | Resolution |
|---|---|---|---|---|
| 2026-10-30 | owner | T00A02 / IG-0 | Closed 2026-10-30: security steps complete; IG-0 tagged; Codex PayPal 1.2.0 skills recorded; live MCP unavailable in Codex 0.164.0; public visibility deferred to submission QA. | closed |

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
