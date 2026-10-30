# FairPool: Group Buying Where Merchants Compete for the Group

*The idea document for FairPool. It is self-contained: someone who reads only this file should understand the problem, the product, what is built and tested, what is not, and what is still open. Last revised October 25, 2026. Sandbox results are from October 20, 2026.*

---

## 1. At a glance

FairPool lets many people who want the same product join a shared **pool** for free, within a fixed time window. When the window closes, a published rule decides who gets a place. Merchants then compete in a **sealed reverse auction** to fulfil that demand at the lowest fair price. Each selected buyer approves their own PayPal payment for the exact final amount. The order is funded only when enough real PayPal payments are completed to meet the merchant's minimum. If the minimum is not reached, every approved amount is released or refunded.

FairPool is built for the **PayPal AI Hackathon** ("Build What's Next with PayPal and AI"), which requires a project that meaningfully uses both PayPal and AI. Submissions close **Thursday, November 12, 2026, 12:00 pm Pacific** (November 13, 1:30 am IST). The project runs entirely in PayPal's free **Sandbox**. No real money moves.

## 2. The problem

### 2.1 Buyers cannot reach volume prices alone

Businesses often get lower unit prices by committing to larger quantities. An individual buyer wanting one unit cannot make that commitment, so they pay the retail price. Many people wanting the same product would together be a large, attractive order, but they have no way to find each other, agree on terms, and buy together safely.

### 2.2 Merchants cannot see that demand

A merchant with spare stock or a bulk price has no efficient way to reach thousands of small buyers who want the same thing. Sending a discount to everyone risks giving it to people who would have paid full price, and a merchant cannot be sure enough buyers will commit to justify a bulk price.

### 2.3 Limited releases reward speed and automation

When a product is scarce, the first buyers to click win. Automated tools and multiple accounts can submit faster than people can, and can take more than one place. The result is unfair access, and real buyers give up.

FairPool reduces the advantage of being first to click and limits duplicate entries from the same linked PayPal account. It does not prove that every account belongs to a different person, prevent resale, or guarantee that bots and account farms are eliminated. Those limits are stated throughout this document.

### 2.4 Payments make group buying hard to trust

Buyers do not want to be charged for something that may never happen, and merchants do not want to ship before they are paid. FairPool answers both concerns with its payment design: nothing is charged when a buyer joins, a payment hold is placed only after the merchant and exact price are known and the buyer approves, and money is taken only when the group is large enough. Those steps are described in sections 4 and 6.

## 3. Who uses FairPool

| Role | What they do | What they must trust |
|---|---|---|
| **Buyer** | Describes what they want and their maximum price, joins a pool for free, approves one PayPal payment if selected | That nothing is charged until they approve, and that the total never exceeds their limit |
| **Buyer's AI assistant** | Acts for the buyer through a documented agent interface (directly or through an AI client) to join or check a pool | That it cannot pay. Only the buyer approves payments on PayPal |
| **Merchant** | Sees open demand for a product, submits a sealed bid per lot, and fulfils the orders of lots it wins | That bids are confidential from competitors, and that FairPool pays out only what PayPal has captured |
| **Merchant's pricing bot** | Submits structured bids through a merchant API key, using generated SDKs | The same rules as a human merchant. A bot's bid is its confirmation |
| **FairPool operator** | Runs pools, watches lots, handles exceptions and refunds | Every money movement is recorded and can be reconciled with PayPal |
| **Public auditor** | Checks that the published rules, commitments and results match | Only public, anonymised data. No personal information is shown |

## 4. Key terms

- **Pool:** a group of buyers who want the same product, in the same variant and condition, for one delivery zone, during one join window. Pools are created from published templates.
- **Entry:** one buyer's place in a pool, created from a confirmed request. One entry is one unit.
- **Confirmed request:** the buyer's requirements after the buyer has checked the structured version of what they asked for. It defines what the buyer agreed to.
- **Cap (maximum total):** the most the buyer will pay in total, including shipping and tax.
- **Lot:** a fulfilment group inside a pool. A large pool can be split into several lots, each with its own merchant, price and outcome.
- **Seat:** a place in a lot that a selected buyer can take.
- **Waitlist:** entries that were not seated in the first allocation. They are offered a seat if one becomes free.
- **Priced out:** a seated buyer whose cap is below the winning merchant's total for them. Their seat is offered to the next person on the waitlist.
- **Bid:** a merchant's sealed offer for a lot, with product, price tiers, minimum order quantity, delivery and return terms.
- **Award:** the winning bid for a lot, frozen as a record that cannot be changed.
- **MOQ (minimum order quantity):** the number of completed payments a lot needs before the merchant is committed to fulfil it.
- **Offer:** the invitation to a selected buyer to approve their payment within a stated time.
- **Authorization (hold):** PayPal's reservation of the buyer's money for the exact amount. It is not a completed payment.
- **Capture:** the completed payment, taken from an authorization. Only a completed capture counts as paid.
- **Void:** releasing an authorization that was never captured. The hold is removed.
- **Refund:** returning a captured payment.
- **Funded lot:** a lot whose completed captures from different buyers have reached its MOQ.
- **Commitment:** a fingerprint of one entry, published when the pool closes, so entries cannot be changed afterwards.
- **Receipt:** a signed record given to each buyer showing their entry was received.
- **Seed:** a random value from a public randomness source that is announced after the pool closes. It decides the order of entries.
- **Stand-in seller:** a single sandbox seller account that receives payments in the demonstration on behalf of the winning merchant. See section 9.

## 5. How it works

### 5.1 Joining: free, with a clear limit

A buyer describes what they want in plain language, for example:

> *"I want a 27-inch 4K monitor delivered to New York by Friday. My maximum total is $600."*

An AI assistant turns this into structured fields: exact product and variant, condition, delivery region, required-by date, maximum total, firm requirements and preferences. It asks a question when something important is unclear, such as whether "by Friday" means the delivery date or the order date. The buyer checks the structured version and confirms it. Only then does the request become an entry.

Joining is free. It places no PayPal hold and does not reserve money.

If PayPal Login is used, the buyer connects their PayPal account first and sees a disclosure of what FairPool asks for. FairPool then allows one entry per linked PayPal account per pool. This is **account-level** duplicate control. It does not establish one person per account.

### 5.2 Allocation: a published rule, not a race

Each pool has a fixed join window of a few minutes in the demonstration and typically 15 to 30 minutes in a real pool. Every eligible entry received before the window closes is considered under the same rule. Arrival time gives no advantage.

When the window closes, FairPool does four things, in this order:

1. **Freezes the entry list.** Each entry's commitment is calculated and published, together with the count. Entries cannot be changed after this point.
2. **Waits for the public seed.** The seed comes from a public randomness source announced after the close. FairPool cannot choose it after seeing the entries.
3. **Orders the entries.** Each entry's position is calculated from its commitment and the seed. Anyone with the published list and seed can recompute the same order.
4. **Fills the lots.** Positions are assigned to lots in the published order. Entries beyond the seats of all lots form an ordered waitlist.

Each buyer receives a receipt, so they can check that their own entry was included.

The claim is **auditable under published rules**. It is not "provably fair". An outside auditor can check the order, but cannot check that no eligible entry was left out. A buyer can check their own entry only.

### 5.3 Lots: large demand, split on purpose

A pool of 10,000 requests might become a first lot of 3,000 seats and a waitlist. The lot plan (how many lots, how many seats, and the minimum size for a lot to run) is published before bids are accepted. Merchants bid on lots that already exist. A merchant's capacity does not change the lot plan.

Each lot is independent. Two lots in the same pool can end with different winning merchants and different prices. Participants are told this before allocation. No buyer holds more than one active offer in the same pool. A request is never split in a way that silently changes the product, condition, delivery terms or price the buyer sees.

If shipping or tax differs by region, buyers are grouped by delivery zone and each buyer's exact total is calculated separately. A single estimated price is never shown as the final price for everyone.

### 5.4 Bidding: sealed, structured, and checked

After the window closes, eligible merchants bid on each lot. A bid includes:

- the exact product, variant, condition and bundle contents;
- capacity, the target quantity, the minimum order quantity, and up to three price tiers (a lower price applies when enough buyers can accept it);
- the item price and how shipping and tax are calculated for each buyer;
- delivery time, return terms, and how long the offer stays valid, including the checkout and waitlist period;
- evidence of stock, which the merchant declares. FairPool does not verify it.

Bids are sealed. Competing merchants cannot see each other's prices. Sealing protects confidentiality only. It is not compliance with a manufacturer's Minimum Advertised Price (MAP) policy, which each merchant must confirm separately.

A merchant can paste a free-text quote. An AI proposes the structured fields from it. The merchant checks and confirms them. Only confirmed fields are used.

Deterministic rules then decide. A bid is rejected if it misses the deadline, does not match the lot's product and condition, lacks enough capacity, has delivery or return terms worse than the published minimum, or cannot cover the lot. Tier prices are applied to the buyers who can afford them. A bid that cannot fill its minimum is not feasible. Among feasible bids, the lowest qualifying delivered price wins, using a published tie-break.

The AI can add a warning, or hold a bid for correction if it finds a serious mismatch such as an extra item in the bundle. It can never qualify a bid that the rules reject, change a bid's terms, or accept a variation for a buyer.

### 5.5 Checkout: each buyer approves their own payment

The winning merchant, exact product and condition, delivery and return terms, and the buyer's own total are shown. The total cannot exceed the buyer's cap. The buyer then has a stated period, for example 15 minutes, to approve.

Approval happens in PayPal's approval step, through PayPal's JavaScript SDK popup where it works, or on PayPal's own approval page as a fallback. Approval creates an `AUTHORIZE` order in PayPal for that buyer, addressed to the winning merchant, for exactly the amount shown. PayPal places a hold for that amount only after the buyer approves. The unused part of the cap is never held.

When a buyer approves, FairPool's server fetches the order from PayPal and checks the amount, currency, payee, payer country and duplicate-entry rules before it authorizes. Nothing is captured in the browser, and the browser never sends an amount.

If a buyer does not approve in time, or declines, their place is offered to the next eligible person on the waitlist. Waves are bounded, so FairPool never asks more people to pay than the lot can fulfil. A place is released only after FairPool confirms that the old order can no longer complete.

If a price changes after approval, a new order is created and the buyer must approve again. The old order is abandoned.

### 5.6 Funding: capture only when the group is real

Once enough buyers have authorized to meet the MOQ, FairPool captures their authorizations. A lot is **funded** only when PayPal confirms enough **completed** captures from different buyers to reach the MOQ. Pending or declined captures do not count. Duplicate events do not count twice.

FairPool tells the merchant the lot is funded only after this confirmation, and reports the actual number of completed payments.

### 5.7 Failure: money goes back

If a lot misses its minimum by its deadline, FairPool stops new offers and authorizations. It voids every authorization that was not captured, and refunds every completed capture. It waits for pending captures and refunds any that complete late. The lot closes as failed only when the net amount paid is zero.

A void removes a hold. How quickly a bank shows that is up to the bank. FairPool says so in the buyer's messages.

### 5.8 Fulfilment: after funding

For a funded lot, the merchant sees the shipping list for the buyers who paid. Addresses are shown only after the lot is funded. The merchant can mark each order shipped with a tracking number. Where PayPal's shipment tracking is available, FairPool sends the tracking number to PayPal too.

The merchant can also check the lot's PayPal payments against FairPool's verification list, either in FairPool or with an AI client connected to PayPal's read-only tools.

## 6. What users see

These are the screens the product is designed around. Labels and notices are fixed text, and every fallback, simulation and sandbox element is labelled on the screen where it appears.

**Buyer, three tabs**

1. **Discover and join.** A prompt box ("What are you looking for and what is your maximum price?") and a grid of open pools. Every pool card carries the badge: **"$0 to join. No hold until a merchant meets your price and you approve."**
2. **My pools.** Pools waiting for bids; waitlist status with position ("Waitlisted, position #142"); and offers that need action, with a live countdown and the PayPal approval button.
3. **Orders.** Completed and failed orders with receipts: amounts, PayPal capture reference, winning merchant, and return terms.

**Merchant, four tabs**

1. **Demand board.** A live list of lots open for bids, with the product, variant, condition, bundle, seats, zone, delivery terms, minimum return period and bid deadline. The merchant can search it, paste a quote, or fill in the bid form.
2. **Active bids.** Pending bids; for lots the merchant won, a live tracker showing holds placed against the MOQ, then completed payments, refills and time left; and lost or failed bids with reasons.
3. **Fulfilment.** Funded lots, the shipping list, shipping marks and tracking numbers, and the verification list.
4. **Developer.** Merchant API keys (shown once), their permissions and rate limits, and links to the generated SDKs and developer documentation.

**Public audit page.** The published rules and their fingerprint, the commitment list and root, the seed and its source, the lot boundaries, the award summary, and a "verify my place" check that recomputes a buyer's position in the browser from their receipt.

## 7. Worked example

*This example is illustrative. It is not evidence that ten merchants will bid, or that this price exists in the market.*

1. **Pool.** 10,000 buyers request the same product in the same condition for one zone. The first lot has 3,000 seats. The rest form the waitlist.
2. **Auction.** Ten merchants bid. The winner offers $500 per unit for 1,800 to 3,000 units. The $500 is the final amount for these buyers, within their caps.
3. **Approval.** Each selected buyer gets a separate PayPal order for $500 addressed to the winner. A buyer with a $600 cap approves. PayPal holds $500. The remaining $100 is never held.
4. **Funding.** FairPool captures the approvals. If 1,800 or more captures complete, the merchant is told the lot is funded, with the actual count. If not, every approval is voided or refunded and the net amount paid is zero.

## 8. Using AI, and where it stops

AI is used at the edges of the product: understanding requests, reading quotes, flagging mismatches, and writing simulation text. It is never the decision-maker.

| Task | What the AI does | What decides |
|---|---|---|
| Buyer request | Proposes structured fields and asks questions | The buyer confirms; rules check every field |
| Merchant quote | Proposes structured fields from pasted text | The merchant confirms |
| Offer check | Flags serious mismatches, which can hold a bid | Deterministic rules; the AI cannot qualify or change a bid |
| Retrieval | Helps find candidate pools and lots from public descriptions | Retrieval is a convenience, not a gate. Buyer requests are never indexed |
| Simulation | Writes varied buyer and merchant text for the demonstration | Numbers and behaviour come from a seeded generator, and every output is labelled SIMULATED |

AI tools never create, authorize, capture, void or refund a PayPal payment. No AI client, agent interface or AI-facing action in FairPool can move money.

Accuracy of the AI parts is measured on labelled sets of messages and quotes, and the measured results are published with the project.

## 9. PayPal: what is used, what is verified, what is not

### 9.1 How PayPal is used

- **Orders v2:** one `AUTHORIZE` order per buyer, addressed to the winning merchant.
- **Authorizations and captures:** a hold at approval, a capture once the group is large enough, a void when a lot fails, and refunds for captured payments.
- **JavaScript SDK v6:** the approval popup, with PayPal's own approval page as a fallback.
- **Webhooks and reconciliation:** PayPal notifications are checked for signature and duplicates, and FairPool always confirms a status by fetching it from PayPal.
- **Read-only verification:** a merchant can check a funded lot's payments through PayPal's MCP server or FairPool's verification endpoint.
- **Shipment tracking:** tracking numbers can be submitted to PayPal for captured payments.

### 9.2 Verified in the Sandbox (October 20, 2026)

All tests used PayPal's free Sandbox at USD 1.00, and each captured payment was fully refunded.

| Capability | Result |
|---|---|
| Create an `AUTHORIZE` order addressed to a seller | Passed |
| Retrieve the order after buyer approval (status APPROVED, US payer, correct amount) | Passed |
| Authorize an approved order | Passed. The response reads COMPLETED in the test log; the authorization's own status is being confirmed |
| Repeat authorize with the same request ID | Passed. Same result |
| Capture an authorization | Passed (COMPLETED) |
| Repeat capture with the same request ID | Passed. One capture only |
| Full refund, and a repeat with the same request ID | Passed (COMPLETED) |
| Void an authorization | Passed (VOIDED) |
| Repeat a void, with or without a request ID | Returns 422. FairPool therefore checks the status before voiding |
| Capture after a void | Rejected with 422 AUTHORIZATION_VOIDED |
| Authorize or capture before buyer approval | Rejected with ORDER_NOT_APPROVED; nothing is created |
| Partner onboarding of a second seller | Failed: 403 NOT_AUTHORIZED. The app has no partner permission |
| Authorize to a second seller with the partner assertion | Failed: 401 invalid_subject |
| Platform fee on a purchase | Failed: 422 UNSUPPORTED_PAYMENT_INSTRUCTION |
| Create an order addressed to a second business account (creation only) | Passed. Approval and authorization to that account are not yet tested |

### 9.3 Not yet verified

- **PayPal Login and the account ID.** The account-ID scope has returned `invalid_scope` and has not yet returned an ID. Until it works, duplicate control moves to checkout (section 9.5).
- **The popup approval** in the JavaScript SDK v6 has not been tested.
- **Webhook delivery and signature checks** have not been tested.
- **Buyer pool.** Several distinct sandbox buyers must approve before the live demonstration; only one has been used so far.
- **Approval and authorization to a second sandbox business account** (by payee email) are not yet tested.
- **Shipment tracking** and **PayPal MCP read-only access** are not yet tested.

### 9.4 What the results mean

- **Authorization-first checkout works** in the Sandbox, so the design holds money only until the group is confirmed.
- **Several sellers cannot be paid directly in this app**, because marketplace permission is not available. The demonstration therefore uses a single, clearly labelled stand-in seller. The merchant named on each lot is shown; the money is received by the stand-in seller. This is a demonstration limit, not a settlement claim.
- **Platform fees are unavailable.** Revenue is described as a planned merchant-paid success fee, not as something the demonstration collects.
- **Voids are checked before they are repeated**, which is handled inside FairPool without changing what buyers see.

### 9.5 Fallbacks

If a test that a feature depends on fails, FairPool uses a labelled fallback rather than claiming the feature works:

- No account-ID check at entry: duplicate control happens at checkout, where the paying account is checked against others in the same pool.
- No direct multi-seller payment: the single stand-in seller, labelled wherever it appears.
- No embedded popup: PayPal's approval page.
- No Zapier bridge or PayPal MCP access: the FairPool agent interface and FairPool's own verification endpoint are used instead.

### 9.6 Regional limits

PayPal does not allow domestic payments from Indian customers to Indian recipients. FairPool supports US payers in US dollars for the demonstration and does not describe PayPal as the domestic checkout for an India-only marketplace. Domestic Indian sales would need local payment providers and their own evaluation.

## 10. Integrations

Each integration is listed with its status. "Planned" means it is designed and its integration test is scheduled. "Conditional" means it depends on a test or a trial.

| Integration | Purpose in FairPool | Status |
|---|---|---|
| PayPal Orders v2, authorize, capture, void, refund, webhooks | All payments | Core. Partly verified (section 9.2) |
| PayPal JavaScript SDK v6 | Approval popup | Planned. Conditional on a test |
| PayPal MCP server | Read-only verification by a merchant's AI client | Conditional on a read-only test |
| PayPal shipment tracking | Tracking numbers for captured payments | Conditional on a test |
| PayPal Agent Toolkit | Development aid only | Not used at runtime. It cannot express FairPool's payment rules |
| Elastic | Hybrid search over public pool and lot descriptions | Conditional on a test; a database search is the fallback |
| Zapier MCP (managed mode) | Lets a buyer's own AI client join or leave a pool through four locked actions | Conditional on a test and a trial |
| FairPool MCP server | The same four agent actions, served by FairPool, with no payment actions | Planned |
| APIMatic | Generates Python and TypeScript merchant SDKs and a developer portal | Conditional on a test and a trial |
| Anthropic Claude | Request parsing, quote parsing, offer checks, simulation text | Planned |
| Render | Hosting | Planned |

## 11. Claims

**We claim:**

- Joining is free, and no PayPal hold exists before a buyer approves a specific amount.
- Selection follows a published rule with a public seed and per-buyer receipts, and it is **auditable under published rules**.
- One entry per linked PayPal account per pool, where the account-ID check works, and account-level duplicate control at checkout otherwise.
- A lot is funded only when completed PayPal captures reach its minimum.
- Failed lots are voided or refunded, with net zero.
- Every fallback and simulation is labelled.

**We do not claim:**

- that selection is provably or cryptographically fair;
- one person, one entry, or that bots are eliminated;
- that money is "safe", that buyers "will not be charged", or that savings are guaranteed;
- wholesale prices, or that merchants will compete on price;
- MAP compliance, which sealing does not provide;
- production readiness, marketplace approval, or merchant settlement;
- that the AI verifies or approves payments;
- that a simulation proves buyer conversion, merchant participation or price reductions;
- anything about products, brands or prices that the demonstration does not use.

## 12. Scope

**In scope for the hackathon:** one unit per entry, US dollars, US payers, one delivery zone per pool, lot plans fixed before bids, sealed bids with confirmed fields, individual approvals, funding by completed captures, void and refund on failure, buyer and merchant screens, the public audit page, the agent interface, and labelled simulation at scale.

**Out of scope:** live payments, marketplace approval, multi-seller settlement, platform fees, split-lot combinatorial auctions, multiple units per entry, multiple currencies, a real tax engine, delivery tracking beyond recording, India-domestic checkout, emergent pools created from free text, and any claim about real-world volume.

**Roadmap:** marketplace approval and direct merchant settlement; quantity-dependent price tiers after partial capture is verified; emergent pools; multi-currency; a merchant success fee once platform fees are available; local payment routes for other countries.

## 13. Demonstration

The demonstration uses only generic product names on screen and in audio, because the hackathon rules forbid third-party trademarks in the video. It runs a live Sandbox pool with several real sandbox buyers and two lots, shows a headless join through an AI client, a merchant bid through an SDK, approvals, funding, a refill and a failure path, and a labelled simulation at 10,000 entries. The video is under three minutes.

## 14. Open decisions and open questions

These items are not settled. Each is listed with its owner and the test that will decide it.

- **Confirmed design choices** (assumed until the team confirms them): Python and FastAPI for the backend, React for the frontend, operator-created pool templates, a public randomness source for the seed, and one-unit entries. Owner: the team, at the start of build.
- **Duplicate control:** decided by the PayPal Login test.
- **Approval popup:** decided by the JavaScript SDK test.
- **Authorization status reading:** the authorization's own status is being confirmed, so the design does not yet depend on the order's status.
- **Second-seller approval:** decided by a test that approves and authorizes an order addressed by email to a second sandbox account. If it passes, the owner decides whether the demonstration uses it.
- **Trials and plans:** the Zapier and APIMatic trials, and the Elastic trial, must be active when the demonstration is recorded. Their start dates are fixed in the build plan.
- **Idea-level claims that change if tests fail:** the stand-in seller, the popup, the agent bridge and the verification tools each have a labelled fallback in section 9.5.

## 15. Revision notes

**October 25, 2026 revision.**

- Added a plain-language summary, the problem in more detail, users and roles, key terms, and the user screens.
- Replaced the sandbox summary with the October 20 results and their meaning.
- Added the integrations and their status, including those proposed in the PayPal planning notes. Each is conditional on a test or a trial where needed.
- Recorded corrections to the planning notes, listed below.
- Removed the revision-specific scope list and folded its contents into sections 5, 9 and 12.

**Corrections made to the planning notes:**

1. The hackathon requires meaningful use of PayPal and AI. It does not require agents to transact on their own. FairPool keeps every payment with the buyer's approval.
2. The first draft used a brand-named product, a "PS6", and an invented pool size of $1.5 million. These are replaced by generic products and real Sandbox amounts.
3. "Pay only if your price is met" was imprecise: PayPal places a hold at approval. The badge now reads "$0 to join. No hold until a merchant meets your price and you approve."
4. "Funds legally captured" is not a claim FairPool makes. The fulfilment screen says "Funded: PayPal captures completed."
5. A live "payments captured" bar shows holds against the MOQ first, then captures once the capture stage starts. It does not show captures before they happen.
6. The JavaScript SDK documentation used for v6 is the current version. Older patterns are not used.
7. Elastic can reduce wrong matches but cannot enforce requirements. FairPool's rules enforce them, and search is never a gate.
8. The Zapier bridge uses four locked actions in managed mode. It does not use Zapier's wider app catalogue.
9. The merchant developer API uses ten operations, not the single quote-submission endpoint named in the planning notes.

**Changes from the first draft that the owner should review:**

- Duplicate control is described as depending on PayPal Login, with a checkout-stage fallback.
- Lot plans are fixed before bidding.
- Merchant quotes are parsed by AI and confirmed by the merchant.
- Bids keep both target quantity and an evidence field, which FairPool does not verify.
- Approval happens in a PayPal popup, with the redirect as a fallback.
- The single stand-in seller is the demonstration's payment route, because marketplace permission is not available.

These changes are design decisions taken to match the verified results. Only the first two of the list above were discussed in the earlier approval round; the rest are recorded here for the owner to confirm.
