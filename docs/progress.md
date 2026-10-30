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
| Member B name and handle | solo operator @shaahir27 (both workstreams) |
| ContextMatic plugin version (A, B) | not yet recorded |
| PayPal AI Toolkit plugin version (A, B) | not yet recorded |
| Current phase and gate | PH0, IG-0 |

## Gates

| Gate | Status | Tagged by | Notes |
|---|---|---|---|
| IG-0 | TODO | not yet | |
| IG-1 | TODO | not yet | |
| IG-2 | TODO | not yet | |
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
| T00A02 | A | S | TODO | | Secrets hygiene |
| T00A03 | A | S | TODO | | API and worker skeleton, settings, host guard |
| T00A04 | A | S | TODO | | Containers, CI and repo tools |
| T00B01 | B | L | TODO | | Pure domain library with shared vectors |
| T00B02 | B | S | DONE | | Spike S1 Log in with PayPal |
| T00B03 | B | S | DONE | | Spike S7 payee-email routing |
| T00X01 | AB | M | TODO | | Contract review and freeze |

### PH1: Data, platform and shell foundations

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T01A01 | A | L | TODO | | Database foundation and migration 0001 |
| T01A02 | A | M | TODO | | Platform services |
| T01A03 | A | S | TODO | | Deploy the skeleton to Render |
| T01A04 | A | S | TODO | | Spike S2 follow-up |
| T01B01 | B | M | TODO | | API schemas, route-table test and Merchant API OpenAPI |
| T01B02 | B | M | TODO | | Port fakes and award fixture |
| T01B03 | B | M | TODO | | Frontend scaffold |
| T01B04 | B | S | DONE | | Spike S6 beacon and sandbox buyers (recorded Oct 29; see spike-results.md) |

### PH2: Core engines I: PayPal gateway, ledger, identity, catalog, AI adapter

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T02A01 | A | L | TODO | | PayPal gateway (raw REST) |
| T02A02 | A | M | TODO | | Payment routers and fake gateway |
| T02A03 | A | S | TODO | | Ledger service |
| T02A04 | A | S | TODO | | Spike S4 payload ladder |
| T02B01 | B | M | TODO | | Identity and notifier |
| T02B02 | B | M | TODO | | Catalog, pool templates, admin publish and rules |
| T02B03 | B | M | TODO | | AI adapter and run logging |
| T02B04 | B | S | IN PROGRESS | | Spike S8 Elastic hybrid search (partly recorded Oct 28; see spike-results.md) |
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
| T04B02 | B | M | TODO | | Beacon adapter and pool.seed |
| T04B03 | B | L | TODO | | Allocation and AllocationReadService |
| T04B04 | B | S | TODO | | Public audit endpoint and keys |
| T04X01 | AB | L | TODO | | First integration: pool to checkout |

### PH5: Real PayPal path, auction core and merchant foundation

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T05A01 | A | L | TODO | | Real PayPal path for one buyer (redirect) |
| T05A02 | A | L | TODO | | Checkout UI |
| T05A03 | A | M | TODO | | Failure path and compensating refund (fake router) |
| T05B01 | B | M | TODO | | Merchant profile and onboarding states |
| T05B02 | B | L | TODO | | Bid API with receipts and sealing |
| T05B03 | B | L | TODO | | Auction rules engine |

### PH6: Money completion and auction to checkout

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T06A01 | A | L | TODO | | Funding sweep and failure path on the real Sandbox |
| T06A02 | A | M | TODO | | Webhooks |
| T06A03 | A | L | TODO | | Reconciler and unknown-outcome resolution |
| T06A04 | A | M | TODO | | Payload ladder levels and shipping address |
| T06B01 | B | M | TODO | | Quote parsing and confirmation |
| T06B02 | B | M | TODO | | AI offer reconciliation and flags |
| T06B03 | B | L | TODO | | Lot handlers: bid_open, bid_close, award |
| T06B04 | B | M | TODO | | Merchant API keys and MerchantAuth |
| T06B05 | B | L | TODO | | Buyer UI v1: Discover and Join |

### PH7: Live end to end and the agent and merchant lanes

| ID | Owner | Size | Status | PR | Notes |
|---|---|---|---|---|---|
| T07A01 | A | L | TODO | | JavaScript SDK v6 approval |
| T07A02 | A | M | TODO | | Refill orchestration |
| T07A03 | A | S | TODO | | Routers per S3 and S7 |
| T07A04 | A | L | TODO | | Ops console v1 |
| T07B01 | B | L | TODO | | Buyer UI v2: My Pools and Orders |
| T07B02 | B | L | TODO | | Agent API and delegations |
| T07B03 | B | M | TODO | | FairPool MCP server |
| T07B04 | B | M | TODO | | Merchant Agent API sub-app: lots and bids |
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
| Q-O2 | owner | Exact issue name in the void-replay 422 body | `docs/spike-results.md` S2 | answered by T01A04 |
| Q-S7 | owner | Does an order addressed to a second sandbox business account by payee email approve and authorize (S7)? Owner decides whether the demo uses `payee_email` | `docs/spikes.md` S7 | answered Oct 28: no. Separate seller captures arrive but void and refund are denied; `payee_email` rejected, `single_seller` final |
| Q-D1 | owner | Confirm the assumed design decisions D1 to D11 in `docs/decisions.md` section 2 (stack, operator-defined pools, and the rest) | `docs/decisions.md` | answered at T00X01 |

## Requests to the owner

| Date | From | Request | Status |
|---|---|---|---|

## Requests between members

| Date | From | To | Request | Status |
|---|---|---|---|---|

## Blockers

| Date | Member | Task | Blocker | Resolution |
|---|---|---|---|---|

## Decisions log

| Date | Decision | By | Recorded in |
|---|---|---|---|
| 2026-10-30 | Single `phase-0` branch from an empty `main` base; one pull request; all PH0 tasks are sequential commits on the branch. | owner | progress.md, plan |
| 2026-10-30 | Ruff excludes legacy spike/validation scripts; backend and the new repository tools are linted. | owner | progress.md |
| 2026-10-30 | pip-compile 7.6.2 lacks `--universal`; hashed locks are generated on Windows and verified by the Linux CI install. | owner | progress.md |

## Defects from rehearsals

| ID | Found in | Description | Owner | Status |
|---|---|---|---|---|

## Submission notes

Devpost text draft, video link and the final checklist result are recorded here by T10A03, T10B02 and T11X01.

## Daily log

One line per member per day: date, member, what merged, what is next.
