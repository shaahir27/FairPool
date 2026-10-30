# Registry of IDs

Every ID used anywhere in `docs/` must be defined here or in the file named in the last section. `tools/validate_docs.py` fails CI when an ID is used but never defined. Full rationale for each item lives in `docs/system-design.md` (the exported design document), cited by section.

Evidence tags: **V#** verified in the Sandbox report or checklist. **P#** documented by PayPal per those files, untested. **G#** open gate with a spike and fallback. **X** PayPal behaviour from outside the files, unconfirmed until a spike proves it.

## Invariants (never break; design section 2)

| ID | Invariant |
|---|---|
| I1 | No money moves without the buyer approving the exact amount on PayPal |
| I2 | Only the server-side payment adapter calls authorize, capture, void or refund; neither the browser nor the AI can |
| I3 | Final total is at most the buyer's confirmed cap and equals the authorization amount |
| I4 | Paid means a PayPal capture with status COMPLETED; order status, approval, authorization or webhook text never count |
| I5 | A lot is funded only when completed captures from distinct buyers reach the MOQ |
| I6 | At most one seat per FairPool user and per PayPal account key in a pool |
| I7 | A seat is never released while we could still authorize its order |
| I8 | Offers in flight plus committed buyers never exceed lot seats |
| I9 | Every external call has a stable idempotency key where PayPal honours one (create, authorize, capture, refund) and a GET-before-act guard where it does not (void); a key is never reused with a different payload |
| I10 | Every state change is legal per the transition tables and is atomic with its audit record and next-job enqueue |
| I11 | Allocation order is a pure function of rule version, frozen entry commitments and public seed |
| I12 | No synthetic entity reaches a PayPal call, and no simulated outcome counts as paid |
| I13 | No UI or README claim exceeds verified capability |
| I14 | Secrets exist only in server environment memory, never in logs, repo or client |
| I15 | Deadlines are data and timers are triggers: every action re-checks stored deadlines against the database clock when it executes |

## Verified facts (design section 3.1)

| ID | Fact |
|---|---|
| V1 | OAuth client-credentials returns 200; token lifetime 32,400 s |
| V2 | Create AUTHORIZE order (USD 1.00) returns 201 CREATED; payee email echoed, no payee merchant_id; links include approve and authorize |
| V3 | Same PayPal-Request-Id on create returns 201 then 200 with the same order ID |
| V4 | Authorize or capture before approval returns 422 ORDER_NOT_APPROVED and creates nothing |
| V5 | Two orders to the same seller return 201 each with distinct IDs |
| V6 | PayPal-Mock-Response produced 422 DUPLICATE_INVOICE_ID on create and capture |
| V7 | Webhook event types exist; zero listeners were registered |
| V8 | US buyer, approved AUTHORIZE order: authorize 201 CREATED; void 200 VOIDED; GET shows VOIDED, no capture; order itself then read COMPLETED |
| V9 | Approved CAPTURE-intent order: capture 201 COMPLETED; full refund 201 COMPLETED |
| V10 | Replaying capture and refund with the same request IDs returned 200 and the original object |
| V11 | Approved order payer object carries payer_id, email_address, name, address (country US) |
| V12 | India buyer plus India seller: UNSUPPORTED_PAYEE_CURRENCY; INR is not in the REST currency list |
| V13 | Local rule harness passed 17 of 17 (rules only, no PayPal) |

## PayPal-documented, untested (design section 3.2)

| ID | Fact |
|---|---|
| P1 | An authorization is valid for 29 days and has a 3-day honor period; PayPal recommends capturing inside the honor period. A later capture needs a reauthorization (new authorization ID) and can be declined |
| P2 | Void may return 204 with an empty body (200 with a body was observed) |
| P3 | Capture statuses include COMPLETED, PENDING, DECLINED, FAILED; only COMPLETED is paid |
| P4 | Webhooks must be signature-verified and de-duplicated by event ID, with state confirmed by fetching the resource; simulator events are mock |
| P5 | Production marketplace payments need PayPal platform approval and seller onboarding; onboarding after payment does not support authorization intent |
| P6 | PayPal keeps idempotency keys for different periods per API, so our ledger must also stop duplicates |
| P7 | An order may hold up to 10 purchase units; we never use that as a multi-buyer order |

## Open gates (design section 3.3 plus G11 to G17; spikes in `docs/spikes.md`; results in `docs/spike-results.md`)

| ID | Gate |
|---|---|
| G1 | Does Log in with PayPal return the account ID with the paypalattributes scope (S1, Oct 28: no, `invalid_scope`; `openid` alone works) |
| G2 | Is the Login account ID the same identifier as payer_id on an approved order (S1, Oct 28: the raw strings differ; keep two keys) |
| G3 | Does authorize, then capture of that authorization, then refund work |
| G4 | Can FairPool direct an order to a second onboarded seller |
| G5 | Do webhooks arrive and verify |
| G6 | Do several distinct sandbox buyers complete approvals |
| G7 | What a buyer cancel or decline leaves behind |
| G8 | Which payload fields are accepted (custom_id, invoice_id replay, breakdown with items, address lock) |
| G9 | Is a platform fee available on the purchase unit |
| G10 | PENDING or DECLINED capture and authorization-expiry behaviour |
| G11 | Can an order addressed to a second sandbox business account by payee email alone (no partner assertion) be approved and authorized (added Oct 20 after S3; now in design 3.3). S7, Oct 28: captures arrive but void and refund are denied, so no |
| G12 | Elastic: can a `semantic_text` index with an explicit inference endpoint be created and the RRF hybrid query run from Python on the trial or local cluster (added with the integration review) |
| G13 | Zapier MCP: can Webhooks by Zapier actions be exposed as managed-mode tools with locked URL and header values, and can Claude connect to the server |
| G14 | PayPal MCP: is a read-only tool allowlist possible, and what does the get-order tool accept in the Sandbox |
| G15 | APIMatic: does the Merchant Agent API OpenAPI document generate Python and TypeScript SDKs within plan limits during the trial, and what are the licence terms of generated code |
| G16 | PayPal shipment tracking: does submitting a tracker for a captured transaction work in the Sandbox |
| G17 | JavaScript SDK v6: does `createInstance` work with the client ID, does the popup approve an AUTHORIZE order, and what does `onApprove` return |

## Auction rules (design section 10.4)

| ID | Rule |
|---|---|
| R1 | Schema valid, fields confirmed by the merchant, bid received before the deadline |
| R2 | Merchant eligible for the active router, attestations present |
| R3 | Product key, condition and bundle equal the lot requirement |
| R4 | Capacity covers the lot seats and fits the merchant remaining total capacity |
| R5 | Delivery within the pool terms; returns at least the pool minimum |
| R6 | valid_until at least fund deadline plus capture grace |
| R7 | No BLOCKING flag from the AI consistency check |
| R8 | A tier applies and the bid is feasible |
| R9 | Lots are awarded in lot order and merchant remaining capacity shrinks with each award |

## Failure modes (design section 19)

| ID | Failure |
|---|---|
| F1 | Authorize times out, outcome unknown |
| F2 | Webhook lost |
| F3 | Duplicate webhook |
| F4 | Webhooks out of order |
| F5 | Buyer approves after the seat expired |
| F6 | Buyer approves then closes the tab |
| F7 | Capture PENDING |
| F8 | Some captures decline, completed below the MOQ |
| F9 | Capture completes after the lot failed |
| F10 | Authorization expires or is voided unexpectedly |
| F11 | Winning offer expires mid-checkout |
| F12 | Merchant withdraws |
| F13 | Price must change after approval |
| F14 | Concurrent duplicate joins |
| F15 | Agent and human on one account |
| F16 | Relinking to dodge dedupe |
| F17 | One person with several PayPal accounts (disclosed limit, not detectable) |
| F18 | FairPool omits an entry (disclosed limit) |
| F19 | AI misparses a request |
| F20 | Prompt injection in notes or quotes |
| F21 | Token expires |
| F22 | PayPal 429 or 5xx |
| F23 | Worker killed mid-sweep |
| F24 | Refund fails |
| F25 | Wrong currency or payer country |
| F26 | Clock skew |
| F27 | Beacon down |
| F28 | Payee on the created order is not the expected one |
| F29 | Double click or two tabs |
| F30 | Buyer funding source denied at authorization |

## Design decisions (design section 21; status in `docs/decisions.md`)

| ID | Decision |
|---|---|
| D1 | Stack: Python 3.12, FastAPI, SQLAlchemy and Alembic, Postgres 16, React frontend, Docker, Render |
| D2 | Pools are operator-defined templates, not emergent from free text |
| D3 | One unit per entry, USD only, US payers only (same as DEP-1) |
| D4 | Seeded lottery with a public randomness beacon, no arrival priority |
| D5 | Price tiers resolve at award time, not on completed quantity |
| D6 | PayPal link required to enter live pools, degrading per the dedupe outcome matrix |
| D7 | Payment router and mode; superseded by DEP-4 (primary Router A with authorize_capture, fallbacks only if G4 or G3 fails) |
| D8 | Merchants are demo merchants with self-declared attestations |
| D9 | Revenue is a merchant-paid success fee via platform fee if G9 passes, otherwise roadmap |
| D10 | Redirect-based PayPal approval first, JS SDK popup later; superseded by INT-7 (SDK popup primary, redirect fallback) |
| D11 | Six sandbox buyer accounts for the live demo |

## Spikes (design section 20.1 plus S7 to S13; plans in `docs/spikes.md`)

| ID | Spike |
|---|---|
| S1 | Log in with PayPal: consent, userinfo, compare account ID with payer_id (G1, G2) |
| S2 | Authorize, capture the authorization, refund; replay each; check whether authorize and void accept PayPal-Request-Id (G3) |
| S3 | Second seller via Partner Referrals; AUTHORIZE with PayPal-Auth-Assertion; platform fee (G4, G9) |
| S4 | Payload ladder levels 1 to 3 (G8) |
| S5 | Webhook listener on the deployed skeleton (G5) |
| S6 | Beacon endpoint and round timing; create sandbox buyer accounts (G6) |
| S7 | Approve, authorize and void an order whose payee is a second sandbox business account, using payee email only (G11); added Oct 20 after S3 |
| S8 | Elastic hybrid search with `semantic_text`: index, ingest, RRF query from Python, local fallback (G12) |
| S9 | Zapier MCP managed mode with Webhooks by Zapier tools calling the Agent API (G13) |
| S10 | PayPal MCP read-only verification: tool list, allowlist, get-order lookup of a FairPool order (G14) |
| S11 | APIMatic: validate and generate SDKs from the Merchant Agent API OpenAPI (G15) |
| S12 | PayPal shipment tracking for a captured sandbox transaction (G16) |
| S13 | JavaScript SDK v6: initialize, popup approval of an AUTHORIZE order, server-side authorize (G17) |

## Where the other ID families are defined

| Family | Meaning | Defined in |
|---|---|---|
| DEP-1 to DEP-4 | Departures from the idea text approved by the owner | `docs/decisions.md` |
| BD-nn | Build decisions (tooling, versions) | `docs/decisions.md` |
| INT-1 to INT-9 | Integration decisions (Elastic, Zapier MCP, FairPool MCP, APIMatic, Agent Toolkit, PayPal MCP, JS SDK v6, shipment tracking, Merchant Agent API) | `docs/decisions.md` |
| FR-xx-nn | Functional requirements | `docs/product-spec.md` |
| N1 to N14 | Contract notes (ambiguities resolved in the contracts) | `docs/contracts/README.md` |
| PS-nn, LS-nn, BO-nn, BS-nn, ES-nn | Pool, lot, buyer-order, bid and entry transitions | `docs/contracts/state-machines.md` |
| T, two-digit phase, owner letter (A, B or X), two-digit number | Tasks, for example T02A03 | `docs/implementation-plan.md` |
| HO-1 to HO-13 | Handoffs between the two lanes | `docs/team-split.md` |
| PH0 to PH11 | Phases | `docs/implementation-plan.md` |
| IG-0 to IG-11 | Integration gates (merge gates, one per phase) | `docs/implementation-plan.md` |
| IT-0 to IT-11 | Integration acceptance tests, one per gate | `docs/testing-strategy.md` |
| PT-nn | Property tests | `docs/testing-strategy.md` |
