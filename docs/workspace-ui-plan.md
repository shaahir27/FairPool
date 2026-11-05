# Buyer, merchant and administration workspace plan

Reviewed 5 November 2026. Scope: T09B04 usability work on the existing T07B01,
T08B01, T08B02 and T08A02 screens. Owner-authorized CR-10 adds commerce context to existing read models and a stored
merchant profile read. No payment behavior, dependency or landing-page change is included.

## Direction and evidence

These are working commerce interfaces. The visual identity stays with the current
FairPool logo, fonts and semantic color tokens; a palette replacement would repeat
the earlier problem rather than solve the workflow. Use a compact navigation rail,
a clear page title, task controls, then actual records. Reserve strong color for the
current destination, primary action and meaningful status. Avoid decorative KPI
cards, invented activity, marketing heroes and repeated explanatory cards.

The research informs patterns, not copied page designs:

- [Carbon tables](https://carbondesignsystem.com/components/data-table/usage/): put
  search and actions with the records they affect; batch actions require an explicit
  selection. Use tables for comparisons and stacked labeled rows on narrow screens.
- [Shopify App Home](https://shopify.dev/docs/apps/build/app-home): merchant tools
  revolve around familiar resource lists, forms and clear navigation. Borrow the
  task model; adding an embedded-Shopify component framework is unnecessary here.
- [Baymard form effort](https://baymard.com/research-articles/checkout-flow-average-form-fields)
  and [required fields](https://baymard.com/research-articles/required-optional-form-fields):
  reduce perceived effort, group related inputs and mark optional fields explicitly.
  Price tiers are related quantity/price pairs; unrelated long forms stay vertical.

Audit correction: fulfillment, merchant profile and admin already contain real
controls in the current code. The remaining JSON editor is the merchant bid form.
Developer examples, signed proofs, verification manifests and audit downloads are
legitimate technical artifacts, not customer-facing forms to remove indiscriminately.

## Screen-by-screen decisions, in implementation order

### 1. Merchant navigation — all `/merchant/*` routes

**Job:** know where to find demand, bids, shipments and integration tools. The old
horizontal tab shell differs from the buyer/admin workspace and crowds laptop and
mobile headers. Reuse the established rail and mobile primary navigation, with an
explicit Merchant identity, four primary destinations and Profile in Account.
Keep route guards, sign-out error handling and Sandbox disclosure. Verify current
route highlighting, keyboard navigation, 44px targets and wrapping at 360px.

### 2. Demand Board — `/merchant/demand`

**Job:** decide which open lot can be supplied. Each lot presents product, variant,
condition, seats/minimum, destination, delivery/return requirements and deadline in
that order. Keep one search over loaded records; no request per character. Open the
bid editor immediately under the selected lot, not below every result. Permit an
explicit close and preserve keyboard focus. Loading, zero demand, no search match
and failed refresh must be distinct. Deadline authority stays with server data.

### 3. Prepare, review and confirm a bid — within Demand Board

**Job:** submit an accurate sealed offer without programming. Replace editable JSON
with labeled fields: product/condition, included items, available/target/minimum
quantity, one to three delivered-price tiers, delivery days, return days, validity
and evidence. Keep optional aggregate capacity and evidence URL accessible. State
that prices include tax and shipping. Currency inputs use dollars and preserve
integer cents in the payload; blank/parser-null values remain visibly incomplete.
Quote parsing is an optional shortcut, never the only path. Show unresolved questions
as readable text. Do not invent omitted proposal values or silently discard fields.
Review is a separate human-readable step; only Save and confirm sends the existing
PUT and confirmation POST with their existing idempotency keys. Server validation
remains authoritative. Preserve saved-but-unconfirmed recovery and the sealed receipt.

### 4. Active Bids — `/merchant/bids`

**Job:** see what needs attention and track confirmed offers. Put state groups and
counts before records; allow focusing a group without changing server eligibility.
Lead with product, status and revision, then quantities/prices and next action.
Show rejection explanation before its diagnostic code. Keep raw references and
flags available as supporting evidence rather than the page's visual headline.
Checkout tracking stays attached to its bid. Distinguish no bids from a failed load.

### 5. Checkout tracker — within Active Bids

**Job:** understand funding progress without mistaking authorization for payment.
Use the existing offered/authorized/captured figures with textual labels, displayed
deadline and factual next step. Never synthesize a paid percentage from order status.
Keep stale/error feedback and read-only behavior. On mobile stack facts and preserve
their labels; no animated numbers or fake progress.

### 6. Fulfillment — `/merchant/fulfillment`

**Job:** ship funded orders and record tracking accurately. Keep lot selection first,
then funded order queue, shipping input, selection summary and explicit confirmation.
Carrier and tracking belong to the same row; batch actions show the selected count.
Separate shipping work from read-only verification/export tools. Preserve exact CSV
bytes, per-row partial results, the 100-order limit, funded-only address access and
GET-confirmed provider facts. Never expose addresses in public proofs. Narrow screens
need labeled stacked rows and a visible action area, not squeezed desktop columns.

### 7. Merchant profile — `/merchant/profile`

**Job:** identify the business and confirm supply obligations. Group business name,
payment destination and the three attestations; use short explanations alongside
existing checkboxes. Keep optional payee semantics: a blank unedited field must not
erase stored values. Show actual onboarding and fallback status, not a fabricated
Verified merchant badge. Save feedback should remain near the action.

### 8. Developer API — `/merchant/developer`

**Job:** connect a merchant's software safely. Separate key creation/permissions,
existing keys/revocation and quickstart documentation. Code and JSON are appropriate
here, behind clear headings. Preserve show-once credentials, copy feedback and scope
boundaries. Do not place a secret in a URL or persist it in browser storage. Existing
keys need readable names, creation/status and explicit revoke action.

### 9. Discover — `/discover`

**Job:** find an appropriate pool or request one. Preserve the compact product search
and existing catalogue, with one search control and no explanatory hero above it.
Product, condition, participation and closing state should be scannable. Keep request
creation secondary to shopping, with clear success/recovery. Do not change `/`.

### 10. My Pools — `/my-pools`

**Job:** follow participation and know the next action immediately. Use one product-led
feed of Current pools, with Past entries as a separate view and one search. Offers
ready to review appear first and link to the existing checkout. Do not stack Action
required, Pending and Waitlist sections. Each card shows a readable state, one next
action, and a deadline only when applicable. Keep raw references in Entry details.
Cancelled and completed pools without an order also move to history. Simulation
and fallback labels remain visible on the affected records. Terminal orders are
retained in owner-only history; agent API live-offer semantics
stay unchanged. Never show Join/Approve before membership and offer state are known.

### 11. Orders - `/orders`

**Job:** identify the purchase and actual payment/delivery outcome. Use one named
purchase feed with product, merchant, total, terms and a primary order action. Search
and a Payment status select filter loaded records without stacked outcome groups.
Capture references and internal states belong in a details disclosure. An entry
receipt is labeled explicitly and never presented as proof of payment. Loading does
not imply an empty history; failures retain a retry.

### 12. Order details and checkout — `/orders/:id`, `/offers/:id`

**Job:** understand an order or deliberately approve the final price. Keep product,
merchant, exact total and delivery terms above payment action. Show payment, shipment
and refund facts separately. Retain approval/authorization/capture distinctions,
expiry and fallback disclosures. Never turn technical state into a false Paid claim.
The existing receipt/download work is retained; no new payment or discount logic.

### 13. Pool details and entry receipt — `/pools/:id`

**Job:** inspect the pool, understand one's place and retain entry evidence. Product
and stage information come first, membership action second, receipt/proof lower down.
Keep the entry receipt explicitly different from a purchase invoice. Technical hashes
and verification belong in supporting disclosures, not the primary transaction view.
Preserve the existing branded PDF, embedded font and print recovery.

### 14. Buyer settings — `/settings/paypal`, `/settings/addresses`, `/settings/agents`

**Job:** manage linked identity, reusable shipping details and delegated access.
Use a consistent narrow form measure and section rhythm rather than a dashboard.
Separate linked-identity status from payment permissions. Address cards show recipient,
address and default with explicit edit/delete actions. Delegation forms explain scope
and expiry, show credentials once and distinguish revoke from sign-out. Keep account
and checkout behavior unchanged; do not claim one verified human per PayPal account.

### 15. Admin overview — `/ops`

**Job:** triage actual reported problems. Keep the truthful alert summary and sort
attention through existing severities. Put Inspect lot or Review recovery alongside
each actionable alert; stop making the operator copy IDs between pages. No green
system-health claim from an empty alert response. Technical event codes remain useful
secondary context for operators. Refresh failures must not erase known alerts.

### 16. Lot operations — `/ops/lots`

**Job:** inspect one known lot before intervention. Retain UUID lookup and affected-lot
shortcuts; the backend has no all-lots browser to invent. Lead the result with state,
seats, award and payment mode; keep identifiers copyable. Collapse redundant static
guidance into a brief inline note. Preserve backend whitelist, abort eligibility,
explicit confirmation, Escape recovery and focus restoration.

### 17. Recovery — `/ops/recovery`

**Job:** recover a failed event or queue an order check. Keep failed events and
reconciliation as distinct operations, with event type/time/verification/attempt and
per-row retry. Explain that requeue is not payment success. Retain in-flight button
protection and server results. Mobile must retain action labels and row context.

### 18. Audit trail — `/ops/audit`

**Job:** retrieve recorded evidence. Present the existing export controls with the
format and read-only explanation close to Download; remove the duplicate explanatory
side panel. JSON is appropriate for an audit export. Do not invent customer invoices
or imply exporting changes a payment.

### 19. Sandbox controls — `/ops/sandbox`

**Job:** deliberately exercise known demo failure cases. Keep this separate from
normal admin navigation, with persistent Sandbox wording, scoped inputs, explicit
actions and results. Never create live-host controls or broaden payment powers.

## Shared acceptance and verification

- Landing page, auth/role guards, API contracts and payment state rules remain intact.
- No raw JSON is needed to prepare a merchant bid; manual and parser-assisted paths
  both reach review and explicit confirmation. Test exact submitted fields and cents.
- Controls are labeled, optional fields marked, focused state visible; mobile navigation
  and forms fit 360px without relying on hover. Preserve reduced-motion preferences.
- Use existing loading/error/empty patterns; no fixed artificial loading delay, new
  animation dependency, per-keystroke request or extra data fetch for decoration.
- Run focused flow tests, complete frontend tests, type/build/lint, repository verification
  and Graphify update. Record unavailable browser inspection honestly rather than claim
  screenshot approval. Computer-use inspection was blocked by URL-policy verification.

This is the complete screen inventory and decision plan, not a claim that every
screen has already been redesigned. Implementation and verification status are recorded
with the delivered change.

## Verification status

Implementation is on `b/T09B04-workspace-ux`. `make verify` exited 0 on 5 November
2026: 1,207 backend tests and 253 frontend tests passed; domain coverage is 94.59%.
Production build, lint/type checks, import boundaries, generated merchant API check,
documentation validation and secret scans pass. Documentation has two existing
warnings about the intentionally invalid example route. Independent source review
found no remaining blocker after the history and simulation-label corrections.

Regression coverage includes `my-pools.test.tsx` (one feed, search, review handoff,
terminal history and simulation disclosure), `orders.test.tsx` (named purchases and
payment truth), `buyer.shell.test.tsx` (role navigation and sign out),
`settings.pages.test.tsx` (confirmed revocation, focus restoration and shared account
state), `merchant.console.test.tsx` / `merchant.bid-fields.test.tsx` (typed bid input,
integer cents and stored profile), and the owner-scoped checkout/profile/ops API tests.

Graphify AST update completed; the optional SQL parser is unavailable. Markdown
changes were reviewed directly and validated, not semantically rebuilt by Graphify.
Desktop browser inspection was blocked by URL-policy verification; no visual approval
or Render deployment is claimed. T09B04 stays IN PROGRESS pending visual acceptance.
Landing and payment execution remain outside this change. No new dependency was added.
