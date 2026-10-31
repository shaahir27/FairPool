# Decisions

Status values: **CONFIRMED** (the owner said yes), **ASSUMED** (the design proposed it and work proceeds on it; change it here before gate IG-0 if wrong), **SPIKE** (the value is set by a spike result), **RESOLVED** (a recorded spike result settled it), **SUPERSEDED** (replaced by the decision named in the note).

Rule for agents: never silently change a decision. If a decision must change, open a contract change request (see `docs/contracts/README.md`) and update this file in the same pull request.

## 1. Approved departures from the idea text

The idea text is `docs/fairpool-idea.md`. These four departures were proposed and approved ("Go"). In chat they were numbered D1 to D4; in these files they are DEP-1 to DEP-4 so they cannot be confused with the design decisions D1 to D11 below.

| ID | Departure | Idea text says | We build | Status |
|---|---|---|---|---|
| DEP-1 | Scope limits | Request has quantity and currency fields | Quantity is always 1, currency USD only, payer country US only (same as D3) | CONFIRMED |
| DEP-2 | Merchant quotes | AI parses a merchant free-text quote into fields | AI proposes the fields from a pasted quote; the merchant confirms them; only confirmed fields reach the auction rules | CONFIRMED |
| DEP-3 | Bid fields | Bid has target quantity and evidence of eligibility and inventory | Both fields are present; evidence is merchant-declared and never verified by FairPool | CONFIRMED |
| DEP-4 | Fallbacks | Authorization-first checkout, orders addressed to the winning merchant | Amended Oct 29 by the owner: the primary payment path is now vault-and-charge (`PAYMENT_MODE=vault_charge`): the buyer saves PayPal at join, FairPool charges once after the award, no hold exists. Authorization-first stays as the selectable fallback; the single stand-in sandbox seller is final (G4 failed, S7 rejected the alternative) and is labelled | CONFIRMED |

## 2. Design decisions (from design section 21)

| ID | Decision | Status | Note |
|---|---|---|---|
| D1 | Python 3.12, FastAPI, SQLAlchemy 2 and Alembic, Postgres 16, React frontend, Docker, Render | ASSUMED | Tell both members before IG-0 if TypeScript is preferred; this changes `docs/scaffold.md` only |
| D2 | Pools are operator-defined templates; a confirmed request is matched to an open pool | ASSUMED | The idea's fixed-window rule needs a pool to exist before entries arrive |
| D3 | One unit per entry, USD only, US payers only | CONFIRMED | Same as DEP-1 |
| D4 | Seeded lottery using a public randomness beacon, no arrival priority | ASSUMED | Matches the idea's published-rule wording; the checklist anticipates a seeded draw |
| D5 | Price tiers resolve at award time, not on final completed quantity | ASSUMED | Partial capture is untested |
| D6 | PayPal link required to enter live pools, degrading per `DEDUPE_MODE` | ASSUMED | Allowed by the idea if disclosed before joining |
| D7 | Payment router and mode | SUPERSEDED by DEP-4 | DEP-4 makes vault-and-charge primary and `single_seller` final; this row is kept for history |
| D8 | Merchants are demo merchants with self-declared attestations | ASSUMED | FairPool cannot verify inventory |
| D9 | Revenue: merchant-paid success fee via platform fee | RESOLVED | S3 (G9) failed: platform fee returned 422 UNSUPPORTED_PAYMENT_INSTRUCTION. Revenue is roadmap text only (fee shown as a planned merchant-paid success fee, not implemented) |
| D10 | PayPal approval UX | SUPERSEDED by INT-7 | JavaScript SDK v6 popup is primary; redirect approval (verified in the Sandbox) is the fallback |
| D11 | Six sandbox buyer accounts for the live demo | ASSUMED | Two lots, a refill and a failure path need about this many |

## 3. Build decisions

| ID | Decision | Status |
|---|---|---|
| BD-01 | License: MIT, file `LICENSE` at the repo root so the repo About section detects it | ASSUMED |
| BD-02 | Backend: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x (async), Alembic, httpx, uvicorn, `cryptography`, `argon2-cffi`; tests with pytest, pytest-asyncio, hypothesis, respx; lint with ruff; types with mypy | ASSUMED |
| BD-03 | Frontend: Vite, React 18, TypeScript, Tailwind, React Router; API client generated from the OpenAPI document | ASSUMED |
| BD-04 | AI: Google Gemini API via the official `google-genai` SDK; model names come from `AI_MODEL_PARSE` and `AI_MODEL_SIM`; defaults `gemini-3.5-flash-lite` and `gemini-3.5-flash-lite`; verify names in Google's Gemini docs when first used | Owner-approved Phase 2 plan |
| BD-05 | Hosting: Render (web service, background worker, Postgres, cron) from Docker images; local run with `docker compose`. Plan rule (checked against Render's free-tier docs, Oct 27, 2026): free web services spin down after 15 minutes idle, background workers and cron have no free instance type, and free Postgres expires 30 days after creation (14-day grace, then deleted). Judging runs to Dec 15 and winners are announced about Dec 21, so the hosted demo must run on paid instances (about $7/month per web or worker instance, Postgres from about $6/month) from first deploy until after the announcement. Paying for your own hosting is not support from PayPal or Devpost | ASSUMED |
| BD-06 | CI: GitHub Actions | ASSUMED |
| BD-07 | Git: trunk-based on `main`, short-lived branches, squash merges, tags at every gate | ASSUMED |
| BD-08 | Time: all timestamps are UTC `timestamptz`; the database clock (`now()`) is the only clock for deadlines | CONFIRMED (design I15) |
| BD-09 | IDs: UUID v4 for every primary key, generated in the application | ASSUMED |
| BD-10 | Password hashing: argon2id | ASSUMED |
| BD-11 | Address encryption: Fernet with `ADDRESS_ENCRYPTION_KEY` | ASSUMED |
| BD-12 | Receipts and bid receipts signed with Ed25519; account keys are HMAC-SHA256 | ASSUMED |
| BD-13 | Seed beacon: drand over HTTP (chain and endpoint confirmed in S6); labelled demo seed when unavailable | SPIKE |
| BD-14 | Money is integer cents everywhere; strings with two decimals exist only at the PayPal boundary | CONFIRMED (design 5.3) |
| BD-15 | Search: Elasticsearch via the official Python client; Elastic Cloud Serverless trial or a local container as the fallback environment; Postgres `pg_trgm` as the always-available fallback | ASSUMED |
| BD-16 | MCP: the official MCP Python SDK over Streamable HTTP; confirm the package version at build time | ASSUMED |
| BD-17 | Frontend PayPal: v6 script tag plus web components (`<paypal-button>`), no npm wrapper | ASSUMED |
| BD-18 | SDK generation: APIMatic CLI against the Merchant Agent API OpenAPI document; generated SDKs committed under `sdk/` | ASSUMED |

## 4. Spike-driven switches

Values are recorded from `docs/spike-results.md`. A switch marked PENDING keeps its default until that spike is recorded. Each spike is due at the gate named in `docs/spikes.md`, and its switch is filled at that gate. Changing a value means editing this table and the environment of both members in the same pull request.

| Switch | Value now | Status | Allowed values and meaning |
|---|---|---|---|
| `PAYMENT_MODE` | `vault_charge` | OWNER DECISION Oct 29 on the vault spike (merchant-scoped setup and exchange, 16 off-session USD 1.00 captures, all refunded; deleted permission rejected with 403; simulated decline 422). Limits: real low-balance decline and natural setup-token expiry not reached; the consent screen shows no amount; no portability to another seller | `vault_charge` (primary, `contracts/vault-charge.md`), `authorize_capture` (fallback; passed S2 on Oct 20, switch back if vault proves unsafe), `capture_only` (older fallback) |
| `BID_PRICING_MODE` | `flat_delivered` | OWNER DECISION Oct 29 (`contracts/flat-delivered-bids.md`); no PayPal test needed | `flat_delivered` (one delivered price per tier, shipping and tax included) or `itemised` |
| `AUTHORIZE_USE_REQUEST_ID` | `true` | RESULT S2: replaying authorize with the same PayPal-Request-Id returned 200 with the same result | `true`, or `false` meaning GET-before-act |
| `PAYMENT_ROUTER` | `single_seller` | RESULT S3 (Partner Referrals 403, assertion 401) and RESULT S7 (Oct 28): a separately selected seller could receive captures, but void and refund returned PERMISSION_DENIED. Final | `platform` (Router A, unavailable), `single_seller` (Router B, the only usable route, labelled under DEP-4), `payee_email` (**rejected by S7**: the adapter raises `NotEnabled`), `fake` (tests and simulation) |
| `PLATFORM_FEE_ENABLED` | `false` | RESULT S3: 422 UNSUPPORTED_PAYMENT_INSTRUCTION (G9 failed) | Always `false` unless platform access is provisioned later |
| `DEDUPE_MODE` | `two_keys` | RESULT S1 (Oct 28-29): basic Login with scope `openid` works and two sign-ins returned matching opaque identifiers (cross-login stability for the tested account and app); the account-attributes scope was rejected (`invalid_scope`); the userinfo `user_id` and the checkout `payer_id` strings differ | `full`, `two_keys`, `checkout_only` per design 7.4. Keep the login identifier and the checkout `payer_id` as separate provider identifiers; neither proves one human |
| `PAYPAL_PAYLOAD_LEVEL` | `0` | RESULT S4 (Oct 31): levels 1-2 passed; level 3 (address lock) needs a human attestation and was not verified; level 4 is unavailable. The app stays at level 0 | Highest payload ladder level PayPal accepted (0 to 3; level 4 needs platform access and is unavailable) |
| `WEBHOOKS_ENABLED` | `false` | RESULT S5 (Oct 28-29, partial): real `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.REFUNDED` and vault token events arrived and verified; `CHECKOUT.ORDER.APPROVED` did not arrive within four minutes | `true` turns the handler on for the three verified types only, as a hint that triggers a GET; it never gates approval, and state changes are always confirmed by GET. Set `true` when task T03A03 ships the handler |
| `BEACON_MODE` | `drand` | RESULT S6 (Oct 29, complete): the public beacon's signature checks succeeded and six distinct US buyer accounts approved USD 1.00 orders (six distinct payer IDs, no authorization or capture) | `drand` or `demo` |
| `PAYPAL_APPROVAL_UI` | `sdk_popup` | RESULT S13 (Oct 28): approval, authorize, void and cancel passed on the owner's public HTTPS tunnel (client-token initialisation); blocked-popup fallback is user-attested | `sdk_popup` (primary) or `redirect` (verified fallback) |
| `PAYPAL_SDK_AUTH` | `client_id` | RESULT S13: client-ID initialisation worked on localhost; client-token worked only on a configured public domain (localhost returned 401 `invalid_domain`) | `client_id` (simpler, chosen for standard checkout) or `client_token`. The client-ID flow passed on the owner's public HTTPS tunnel on Oct 29; task T07A01 repeats it once on the real deployed host and switches to `client_token` with that hostname if it fails. In vault mode the SDK approval is only the fallback path |
| `SEARCH_BACKEND` | `elastic` | RESULT S8 (Oct 31): on 20 public documents and ten labelled queries, the live Elastic hybrid RRF (BM25 plus `semantic_text` through managed `.jina-embeddings-v5-text-small`) reached recall@5 10/10, equal to the PostgreSQL baseline, at 205-387 ms; the temporary index was deleted | `elastic` (selected) or `postgres` (fallback) |
| `SHIPMENT_TRACKING_ENABLED` | `true` | RESULT S12 (Oct 28): `POST /v2/checkout/orders/{order_id}/track` returned 201, GET of the order showed one tracker, a repeat returned 200 with still one tracker. The legacy `/v1/shipping/trackers-batch` returned 403 | `true` uses the Orders v2 endpoint after capture; API acceptance is not proof of shipment or delivery |
| `PAYPAL_MCP_VERIFICATION` | `paypal_read_subset` | RESULT S10 (Oct 28): the local official MCP with an explicit read-only tool selection read a known order; the hosted SSE server listed tools but its order read returned a setup error | `paypal_read_subset` means the local, pinned server for inspection only; FairPool's own verification endpoint stays the primary path and nothing in payment correctness depends on MCP |
| `ZAPIER_BRIDGE` | `off` | PENDING S9 (Oct 28: authentication succeeded; the four FairPool actions cannot exist until the Agent API is built) | `managed` once S9 passes (documentation switch for the demo; not read by code) |

Void has no switch: replaying a void returned 422 with and without a request ID, so void is always GET-before-act (see `docs/contracts/paypal-adapter.md`).

**DEP-4 is final for the router.** Router A is unavailable and S7 rejected the payee-email route, so `PAYMENT_ROUTER=single_seller` applies and is labelled wherever it matters. `SINGLE_SELLER_EMAIL` must be the sandbox business account that owns the REST app: only that seller's payments could be voided and refunded. A seller email accepted when an order is created is not evidence that the app may manage that seller's payments. The product therefore pays one business account in the prototype; paying several sellers from one pool is out of scope until partner access exists. Oct 29 results: Payouts returned 403 PAYOUT_NOT_AVAILABLE on the first call, so manual settlement of the winning merchant stays final; Partner Referrals returned 403 NOT_AUTHORIZED, and unblocking the platform route needs a configured Sandbox Platform app and seller consent (an optional owner action, not a build dependency).

**Solution 2 correction (Oct 29).** The proposal's "math problem" is not present in this design: shipping is a merchant-supplied zone table and tax a rate table or included, both computed locally; no shipping or tax API is called at close. Lots are per delivery zone resolved by the server, not grouped by Elastic; Elastic keeps its retrieval-only role (INT-1). The flat delivered price rule is adopted as `BID_PRICING_MODE=flat_delivered`.

**Solution 1 corrections (Oct 29).** A saved PayPal permission has no maximum amount in PayPal: the cap is FairPool's own record and rule (the owner confirmed). The PayPal Agent Toolkit cannot convert a setup token; deterministic adapter code does the exchange and the charge, and AI never moves money (FR-IG-09).

Fallback labelling rule (DEP-4, I13): whenever `PAYMENT_ROUTER=single_seller` or `PAYMENT_MODE=capture_only` is active, every checkout screen, README paragraph and video segment that depends on it says so in plain words.

## 5. Integration decisions (INT-1 to INT-9)

Source: the owner's `PayPal.txt` (sponsor and PayPal tool plan and UI plan), evaluated on Oct 20, 2026 against the products' official documentation. For each tool: what the TXT proposed, what the official docs show, what we build. Where a TXT proposal would break an invariant or is not supported by the docs, it is changed here with the reason. None of this changes the idea text: deterministic rules enforce requirements, AI only proposes, humans approve every payment (I1, I2).

Official sources consulted: Elastic hybrid search with `semantic_text` (elastic.co/docs/solutions/search/hybrid-semantic-text); Zapier MCP docs (docs.zapier.com/mcp: how tools work, switch modes, quickstart) and Webhooks by Zapier help pages; APIMatic pricing (apimatic.io/pricing), CLI and Context Plugin pages (docs.apimatic.io, apimatic.io/product/context-plugins); PayPal Agent tools reference (developer.paypal.com/ai-tools/agent-tools), MCP server quickstart (developer.paypal.com/ai-tools/mcp-server), Transaction Search guide, and JavaScript SDK v6 set-up (developer.paypal.com/sdk/js/set-up).

| ID | Tool and role | What the TXT proposed | What the official docs show | Decision |
|---|---|---|---|---|
| INT-1 | Elastic: search and retrieval | Store buyers' JSON constraints in Elastic; semantic similarity "ensures the bid strictly matches" firm requirements; match 10,000 buyer constraints against quotes | `semantic_text` fields with `copy_to` from a `text` field, hybrid search through the RRF retriever (the semantic leg is documented both as a `match` and as a `semantic` query on the `semantic_text` field; S8 records which the cluster accepts), Elastic Inference Service default endpoint, explicit `inference_id` recommended for production, Serverless 14-day trial | **Adopted, scoped.** Used for intake candidate-pool retrieval, merchant Demand Board search, agent pool search, and an advisory wrong-product check on quotes (WARNING flag LOW_SIMILARITY only). **Not adopted:** similarity as a gate (the idea requires deterministic rules; an embedding score can accept a near match such as an extra bundle item), indexing buyer requests (private caps and personal data), and per-buyer matching against quotes (pools are exact-match templates; entries are never compared with bids). Only public pool and lot documents are indexed. Postgres trigram search is the fallback |
| INT-2 | Zapier MCP: headless buyer interface | Buyer tells Claude or ChatGPT to join a pool; Zapier MCP injects the intent into FairPool | Zapier MCP endpoint `https://mcp.zapier.com/api/v1/connect` (Streamable HTTP; OAuth or bearer token). Default **agentic mode** lets the agent discover and enable actions itself; **managed mode** exposes one tool per configured action, no dynamic discovery, with locked field values. Webhooks by Zapier (GET, POST, PUT, Custom Request with headers) is a premium app (14-day premium trial). Each tool call uses two tasks. A token or a URL containing it grants tool access | **Adopted, managed mode only**, exactly four tools (list pools, join pool, list my entries, withdraw entry), each with URL and Authorization header locked to the Agent API and a delegation token; no PayPal or other apps enabled. The buyer's own AI client extracts the structured fields; humans still approve payment on PayPal. Constraint: premium trial window (start the trial in PH4 so recording in PH10 is covered). Spike S9 |
| INT-3 | FairPool MCP server | not in the TXT | MCP Streamable HTTP is the transport Zapier uses | **Added and required.** Our own MCP endpoint `/mcp` with the same tools and delegation-token auth, so the agentic path does not depend on Zapier's plan, quotas or trial. No payment tools |
| INT-4 | APIMatic: SDK, portal, context | Generate the "FairPool Merchant SDK" from OpenAPI in about five minutes; replaces Postman; endpoint `/v1/merchant/quote/submit` | Generates SDKs (Python, TypeScript, Java, C#, PHP, Ruby, Go) and portals from OpenAPI including 3.1; CLI `apimatic sdk:generate`; 14-day trial gives Business features. Plan prices and endpoint limits differ between APIMatic's pricing page and third-party listings (Lite is listed at 20 endpoints per API and one language, at prices from $10 to $115 per month; higher tiers allow 30 to 100 endpoints). The 10-operation Merchant API fits under every figure seen, so the design does not depend on the exact price; S11 records the plan actually used. After a trial ends, SDK and portal generation stop, so generate and commit the SDKs while the trial or plan is active. Context Plugins give coding agents version-aware PayPal Server SDK context | **Adopted in two ways.** (1) Dev time: install the ContextMatic plugin for PayPal in each member's coding agent to reduce hallucinated PayPal calls; our verified facts (V and S results) still override it. (2) Generate Python and TypeScript Merchant SDKs and a portal from a **dedicated** Merchant Agent API OpenAPI document of at most 20 operations (we define 10). Never feed the whole app (60+ operations). `/v1/merchant/quote/submit` does not exist; our route is `PUT /merchant-api/v1/lots/{lot_id}/bid`. Spike S11 |
| INT-5 | PayPal Agent Toolkit | Backend AI uses it to generate the Orders v2 payloads for 3,000 buyers instead of a loop | Tools reference: `create_order` takes only `items` (name, quantity, unit_price) and `currency`; no intent, payee, shipping, custom_id or request ID; `pay_order` captures an order; `create_refund`; no authorize or void tool; reporting and shipment-tracking tools exist | **Not used in the payment path.** It cannot express our AUTHORIZE order with payee and idempotency (V2, V3, S2), takes numeric prices, and an AI generating payloads would break I2, I3 and I9. Deterministic code creates orders. **Dev time only:** the PayPal AI Toolkit plugin for coding agents (skills, doctor and explain-error commands); verified facts still override it |
| INT-6 | PayPal MCP server: merchant verification copilot | Merchant asks Claude whether the batch's buyers paid; MCP queries the merchant's PayPal account | Hosted sandbox server `https://mcp.sandbox.paypal.com` (SSE at `/sse`; the streamable-HTTP path is listed as `/http` in PayPal's docs and `/mcp` in the MCP registry, so S10 records which one answers; bearer credentials or PayPal login) Result (Oct 28, 2026): `/http` returned 404; `/sse` connected and listed tools, but `get_order` returned a business error (`ok=false`, the code PAYPAL_API_SETUP_ERROR, `Unsupported cache mode: default`) while the MCP envelope did not set `isError`; always parse the reply's own `ok` field. The local official `@paypal/mcp` 1.8.1 on `@paypal/agent-toolkit` 1.11.0 with `--tools=orders.get,disputes.list,disputes.get,shipment.get,payments.getRefunds` exposed exactly five tools and read a known order correctly. Pin both versions in a lockfile; local `@paypal/mcp` with access token; read tools such as get order, list transactions, get shipment tracking; write tools such as pay order, create refund. Transaction Search can lag up to three hours and needs a permission enabled on the app, which can take up to nine hours | **Adopted as a read-only verification copilot.** FairPool publishes a per-lot **verification manifest** (PayPal order IDs, capture IDs, amounts, no buyer personal data). The merchant's Claude calls get-order style read tools per ID and compares totals with FairPool's funded total. Never use list-transactions for the live demo (latency). Read-only is enforced by the local server's explicit tool selection (a test boundary, not a permission on the token). FairPool's own verification endpoint (server-side read-only GETs, `GET .../verification`) is the primary path; the PayPal MCP is optional inspection and is never relied on for payment correctness |
| INT-7 | PayPal JavaScript SDK v6: buyer approval | Official PayPal button in a popup inside our app | Script `https://www.sandbox.paypal.com/web-sdk/v6/core`; `window.paypal.createInstance({clientId or clientToken, components, pageType})` (the page recommends client ID; S13 showed a client token works only for a configured public domain, `localhost` returning 401 `invalid_domain`); `findEligibleMethods`; `createPayPalOneTimePaymentSession({onApprove, onCancel, onError})`; `<paypal-button>`; `session.start({presentationMode: "auto"}, createOrder())` where `createOrder` resolves `{orderId}`; never pass totals from the browser | **Adopted as the primary approval UX** (supersedes D10). `continue` returns the PayPal order ID; `onApprove` posts the order ID to our server, which runs the FR-CK-05 checks and then authorizes server-side. The docs' sample captures in `onApprove`; ours does not. The callback fields seen were `fundingSource`, `orderId`, `payerId`: they are hints, never a substitute for a server GET. Redirect remains the fallback |
| INT-8 | PayPal shipment tracking | Fulfillment tab with shipping CSV | Agent tools reference lists create and get shipment tracking; the Orders v2 track endpoint takes the capture ID, tracking number and carrier | **Adopted; S12 passed with a different endpoint.** After capture, FairPool calls `POST /v2/checkout/orders/{order_id}/track`, then GETs the order to verify the tracker; the legacy `/v1/shipping/trackers-batch` returns 403 for this app. Only real seller-supplied tracking is sent, and only after shipment; use `notify_payer=false` in tests. Deterministic REST, not an AI call |
| INT-9 | Merchant Agent API and keys | Developer API tab, keys for pricing bots | not applicable | **Added.** `/merchant-api/v1` with ten operations, hashed API keys with scopes, rate limits and the same sealed-bid rules. A bot's structured submission is its confirmation; pasted quotes still need human confirmation (DEP-2) |

### 5.1 Corrections to statements in the TXT

1. The hackathon brief says the single hard requirement is meaningful use of both PayPal and AI. It does not say agents must autonomously transact.
2. "PS6" and "$1.5M pool" are brand names and invented figures. The demo uses generic products and real sandbox amounts (FR-HK-06).
3. "Pay only if your price is met" is imprecise because PayPal places a hold when the buyer approves. The badge reads: **$0 to join. No hold until a merchant meets your price and you approve.** (I13).
4. "Funds legally captured" is not a claim we can make. The Fulfillment tab says "Funded: PayPal captures completed".
5. A live "payments captured" progress bar would show zero until the capture sweep. The tracker shows holds placed against the MOQ, then captures after the sweep starts (design 11.6).
6. The TXT's JavaScript SDK link opens the v6 documentation; v5 patterns (`client-id` query string, `actions.order`) do not apply.
7. The TXT says Elastic proves matching "without hallucinating". Retrieval can reduce wrong guesses but cannot enforce requirements; deterministic rules do (R3).

### 5.2 What this adds beyond the idea text

Additions that the idea text does not mention (all consistent with its rules): Elastic search (INT-1), Zapier and FairPool MCP agent paths (INT-2, INT-3), merchant bot API and SDK (INT-9), PayPal MCP verification (INT-6), shipment tracking (INT-8), the JS SDK popup (INT-7). The idea's own buyer A2A lane (FR-SL-03) is the base for INT-2 and INT-3.


## Phase 4 onward: owner reassignment and task ID history (2026-10-31)

The owner approved a Member A-heavy split from Phase 4 onward. Phase 0 through 3 IDs and ownership remain unchanged. No task or dependency is deferred. The task IDs below are historical aliases for traceability; the new IDs are current. Member A merges the Phase 7 Agent API before Member B builds its dependent MCP server in the same phase.

| Previous task ID | Current task ID |
|---|---|
| T04B02 | T04A04 |
| T04B03 | T04A05 |
| T04B04 | T04A06 |
| T05B01 | T05A06 |
| T05B02 | T05A04 |
| T05B03 | T05A05 |
| T06B02 | T06A05 |
| T06B03 | T06A06 |
| T06B04 | T06A07 |
| T07B02 | T07A05 |
| T07B04 | T07A06 |
