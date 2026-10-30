# Product spec: FairPool

FairPool groups buyers into demand pools and lets merchants compete in a reverse auction to fulfil each pool. Buyers join free during a fixed window, a published rule allocates places, merchants bid sealed, and each selected buyer approves an individual PayPal payment to the winning merchant.

The idea text is `docs/fairpool-idea.md`. This file restates it as numbered requirements so every task can trace back to it. If this file and the idea text ever disagree, the idea text wins for **what** to build and you stop and raise it (see `docs/agents.md`, uncertainty protocol).

Source tags: **IDEA** from the idea text (section named), **DEP** an approved departure (`docs/decisions.md`), **DESIGN** an addition made in `docs/system-design.md`, **GAP** something the idea text leaves open that the design filled.

In the tags below, `IDEA n` is the n-th stage of the idea text's section 5 (How it works): 1 joining and duplicate control (5.1), 2 request intake (5.1), 3 fixed window and selection (5.2), 4 lots (5.3), 5 bidding (5.4), 6 checkout (5.5), 7 funding, failure and fulfilment (5.6 to 5.8). `IDEA AI` is section 8 and `IDEA PayPal` is section 9.

## 1. Functional requirements

### Identity and duplicate-entry control (idea section 1)

| ID | Requirement | Source |
|---|---|---|
| FR-ID-01 | Customers create a FairPool account | IDEA 1 |
| FR-ID-02 | A customer can connect a PayPal account through Log in with PayPal (scope `openid` only: the account-attributes scope was rejected by this app in S1) when it works for the app; the login identifier and the checkout `payer_id` are kept as separate provider identifiers (`DEDUPE_MODE=two_keys`) and neither proves one human; if it is required for entry, say so before the buyer joins and explain what is requested | IDEA 1 |
| FR-ID-03 | One entry per linked PayPal account per pool; described as account-level duplicate control, never as person-level identity or complete anti-scalper protection | IDEA 1 |
| FR-ID-04 | Checkout-time duplicate control: the approved order's payer_id must not be held by another active seat in the pool, and must equal the linked key when `DEDUPE_MODE=full` | DESIGN 7.3 |
| FR-ID-05 | Sessions, CSRF protection and role checks for buyer, merchant and admin | DESIGN 16 |

### Request intake (idea section 2)

| ID | Requirement | Source |
|---|---|---|
| FR-IN-01 | A buyer's natural-language request becomes structured fields: exact product and model, condition, quantity, delivery location, required delivery date, currency, maximum total price | IDEA 2 |
| FR-IN-02 | Firm requirements are separated from preferences; the system asks a question when an important detail is unclear | IDEA 2 |
| FR-IN-03 | The buyer confirms the structured request before it enters a pool; the saved confirmed request, not the AI output, defines the requirements | IDEA 2 |
| FR-IN-04 | Joining costs $0 and places no PayPal hold or authorization. In `PAYMENT_MODE=vault_charge` (primary, owner decision Oct 29): joining also saves the buyer's PayPal wallet for FairPool after the consent text of `contracts/vault-charge.md` section 6; no funds are reserved, and an entry without an active saved permission is rejected at close (VAULT_MISSING) | IDEA 2 |
| FR-IN-05 | The cap is the maximum delivered total including shipping and tax; the final total never exceeds it; if the total changes the buyer reviews and approves the new amount. In `PAYMENT_MODE=vault_charge` (primary, owner decision Oct 29): the cap is enforced by FairPool, not PayPal, and is stated in the consent text; a charge is never above the awarded total, and the awarded total is never above the cap; a total that would exceed the cap seats nobody and charges nothing | IDEA 2 |
| FR-IN-06 | Quantity is 1, currency USD, payer country US | DEP-1 |
| FR-IN-07 | Pools are operator-defined templates; a confirmed request is matched to an open pool of the same product, variant and condition | GAP (D2) |
| FR-IN-08 | A manual structured form produces the same confirmed request when AI is unavailable or unresolved | DESIGN 8.2 |

### Fixed window and auditable selection (idea section 3)

| ID | Requirement | Source |
|---|---|---|
| FR-SL-01 | Each pool stays open for a published period; every eligible request received before close is considered under the same published rules | IDEA 3 |
| FR-SL-02 | Arrival time gives no priority | IDEA 3 |
| FR-SL-03 | AI shopping agents can submit requests through a documented API with the same required fields and account-level limits; an agent acting for an enrolled account is not a separate buyer | IDEA 3 |
| FR-SL-04 | The allocation rule is published before the pool opens, and the entries included at the cutoff are recorded | IDEA 3 |
| FR-SL-05 | If demand exceeds places, apply the announced rule and create an ordered waitlist | IDEA 3 |
| FR-SL-06 | Describe selection as auditable under published rules; never as cryptographically verified or provably fair | IDEA 3 |
| FR-SL-07 | Selection is a seeded lottery: entry commitments are published before a public beacon seed exists, ordering is a pure function of the seed and commitments, and each buyer gets a signed receipt | DESIGN 9 (D4) |

### Lot batching and waitlists (idea section 4)

| ID | Requirement | Source |
|---|---|---|
| FR-LT-01 | A large pool can be divided into fulfilment lots (for example a 3,000-unit first lot) with an ordered waitlist | IDEA 4 |
| FR-LT-02 | Requests are never split across lots in a way that silently changes product, condition, delivery terms or price | IDEA 4 |
| FR-LT-03 | Each lot has its own quantity, merchant offer, payment status and outcome; participants are told before allocation that lots can end with different winning merchants and prices | IDEA 4 |
| FR-LT-04 | No buyer is assigned to more than one active offer for the same pool | IDEA 4 |
| FR-LT-05 | Where shipping or tax differs by location, buyers are grouped by delivery zone and each buyer's exact total is calculated separately. With `BID_PRICING_MODE=flat_delivered` (primary) each zone lot has one delivered price per tier (shipping and tax included), so a buyer's total is that price and eligibility is one integer comparison with the cap (`contracts/flat-delivered-bids.md`) | IDEA 4 |
| FR-LT-06 | The lot plan (zone, seats per lot, minimum size) is fixed by pool policy and published before bids, never by merchant capacity | GAP (design 9.1) |

### Reverse auction and sealed bidding (idea section 5)

| ID | Requirement | Source |
|---|---|---|
| FR-AU-01 | After the buyer window closes, eligible merchants submit bids per lot | IDEA 5 |
| FR-AU-02 | A bid states exact product and model, condition, bundle contents, capacity, target quantity, MOQ, price tiers, item price, shipping and tax method, delivery dates, return terms, evidence of eligibility and inventory, and offer validity through checkout and waitlist. In flat-delivered mode the price is one delivered price per tier and the bid is rejected if it carries a shipping table or itemised tax | IDEA 5, DEP-3 |
| FR-AU-03 | Bids are sealed from competitors; sealing is not MAP compliance; merchants attest that the offer and its display are allowed by supplier terms | IDEA 5 |
| FR-AU-04 | Offers violating a buyer's firm requirements are rejected; the rest are ranked by buyer-relevant delivered price and disclosed terms; the lowest qualifying offer wins, never merely the lowest number | IDEA 5 |
| FR-AU-05 | Price tiers resolve at award time from the buyers who can accept each tier's price | GAP (D5) |
| FR-AU-06 | A bid is feasible only if enough seated buyers can accept its price; seated buyers whose cap is below their total are priced out and their seats refilled | GAP (design 10.6, 10.7) |
| FR-AU-07 | A merchant's total capacity is shared across lots awarded in published lot order | GAP (R9) |

### Checkout and waitlist waves (idea section 6)

| ID | Requirement | Source |
|---|---|---|
| FR-CK-01 | Selected buyers see the winning merchant, exact product and condition, delivery and return terms and their own final total, which cannot exceed their cap. In vault mode they are told this when the award is made and are charged automatically | IDEA 6 |
| FR-CK-02 | Each selected buyer has a stated period (for example 15 minutes) to review and approve their own PayPal AUTHORIZE order (SDK popup, redirect as fallback); the hold exists only after the winner and price are known and the buyer approves. In `PAYMENT_MODE=vault_charge` (primary, owner decision Oct 29): there is no buyer payment window and no authorization: FairPool charges each seated buyer's saved permission once (BO-23 to BO-27), with at most `VAULT_CHARGE_CONCURRENCY` charges at once | IDEA 6, INT-7 |
| FR-CK-03 | Only available places are offered; before a place is released to the next eligible buyer the old order is confirmed unable to complete; offers go out in bounded waves in published waitlist order; never more buyers are invited to pay than the lot can fulfil. In vault mode a vacancy from a failed or rejected charge is refilled from the waitlist the same way | IDEA 6 |
| FR-CK-04 | Durable per-buyer order records and idempotency controls stop retries or repeated clicks creating duplicate purchases; a delayed payment event is reconciled with PayPal before a place is reassigned; an unknown charge outcome is never retried under a new key (reconcile by GET) | IDEA 6 |
| FR-CK-05 | On approval the server fetches the order and requires status APPROVED, intent AUTHORIZE, expected amount and currency, expected payee, allowed payer country and a passing payer key. In vault mode the server instead requires, before charging: an ACTIVE saved permission, total at or below the cap, lot CHECKOUT_OPEN and a valid award | DESIGN 11.4 |

### Batch confirmation and fulfilment (idea section 7)

| ID | Requirement | Source |
|---|---|---|
| FR-FN-01 | Each buyer approves a separate PayPal order addressed to the winning merchant for that buyer's exact total. In `PAYMENT_MODE=vault_charge` (primary, owner decision Oct 29): each seated buyer is charged through one separate PayPal order for that buyer's exact total, paid to the single seller account (`PAYMENT_ROUTER=single_seller`); the merchant is paid afterwards by manual settlement (Payouts is unavailable) | IDEA 7 |
| FR-FN-02 | Checkout is authorization-first; once enough eligible buyers have authorized to attempt to meet the MOQ, approved authorizations are captured; the lot is funded only after PayPal confirms enough captures as COMPLETED. In vault mode there is no authorization step: the lot is funded when completed captures from distinct buyers reach the minimum | IDEA 7 |
| FR-FN-03 | Webhook signatures are verified, events de-duplicated, and PayPal order or capture status checked when needed | IDEA 7 |
| FR-FN-04 | A failed or pending capture does not count as paid; remaining places can go to the waitlist while the seller's offer remains valid | IDEA 7 |
| FR-FN-05 | If the lot misses its minimum by the agreed deadline, uncaptured authorizations are voided and completed captures refunded. In vault mode every completed capture is refunded in full and the saved permissions are deleted; a refund may not return PayPal's fees, which the README states | IDEA 7 |
| FR-FN-06 | Seller settlement depends on an approved marketplace integration; the product and README state that sandbox order creation does not establish production settlement | IDEA 7 |
| FR-FN-07 | Capture-first mode and the single stand-in sandbox seller exist only as fallbacks and are labelled wherever they apply | DEP-4 |
| FR-FN-08 | An append-only ledger records money facts; a reconciler heals unknown or stale states by fetching PayPal | DESIGN 12 |

### AI architecture (idea, AI Architecture section)

| ID | Requirement | Source |
|---|---|---|
| FR-AI-01 | AI converts buyer text to structured fields, detects ambiguity and asks, and the buyer confirms | IDEA AI 1 |
| FR-AI-02 | AI flags differences between a merchant offer and the buyer's firm requirements; deterministic backend rules enforce hard requirements and the price ceiling; AI cannot override them, accept a changed offer for the buyer or execute a payment | IDEA AI 2 |
| FR-AI-03 | Synthetic buyer and merchant agents rehearse grouping, allocation and bids; everything simulated is labelled; a simulation does not prove conversion, participation or price compression | IDEA AI 3 |
| FR-AI-04 | A pasted merchant quote is parsed by AI into proposed fields that the merchant confirms | DEP-2 |
| FR-AI-05 | AI extraction and quote parsing are measured on labelled sets and the results are published in the README | DESIGN 8.4 |

### Agent lane, audit, operations, simulation

| ID | Requirement | Source |
|---|---|---|
| FR-AG-01 | Documented agent API: list and search pools, create entry (idempotent), list own entries or read one entry's status, withdraw entry; delegation tokens scoped by pool or category, maximum cap and expiry; also reachable through the FairPool MCP server and the Zapier managed-mode bridge | IDEA 3, DESIGN 13, INT-2, INT-3 |
| FR-AG-02 | The agent API has no payment endpoint; humans approve payments on PayPal. In vault mode an agent can submit the confirmed request, but the entry needs the buyer to open the returned `vault_action_url`, accept the consent text and approve saving PayPal; until then the entry is not eligible | DESIGN 13 |
| FR-AD-01 | Public audit page: rules and rules hash, commitments list and root, beacon round and value, lot boundaries, award summary, and a verify-my-place check | DESIGN 9, 15 |
| FR-AD-02 | Hash-chained, append-only audit log with published checkpoints | DESIGN 5 |
| FR-OP-01 | Ops console: lot state view, dead-letter webhooks, reconciler runs, mock-failure toggles for the demo, lot abort, audit export | DESIGN 15 |
| FR-OP-02 | Structured logs, metrics and alerts for rejected transitions, amount mismatches, unknown outcomes and dead letters | DESIGN 17.2 |
| FR-SM-01 | Simulation pools are isolated from live pools by mode, use a fake payment router, make no PayPal calls, and show a SIMULATED banner everywhere | DESIGN 14 |

### PayPal integration and compliance (idea, PayPal Integration section)

| ID | Requirement | Source |
|---|---|---|
| FR-PP-01 | Use PayPal Orders v2 for individual buyer checkouts: select winner and price, create AUTHORIZE order per buyer, obtain approval, then authorize. In vault mode the buyer saves PayPal with a Vault setup token at join, and FairPool later creates one CAPTURE order per seated buyer with the saved payment token and captures it (`contracts/vault-charge.md`) | IDEA PayPal |
| FR-PP-02 | The invalid_scope error is resolved by testing the full login request (app config, scopes, encoded request, registered return URL) end to end, not by blaming one checkbox | IDEA PayPal |
| FR-PP-03 | Sandbox status is described honestly; production needs platform review and seller onboarding | IDEA PayPal |
| FR-PP-04 | PayPal is never described as the domestic checkout for an India-only marketplace; the MVP is US-payer, USD | IDEA PayPal |
| FR-PP-05 | Exposed Sandbox secrets are rotated and replacement credentials live only in the environment | IDEA PayPal |
| FR-PP-06 | Code refuses any host other than the PayPal Sandbox API | DESIGN 16 |

### Hackathon deliverables

| ID | Requirement | Source |
|---|---|---|
| FR-HK-01 | Public open-source repository with a license detected in the About section | Hackathon rules |
| FR-HK-02 | Functional demo: hosted URL or run instructions in the repo; not a mockup | Hackathon rules |
| FR-HK-03 | README explains features, how PayPal and AI are used, how to run, tests and limits | Hackathon rules |
| FR-HK-04 | Demo video under 3 minutes, public on YouTube, shows the project running end to end | Hackathon rules |
| FR-HK-05 | Text description and the tools-used statement (which AI tools and models, and how) | Hackathon rules |
| FR-HK-06 | English only; no third-party trademarks or unlicensed music in the video; generic product names in the demo | Hackathon rules |

### Buyer and merchant interface (from the owner's UI plan in `PayPal.txt`)

| ID | Requirement | Source |
|---|---|---|
| FR-UI-01 | Buyer Tab 1, Discover and Join: the AI prompt bar ("What are you looking for and what is your max price?") feeds intake (FR-IN-01); a grid of open pools sorted by public entry count ("trending") where every card shows the badge **$0 to join. No hold until a merchant meets your price and you approve.** | UI plan, INT-1 |
| FR-UI-02 | Buyer Tab 2, My Pools: Pending (pool open, closed or bidding), Waitlist (**Waitlisted, position #N** from the allocation), and Action Required (offers with a live countdown to `offer_expires_at` and the PayPal button of FR-IG-06; in vault mode the only action is finishing the saved-PayPal step, and a seated buyer sees Charged or Charge failed with the reason); priced-out and rejected entries show their reason | UI plan |
| FR-UI-03 | Buyer Tab 3, Orders: orders by outcome (funded, voided, refunded) with a receipt (amounts, PayPal capture ID, winning merchant, return terms) and status history | UI plan |
| FR-UI-04 | Merchant Tab 1, Demand Board: a live feed (server-sent events) of lots in BIDDING with the lot requirement (product, variant, condition, bundle, seats, zone, delivery terms, minimum return period, bid deadline), search (FR-IG-01), and Submit sealed bid (paste a quote or fill the form) | UI plan, INT-1 |
| FR-UI-05 | Merchant Tab 2, Active Bids: Pending; In Checkout with a live tracker (holds placed against the MOQ, or in vault mode charges attempted against the MOQ, then captures completed, refills, time left); Lost or Failed with reason codes | UI plan |
| FR-UI-06 | Merchant Tab 3, Fulfillment: funded lots, a shipping CSV (addresses only after the lot is FUNDED, N14), mark shipped with tracking numbers (FR-IG-08), and the verification manifest download (FR-IG-07) | UI plan |
| FR-UI-07 | Merchant Tab 4, Developer API: create and revoke API keys (secret shown once), scopes, rate limits, SDK downloads and the portal link (FR-IG-05), quickstart | UI plan, INT-9 |
| FR-UI-08 | Every screen shows the honesty labels and notices that the API returns (SANDBOX, FALLBACK, SIMULATED, DEMO SEED, MOCK); the browser never composes a claim itself (I13) | DESIGN 15 |

### Sponsor and PayPal tool integrations (decisions INT-1 to INT-9 in `docs/decisions.md`)

| ID | Requirement | Source |
|---|---|---|
| FR-IG-01 | Search service: hybrid retrieval (Elastic when `SEARCH_BACKEND=elastic`, Postgres trigram otherwise) over **public pool and lot documents only** for intake candidates, the Demand Board and agent pool search; an advisory LOW_SIMILARITY WARNING flag when a quote retrieves a different pool better than its own lot; similarity is never a gate and buyer requests are never indexed | INT-1 |
| FR-IG-02 | FairPool MCP server at `/mcp` (Streamable HTTP) with tools to list or search pools, enter a pool, list own entries and withdraw an entry; delegation-token auth; no payment tools | INT-3 |
| FR-IG-03 | Zapier MCP bridge in managed mode with exactly four tools whose URL and Authorization header are locked to the Agent API; no PayPal or other apps enabled; setup and plan limits documented | INT-2 |
| FR-IG-04 | Merchant Agent API at `/merchant-api/v1` (ten operations) with hashed API keys, scopes, rate limits and sealed-bid rules | INT-9 |
| FR-IG-05 | Python and TypeScript Merchant SDKs and a developer portal generated by APIMatic from the Merchant Agent API OpenAPI document (at most 20 operations), committed under `sdk/` with usage docs | INT-4 |
| FR-IG-06 | PayPal JavaScript SDK v6 approval: the buyer approves in the SDK popup (redirect as fallback); the server verifies the order (FR-CK-05) and authorizes; the browser sends no amounts. In vault mode the saved-PayPal step is a redirect to PayPal's approval link (the SDK save-payment variant was not established) | INT-7 |
| FR-IG-07 | Verification copilot: a per-lot verification manifest (PayPal order and capture IDs and amounts, no buyer personal data) and documented read-only prompts for the merchant's Claude connected to the PayPal MCP server; a FairPool live verification endpoint (read-only GETs) as fallback | INT-6 |
| FR-IG-08 | After a merchant marks a funded lot shipped, FairPool submits tracking to PayPal through the adapter (deterministic REST) when `SHIPMENT_TRACKING_ENABLED`; otherwise tracking stays inside FairPool and is labelled | INT-8 |
| FR-IG-09 | Coding agents use the APIMatic ContextMatic plugin and the PayPal AI Toolkit plugin at development time; the PayPal Agent Toolkit is never used in the runtime payment path | INT-4, INT-5 |

## 2. Non-goals

Live production payments or PayPal platform approval; AI-generated payment payloads (the PayPal Agent Toolkit stays out of the payment path); PayPal or other write actions in any MCP server or Zapier tool; platform fees and multi-seller marketplace settlement (Sandbox app lacks partner access, S3); India-domestic checkout; proof of one human per account; MAP compliance; wholesale-price guarantee; multi-currency; more than one unit per entry; split-lot or combinatorial auctions; a real tax engine (tax is simulated and labelled); delivery tracking beyond recording; emergent pools from free text.

## 3. Claims we may and may not make

The full wording table is in `docs/system-design.md` Appendix B. The pool-card badge is fixed by FR-UI-01. Short form: say "auditable under published rules", "one entry per linked PayPal account", "demonstrated in the PayPal Sandbox", "simulated"; never say "provably fair", "bot-proof", "one person one entry", "production-ready", "you will save", "MAP compliant", "your money is safe".

## 4. Demo scope

Generic products only (for example "27-inch 4K monitor"). One live sandbox pool with six real sandbox buyers and two lots, a refill and a failure path (void then refund), a headless join through an AI client (Zapier managed-mode bridge and the FairPool MCP server), a merchant bot bid through the generated SDK, a merchant verification with the PayPal MCP server, plus one clearly labelled simulation pool at 10,000 entries. Storyboard in `docs/demo-and-submission.md`.

## 5. Idea alignment audit

The idea text is `docs/fairpool-idea.md`. This table walks its statements in order and says how the build treats each one. Status values: **SAME** (built as written), **NARROWED** (an approved departure, `docs/decisions.md`), **CLARIFIED** (the idea is silent or ambiguous and the gap is filled, listed in section 5.1), **EXTENDED** (something added that the idea does not forbid; it never weakens a rule of the idea).

| Idea statement | Status | Requirements | Where it is built or tested |
|---|---|---|---|
| Buyers are pooled so merchants can compete for volume | SAME | FR-AU-01 to FR-AU-04 | `domain-ports.md`, `fairness-and-hashing.md`, T05B03, T06B03 |
| FairPool reduces first-click advantage and limits duplicate entries through the same linked account; it does not prove one person per account, stop resale or eliminate bots | SAME | FR-ID-03, FR-SL-02, FR-SL-06 | T03B01, F17 disclosed limit |
| Joining is free and places no PayPal hold | SAME | FR-IN-04 | T03B01; hold only at checkout (T05A01) |
| Buyers state requirements and a maximum delivered price | SAME | FR-IN-01, FR-IN-05 | T04B01 |
| Account connection through PayPal Login (account ID scope, openid) and one entry per linked account | SAME | FR-ID-02, FR-ID-03 | T03B03; outcome depends on S1 |
| If Login is required for entry, say so before joining | SAME | FR-ID-02 | disclosure screen in T03B03 |
| Natural language to structured fields; firm requirements vs preferences; ask when unclear; buyer confirms | SAME | FR-IN-01 to FR-IN-03 | T04B01 |
| Structured fields include quantity and currency | NARROWED | FR-IN-06 | DEP-1: quantity 1, USD, US payers |
| Final total including shipping and tax never exceeds the cap; a changed total needs new approval | SAME | FR-IN-05 | I3, F13 |
| Fixed published window; every eligible request before close is considered; arrival time gives no priority | SAME | FR-SL-01, FR-SL-02 | T03B01, trigger `trg_entry_insert_window` |
| AI agents can submit requests through a documented API with the same fields and limits; an agent for an enrolled account is not a separate buyer | SAME | FR-SL-03, FR-AG-01 | T07B02 |
| The agent lane is reachable through MCP clients | EXTENDED | FR-IG-02, FR-IG-03 | INT-2, INT-3; no payment tools (I1, I2) |
| Publish the allocation rule before opening; record the entries included at the cutoff; ordered waitlist | SAME | FR-SL-04, FR-SL-05 | T02B02, T03B04, T04B03 |
| A hash alone does not prove completeness; a future proof needs a seed FairPool cannot choose after seeing entries and must protect personal data; describe selection as auditable | EXTENDED | FR-SL-06, FR-SL-07 | beacon, commitments and receipts are built now; the wording stays "auditable" (I13) |
| Pools can be divided into lots (for example 3,000 plus a waitlist) | SAME | FR-LT-01 | T04B03 |
| Lot size is fixed by FairPool before bids | CLARIFIED | FR-LT-06 | section 5.1 item 1 |
| Requests are never split across lots in a way that silently changes terms; each lot is isolated; different winners and prices are disclosed before allocation; no buyer has two active offers per pool | SAME | FR-LT-02 to FR-LT-04 | rules document, `idx_one_active_order_per_entry` |
| Delivery groups or exact per-buyer totals | SAME | FR-LT-05 | zones in the lot plan, T06A04 |
| After the window closes, eligible merchants bid; bid contents as listed, with target quantity and evidence | SAME | FR-AU-01, FR-AU-02 | DEP-3 keeps both fields |
| AI parses a merchant's free-text quote into fields | NARROWED | FR-AI-04 | DEP-2: AI proposes, the merchant confirms |
| Bids are sealed; sealing is not MAP compliance; merchants attest | SAME | FR-AU-03 | T05B01, T05B02 |
| Offers violating firm requirements are rejected; the lowest qualifying offer wins | SAME | FR-AU-04 | R1 to R9, T05B03 |
| Tiers, feasibility, price-out and capacity across lots | CLARIFIED | FR-AU-05 to FR-AU-07 | section 5.1 items 2 to 4 |
| Selected buyers see merchant, product, terms and their own total; a stated window to approve their own AUTHORIZE order; the hold exists only after the winner is known and the buyer approves | SAME | FR-CK-01, FR-CK-02 | T04A01, T05A02, T07A01 |
| Waitlist offers only available places, confirms the old order cannot complete, goes in bounded waves, never over-invites; offers stay valid long enough | SAME | FR-CK-03 | T03A02, T07A02, I7, I8 |
| Retry protection and reconciliation before reassigning a place | SAME | FR-CK-04 | T03A01, T06A03 |
| Each buyer approves a separate PayPal order to the winning merchant | SAME | FR-FN-01 | fulfilled through the labelled single stand-in seller (DEP-4) because the Sandbox app lacks partner access |
| Authorization first; capture when enough have authorized; funded only on COMPLETED captures reaching the MOQ | SAME | FR-FN-02 | T04A03, T06A01, PT-09 |
| Verify webhook signatures, de-duplicate, check order or capture status | SAME | FR-FN-03 | T06A02 |
| A failed or pending capture is not paid; refill from the waitlist while the offer is valid | SAME | FR-FN-04 | T04A03, T07A02 |
| Miss the minimum: void authorizations and refund captures | SAME | FR-FN-05 | T05A03, T06A01 |
| Seller settlement depends on an approved marketplace integration; Sandbox is not production | SAME | FR-FN-06 | README and UI notices (T05A02, T09X01) |
| Synthetic rehearsal agents are labelled and prove nothing about conversion | SAME | FR-AI-03 | T08B04 |
| PayPal Orders v2 sequence: select winner, create AUTHORIZE order per buyer, approve, authorize | SAME | FR-PP-01 | T05A01 |
| The `invalid_scope` error is resolved by an end-to-end test of the full request | SAME | FR-PP-02 | S1, T00B02 |
| The idea's Sandbox results (section 9.2) | SAME | none | recorded in `docs/spike-results.md` (S2, S3); keep the two in step |
| India-only marketplaces are not PayPal-domestic; evaluate local providers | SAME | FR-PP-04 | non-goal; MVP is US payers |
| Rotate exposed Sandbox secrets | SAME | FR-PP-05 | T00A02 |
| Example walkthrough (10,000 buyers, 3,000-seat lot, a USD 500 offer) | SAME | none | illustrative only; never quoted as evidence |

### 5.1 Gaps in the idea that the design filled

1. **Lot size** is a published pool setting fixed before bids (the idea's walkthrough sets 3,000 before the auction but does not say who chooses it).
2. **Tiers** resolve at award time from the buyers who can accept each tier's price; quantity-dependent final pricing needs partial capture, which is untested.
3. **Feasibility and price-out**: selection happens before the price is known, so seated buyers whose cap is below their total are priced out and their seats refilled.
4. **Capacity across lots**: a merchant's total capacity is shared by lots awarded in published order.
5. **Pools** are operator-defined templates (D2); the fixed-window rule needs a pool to exist before entries arrive.
6. **Approval UX** is the PayPal JavaScript SDK popup with redirect fallback (INT-7).

## 6. Challenge register

Challenges named or implied by the idea text, the checklist and the sandbox report, and how the build answers each.

| Challenge | Answer | Requirement or contract | Proof |
|---|---|---|---|
| Bots, multiple agents, first-click advantage | Fixed window, no arrival priority, account-level key, disclosed limits | FR-SL-01, FR-SL-02, FR-ID-03 | PT-13, F14, F15, F17 |
| Free join means flaky buyers | MOQ, waitlist refill, bounded waves, offer expiry, optional capture buffer | FR-CK-03, FR-FN-04 | PT-08, F8, F30 |
| PayPal Login `invalid_scope` | Spike S1 tests the full request; `DEDUPE_MODE` degrades honestly | FR-PP-02, FR-ID-04 | T00B02, T03B03 |
| Marketplace approval and seller settlement are unavailable | Labelled single stand-in seller; no claims of marketplace settlement | FR-FN-06, FR-FN-07 | S3 recorded, T07A03 |
| India-domestic payments are not supported by PayPal | US payers and USD only | FR-IN-06, FR-PP-04 | F25, C-13 |
| MAP and supplier terms | Merchant attestations; sealing is not compliance | FR-AU-03 | T05B01 |
| Price changes after approval | Re-quote with a new attempt; buyer approves again | FR-IN-05 | F13 |
| Holds versus payments | Capture only after the threshold; void and refund paths; exact wording | FR-FN-02, FR-FN-05 | IT-6, PT-11 |
| Delayed payment events | Reconcile before reassigning a seat | FR-CK-04 | F1, F9, T06A03 |
| Duplicate purchases and retries | Idempotency keys where PayPal honours them; GET before void | FR-CK-04, I9 | C-03, C-10, PT-10 |
| Untrusted webhooks | Signature verification, de-duplication, confirm by GET | FR-FN-03 | F2, F3, F4 |
| A hash does not prove fair selection | Beacon seed, published commitments, signed receipts; the wording stays "auditable" | FR-SL-06, FR-SL-07 | PT-03, T09B01 |
| Quotes that differ from requirements (an extra bundle item) | Deterministic R3 plus AI flags that can only withhold | FR-AI-02, FR-AU-04 | F20, T06B02 |
| Prompt injection in buyer and merchant text | Closed schemas, no tools, no authority | FR-AI-01, FR-AI-02 | F19, F20 |
| AI must not move money | No AI-callable payment surface; Agent Toolkit kept out of the payment path | I1, I2, FR-AG-02 | PT-16 |
| Search used as a gate | Search is retrieval only; PT-14 compares award results with and without search | FR-IG-01 | PT-14 |
| Exposed secrets | Rotation, environment-only secrets, redaction, scanning | FR-PP-05, I14 | T00A02, T10A02 |
| Trademark rule in the video | Generic products everywhere | FR-HK-06 | T09B04, T10B02 |
| Trial windows for Zapier and APIMatic | Start dates fixed in the plan; the product works without them | decisions.md INT-2, INT-4 | T08B03, T10A04 |
| Two members cannot cover the full scope at the planned sizes | Computed capacity check, velocity log, owner decision rule | implementation-plan.md section 4 | gates IG-2 and IG-4 |

