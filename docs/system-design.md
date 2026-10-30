# FairPool: System Design and Solution Architecture (v1)

*Design only, no code. Prepared Oct 20, 2026 for the PayPal AI Hackathon. Submissions close Thu Nov 12, 12:00 pm PT (Nov 13, 1:30 am IST). Inputs: the FairPool idea document, the Final Verification Checklist, the Sandbox Test Report and the hackathon brief.*

**Revision note (Oct 27, 2026).** This text was prepared on Oct 20, before spikes S2 and S3 were recorded and before the integration decisions (INT-1 to INT-9). It has been updated to match `docs/spike-results.md`, `docs/decisions.md` and `docs/contracts/README.md`. Changed: sections 2 (I9), 3.1, 3.3, 4.1 to 4.4, 6.1, 6.3, 8.2, 11.1, 11.4, 11.5, 11.7, 13.2, 13.3, 15, 16, 17.1, 17.4, 18, 19 (F1), 20.1, 20.2, 21 and Appendices A and C. Added: 4.5 (every sponsor and partner tool, INT-1 to INT-9, with its layer, usage and fallback), 10.9 (Merchant Agent API), 11.11 (fulfillment and verification) and 13.4 (tools in the agent lane). Schedule dates were removed (header, Step 0 and 20.2); the submission deadline stays. Section numbering is unchanged, so every cross-reference still resolves. Where a heading says “idea section N”, N is the stage number in the how-it-works part of the idea text (stages 1 to 7 are sections 5.1 to 5.8 of `docs/fairpool-idea.md`; see `docs/product-spec.md`). The idea, the invariants and the layer structure are unchanged. **Errata (Oct 28, 2026).** The owner's Sandbox runs changed several statements below; where this file disagrees, `docs/decisions.md` section 4, `docs/spike-results.md` and `docs/contracts/` win. Changed: Log in with PayPal uses scope `openid` only (account-attributes scope rejected; `DEDUPE_MODE=two_keys`); the payee-email route is rejected and `single_seller` is final; shipment tracking uses Orders v2 `POST /v2/checkout/orders/{order_id}/track`, not `/v1/shipping/trackers-batch`; order approval is always confirmed by GET, and webhooks are verified only for authorization-created, capture-completed and capture-refunded; the SDK v6 popup is the primary approval UI; the PayPal MCP is used only as the local, pinned, read-only inspection server. **Oct 29 owner decisions:** the primary payment path is vault-and-charge (`docs/contracts/vault-charge.md`), replacing the authorization-first checkout described in sections 3 and 11 (which remain the fallback); bids are one flat delivered price per lot (`docs/contracts/flat-delivered-bids.md`); the cap is enforced by FairPool, not PayPal; merchants are settled manually (Payouts and the platform route are blocked).

## 0. How to read this document

The design is built in layers, each resting on the one before: invariants, evidence, architecture, data, state machines, then the engines (identity, intake, pool, auction, checkout), then the cross-cutting layers (webhooks, agent lane, simulation, UI, security, platform). Every layer says what it decides, why each component exists, and how it can break.

Evidence tags used throughout:

- **V#**: verified in your Sandbox report or checklist (tested Oct 19 to 20, 2026).
- **P#**: documented by PayPal per your files, not tested by you.
- **G#**: open gate. Unverified, so it gets a test (a spike) before the design depends on it, plus a fallback.
- **X**: PayPal behaviour from my own knowledge, not in your files. Unconfirmed until a spike proves it.
- **D#**: a decision for you to confirm (section 21).

Rule: nothing tagged P, G or X sits on the critical path without an adapter boundary and a fallback. That rule is what keeps the PayPal logic from breaking midway.

## 1. Design principles and non-goals

Principles, in priority order:

1. Money correctness beats features.
2. Claims never exceed evidence.
3. Deterministic core, AI at the edges: AI proposes, rules decide, buyers approve.
4. Smallest stack that preserves 1 to 3: one Postgres, one API, one worker.
5. Every external effect is idempotent, retryable and reconcilable.
6. Authority is explicit: PayPal is authoritative for money state, FairPool for allocation state.
7. Bets are isolated behind adapters, so a failed spike changes configuration, not architecture.
8. Everything must fit a 3-minute demo and a README that a machine (the judges may use automated analysis) can read.

Non-goals for the MVP: live production payments or PayPal platform approval; India-domestic checkout (V12); proof of one human per account; MAP compliance; any wholesale-price guarantee; multi-currency (USD only); more than one unit per entry; split-lot or combinatorial auctions; a real tax engine; shipping and delivery tracking beyond recording.

## 2. Invariants: what must never break

Every later design choice is checked against this list.

| ID | Invariant | Enforced by |
| --- | --- | --- |
| I1 | No money moves without the buyer approving the exact amount on PayPal | PayPal approval gate (V4) plus our single authorize gate (I7) |
| I2 | Only the server-side payment adapter calls authorize, capture, void or refund. Neither the browser nor the AI can | Module boundary; PayPal credentials exist only in the adapter |
| I3 | Final total is at most the buyer’s confirmed cap and equals the authorization amount | Computed from an immutable award snapshot; asserted at order creation, at approval and at authorization |
| I4 | “Paid” means a PayPal capture with status COMPLETED. Order status, approval, authorization or a webhook summary never count (V8: the order read COMPLETED after a void) | Ledger accepts only capture records fetched from, or verified against, PayPal |
| I5 | A lot is funded only when completed captures from distinct buyers reach the MOQ | Funding function reads the ledger only |
| I6 | At most one seat per FairPool user and per PayPal account key in a pool | Unique indexes |
| I7 | A seat is never released while we could still authorize its order | One authorize choke-point plus an AUTHORIZING lock |
| I8 | Offers in flight plus committed buyers never exceed lot seats | Vacancy counter updated in the same transaction as every offer |
| I9 | Every external call has a stable idempotency key where PayPal supports one (verified for create, authorize, capture and refund) and a GET-before-act guard where PayPal does not replay (void, S2). A key is reused on retry and never reused with a different payload | Key table in Appendix A |
| I10 | Every state change is legal per the transition tables and is atomic with its audit record and next-job enqueue | Transactional outbox |
| I11 | Allocation order is a pure function of (rule version, frozen entry commitments, public seed) | Anyone can recompute it |
| I12 | No synthetic entity ever reaches a PayPal call, and no simulated outcome counts as paid | Pool mode check plus a database constraint |
| I13 | No UI or README claim exceeds verified capability | Wording table, Appendix B |
| I14 | Secrets exist only in server environment memory, never in logs, repo or client | Secret scanning plus log redaction |
| I15 | Deadlines are data, timers are triggers: every action re-checks stored deadlines against the database clock when it executes | Guard clauses in every handler |

## 3. Evidence base from your two MD files

### 3.1 Verified facts and what each one forces

| ID | Verified fact | Design consequence |
| --- | --- | --- |
| V1 | OAuth client-credentials returns HTTP 200; token lifetime 32,400 s (9 h) | Cache the token in memory only; refresh about 5 minutes early and once on any 401 |
| V2 | Create AUTHORIZE order (USD 1.00): 201, status CREATED, payee email echoed, no payee.merchant\_id, links include approve and authorize | Verify the payee by email; never require merchant\_id; follow the returned approve link |
| V3 | Same PayPal-Request-Id on create: 201 then 200, same order ID | Order creation is retry-safe with a stable key per buyer-order attempt |
| V4 | Authorize or capture before approval: 422 ORDER\_NOT\_APPROVED, nothing created | Treat as “not approved yet”, never as a failure to retry in a loop |
| V5 | Two orders to the same seller: 201 each, distinct IDs | One PayPal order per buyer, never one order for many buyers |
| V6 | PayPal-Mock-Response produced 422 DUPLICATE\_INVOICE\_ID on create and capture | invoice\_id must be unique per order attempt; the header also gives us fault injection for tests |
| V7 | Webhook event types exist (order approved, authorization created and voided, capture completed, denied, pending, refunded); zero listeners are registered | Nothing is delivered until we register an HTTPS listener (G5) |
| V8 | US buyer, approved AUTHORIZE order: authorize 201 (CREATED), void 200 (VOIDED), GET shows VOIDED with no capture; the order itself then read COMPLETED | Never derive payment state from order.status; money state lives on authorization and capture objects |
| V9 | Approved CAPTURE-intent order: capture 201 then COMPLETED; full refund 201 then COMPLETED | Capture and refund work, but only proven on a CAPTURE-intent order. FairPool uses AUTHORIZE, so capturing an authorization is a gap (G3) |
| V10 | Replaying capture and refund with the same request IDs returned 200 and the original object; still one capture | Capture and refund keys are stable and replay-safe |
| V11 | An approved order’s payer object carries payer\_id, email\_address, name and address (country US) | payer\_id gives an account-level key. It is a PayPal ID, not our user ID, and not proof of one human |
| V12 | India buyer plus India seller: UNSUPPORTED\_PAYEE\_CURRENCY, order stays CREATED; INR is absent from the REST currency list; PayPal India bars domestic receipt | MVP is USD only, with a payer-country guard (US) |
| V13 | Local rule harness passed 17/17 (rules only, no PayPal) | Port as domain tests and re-baseline; its saved-method consent tests belong to the old hold-based design |

Excluded by evidence: Payouts (403 PAYOUT\_NOT\_AVAILABLE) is not a fallback, and NVP/SOAP is legacy and unrelated to Orders v2. Note: the idea document’s earlier Sandbox Testing Status listed buyer approval and the payment lifecycle as NOT TESTED. The Oct 20 report superseded it (V8 to V11), and the idea document now carries those results (idea section 9.2).

### 3.2 Documented by PayPal, not yet tested

- **P1** An authorization is valid for 29 days and has a 3-day honor period; PayPal recommends capturing inside the honor period. A later capture needs a reauthorization (new authorization ID) and can be declined.
- **P2** Void may return HTTP 204 with an empty body (we observed 200 with a body). The client accepts both.
- **P3** Capture statuses include COMPLETED, PENDING, DECLINED and FAILED. Only COMPLETED is paid.
- **P4** Webhooks must be signature-verified and de-duplicated by event ID, with state confirmed by fetching the resource. Simulator events are mock events.
- **P5** Production marketplace payments need PayPal platform approval and seller onboarding. Onboarding after payment does not support authorization intent.
- **P6** PayPal keeps idempotency keys for different periods per API, so our own ledger must also stop duplicates.
- **P7** An order may hold up to 10 purchase units. That is not a multi-buyer order and we do not use it.

### 3.3 Open gates (each needs a spike)

| Gate | Question | Test | If it fails |
| --- | --- | --- | --- |
| G1 | Does Log in with PayPal return the account ID for this app with the paypalattributes scope? (checklist 4.1, 4.2; earlier invalid\_scope) | Complete consent for a sandbox buyer; check whether userinfo contains payer\_id | Duplicate control moves to checkout time (section 7) |
| G2 | Is the Login account ID the same identifier as payer\_id on an approved order? (X) | Compare both for one sandbox buyer | Drop “must pay with the linked account”; keep two independent keys |
| G3 | Does authorize, then capture of that authorization, then refund work? V9 proved capture and refund only on a CAPTURE-intent order | On an approved AUTHORIZE order: authorize, POST /v2/payments/authorizations/{id}/capture, refund the capture; replay each with the same request ID | Switch PAYMENT\_MODE to capture\_only, the V9-verified path: buyers pay at approval and failed lots refund instead of void |
| G4 | Can FairPool direct an order to a second, onboarded seller? (checklist 3.1 to 3.4, 3.8) | Partner Referrals onboarding before payment; AUTHORIZE order with PayPal-Auth-Assertion; verify payee | Router B: one sandbox seller stands in for all merchants, clearly labelled |
| G5 | Do webhooks arrive and verify? (5.1, 5.2) | Public HTTPS listener on 443; real lifecycle events; signature check; dedupe | Reconciler-only mode: correct, slower |
| G6 | Do several distinct sandbox buyers complete approvals? (only one buyer used so far) | Create 4 to 6 personal sandbox accounts; run approvals in parallel | None. The live demo needs them |
| G7 | What does a buyer cancel or decline leave behind? (2.7) | Cancel at PayPal; inspect order and authorization | None needed: our state machine never relies on it |
| G8 | Which payload fields are accepted: custom\_id; invoice\_id with an idempotent retry; amount.breakdown with items; address lock via experience\_context (X) | Payload ladder in section 11.3 | Stay at the minimal V2 payload |
| G9 | Is a platform fee available on the purchase unit? (X) | Test with G4 | Revenue stays on the roadmap |
| G10 | PENDING or DECLINED capture and authorization-expiry behaviour | Mock-response header plus simulated paths | State machine handles it; demo labels simulated paths |
| G11 | Can an order addressed to a second sandbox business account by payee email alone (no partner assertion) be approved and authorized? | Create the order with the second account’s payee email, approve with a sandbox buyer, authorize, void (S7) | PAYMENT\_ROUTER stays single\_seller |
| G12 | Elastic: can a semantic\_text index with an explicit inference endpoint be created and the RRF hybrid query run from Python? | Index public pool documents and run the hybrid query (S8) | SEARCH\_BACKEND stays postgres |
| G13 | Zapier MCP: can Webhooks by Zapier actions be exposed as managed-mode tools with locked URL and header values, and can Claude connect? | Configure four tools and call them from Claude (S9) | ZAPIER\_BRIDGE stays off; our own MCP server covers the same tools |
| G14 | PayPal MCP: is a read-only tool allowlist possible, and what does get-order accept in the Sandbox? | Connect an AI client and call the read tools (S10) | PAYPAL\_MCP\_VERIFICATION stays fairpool\_tool |
| G15 | APIMatic: does the Merchant Agent API OpenAPI document generate Python and TypeScript SDKs within plan limits, and what are the licence terms of generated code? | Export, import, generate and smoke test (S11) | Ship the OpenAPI document and a hand-written minimal client, labelled as such |
| G16 | PayPal shipment tracking: does submitting a tracker for a captured transaction work in the Sandbox? | POST /v1/shipping/trackers-batch for a captured sandbox transaction (S12) | Tracking stays inside FairPool and is labelled as such |
| G17 | JavaScript SDK v6: does createInstance work with the client ID, does the popup approve an AUTHORIZE order, and what does onApprove return? | Minimal page on the deployed skeleton (S13) | PAYPAL\_APPROVAL\_UI stays redirect |

Results recorded since v1 (`docs/spike-results.md`, Oct 20): G3 passed (S2): authorize, then capture of the authorization, then refund works, and authorize replays with the same PayPal-Request-Id (200, same result). G4 failed (S3): Partner Referrals returned 403 NOT\_AUTHORIZED and an order with PayPal-Auth-Assertion returned 401 invalid\_subject, so Router A is unavailable in this Sandbox app. G9 failed (S3): a platform fee returned 422 UNSUPPORTED\_PAYMENT\_INSTRUCTION. Gates G11 to G17 were added after v1 and are listed in the table above (`docs/registry.md`). Every gate not named as passed or failed here is still open.

### 3.4 Hackathon constraints that shape the design

- Sandbox only. The project must run (hosted URL or run instructions), sit in a public open-source repo with a detectable license, and have a public YouTube video under 3 minutes that shows it working and contains no third-party trademarks. So the demo uses generic products, never brand names.
- Judges may not run the project, so the video and README carry the score. A machine may read the repo, so structure and tests matter.
- Ties break on Technological Implementation first, so PayPal depth (authorize, capture, void, refund, webhooks, idempotency) is worth real effort.
- Sponsor tools are optional and never go on the critical path.

## 4. Layer 1: System context and architecture style

### 4.1 Context

```
 Callers in:   Buyer browser (PayPal JS SDK popup)  |  Buyer AI client (Agent API, /mcp, Zapier MCP bridge)
               Merchant UI  |  Merchant bots (/merchant-api)  |  Ops console
                                              │
                                              ↓
               FairPool API ←→ PostgreSQL ←→ Worker (timers, sweeps, webhook processing, reconciler)
                                              │
                                              ↓
 Services out: PayPal Sandbox (OAuth, Orders v2, Payments v2, Webhooks, Log in with PayPal, shipment tracking)
               Anthropic API (intake, quote parsing, simulation text)  |  Randomness beacon (allocation seed)
               Elastic hybrid search (optional, Postgres fallback)  |  Channel3 catalog (optional)

 Outside the product: a merchant’s AI client reads PayPal through the PayPal MCP server (read-only verification);
 coding agents use the ContextMatic and PayPal AI Toolkit plugins; APIMatic generates SDKs and the portal from the
 Merchant OpenAPI document. Section 4.5 maps every tool to its layer.
```

### 4.2 Decision: modular monolith

One codebase, two entry points (API and worker), one Postgres, one static frontend. Money flows need a single transaction boundary between “seat state”, “ledger” and “next job”. Splitting into services would turn those into distributed transactions with no scale benefit at hackathon size. Internal boundaries (ports and adapters) keep the important separations enforceable.

| Alternative | Why not |
| --- | --- |
| Microservices | No scale need; adds distributed-transaction risk to the money path |
| Kafka, Redis or Celery | A jobs table claimed with FOR UPDATE SKIP LOCKED enqueues atomically with state; fewer failure modes |
| Blockchain or zero-knowledge for fairness | A public beacon plus commitments and receipts gives checkable ordering at far lower cost, and the idea document forbids overclaiming |
| PayPal Agent Toolkit or MCP in the payment path | Your evidence is raw REST, and an LLM in the payment path would break I2. The Agent Toolkit is used only as a dev-time plugin (INT-5), and the PayPal MCP server only as a read-only verification copilot outside the payment path (INT-6) |
| PayPal SDK wrappers | Raw REST gives direct control of PayPal-Request-Id, Prefer and PayPal-Auth-Assertion headers, and matches what was actually tested. The browser uses the PayPal JS SDK v6 popup for approval only (INT-7) |
| WebSockets | Server-sent events are enough for countdowns |
| Serverless functions | Timers and long sweeps need a worker |

Hosting: Docker containers deployable to Render (web service, background worker, Postgres, cron). Render is a sponsor with credits, but nothing is Render-specific, and a docker-compose file gives the run instructions the rules require.

### 4.3 Component necessity check

| Component | Needed? | What breaks without it |
| --- | --- | --- |
| PostgreSQL | Yes | Everything: state, ledger, audit, queue |
| API service | Yes | No user surface |
| Worker plus jobs table | Yes | Deadlines would depend on web requests arriving |
| Webhook endpoint | For speed and G5, not for correctness | Slower status updates only, because the reconciler covers it |
| Reconciler | Yes | Lost webhooks and unknown outcomes would strand seats and money |
| AI module | For intake and offer checks, but removable | Manual form replaces intake; deterministic rules still gate offers |
| Randomness beacon | Yes | Without an outside seed, FairPool could bias the draw |
| Commitments, Merkle root, receipts | Yes | Buyers could not check they were included |
| Hash-chained audit log | Yes, cheap | Less tamper evidence (only meaningful with published checkpoints) |
| Ledger table | Yes | I4 and I5 have no source of truth |
| Simulation engine | Yes for the demo | Cannot show scale; isolated by I12 |
| Agent API | Yes (A2A lane in the idea) | The agentic-commerce story disappears. An MCP server is included (INT-3) |
| Merchant Agent API and keys (INT-9) | Yes (merchant lane, added after v1) | Merchant bots and the generated SDKs have nothing to call; the console still works |
| Channel3, AG Grid | Optional | Nothing on the critical path |
| Elastic hybrid search (INT-1) | Optional; Postgres trigram is the baseline | Candidate retrieval and Demand Board search are less precise; no rule depends on it |
| Zapier MCP bridge (INT-2) | Optional | The Zapier path of the headless buyer demo; our own MCP server (INT-3) covers the same tools |
| APIMatic SDKs and portal (INT-4) | Optional; replaces Postman | No generated SDKs or portal; the OpenAPI document still exists |
| PayPal MCP verification (INT-6) | Optional | Verification through PayPal’s MCP; FairPool’s own verification endpoint remains |
| PayPal shipment tracking (INT-8) | Optional | Trackers are not submitted to PayPal; tracking stays inside FairPool and is labelled |
| Redis, object store, email provider | No for MVP | In-app notices are enough |

### 4.4 Module map and dependency rule

| Module | Owns | May call | Forbidden |
| --- | --- | --- | --- |
| identity | users, PayPal link, sessions | PayPal Login adapter | payments |
| catalog | product and pool templates | optional Channel3 | payments |
| intake | proposals and confirmed requests | AI adapter, catalog | payments, ledger |
| pools | pool lifecycle, entries, close, receipts | scheduler, audit | payments |
| allocation | seed, ordering, lots, waitlist | beacon adapter | payments |
| auction | bids, validation, ranking, award | AI (quote parsing, reconcile), pools (read) | payments |
| checkout | buyer orders, seat control, funding, failure paths | payments adapter, ledger | AI |
| payments (adapter) | PayPal REST client, router, token cache | PayPal only | any domain logic |
| ledger | append-only money facts | none | none |
| webhooks and reconciler | ingest, verify, heal | payments adapter, checkout | AI |
| sim | synthetic agents and pools | AI, pools API | payments (hard-blocked) |
| merchants | merchant profiles, attestations, API keys and scopes (INT-9) | ports only | payments |
| search | search service and indexer over public pool and lot documents (INT-1) | search adapter (Elastic or Postgres) | payments, ledger, checkout, AI runs, buyer requests |
| fulfillment | shipments, the per-lot verification manifest and endpoint, tracker submission (INT-6, INT-8) | payments adapter (read-only GETs and tracker submission) | AI |
| agentapi and mcp | buyer Agent API, delegations, the FairPool MCP server (INT-3) | pools, intake and entry services through ports | payment tools, checkout and ledger |
| notify | in-app notices | none | payments |
| api, agent API and merchant API | HTTP, auth, the Merchant Agent API sub-application (INT-9) | services | writing to the database around services |

Dependency rule: domain logic is pure (no I/O); services orchestrate; adapters sit at the edge. The AI package imports nothing from payments, ledger or the database session. A CI lint rule enforces this, which makes I2 a build-time guarantee instead of a convention.

### 4.5 Sponsor and partner tools: layer, usage and fallback

Every outside tool, where it sits, what it is used for, what it is not used for, and what happens if it is unavailable. Decisions INT-1 to INT-9 are in `docs/decisions.md` section 5, switches in section 4, spike results in `docs/spike-results.md`. A tool never decides eligibility, money or fairness: deterministic rules do (I1, I2).

| Tool | Layer and module | Usage | Not used for | Switch or fallback | Spike and gate |
| --- | --- | --- | --- | --- | --- |
| PayPal REST: Orders v2, Payments v2, token | Layer 8, payments adapter and checkout | Create and get orders, authorize, capture, void, refund; raw REST with PayPal-Request-Id keys (Appendix A) | Any AI call; SDK wrappers | PAYMENT\_ROUTER, PAYMENT\_MODE, payload ladder level | S2, S3, S4; G3, G4, G8 |
| Log in with PayPal | Layer 4, identity | Buyer links a PayPal account for duplicate-entry control | Payment | DEDUPE\_MODE | S1; G1, G2 |
| PayPal webhooks | Layer 9, webhooks and reconciler | Signed events speed up status changes; the reconciler is the authority | Correctness | WEBHOOKS\_ENABLED | S5; G5 |
| PayPal JavaScript SDK v6 (INT-7) | Layer 12 checkout page; Layer 8 approval handling (11.4) | Popup approval; onApprove posts the order ID, then the server runs the checks and authorizes | Totals from the browser; capturing in onApprove | PAYPAL\_APPROVAL\_UI (redirect is the fallback), PAYPAL\_SDK\_AUTH | S13; G17 |
| PayPal shipment tracking (INT-8) | Layer 8, fulfillment (11.11) | Merchant uploads tracking; FairPool submits trackers for captured transactions through the adapter | AI calls | SHIPMENT\_TRACKING\_ENABLED; otherwise tracking stays inside FairPool, labelled | S12; G16 |
| PayPal MCP server, read-only (INT-6) | Layer 10 merchant side; Layer 8 fulfillment (11.11) | A merchant’s AI client checks each PayPal order in the per-lot manifest against FairPool’s funded total | Write tools; list-transactions in the live demo; the payment path | PAYPAL\_MCP\_VERIFICATION; FairPool’s own verification endpoint | S10; G14 |
| PayPal Agent Toolkit (INT-5) | Layer 14, dev time only | Plugin in each member’s coding agent (skills, doctor, explain-error) | The payment path: it cannot express an AUTHORIZE order with payee and idempotency, and AI-made payloads would break I2, I3 and I9 | None; verified facts override it | none |
| Anthropic API | Layer 5 intake; Layer 7 quote parsing and reconciliation; Layer 11 simulation text | AI proposes, deterministic rules decide | Eligibility, money, PayPal | Manual form; ops review (8.3, 10.5) | none |
| Elastic hybrid search (INT-1) | Layer 5 candidate retrieval; Layer 7 Demand Board and agent pool search | semantic\_text index with an explicit inference endpoint and an RRF hybrid query over public pool and lot documents only; an advisory LOW\_SIMILARITY warning on quotes | A gate on offers; indexing buyer requests; per-buyer matching against bids | SEARCH\_BACKEND=postgres (trigram) | S8; G12 |
| Zapier MCP (INT-2) | Layer 10, agent lane | Managed mode with exactly four tools (list pools, join pool, list my entries, withdraw entry), URL and Authorization header locked to the Agent API with a delegation token | PayPal or any other app; payment | ZAPIER\_BRIDGE (a documentation switch); our own /mcp | S9; G13 |
| FairPool MCP server (INT-3) | Layer 10, agent lane | /mcp over Streamable HTTP with the same four tools and delegation-token auth | Payment tools | Does not depend on Zapier’s plan or trial | none |
| Merchant Agent API and keys (INT-9) | Layer 7, merchants; Layer 10 for merchant bots | /merchant-api/v1 with ten operations, hashed scoped API keys, rate limits and the sealed-bid rules (10.9) | Exposing the whole app | none | none |
| APIMatic SDKs and portal (INT-4) | Layer 14, build; Layer 7 developer tooling | Python and TypeScript Merchant SDKs and a portal generated from the dedicated Merchant OpenAPI document (10 operations); replaces Postman | Feeding it the whole app (60+ operations) | Ship the OpenAPI document and a hand-written minimal client, labelled | S11; G15 |
| ContextMatic by APIMatic (INT-4) | Layer 14, dev time only | Version-aware PayPal context inside each member’s coding agent | The running product | Verified facts override it | none |
| Randomness beacon (drand) | Layer 6, allocation | Public randomness for the allocation seed (9.5) | none | BEACON\_MODE (demo or drand) | S6; G6 |
| Render | Layer 1 and Layer 14, hosting | Web service, worker, Postgres, cron; sponsor credits | Anything Render-specific in the code | docker-compose for local runs | none |
| Channel3, AG Grid | Layer 1 catalog; Layer 12 | Optional; not in the task plan | The critical path | Omit | none |

## 5. Layer 2: Data model

Every invariant that can be a database constraint is one, because constraints keep holding when code has bugs.

### 5.1 Ground rules

- PostgreSQL is the system of record. All times come from the database clock (I15).
- Money is BIGINT cents with a currency column constrained to USD. No floats anywhere.
- Facts are append-only (ledger, audit, webhook events). Decisions are immutable snapshots (confirmed request, bid receipt, award).
- PayPal objects are mirrored with their raw response, PayPal IDs and debug IDs, so any dispute can be traced end to end.

### 5.2 Entities

| Entity | Key fields | Constraints that carry invariants |
| --- | --- | --- |
| users, paypal\_links | user id; paypal\_account\_key (HMAC of payer\_id); linked\_at | UNIQUE(paypal\_account\_key); one active link per user |
| pools | mode (LIVE\_SANDBOX or SIMULATION), template (product key, variant, condition, quantity 1, currency), rule\_version, rules\_hash, lot plan, timeline, status | CHECK currency = USD; mode immutable after PUBLISHED |
| pool\_entries | pool, user, paypal\_account\_key, canonical\_request (jsonb), request\_hash, cap\_cents, zone, submitted\_via (human or agent), received\_at (DB time), synthetic flag | UNIQUE(pool, user); UNIQUE(pool, paypal\_account\_key); the insert transaction checks pool OPEN and now() < close\_at |
| entry\_receipts | entry, commitment, salt, signature | UNIQUE(entry) |
| allocations | pool, entry, zone, rank, lot (nullable), status (SEATED, WAITLISTED or PRICED\_OUT) | UNIQUE(pool, entry); UNIQUE(pool, zone, rank) |
| lots | pool, zone, seats, status, award, deadlines | seats > 0 |
| merchants | display name, router reference (PayPal merchant ID or demo label), onboarding status, attestations | none |
| bids | lot, merchant, structured fields (jsonb), notes, status, revision, receipt hash | one live bid per (lot, merchant) |
| bid\_flags | bid, AI run, code, severity, evidence | none |
| awards | lot, bid snapshot, tier, item cents, per-entry totals, valid\_until, rule\_version, award\_hash | immutable (UPDATE blocked) |
| buyer\_orders | lot, entry, attempt, status, offer\_expires\_at, total\_cents | partial UNIQUE(entry) where status is active |
| paypal\_orders, paypal\_authorizations, paypal\_captures, paypal\_refunds | PayPal ID, buyer\_order, PayPal-reported status, amount, expiry, raw response, debug ID | UNIQUE(PayPal ID); one buyer order per PayPal order |
| ledger\_entries | lot, buyer\_order, kind, amount\_cents, PayPal ref, idempotency\_key, source (api, webhook, reconciler) | UNIQUE(idempotency\_key); append-only |
| webhook\_events | PayPal event ID, type, raw body, verified, processed\_at | UNIQUE(event ID) |
| idempotency\_keys | key, scope, request hash, response | UNIQUE(key), for our own join and agent endpoints |
| jobs | kind, run\_at, payload, attempts, status, concurrency key | claimed with FOR UPDATE SKIP LOCKED |
| audit\_log | sequence, prev\_hash, hash, actor, action, subject, payload | append-only by trigger; hash chain |
| ai\_runs, sim\_runs | task, model, prompt version, input hash, output; seed, config, results | none |

Ledger kinds: AUTH\_CREATED, AUTH\_VOIDED, CAPTURE\_COMPLETED, CAPTURE\_PENDING, CAPTURE\_DECLINED, REFUND\_COMPLETED, REFUND\_PENDING. Net paid = sum of CAPTURE\_COMPLETED minus sum of REFUND\_COMPLETED.

### 5.3 Money rules

- Total = item + shipping + tax, in cents. Tax rounds half-up per buyer at the total level. Strings like 123.45 exist only at the PayPal boundary.
- Every amount PayPal returns is parsed back to cents and compared with our expected cents. A mismatch blocks the transition and raises an alert (I3).
- Any amount.breakdown we send must sum exactly to the order value, or PayPal rejects it.

### 5.4 Privacy

- The raw payer\_id is not stored. The HMAC key plus PayPal order and capture IDs are enough.
- A delivery address lives only on the buyer order, encrypted at the application layer, and reaches the winning merchant only after the lot is FUNDED. Sandbox uses fake data.
- No card or bank data ever reaches FairPool because approval happens on PayPal, so card-data compliance stays with PayPal.
- Public pages show commitments and aggregates only.

## 6. Layer 3: State machines

### 6.1 Pool and lot lifecycles

```
Pool: DRAFT → PUBLISHED → OPEN → CLOSED → SEEDED → ALLOCATED → RUNNING → COMPLETED
      (CANCELLED is allowed before RUNNING; no money exists yet)

Lot:  PLANNED → BIDDING → BID_CLOSED → AWARDED → CHECKOUT_OPEN → FUNDING → FUNDED → CLOSED
                              │                          │             │
                              └→ CANCELLED               └─────────────┴→ FAILING → FAILED_CLOSED
                                 (no feasible bid, no money exists)
```

A pool is RUNNING while any lot is active and COMPLETED when every lot is CLOSED, FAILED\_CLOSED or CANCELLED. A lot below its minimum size is created directly as CANCELLED at allocation (9.6), and an ops abort of an AWARDED lot before checkout opens also moves it to CANCELLED; no money exists in either case.

### 6.2 Lot transitions

| From to | Trigger | Guard |
| --- | --- | --- |
| PLANNED to BIDDING | Pool ALLOCATED and bid window opens | Bid-window times are stored on the lot |
| BIDDING to BID\_CLOSED | Bid deadline (database time) | Late bids are rejected at write time |
| BID\_CLOSED to AWARDED | At least one bid passes rules R1 to R9 (section 10) | Award snapshot written in the same transaction |
| BID\_CLOSED to CANCELLED | No feasible bid | No money exists; entries are released |
| AWARDED to CHECKOUT\_OPEN | Seats whose cap is below their total are marked PRICED\_OUT, vacancies are refilled, offers go out | I8 holds before any offer is sent |
| CHECKOUT\_OPEN to FUNDING | Trigger rule in section 11.6 | Per-lot advisory lock |
| FUNDING to FUNDED | Completed captures from distinct buyers reach the MOQ (I5) | Counted from the ledger only |
| CHECKOUT\_OPEN or FUNDING to FAILING | Fund deadline passed and the MOQ cannot be reached, or the winning offer expired, or ops abort | Stops all new offers and authorizations |
| FAILING to FAILED\_CLOSED | Every authorization is VOIDED or expired, every completed capture has a COMPLETED refund, and no capture is PENDING | Net paid for the lot equals zero |
| FUNDED to CLOSED | Capture window over, ledger balanced, merchant notified | Final quantity recorded |

### 6.3 Buyer-order (seat) transitions

Active statuses (they count toward I8): OFFERED, ORDER\_CREATED, APPROVED, AUTHORIZING, AUTHORIZED, CAPTURING, CAPTURE\_PENDING, CAPTURED, REFUNDING. Terminal: EXPIRED, REJECTED, AUTH\_FAILED, CAPTURE\_FAILED, VOIDED, REFUNDED, DECLINED. PRICED\_OUT is an allocation status, because it is decided at award, before any buyer order exists.

| # | Transition | Trigger and guard | PayPal call (idempotency key) |
| --- | --- | --- | --- |
| 1 | OFFERED to ORDER\_CREATED | Buyer clicks Continue to PayPal. Seat valid, now before offer expiry, lot CHECKOUT\_OPEN, award valid, total at most the cap | Create order (create:{buyer\_order}:{attempt}) |
| 2 | ORDER\_CREATED to APPROVED | Buyer returns, or webhook, or poll. GET order shows APPROVED and the checks in 11.4 pass | GET order |
| 3 | APPROVED to AUTHORIZING | Worker takes the row lock. Seat still valid and lot CHECKOUT\_OPEN | None (state lock only) |
| 4 | AUTHORIZING to AUTHORIZED | Authorize response or reconciler. Authorization status CREATED and amount equals expected | Authorize (auth:{buyer\_order}) |
| 5 | AUTHORIZING to AUTH\_FAILED | Definitive denial, or a definitive 4xx other than ORDER\_NOT\_APPROVED | None |
| 6 | AUTHORIZED to CAPTURING | Funding sweep. Lot FUNDING or FUNDED | Capture (cap:{authorization\_id}) |
| 7 | CAPTURING to CAPTURED | Capture COMPLETED, from the response, a GET or a verified webhook | GET capture |
| 8 | CAPTURING to CAPTURE\_PENDING | Capture PENDING | Poll GET capture |
| 9 | CAPTURE\_PENDING to CAPTURED or CAPTURE\_FAILED | Resolves | GET capture |
| 10 | CAPTURING to CAPTURE\_FAILED | DECLINED or FAILED, which creates a vacancy | None |
| 11 | AUTHORIZED to VOIDED | Lot FAILING, buyer withdraws, or the authorization-age guard fires. Not yet captured | Void (no PayPal key: void does not replay, S2; GET before act) |
| 12 | CAPTURED to REFUNDING to REFUNDED | Lot FAILING or an ops refund | Refund (refund:{capture\_id}:1) |
| 13 | OFFERED, ORDER\_CREATED or APPROVED to EXPIRED | Offer timer. Not AUTHORIZING (I7); deadline re-checked at execution (I15) | None |
| 14 | ORDER\_CREATED or APPROVED to REJECTED | Duplicate payer, wrong country, amount or payee mismatch | None. Never authorize |
| 15 | AUTHORIZING to REJECTED | The authorization amount differs from the expected amount (11.5) | Void at once (GET before act) |
| 16 | OFFERED or ORDER\_CREATED to DECLINED | The buyer declines or cancels (11.8) | None |

### 6.4 Rules

- The tables are a code whitelist. Any other transition is rejected and alerts.
- State advances along a partial order. A late or duplicate signal can never move a buyer order backwards (CAPTURED never returns to AUTHORIZED).
- Each seat transition takes the buyer-order row lock. Lot-level decisions (funding, failing) take a per-lot advisory lock, so each lot has one writer at a time.
- Each transition writes the audit record, the ledger fact (if it is a money fact) and the next job in one transaction (I10).
- Vacancy rule: leaving an active status without reaching CAPTURED creates one claimable vacancy on the lot.

## 7. Layer 4: Identity and duplicate-entry control (idea section 1)

### 7.1 Purpose and limits

Stop one linked PayPal account from creating several entries in one pool. It does not establish one human per account, stop people who hold several PayPal accounts, or prevent resale (idea document, V11).

### 7.2 Flow

1. FairPool sign-up (email and password with a session cookie, or seeded demo accounts).
2. A disclosure screen before joining: what Connect PayPal requests (OpenID plus the account ID), why, and that no payment happens at this step.
3. Log in with PayPal authorization-code flow, run on the server with state and nonce checks. Scopes: openid and https://uri.paypal.com/services/paypalattributes (add profile and email only if needed). The return URL must be our own registered HTTPS callback. Your probe used nativexo://paypalpay (checklist 4.1), which is not a web callback, so registering a web return URL is part of G1.
4. The server exchanges the code, calls userinfo, extracts the account ID and computes paypal\_account\_key = HMAC-SHA256(server secret, account ID). Only the key is stored.
5. Rules: one active link per user, one user per key (global), and relinking is blocked while the user holds active entries.

### 7.3 Where each key is enforced

- At entry: UNIQUE(pool, user) and UNIQUE(pool, paypal\_account\_key).
- At approval (defence in depth): the approved order’s payer\_id becomes a checkout key. It must not be held by another active seat in the pool and, only if G2 passes, must equal the linked key. A mismatch means REJECTED and no authorization.

### 7.4 Outcome matrix

| G1 | G2 | Result | Claim allowed |
| --- | --- | --- | --- |
| Works | Same ID | Full design: key at entry and again at approval | Duplicate control per linked PayPal account |
| Works | Different IDs | Two independent keys, no pay-as-linked rule | Duplicate control per linked account at entry, plus per paying account at checkout |
| Fails | not applicable | Entry keyed on FairPool user only; payer\_id check at approval; a duplicate loses its seat later and the seat refills | Duplicate control at checkout, not at entry |

### 7.5 Failure modes

- Login consent abandoned, or invalid\_scope: entry is blocked with a clear message, and ops can switch the pool to the third row of the matrix.
- Relinking to dodge the check: blocked by the relink rule and the global key.
- Agent lane and human on one account: same unique key, so one entry (section 13).

## 8. Layer 5: Request intake and AI (idea section 2)

### 8.1 Where AI sits

Between the buyer’s words and a structured request. It never decides eligibility, never sees PayPal, and can be switched off: a manual structured form produces the same confirmed request.

### 8.2 Pipeline

1. Candidate retrieval: the open pools matching the message, found through the search adapter over public pool documents only (Elastic hybrid search when S8 passes, Postgres trigram otherwise, INT-1), at most 5, plus a “none” option. Retrieval only narrows the choices; every check below stays deterministic.
2. AI parse: the model receives the buyer’s message and the candidate list and returns JSON against a closed schema: pool choice (from the candidates only), condition, quantity, delivery location, required-by date, max total, firm requirements, preferences, ambiguities, and one clarifying question if needed.
3. Deterministic validation: pool is OPEN; condition equals the template; quantity is 1; currency is USD; location maps to a zone; the required-by date is not earlier than the pool’s latest delivery date (fund\_by plus delivery SLA, both published); max total is positive and within template bounds; firm requirements are a subset of the template. Failures are explained to the buyer, never guessed around.
4. Ambiguity loop: one question at a time, three turns, then the manual form. (Does “by Friday” mean delivery or order date? The pool’s published delivery rules usually settle it.)
5. Confirmation card, rendered by the server from catalog data and not from AI prose: product, variant, condition, delivery zone and window, max delivered total (shipping and tax included), the statement that nothing is charged now and a PayPal hold only follows a known merchant and price, and the statement that separate lots in the pool can end with different winning merchants and prices.
6. Confirming writes the canonical request (JSON, version, SHA-256 hash). That record, not the AI output, defines the buyer’s requirements. Joining is a separate action on top of it (one button in the UI, two records).
7. Preferences are stored and shown but never enter the engine.

### 8.3 AI contract

- Closed JSON schema with enums. Outputs are validated and retried once, then fall back to the form.
- Every run is stored (task, model, prompt version, input hash, output, latency, tokens) for audit and replay.
- The AI module holds no database session and no PayPal credentials (section 4.4).
- Model choice is configuration: a mid-size model for parsing and reconciliation, a small one for simulation. Confirm current model strings in Anthropic’s docs when coding.

### 8.4 Evaluation

Your checklist records AI extraction as NOT TESTED. We close that with a labelled set of about 50 messy buyer messages and 30 merchant quotes, publish the measured accuracy in the README, and keep the set as a regression test.

### 8.5 Failure modes

Wrong product match (caught by the confirmation card); unresolved ambiguity (manual form); AI outage (manual form); injected text in a buyer message (schema-bound output, no tools, no authority); a confirmed request that becomes invalid because the pool closed (join rejected by the database time check).

## 9. Layer 6: Pool engine (idea sections 3 and 4)

### 9.1 What is fixed before the pool opens

One published rules document, whose hash (rules\_hash) is shown on the public page: product key and variant, condition, quantity 1, USD, delivery zones, lot plan (zone and seats per lot), a plain statement that separate lots can end with different winning merchants and prices, timeline, delivery SLA and fund\_by date, minimum return terms, the require-PayPal-link flag, the allocation rule version (seeded lottery), refill rules and the beacon round rule. Nothing can change after PUBLISHED; a change means a new pool.

The lot plan is set by policy before bids, not by merchant capacity. This removes a circularity in the idea document (lots depend on merchant capacity, bids depend on lots). Merchants bid on lots that already exist, and a bid must cover the whole lot.

### 9.2 Timeline and defaults

```
open_at ─ entry window ─ close_at ─ Δ ─ beacon round R ─ allocation ─ bid window ─ award
   ─ checkout (offer window per buyer) ─ fund_deadline ─ settle
```

| Parameter | Demo | Production-like (assumption) |
| --- | --- | --- |
| Entry window | 3 min | 15 to 30 min (idea document) |
| Beacon delay Δ | seconds, or a labelled demo seed | At least one beacon round after close |
| Bid window | 2 min | Hours |
| Offer window per buyer (T\_c) | 3 min | 15 min (idea document) |
| Fund deadline | 10 min | At most 48 h after the first authorization (P1) |

### 9.3 Join (concurrency-safe)

One transaction: pool is OPEN and database now() is before close\_at; PayPal link present if required; insert into pool\_entries with the unique keys. A conflict returns the existing entry (idempotent: same receipt, HTTP 200). The commitment is computed and a signed receipt issued (entry ID, commitment, pool ID, database time, Ed25519 signature; public key published). Arrival time is stored for audit and never used for ordering. A burst of 10,000 joins is ordinary inserts, rate-limited per IP and per token.

### 9.4 Close

At close\_at the worker confirms CLOSED (the insert check already blocks late joins even if the job runs late, I15), runs a final eligibility pass (link still active, request still valid, exclusions logged with reasons), builds commitments c = SHA-256(pool ID, entry ID, request hash, salt), builds a Merkle root over the sorted commitments, publishes root, count and the commitment list (no personal data), and writes an audit checkpoint hash. All of this happens before the seed exists.

### 9.5 Seed and ordering

- **Seed:** the value of a public randomness beacon round R, announced at publication as the first round after close\_at plus Δ. We store and verify the beacon response (round, value, signature). A service such as drand fits; chain, endpoint and round timing are confirmed in spike S6. If the beacon is unavailable, selection waits. There is no FairPool-chosen fallback. A clearly labelled DEMO SEED mode exists for offline recording.
- **Ordering:** rank = SHA-256(seed, commitment) read as a 256-bit integer, ascending, computed per delivery zone. Ties break on entry ID.
- Because every commitment is fixed and published before the seed exists, FairPool cannot steer who wins by choosing the seed.

### 9.6 Lots and waitlist

Per zone, walk the ordered entries: lot 1 takes ranks 1 to s1, lot 2 the next s2, and so on per the lot plan. The remainder is that zone’s ordered waitlist. If a zone has fewer entries than a lot’s seats, the last lot shrinks to the entries available; a lot below its minimum size is CANCELLED with no money involved. An entry is seated or waitlisted, never both.

### 9.7 Vacancy and refill (bounded waves)

- A vacancy comes from PRICED\_OUT, EXPIRED, DECLINED, AUTH\_FAILED, CAPTURE\_FAILED, VOIDED (buyer withdrawal) or REJECTED.
- Invites never exceed vacancies (I8). The vacancy count is read and decremented in the same transaction as the invite.
- Next candidate: the first waitlisted entry in the same zone, in rank order, whose cap covers that lot’s total for them and who is still eligible. A candidate that fails is skipped, not dropped, and stays waitlisted for other lots.
- Each refill offer gets a full offer window T\_c, and no offers go out after refill\_cutoff = fund\_deadline minus T\_c, so every offer has time to finish.
- Waves are configuration: a wave is the number of open vacancies, max waves defaults to 3, and the demo uses one pass.
- A seat goes to a waitlisted buyer only when the old order can no longer complete. Our authorize call is the only route to an authorization and it is gated by seat state (I7).

### 9.8 What this layer can and cannot claim

Can: a published rule, a frozen list, an ordering anyone can check given the public seed, and per-buyer inclusion receipts. Cannot: prove that FairPool included every eligible entry (an omitted buyer can notice through their receipt; an outside auditor cannot), prove one human per account, or stop resale. Wording: “auditable under published rules”, never “provably fair”.

## 10. Layer 7: Merchant and auction engine (idea section 5)

### 10.1 Merchants

Router A merchants are onboarded through PayPal (G4). Router B merchants are demo profiles with a label. Both record timestamped attestations: inventory is real and reserved, the offer complies with supplier MAP terms (the FTC guidance link from the idea document is shown), and delivery terms are accurate. These are self-declarations. FairPool cannot verify them and PayPal APIs cannot either.

### 10.2 Bid schema (merchant-confirmed structured fields are authoritative)

- Lot, merchant, product key, condition, exact bundle contents.
- Capacity (at least the lot’s seats), target quantity, MOQ, 1 to 3 price tiers with an item price each.
- Shipping fee per delivery zone and tax method (included, or a rate table; simulated tax in the MVP).
- Delivery date or SLA days, return terms, valid\_until, total capacity across lots, and evidence of eligibility and inventory (a stock note or document link; merchant-declared and not verified by FairPool).
- Free-text quote or notes (untrusted). A pasted quote is parsed by the AI into proposed fields, which the merchant confirms before the bid counts (10.5).

### 10.3 Sealing

Bids are readable only by the owning merchant and the auction engine until the deadline. Each save returns a signed receipt hash, so a bid cannot be altered later without the merchant noticing. Staff access is break-glass and audited. After close, buyers see the winning merchant and clearing price, and losing merchants see their own result plus the clearing price. Sealing protects bid confidentiality only. It is not MAP compliance (idea section 5).

### 10.4 Rule pipeline (deterministic, in this order)

| Rule | Check |
| --- | --- |
| R1 | Schema valid, fields confirmed by the merchant, and bid received before the deadline (database time) |
| R2 | Merchant eligible for the active router, with attestations present |
| R3 | Product key, condition and bundle equal the lot’s requirement |
| R4 | Capacity covers the lot’s seats and fits the merchant’s remaining total capacity (R9) |
| R5 | Delivery within the pool’s published terms; returns at least the pool minimum |
| R6 | valid\_until at least fund\_deadline plus capture grace (section 11.2) |
| R7 | No BLOCKING flag from the AI consistency check (10.5) |
| R8 | A tier applies and the bid is feasible (10.6) |
| R9 | Lots are awarded in lot order and a merchant’s remaining capacity shrinks with each award. A bid that exceeds it at its turn is disqualified and the next-best bid wins. The order dependence is deterministic and published |

Every rejection carries a reason code the merchant can see.

### 10.5 AI quote parsing and offer reconciliation

Quote parsing: a merchant may paste a free-text quote, and the AI proposes the product, condition, quantity, delivery and bundle terms as fields in the same closed schema. The merchant reviews and confirms them, as buyers do in 8.2, and unconfirmed proposals never enter the auction. Reconciliation then runs on the confirmed bid. Input: the lot’s structured requirement, the bid’s structured fields and its free-text notes. Output: consistent yes or no plus flags from a closed list (BUNDLE\_MISMATCH, CONDITION\_MISMATCH, DELIVERY\_CONFLICT, HIDDEN\_FEE, QUANTITY\_CONFLICT, RETURN\_CONFLICT, OTHER), each with severity and the quoted snippet.

Asymmetry rule: the AI can only withhold an offer. A BLOCKING flag leaves it FLAGGED and excluded until the merchant corrects the structured fields. The AI can never qualify an offer that R1 to R6 reject, change a field, or accept a variation for a buyer. The notes are untrusted data, and instructions inside them have no effect because the output is a closed schema.

### 10.6 Tiers, feasibility and ranking

- **Tier resolution at award time:** for each tier, n is the number of seated entries whose total at that price is within their cap. The tier applies if n reaches the tier’s minimum quantity, and the lowest applicable price is used. If none applies, the bid is infeasible (NO\_FEASIBLE\_TIER).
- **Feasibility:** the bid is feasible only if n for its applicable tier is at least the bid’s MOQ.
- **Decision D5:** tiers do not depend on how many buyers finally complete payment. Buyers approve an exact amount before capture, and a quantity-dependent final price would need partial capture, which is untested. Merchants protect themselves with the MOQ. Completed-quantity pricing is a roadmap item.
- **Ranking key (ascending):** mean delivered total across the buyers who can accept at the bid’s applicable price (integer cents, fixed rounding); then the highest total in that group; then a hash of (lot seed, merchant ID). Published with the rules.
- The winner is the lowest qualifying offer by delivered price, as the idea document states, never merely the lowest number.

### 10.7 Award snapshot and price-out

The winner becomes an immutable award: bid snapshot, tier, item price, per-zone fees, an exact total per seated entry, valid\_until, rule version and award hash. Seated entries whose cap is below their total become PRICED\_OUT before any offer exists (no PayPal object, no money), and 9.7 refills their seats.

### 10.8 Edge cases

- Merchant withdraws after award: not possible through the UI. An ops abort fails the lot with void or refund and records the withdrawal.
- No bids, or none feasible: lot CANCELLED, entries released, no money.
- Bid revision: the last save before the deadline wins, and every revision keeps a receipt.

### 10.9 Merchant Agent API and developer tooling (INT-1, INT-4, INT-9)

Merchants can bid through the console or through a documented Merchant Agent API at /merchant-api/v1: ten operations for lots, bids, progress, fulfillment, shipments and verification (`docs/contracts/api.md` section 4.3). Access uses hashed API keys with scopes and rate limits, shown once at creation. The same sealed-bid rules apply: a bot’s structured submission is its confirmation, while a pasted free-text quote still needs the merchant’s confirmation (DEP-2). The API has its own OpenAPI document of at most 20 operations (we define ten), never the whole app, and APIMatic generates the Python and TypeScript SDKs and a developer portal from it (S11). The Demand Board and agent pool search use the search adapter (Elastic when S8 passes, Postgres otherwise). The advisory LOW\_SIMILARITY warning on a quote comes from the same adapter; it is a warning only and never blocks a bid (INT-1).

## 11. Layer 8: Checkout and PayPal orchestration (idea sections 6 and 7)

This is the layer where the V, G and X tags matter most.

### 11.1 Two switches: router and mode

- **Router** (who the payee is): A is platform multi-seller (needs G4). B is a single sandbox seller standing in for merchants (the V2, V8 and V9 evidence).
- **Mode** (when buyers pay): authorize\_capture is the idea’s design (needs G3). capture\_only is the V9-proven path: capture at approval, refund if the lot fails.

| Router | Mode | Evidence | Use |
| --- | --- | --- | --- |
| B | authorize\_capture | V2, V3, V8 verified; G3 passed (S2) | In force: G4 failed (S3) |
| B | capture\_only | V2, V9, V10 verified | Last resort if both G3 and G4 fail (not needed: G3 passed, S2) |
| A | authorize\_capture | G3 passed (S2); G4 failed (S3) | Target design, as in your idea. Unavailable in this Sandbox app |
| A | capture\_only | G4 failed (S3) | Unavailable |

Primary path: Router A with authorize\_capture, exactly as your idea describes. Router B and capture\_only are fallbacks that apply only if G4 or G3 fails, and any screen, video frame or README line under a fallback says so. Router B behaviour: every order goes to the verified sandbox seller. The winning merchant appears in the order description and on screen, and the UI and README state plainly that one sandbox seller stands in for the merchants. The ledger tracks amounts owed per merchant as notional only. Both switches are configuration: the data model and state machines are identical, because the merchant is stored on the award and the PayPal payee is recorded on each order.

**Status after spikes S2 and S3 (Oct 20, `docs/spike-results.md`):** G3 passed, so the mode is authorize\_capture. G4 failed, so Router B is in force (PAYMENT\_ROUTER=single\_seller) and is labelled as a fallback wherever it matters (DEP-4, I13). G9 failed, so revenue stays on the roadmap. Spike S7 asks whether payee-email routing to a second sandbox business account can be approved and authorized; if it passes and the owner approves, PAYMENT\_ROUTER=payee\_email is a labelled, sandbox-only option.

### 11.2 Time constraints

- Offer window T\_c per buyer, starting when the offer is sent.
- bid.valid\_until is at least fund\_deadline plus the capture grace.
- fund\_deadline is at most 48 hours after the first authorization, inside P1’s three-day recommendation. An age guard voids any uncaptured authorization approaching 60 hours (assumption) and fails the lot if it is not funded.

### 11.3 Order creation: the payload ladder

Orders are created lazily, when the buyer clicks Continue to PayPal, not when the offer is sent. That gives fewer unused orders, no dependence on PayPal’s order-expiry window (X) and less to reconcile. The browser sends only the buyer-order ID. Amount, payee and everything else come from the award snapshot (I3).

| Level | Adds | Status |
| --- | --- | --- |
| 0 | intent AUTHORIZE; one purchase unit with reference\_id, description, amount (currency, value) and payee email; headers PayPal-Request-Id and Prefer return=representation | Exactly the payload verified in V2 and V3 |
| 1 | custom\_id = buyer-order ID; invoice\_id unique per attempt | G8. Mind the V6 DUPLICATE\_INVOICE\_ID rule and test an idempotent retry that includes invoice\_id |
| 2 | amount.breakdown and items (item total, shipping, tax) | G8. The breakdown must sum exactly |
| 3 | experience\_context with return and cancel URLs, pay-now action and a provided shipping address with changes disabled | G8, X |
| 4 | Router A only: PayPal-Auth-Assertion header and payee merchant ID; optional platform fee | G4, G9 (both failed in S3: level 4 is unavailable) |

Each level is switched on by configuration only after its spike passes. Reconciliation never depends on a level above what is enabled: we store the PayPal order ID we created, so we can always map it back, and custom\_id is a convenience for webhooks. Idempotency key: create:{buyer\_order}:{attempt}. If the amount must change (a re-quote), the attempt number increments and the old order is abandoned. A key is never reused with a different payload (I9).

### 11.4 Approval handling (redirect first, D10; superseded by INT-7)

Update: D10 is superseded by INT-7 (`docs/decisions.md`). The PayPal JavaScript SDK v6 popup is the primary approval UX once spike S13 passes, and the redirect described here is the fallback verified in the Sandbox (PAYPAL\_APPROVAL\_UI). The server-side checks below are the same for both.

The buyer goes to the returned approve link, the path your sandbox buyer already used. On return (or webhook, or poll) we never trust query parameters. We GET the order and require: status APPROVED; intent AUTHORIZE; currency USD and a value equal to the expected cents; payee email equal to the expected payee (and merchant ID if present, remembering V2 returned none); payer country in the allowed set (US, from V11 and V12); and the payer key passing section 7.3.

Pass: continue to authorization. Fail: REJECTED with a buyer-facing reason, no authorization, seat released by the vacancy rule. We never use any auto-complete-on-approval option (X), so our server is the only caller of authorize (I7). If the buyer approves but never returns, the reconciler polls ORDER\_CREATED orders inside the offer window, finds APPROVED and continues. Approval is the buyer’s consent to the amount on PayPal’s review page.

### 11.5 Authorization with a seat lock

The worker moves APPROVED to AUTHORIZING under the row lock, re-checks seat validity, then calls authorize with key auth:{buyer\_order}.

- Authorization CREATED with the expected amount: AUTHORIZED. Record the ID and expiry, ledger AUTH\_CREATED.
- Amount differs: void immediately, REJECTED, alert.
- ORDER\_NOT\_APPROVED (V4): wait; this is not an error.
- Timeout or 5xx with an unknown outcome: stay AUTHORIZING and GET the order first for a recorded authorization; then replay the call with the same key (S2 showed that authorize honours PayPal-Request-Id). The offer-expiry job may not release this seat while it is AUTHORIZING (I7), and the reconciler resolves it within a bounded time.
- The buyer sees PayPal-hold wording, never “charged”.

### 11.6 Funding decision

Symbols: S seats on the lot, M the MOQ from the award, A authorizations currently AUTHORIZED, C captures COMPLETED, b the capture buffer (default 0, so capture starts once enough buyers have authorized to meet the MOQ, as your idea says; tunable upward).

**Trigger** (evaluated under the lot lock whenever an authorization lands or a deadline passes): A is at least min(S, M + b), or fund\_deadline has passed and A is at least M.

**Sweep:** capture each authorization in rank order, at most 5 in flight, each with key cap:{authorization\_id} and the full amount as the final capture. Every outcome goes to the ledger.

**Outcomes:**

- C at least M: lot FUNDED. The merchant is told the lot reached its minimum, with the actual completed quantity, which can still change while captures are PENDING.
- DECLINED or FAILED captures create vacancies. If before refill\_cutoff and the offer is still valid, refill (9.7). A refilled buyer’s authorization is captured as soon as it lands, because the lot is already in FUNDING.
- PENDING captures are not paid (I4, P3). Wait up to pending\_wait, then treat them as unpaid for the decision. A capture that completes later is counted if the lot is FUNDED, or refunded by a compensating job if the lot has failed.
- Sweep resolved with C below M and no refill possible: FAILING.
- Optional top-up: after FUNDED, late authorizations are captured immediately while seats remain, until fund\_deadline.

Why a buffer exists: with b at 0, a capture failure after capture starts can leave the lot below M and force refunds. Raising b makes that less likely at the cost of starting capture later, and never guarantees anything. Real failure rates are unknown and the sandbox will show close to zero, so failure paths are exercised with the mock header (V6) and labelled simulated.

### 11.7 Failure path (FAILING)

Ordered, each step idempotent: (1) close the lot to new offers and authorizations; (2) void every AUTHORIZED authorization (GET before act, because void does not replay, S2), accepting 200 or 204 (P2); (3) refund every COMPLETED capture in full with refund:{capture\_id}:1; (4) wait for PENDING captures and refund any that complete; (5) mark orders VOIDED or REFUNDED; (6) reconcile until net paid is zero, then FAILED\_CLOSED. Buyer messages explain that a void releases the hold and that how soon a bank shows it is up to the bank (idea document). Refund fees and timing in production are not verified in the sandbox, so the README says so.

### 11.8 Buyer-initiated exits

Before authorization: cancel locally. Nothing at PayPal has moved money, and G7 covers what a cancelled approval leaves behind, though we never rely on it. After authorization and before capture: void. After capture: an ops refund, which the buyer-facing policy states.

### 11.9 Settlement and revenue

Router A: captured funds go to the merchant under the platform arrangement (P5) and FairPool never holds funds. Router B: notional per-merchant ledger only. Revenue: a merchant-paid success fee through a platform fee on the purchase unit if G9 passes, otherwise shown as roadmap. Production needs PayPal platform approval and seller onboarding (P5), and the README says so.

### 11.10 Happy-path sequence

```
Buyer          FairPool (API and worker)                    PayPal Sandbox
  │ Continue to PayPal │                                         │
  │───────────────────→│ create order (create:{bo}:{n}) ────────→│ 201 CREATED + approve link
  │←── redirect to approve link ─────────────────────────────────│
  │ approve on PayPal ───────────────────────────────────────────→│ status APPROVED
  │ return URL ───────→│ GET order, run the 11.4 checks ────────→│
  │                    │ AUTHORIZING (row lock)                  │
  │                    │ authorize (auth:{bo}) ─────────────────→│ authorization CREATED (hold)
  │                    │ lot trigger: A ≥ min(S, M+b)            │
  │                    │ capture (cap:{auth}) ──────────────────→│ capture COMPLETED
  │                    │ ledger CAPTURE_COMPLETED; C ≥ M → FUNDED│
  │←── status page ────│←──── webhooks (verified, deduped, confirmed by GET)
```

### 11.11 Fulfillment and verification (INT-6, INT-8)

After a lot is FUNDED the merchant’s Fulfillment tab shows the funded lots, a shipping list for captured orders (addresses only after FUNDED, N14), a way to mark orders shipped with tracking numbers, and a per-lot verification manifest (PayPal order IDs, capture IDs and amounts, no buyer personal data). When SHIPMENT\_TRACKING\_ENABLED is true (S12 passed), FairPool submits trackers for the captured transactions through the PayPal adapter with deterministic REST, never an AI call; otherwise tracking stays inside FairPool and is labelled as such. For verification, the merchant’s own AI client can call PayPal’s read tools through the PayPal MCP server, one order ID at a time, and compare totals with the manifest. Read-only is enforced by a tool allowlist if S10 proves one exists; otherwise FairPool’s own verification endpoint (server-side read-only GETs) is used and the PayPal MCP is shown only for single-order lookups. List-transactions is not used live because Transaction Search can lag by hours. Neither path can move money (I2).

## 12. Layer 9: Webhooks, reconciliation and idempotency

### 12.1 Who is the authority

| State | Authority | Changed by |
| --- | --- | --- |
| Money: order, authorization, capture, refund status | PayPal | Our own fetch of the resource. A webhook only triggers the fetch |
| Allocation: entries, ranks, lots, awards | FairPool | The deterministic engine |
| Seat status | FairPool, constrained by PayPal facts | The state machine (6.3) |
| Ledger | Derived from PayPal-fetched records | Append-only writes |

Webhooks are accelerators and the GET is the truth. That is why a lost, late, duplicated or reordered webhook cannot corrupt money state.

### 12.2 Ingest

POST /webhooks/paypal reads the raw body and verifies the signature (P4; the method, most likely PayPal’s verify-webhook-signature call with our webhook ID, is confirmed in G5, X). It inserts into webhook\_events with a unique event ID (a duplicate returns 200 and stops), answers 200 quickly and enqueues a processing job. An unverified request gets 400, an audit record, and is never processed. The listener must be public HTTPS on port 443 (checklist 5.1) and registered in the Sandbox for the seven events V7 lists: CHECKOUT.ORDER.APPROVED, PAYMENT.AUTHORIZATION.CREATED, PAYMENT.AUTHORIZATION.VOIDED, PAYMENT.CAPTURE.PENDING, PAYMENT.CAPTURE.COMPLETED, PAYMENT.CAPTURE.DENIED and PAYMENT.CAPTURE.REFUNDED.

### 12.3 Processing

Map the event to our object using the authorization or capture ID we stored, the order ID (your report notes capture events carry it under supplementary\_data.related\_ids.order\_id), or custom\_id if Level 1 is enabled. Then GET the resource and apply the snapshot through the state machine, monotonically. The event summary text is never used. Unknown or unmappable events go to a dead-letter list on the ops console. Simulator events only test plumbing (P4); proof of signature and real delivery comes from real sandbox lifecycle events (checklist 5.2).

### 12.4 Reconciler

Runs every 60 seconds for lots in CHECKOUT\_OPEN, FUNDING or FAILING, and hourly otherwise. It scans buyer orders stuck in ORDER\_CREATED, APPROVED, AUTHORIZING, CAPTURING, CAPTURE\_PENDING or REFUNDING beyond a threshold, fetches each from PayPal and heals through the state machine. It also checks each lot’s ledger against fetched PayPal records, and keeps FAILING lots open until net paid is zero. If G5 fails, this is the only update path, so the demo interval stays short.

### 12.5 Retry policy

| Response | Action |
| --- | --- |
| Network error, timeout, 5xx or 429 | Retry with the same key, exponential backoff with jitter (1 s growing to 30 s, at most 5), then mark the outcome UNKNOWN and hand it to the reconciler |
| 401 | Refresh the token once and retry with the same key |
| 422 ORDER\_NOT\_APPROVED | Not an error. Wait for approval |
| 422 DUPLICATE\_INVOICE\_ID | A bug in attempt or invoice numbering. Alert, never loop |
| Other 4xx | Definitive. Record the debug ID, no retry, state-specific handling |
| 200 on a replay (V3, V10) | Success, and it returns the original object |

A money-moving call is never fire-and-forget: the result is persisted before the next step runs.

### 12.6 Crash safety

A worker that dies mid-sweep leaves its jobs to be re-claimed. Each capture step has a fixed key and the state machine rejects duplicates, so replaying is safe. A database restart loses nothing because all state is durable. Our own endpoints (join, agent entries) take an Idempotency-Key header stored in idempotency\_keys.

## 13. Layer 10: Agent (A2A) lane

### 13.1 What the lane is

A documented API through which an AI shopping agent can enter pools for an already-enrolled account, using the same validator, required fields and account limits as the web flow. The agent is never a separate buyer.

### 13.2 Endpoints and delegation

- GET /agent/v1/pools returns open pools with their published rules.
- POST /agent/v1/entries takes the structured request and an Idempotency-Key header, and returns the entry, receipt and status.
- GET /agent/v1/entries/{id} returns status, seat, waitlist position and a checkout URL once an offer exists.
- DELETE /agent/v1/entries/{id} withdraws before close.
- GET /agent/v1/entries lists the account’s own entries (optional pool\_id or entry\_id filter) and POST /agent/v1/entries/withdraw withdraws by ID in the body. These flat forms exist for tool bridges (INT-2, INT-3).
- The user creates a delegation in the UI: pools or category, a maximum cap, an expiry. The token is shown once, stored hashed, and is revocable.

### 13.3 Behaviour that keeps the invariants

- Agent and human share UNIQUE(pool, user), so a second submission from either lane returns the existing entry with already\_entered true. This is how the A2A lane avoids creating extra entries for the same linked account.
- There is no payment endpoint. The checkout URL is for the human, who approves on PayPal (I1, I2).
- Requests record the delegation ID and the lane (submitted\_via = agent), and are rate-limited per token.
- MCP server (INT-3, added and required): wraps the same services as four tools (list\_pools, enter\_pool, list\_entries, withdraw\_entry), with the same delegation-token auth and no payment tools. The Zapier managed-mode bridge (INT-2) exposes the same four actions. Neither adds new logic.

### 13.4 Tools in this layer (INT-2, INT-3, INT-6, INT-9)

Four front doors reach FairPool’s services and none can pay. Buyers’ AI clients use the Agent API directly, the FairPool MCP server at /mcp, or the Zapier MCP bridge in managed mode (exactly four locked actions; a premium-trial window to plan around; a token or a URL containing it grants tool access, so it is treated as a secret). Merchants’ bots use the Merchant Agent API with scoped keys (10.9). A merchant’s AI client may also use the PayPal MCP server read-only for verification (11.11). In every case a person approves payment on PayPal (I1).

## 14. Layer 11: Synthetic rehearsal engine

### 14.1 Isolation by pool mode

Pools are either LIVE\_SANDBOX or SIMULATION, and the mode is immutable. A SIMULATION pool contains only synthetic entries and merchants, runs the same pool, allocation and auction engines, and uses a fake payment router that makes no PayPal calls. A LIVE\_SANDBOX pool contains real sandbox buyers only. They are never mixed, because mixing would let simulated captures count towards a real lot, breaking I4, I5 and I12. The payment adapter refuses any call unless the pool is LIVE\_SANDBOX, and a database constraint backs this up.

### 14.2 What it produces

- Scale: a 10,000-entry pool with a 3,000-seat lot, showing selection, waitlist, bids and the public verification at scale. Allocation is hashing and sorting, so it finishes in seconds.
- Variety: the model writes natural-language buyer messages and merchant quote notes, so the intake and reconciliation steps get real text. Caps, prices and behaviour (decline, no-show) are drawn from a seeded generator, not from the model, so every run is reproducible.
- Labelling: every screen, export and video frame for a SIMULATION pool carries a visible SIMULATED banner (idea section on rehearsal). It demonstrates the product flow. It does not prove buyer conversion, merchant participation or price compression.

## 15. Layer 12: Experience layer

| Surface | Must-have behaviour |
| --- | --- |
| Buyer app | Sign-in; Connect PayPal with disclosure; chat intake and confirmation card; pool lobby with countdown (server-sent events); entry receipt; result (seated, waitlisted position, priced out); checkout page; status page. Tabs: Discover and Join, My Pools and Orders; settings hold the PayPal link and agent delegations |
| Checkout page | Winning merchant, exact product and condition, delivery and return terms, exact total, the cap, a plain statement that PayPal places a hold now and it is released if the lot fails, time left, then Continue to PayPal (JS SDK popup, with the redirect as the fallback) |
| Merchant console | Onboarding (PayPal consent for Router A, or a demo profile for B), attestations, structured bid form plus notes, sealed status and receipt, result and reason codes. Tabs: Demand Board (live lots and search), Active Bids, Fulfillment (shipping list, tracking, verification manifest) and Developer API (keys, scopes, SDKs, portal link) |
| Public audit page | Rules and rules\_hash, commitments list and root, beacon round and value, rank function, lot boundaries, award summary, and a verify-my-place widget that recomputes a rank in the browser from a receipt |
| Ops console | Create pools, lot plan, state-machine view per lot, dead-letter webhooks, reconciler runs, simulation controls, mock-failure toggles for the demo, audit export |
| Agent docs | OpenAPI reference and a sample agent script |

Approval uses the PayPal JS SDK v6 popup as the primary path once spike S13 passes (INT-7, which supersedes D10). The redirect to PayPal, the path your sandbox buyer already used, is the verified fallback.

## 16. Layer 13: Security, privacy and compliance

| Threat or duty | Control |
| --- | --- |
| Secrets already exposed in chat and screenshots (report and checklist 0.1) | Step 0: rotate the Sandbox REST secret, change the Sandbox buyer password, regenerate or disable the NVP/SOAP credentials (unused here). Secrets only in environment variables or the host secret store; secret scanning in pre-commit and CI; log redaction; token cached in memory only (I14) |
| Wrong environment | Config allowlist: only the Sandbox API host. A live host is refused in code for this project |
| Webhook spoofing | Signature verification; reject otherwise; raw body stored |
| Session and CSRF | HttpOnly, SameSite cookies; CSRF token on state-changing calls; state and nonce on the PayPal Login flow |
| Broken access control | Per-row ownership checks; merchants cannot read other merchants’ bids; buyers see only their own entries |
| Prompt injection | Closed-schema outputs, untrusted text delimited as data, no tools, no authority (8.3, 10.5) |
| Abuse and bursts | Per-IP and per-token rate limits, request size limits, join throttle |
| Replay and duplicates | Idempotency keys on every external call and our own endpoints |
| API keys and delegation tokens | Secret shown once, stored hashed, scoped, revocable and rate-limited (13.2, 10.9) |
| Zapier and MCP surfaces | A Zapier token or a URL containing it grants tool access, so only four locked, non-payment actions are exposed; MCP tools never include payment; the PayPal MCP is used read-only (INT-2, INT-3, INT-6) |
| Dev-time tools | ContextMatic and the PayPal AI Toolkit run only inside coding agents and never in the product; verified facts override their suggestions (INT-4, INT-5) |
| Insider tampering | Hash-chained audit log with published checkpoints; break-glass bid access is logged |
| Personal data | Minimal collection, HMAC account keys, encrypted addresses, delete synthetic data after demos |
| Platform and legal | No card data touches FairPool. Production needs PayPal platform approval (P5). Merchants attest MAP compliance. Terms explain holds, voids and refunds. Savings are never promised |

## 17. Layer 14: Platform, observability and testing

### 17.1 Deployment

Docker images for API, worker and frontend, a docker-compose file for local runs (this satisfies the run-instructions rule), and a Render deployment (web service, background worker, Postgres, cron). The public webhook listener needs a stable HTTPS URL, so deploy the skeleton on day 2 for spike S5. Migrations run at start. Health endpoints for API and worker. Feature flags: PAYMENT\_ROUTER, PAYMENT\_MODE, AUTHORIZE\_USE\_REQUEST\_ID, PLATFORM\_FEE\_ENABLED, PAYPAL\_PAYLOAD\_LEVEL (the payload ladder level), require\_paypal\_link, beacon mode, and the switches added with the integrations (PAYPAL\_APPROVAL\_UI, PAYPAL\_SDK\_AUTH, SEARCH\_BACKEND, SHIPMENT\_TRACKING\_ENABLED, PAYPAL\_MCP\_VERIFICATION, ZAPIER\_BRIDGE; values and status in `docs/decisions.md` section 4).

Dev-time tooling: each member’s coding agent has the ContextMatic and PayPal AI Toolkit plugins installed, with versions recorded in `docs/progress.md` (INT-4, INT-5). They help write code and never run in the product. The Merchant OpenAPI document is exported by `tools/export_merchant_openapi.py` and checked in CI, and APIMatic generates the SDKs from it (S11).

### 17.2 Observability

Structured logs with correlation IDs (pool, lot, buyer order, PayPal debug ID). Metrics: lot funnel (offered, approved, authorized, captured), job latency, webhook lag, reconciler corrections, retry counts, AI latency and failures. Alerts surface on the ops console: any transition rejected by the whitelist, any amount mismatch, any UNKNOWN outcome older than its bound, any webhook dead letter.

### 17.3 Test layers

| Layer | What it covers |
| --- | --- |
| Domain properties | Allocation is deterministic and a full permutation; seats never exceeded (I8); money math; every transition not in the tables is rejected; I3, I5 and I6 as properties |
| Ported harness | The 17 rule tests from V13, re-baselined to the new flow (drop the saved-method gates) |
| Sandbox contract tests | V1 to V12 as executable checks, plus G3 and G8, tagged and run on demand. They fail loudly if PayPal behaviour changes |
| Fault injection | PayPal-Mock-Response (V6) for capture failures; timeouts after the request was sent; duplicate and reordered webhooks; worker killed mid-sweep; database restart |
| Concurrency | 200 parallel joins by one account yield one entry; offer-versus-expiry races keep I7 and I8 true |
| AI evaluation | The labelled intake and reconciliation sets (8.4) |
| End-to-end rehearsal | Real sandbox buyers through a full live pool, twice, before recording the video |

### 17.4 How your checklist maps onto the design

| Checklist item | Where it lives |
| --- | --- |
| 0.1, 0.2 credentials | Section 16 Step 0; I14 |
| 1.1 Sandbox only | Config allowlist (section 16) |
| 1.2 scopes and app identity | Startup self-check logs scope names, never values; scope is not marketplace approval |
| 1.3, 1.4 NVP/SOAP balance and Express Checkout setup | Not used: legacy and unrelated to Orders v2 (section 3.1) |
| 2.1 to 2.6 approve, authorize, void, capture, refund | Contract tests; G3 closes the authorization-capture gap |
| 2.7 decline or cancel | G7 test; state machine does not depend on it |
| 2.8 minimum uses completed captures only | I4 and I5; domain property test plus end-to-end |
| 3.1 to 3.4, 3.8 second seller, intent, assertion, payee | G4 spike; Router A contract tests; Router B as fallback |
| 3.5 separate buyer orders | V5 contract test plus multi-buyer rehearsal (G6) |
| 3.6 Payouts | Not used and absent from the code |
| 3.7 India domestic | Payer-country guard test |
| 4.1 to 4.3 Login and payer\_id | G1 and G2; outcome matrix in 7.4 |
| 5.1, 5.2 webhooks | G5; section 12 |
| 6.1 negative tests | Mock-response tests |
| 6.2 idempotent retries | Replay tests for create, authorize, capture and refund; void gets a GET-before-act test because it does not replay (S2) |
| 6.3 pool failure handling | Failure-path rehearsal: void, then refund, then net zero |
| FairPool rows: price cap, batching, allocation | Domain tests (sections 9 and 10) |
| FairPool rows: AI extraction | AI evaluation sets |
| FairPool rows: flake, waitlist, concurrency, bots | Simulation plus fault injection plus concurrency tests; bots remain a disclosed limit |
| FairPool rows: fairness audit | Public verifier tests; claims limited per 9.8 |
| FairPool rows: MAP and inventory | Outside the sandbox; merchant attestations only |

## 18. Cross-component impact matrix

How a change or failure in one component spreads, and what stops it.

| If this changes or fails | It directly affects | Control |
| --- | --- | --- |
| Allocation rule version or lot plan | rules\_hash, receipts, public verifier, bid feasibility, refill | Frozen at PUBLISHED; a change means a new pool |
| Confirmed-request schema | Commitments (they hash the request), intake validator, verifier, agent API | Versioned schema, version stored in every request |
| Lot seats S or MOQ M | Bid feasibility (R8), capture trigger (11.6), refill bounds, the FAILING condition | Both frozen in the award snapshot |
| Bid valid\_until | Fund deadline, offer windows, authorization-age guard | R6 rejects bids with short validity |
| Buyer cap | Price-out, refill candidates, the I3 total check, feasibility counts | Cap lives in the immutable canonical request |
| Router A or B | Merchant onboarding, bid eligibility (R2), payee check (11.4), meaning of the ledger (settlement or notional), README claims | One config switch, identical state machines, claims chosen by router (Appendix B) |
| Payment mode | Failure path (void or refund), buyer wording, funding trigger | Mode stored on the lot at award and never changed mid-lot |
| Webhooks unavailable | Update latency, reconciler load, demo timing | Short reconciler interval; demo script waits for it |
| Token expiry | Every PayPal call | Refresh once on 401, same idempotency key |
| Scheduler downtime | Timers fire late | I15: handlers check stored deadlines, so late is safe |
| AI outage | Intake and offer reconciliation | Manual form (merchants enter structured fields directly); bids that carry free-text notes wait for ops review |
| Beacon unavailable | Selection start and every later timer | Wait, no fallback; the shifted timeline is published |
| Simulation changes | Must never touch a live pool | Pool mode separation (I12) |
| PayPal Login failure | Strength of duplicate control | Outcome matrix in 7.4 |
| Search backend (Elastic or Postgres) | Candidate retrieval, Demand Board and agent pool search | Both return the same hit shape; only public documents are indexed; every check stays deterministic; SEARCH\_BACKEND (INT-1) |
| Approval UI (JS SDK popup or redirect) | Checkout page and approval handling | Server-side checks are identical for both; PAYPAL\_APPROVAL\_UI (INT-7) |
| Merchant API keys or scopes | Merchant bots, bid submission, fulfillment reads | Hashed keys, scopes, rate limits and the same sealed-bid rules (10.9) |
| Zapier or MCP availability | The headless buyer demo | Our own /mcp server; Zapier is a documentation switch (INT-2, INT-3) |
| Shipment tracking | Fulfillment tab and verification manifest | SHIPMENT\_TRACKING\_ENABLED=false keeps tracking inside FairPool, labelled (INT-8) |

## 19. Failure-mode catalogue

| # | Failure | Detection | Response | Protects |
| --- | --- | --- | --- | --- |
| F1 | Authorize times out, outcome unknown | No response | Stay AUTHORIZING, fetch the order first, then replay with the same key (S2: honoured) | I7, I9 |
| F2 | Webhook lost | Reconciler sees stale state | Poll PayPal | I4 |
| F3 | Duplicate webhook | Unique event ID | Ignore | I9 |
| F4 | Webhooks out of order | Fetch plus monotonic merge | State cannot regress | I10 |
| F5 | Buyer approves after the seat expired | Seat-state check | Never authorize; the order lapses | I1, I7 |
| F6 | Buyer approves then closes the tab | Reconciler finds APPROVED inside the window | Continue to authorize | I1 |
| F7 | Capture PENDING | Status | Wait; unpaid until COMPLETED | I4 |
| F8 | Some captures decline, completed below M | Sweep result | Refill if time and offer allow, otherwise FAILING | I5 |
| F9 | Capture completes after the lot failed | Webhook or poll | Compensating refund | I4, I5 |
| F10 | Authorization expires or is voided unexpectedly | GET status | Vacancy, refill | I8 |
| F11 | Winning offer expires mid-checkout | Timer | FAILING, void everything | I3 |
| F12 | Merchant withdraws | Ops action | Fail the lot, record it | none |
| F13 | Price must change after approval | Re-quote | New attempt, buyer re-approves, old order abandoned | I3, I9 |
| F14 | Concurrent duplicate joins | Unique index | One entry | I6 |
| F15 | Agent and human on one account | Unique index | Existing entry returned | I6 |
| F16 | Relinking to dodge dedupe | Relink rule | Blocked | I6 |
| F17 | One person with several PayPal accounts | Not detectable | Disclosed limit | none |
| F18 | FairPool omits an entry | Only the omitted buyer, via receipt | Disclosed limit | none |
| F19 | AI misparses a request | Confirmation card | Buyer corrects | I3 |
| F20 | Prompt injection in notes | Closed schema | No effect | I2 |
| F21 | Token expires | 401 | Refresh once | none |
| F22 | PayPal 429 or 5xx | Status | Backoff, same key | I9 |
| F23 | Worker killed mid-sweep | Job lock timeout | Re-claim; steps idempotent | I9, I10 |
| F24 | Refund fails | Status | Retry; lot stays FAILING | I5 |
| F25 | Wrong currency or payer country | Approval checks | REJECTED | I3 |
| F26 | Clock skew | Not applicable | Database clock only | I15 |
| F27 | Beacon down | Fetch fails | Wait | I11 |
| F28 | Payee on the created order is not the expected one | Compare | REJECTED, alert | I1 |
| F29 | Double click or two tabs | Idempotent create plus state guard | One order | I9 |
| F30 | Buyer funding source denied at authorization | DENIED | AUTH\_FAILED, vacancy, refill | I8 |

## 20. Build plan

### 20.1 Step 0 and spikes

Step 0 (first): rotate the exposed Sandbox secrets, change the Sandbox buyer password, create the repo with a detectable open-source license, a .gitignore and secret scanning.

| Spike | Tests | Gates | What I need back from you |
| --- | --- | --- | --- |
| S1 | Login consent, userinfo, compare the account ID with an approved order’s payer\_id | G1, G2 | Sanitized: scope accepted yes or no, account ID present yes or no, equal to payer\_id yes or no |
| S2 | Authorize, capture the authorization, refund; replay each with the same key; check whether authorize and void accept PayPal-Request-Id | G3 | HTTP codes and statuses |
| S3 | Second seller via Partner Referrals; AUTHORIZE with PayPal-Auth-Assertion; check platform fee | G4, G9 | Referral outcome; payee returned |
| S4 | Payload ladder levels 1 to 3 | G8 | Which levels PayPal accepted |
| S5 | Webhook listener on the deployed skeleton | G5 | Events arrived, verification result |
| S6 | Beacon endpoint and round timing; create 4 to 6 sandbox buyers | G6 | Confirmation |
| S7 | Order addressed to a second sandbox business account by payee email: approve, authorize, void | G11 | HTTP codes and the payee returned |
| S8 | Elastic semantic\_text index with an explicit inference endpoint and the RRF hybrid query from Python | G12 | Works yes or no |
| S9 | Zapier MCP managed-mode tools with locked URL and header values; connect Claude | G13 | Tools listed and called yes or no |
| S10 | PayPal MCP: read-only allowlist possible; what get-order accepts in the Sandbox | G14 | Allowlist yes or no; get-order result |
| S11 | APIMatic: generate Python and TypeScript SDKs and a portal from the Merchant Agent API OpenAPI document; licence terms | G15 | Generated yes or no; plan limits; licence result |
| S12 | Submit a tracker for a captured sandbox transaction | G16 | HTTP code and status |
| S13 | JavaScript SDK v6: createInstance with the client ID, popup approval of an AUTHORIZE order, the onApprove result | G17 | Which initialisation worked; callback fields |

S2 and S3 go first because they decide the payment mode and the router. Recorded since v1: S2 and S3 (Oct 20). The other spikes are pending; S7 to S13 were added after v1 and are in the table above (`docs/spikes.md`, `docs/spike-results.md`).

### 20.2 Schedule

This is the v1 stage order, without dates. The working plan is `docs/implementation-plan.md` (twelve phases with merge gates).

| Stage | Focus |
| --- | --- |
| 1 | Step 0, spikes S1 to S6, deploy the skeleton |
| 2 | Data model, state machines, pool engine (entries, close, commitments, seed, lots, waitlist), AI intake, audit log |
| 3 | Auction, checkout and payment orchestration (router and mode), webhooks and reconciler, refill, agent API |
| 4 | Simulation, public verify page, UI polish, test suites, AI evaluations, README |
| 5 | End-to-end rehearsals, record the video, repo cleanup, license check |
| 6 | Submit a day early. The deadline is Nov 12, 12:00 pm PT (Nov 13, 1:30 am IST) and nothing can be edited afterwards |

Cut line, in order: top-up after FUNDED, refill waves beyond one pass, sponsor integrations. The MCP server (INT-3) and the JS SDK popup (INT-7, with the redirect as its fallback) were cut candidates in v1 and are now adopted. Never cut: section 1 and section 4 as you decided, the authorize, capture, void and refund lifecycle, the reconciler, the audit and verify page.

### 20.3 Three-minute demo storyboard (no brand names on screen)

| Time | Beat |
| --- | --- |
| 0:00 to 0:20 | The problem and the idea in one sentence |
| 0:20 to 0:50 | A buyer talks to the AI, sees the confirmation card, joins, gets a receipt |
| 0:50 to 1:10 | Pool closes; the public page shows the committed list, beacon seed, lot split and a verify-my-place check |
| 1:10 to 1:30 | Sealed bids arrive; the AI flags a bundle mismatch; the winner is chosen |
| 1:30 to 2:15 | Real sandbox buyers approve on PayPal; holds appear; capture; lot FUNDED |
| 2:15 to 2:40 | A second lot: a buyer drops, the waitlist refills, or the lot misses its minimum and void then refund shows net zero |
| 2:40 to 3:00 | Simulated scale (labelled), the limits we state, the roadmap |

## 21. Decisions and what I need from you

| D | Decision | My default and why |
| --- | --- | --- |
| D1 | Stack | Python 3.12 with FastAPI, SQLAlchemy and Alembic, Postgres 16, a React frontend, Docker, Render. One language for the money path, and PayPal’s tooling supports Python and TypeScript. Tell me if you want TypeScript |
| D2 | How pools come to exist | Operator-defined pool templates, not emergent from free text. It is the simplest way to guarantee exact product, condition and variant. Emergent pooling is roadmap |
| D3 | Scope limits | One unit per entry, USD only, US payers only (V11, V12) |
| D4 | Selection rule | Seeded lottery with a public beacon, no arrival priority |
| D5 | Price tiers | Resolve at award time (10.6) |
| D6 | PayPal link | Required to enter live pools (your section 1 in full), degrading per 7.4 |
| D7 | Payment | Run spikes S2 and S3 first. Primary: Router A with authorize\_capture (your idea). Router B and capture\_only are labelled fallbacks, used only if G4 or G3 fails. Update: S2 and S3 are recorded; G3 passed and G4 failed, so Router B with authorize\_capture is in force (DEP-4) |
| D8 | Merchants | Demo merchants with self-declared attestations |
| D9 | Revenue | Merchant-paid success fee via platform fee if G9 passes, otherwise roadmap. Update: G9 failed (S3), so roadmap text only (RESOLVED) |
| D10 | Approval UX | Redirect first, JS SDK popup later. Update: superseded by INT-7 (SDK popup primary, redirect fallback) |
| D11 | Live demo buyers | Six sandbox buyer accounts (assumption: two lots, a refill and a failure path need about this many) |

Decisions added since v1 (`docs/decisions.md`): DEP-1 to DEP-4 (scope limits, merchant-confirmed quotes, bid fields, labelled fallbacks) and INT-1 to INT-9 (the sponsor and partner tools, mapped to layers in 4.5).

What I need from you:

1. Confirm or change D1 to D11, above all D1 (stack), D2 (operator-defined pools) and D7.
2. Spike results as they arrive (sanitized, never secrets), starting with S2 and S3.
3. Team size and hours per week, so I can size the schedule honestly.

## Appendix A: PayPal call catalogue

Idempotency values should be opaque strings. Derive a UUID deterministically from the key text so the same logical call always yields the same PayPal-Request-Id (header format limits are X). Replays were verified for create, capture and refund (V3, V10) and, in spike S2, for authorize (200, same result). Void does not replay (a second void returned 422 with and without a request ID), so void relies on a GET before acting and on our own seat lock.

| Operation | Endpoint | Idempotency key | Expected | Evidence |
| --- | --- | --- | --- | --- |
| Token | POST /v1/oauth2/token | none; cache | 200, expires\_in 32,400 | V1 |
| Create order | POST /v2/checkout/orders | create:{buyer\_order}:{attempt} | 201, then 200 on replay | V2, V3 |
| Get order | GET /v2/checkout/orders/{id} | not applicable | 200, CREATED or APPROVED | V8 |
| Authorize | POST /v2/checkout/orders/{id}/authorize | auth:{buyer\_order} | 201 with authorization CREATED; 422 ORDER\_NOT\_APPROVED before approval | V4, V8, S2 |
| Get authorization | GET /v2/payments/authorizations/{id} | not applicable | 200 | V8 |
| Capture authorization | POST /v2/payments/authorizations/{id}/capture | cap:{authorization\_id} | 201 COMPLETED or PENDING | S2 (G3 passed; V9 proved order capture only) |
| Get capture | GET /v2/payments/captures/{id} | not applicable | 200 | V9 |
| Void | POST /v2/payments/authorizations/{id}/void | none sent to PayPal (void does not replay); GET before act | 200 with body (observed) or 204; a second void returns 422 | V8, P2, S2 |
| Refund | POST /v2/payments/captures/{id}/refund | refund:{capture\_id}:{n} | 201 COMPLETED | V9, V10 |
| Get refund | GET /v2/payments/refunds/{id} | not applicable | 200 | V9 |
| Add trackers (INT-8) | POST /v1/shipping/trackers-batch | not applicable | 200 with a result per item | X, G16 |
| SDK client token (only if S13 needs it, INT-7) | POST /v1/oauth2/token with response\_type=client\_token | not applicable | Access token for the browser only | X, G17 |
| List webhooks and event types | GET /v1/notifications/webhooks and /webhooks-event-types | not applicable | 200 | V7 |
| Verify webhook signature | POST /v1/notifications/verify-webhook-signature | not applicable | SUCCESS | X, G5 |
| Partner Referrals and assertion | per checklist 3.1 to 3.3 | not applicable | Not available: onboarding returned 403 NOT\_AUTHORIZED and an assertion order returned 401 invalid\_subject (S3) | G4 failed (S3) |
| Log in with PayPal | Authorization code, token and userinfo | state and nonce | Account ID returned | G1 |

## Appendix B: Claim wording guide (I13)

| Say | Never say |
| --- | --- |
| Auditable under published rules; entries are committed before the random seed exists | Provably fair, cryptographically verified, bot-proof |
| One entry per linked PayPal account in a pool (if G1 passes) | One person, one entry; guaranteed anti-scalper |
| PayPal places a hold only after the winning merchant and exact price are known and you approve; nothing is captured until the lot reaches its minimum | Your money is safe; you will not be charged |
| A lot is funded only when completed PayPal captures reach the minimum | Merchant payment is guaranteed |
| Demonstrated in the PayPal Sandbox | Production-ready, approved marketplace |
| Simulated results shown for illustration | The simulation proves conversion, participation or price compression |
| Prices depend on merchants choosing to compete | Wholesale pricing guaranteed; you will save |
| Sealed bidding keeps bids confidential | MAP compliant |
| Router B: one sandbox seller stands in for the winning merchants | FairPool pays merchants directly |
| AI proposes; deterministic rules and the buyer decide | The AI verifies or approves payments |

## Appendix C: Configuration defaults (all tunable assumptions, not evidence)

| Parameter | Demo | Production-like |
| --- | --- | --- |
| Entry window | 3 min | 15 to 30 min |
| Offer window per buyer | 3 min | 15 min |
| Capture buffer b | 0 (your idea’s rule: capture once enough buyers have authorized to meet the MOQ) | 0, raise only with real failure data |
| Capture concurrency | 5 | 5 |
| Retry policy | 5 tries, 1 s to 30 s with jitter | same |
| Token refresh margin | 5 min | 5 min |
| Reconciler interval | 60 s | 60 s active lots, hourly otherwise |
| Max refill waves | 1 | 3 |
| Pending-capture wait | 2 min | 24 h |
| Authorization-age guard | not applicable | 60 h |
| Fund deadline | 10 min | 48 h after the first authorization |
| Join rate limit | per IP and per token | same |
