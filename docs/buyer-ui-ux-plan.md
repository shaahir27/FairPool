# FairPool buyer experience: design and implementation plan

Prepared 9 November 2026 for the PayPal AI Hackathon. Task: owner-requested
buyer follow-up to T09B04. Branch: `b/T09B04-buyer-experience`, from `main`.
This document precedes implementation. Delivery evidence is recorded at the end.

## 1. Product understanding

FairPool aggregates individual demand for one exact product into a fixed-window
pool. A buyer confirms requirements and a maximum **delivered total**, then records
one free entry. Joining does not buy the product, reserve stock, place a hold or
guarantee a seat. Arrival speed provides no priority in the published draw.

After close, frozen commitments and a public seed determine allocation. The pool
is divided into predefined lots; merchants submit sealed bids against those lots.
Deterministic rules check product, capacity, delivery, returns, deadlines, affordability
and AI blocking flags. The qualifying award determines the price. Lots can have
different merchants, prices and outcomes. A waitlist is ordered, conditional access.

The buyer's maximum is a ceiling, not a displayed selling price. AI translates
requests and flags mismatches; it does not allocate seats, promise a deal, accept
changed terms or move money. The buyer confirms AI proposals before participation.

In the approval flow selected by the owner for this redesign, the buyer reviews
the merchant, exact total, delivery and returns, then approves through PayPal.
The server checks the provider order and creates the hold. Approval and a hold
are not payment. Only a confirmed COMPLETED capture counts as paid; only enough
distinct paid buyers make a lot funded. Failure requires releasing uncaptured
holds and refunding captures, including late captures, before failure closes.

This solves three linked problems: individual buyers cannot assemble volume
demand, merchants cannot reliably see it, and speed-based releases reward fast
clicking. The product's differentiation is a readable price ceiling, published
allocation evidence and an individual payment lifecycle that buyers can follow.
Savings, stock availability, unique humans and production settlement are not
guaranteed. Sandbox status and the stand-in seller remain explicit.

### Approved evolution of the idea

`fairpool-idea.md` describes approval after the award. DEP-4 and `vault-charge.md`
later adopt saved PayPal permission as primary: explicit consent at entry, an
ACTIVE permission at close, then a server charge within the confirmed cap.
That mode has no authorization hold or offer approval window. PayPal's save
screen shows no amount, and FairPool enforces the cap.

**Owner decision, this session:** improve the existing approval flow first;
document the saved-permission gap and its API work. This pass does not select a
different backend payment mode or implement consent, vault setup or money movement.
Mode-dependent work below remains a separate contract change, not an implicit
approval to alter frozen contracts.

## 2. Evidence and coverage

Navigation began with the existing 8,869-node Graphify graph. Primary references:
`00-index.md`, `registry.md`, root `AGENTS.md`, `implementation-plan.md`,
`team-split.md`, `progress.md`, `fairpool-idea.md`, `product-spec.md`,
`decisions.md`, `workspace-ui-plan.md`, `contracts/api.md` and
`contracts/vault-charge.md`.

Buyer source review covers the route shell, discovery and intake, pool details,
entry and receipt presentation, My Pools, Orders, shared read cache and prefetch,
status/amount/date formatting, palette, and their regression tests. Backend
tracing covers pool listing/detail projection, entry read projection and checkout
read schemas/routes. The wider architecture is mapped through the graph and
contracts: identity, intake/search, allocation, auction, checkout, ledger,
fulfillment, notification, audit, simulation and agent boundaries.

This is a deep buyer-journey review, not a claim that every backend file has been
audited line by line or every PayPal failure has been retested. Merchant and ops
implementations are context and separate future design passes.

### Research and design references

Research informs the particular decisions below; it is not a license to clone a
site or import its branding into demo data. Consulted 9 November 2026:

| Reference | Application to FairPool |
|---|---|
| [Baymard: information in product lists](https://baymard.com/research-articles/product-listing-information) | Put condition, variant, destination, closing time and pricing semantics beside the product so buyers can judge suitability before opening each pool. |
| [GOV.UK: check answers](https://design-system.service.gov.uk/patterns/check-answers/) | Review the structured request before commitment; preserve inputs when correcting it and make the final action explicit. |
| [GOV.UK: confirmation pages](https://design-system.service.gov.uk/patterns/confirmation-pages/) | Entry success needs its reference, what happens next and a durable record. An entry receipt must not imply payment. |
| [NN/g: progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/) | Keep hashes, identifiers and proof tools accessible beneath the buying decision. Payment limits and consequences remain visible. |
| [Carbon: empty states](https://www.carbondesignsystem.com/building-blocks/core/patterns/empty-states) | Treat first use, no filter match and failed loading as different states with useful recovery. |
| [W3C: modal dialog](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/) | Receipt inspection must contain keyboard focus, support Escape and restore focus on close. |
| [Linear: interface refresh](https://linear.app/now/behind-the-latest-design-refresh) | Use consistent headers and quieter navigation so task content leads; do not copy its issue-tracker arrangement. |

Tavily search could not access its local configuration directory; browser web
search supplied the references. The complete local Taste scripts and UI/UX Pro
Max search live under `.codex/skills/`; the `.agents/skills/` copies lack scripts.
Impeccable's context executable is unavailable; source and references supply context.
UI/UX Pro Max's broad design-system results were rejected as marketing/pharmacy
matches; its accessibility and interaction guidance remains applicable.

## 3. Design direction

Mode: **Operate**. A buyer checks this between other tasks, often on a phone in
daylight. Use a light workspace, visible labels and familiar buying controls.
Premium means confident hierarchy, clear data and precise behavior, rather than
extra decoration or extra steps.

### Direction contract

**Thesis:** the product and the buyer's next decision lead. A pool is an opportunity
with conditions, not a sale price or a guaranteed purchase.

**Own world:** retain the existing FairPool mark, self-hosted Inter, cerulean blue
and raspberry action. Pale blue chrome surrounds a white working sheet. Dark blue
ink carries the text. Color identifies action and meaningful state.

**Story:** find a suitable pool, understand the conditions, confirm a ceiling,
record the entry, follow the outcome and deliberately approve the exact offer.

**First viewport:** compact account/navigation frame; noun title and one sentence;
search and a direct request shortcut; the first product row. Product illustrations
are subordinate to names, conditions, price semantics and the closing deadline.

**Form:** Taste `framed-sheet`, seed `977748516`, with existing palette/type kept.
Its tinted frame and white sheet replace the saturated sidebar. Peer product
cards remain appropriate for comparison. No marketing hero or invented KPI row.

**Finish:** real browser checks at desktop, tablet and phone; regression tests;
documented independent review and explicit remaining limitations.

### Buyer-only tokens

Keep shared global tokens intact for landing, merchant, ops and standalone checkout.
Scope the following roles under the buyer workspace; children, including dialogs,
inherit them. Keep the brand's hue while reducing its area and saturation.

| Role | Target | Use |
|---|---|---|
| Canvas | `#F2F7FA` | Pale blue frame and page surround |
| Working sheet | `#FFFFFF` | Primary task surface |
| Card/raised surface | `#FFFFFF` / `#F3F7F9` | Product cards and quiet groupings |
| Ink | `#17364C` | Product names, amounts, primary text |
| Secondary ink | `#4B6070` | Readable metadata and help |
| Blue | `#005383` | Brand detail, links, progress |
| Primary action | `#BE2859`, hover `#A61F4B` | One next action, white label |
| Edge | `#D8E3EA` | Quiet panels; stronger field border where needed |
| Accent support | Pale blue / pale raspberry | Product illustration and meaningful action context |
| Caution/error | Existing semantic pairs | Actual caution/error, always accompanied by text |

Body copy is 14–16px, form inputs 16px, supporting copy at least 12px, page titles
24–30px. One font family for normal UI; mono is for references and signed data.
Money and changing numerals use tabular figures. Cards use one radius, controls
one smaller radius, and pills remain status marks. No resting shadows, gradients,
glass, ornamental badges, animated counters or decoration that looks like data.

## 4. Information architecture and layer-by-layer decisions

### Shared buyer frame

- Keep the three established destinations: Discover and Join, My Pools, Orders.
- Keep PayPal settings, addresses and agent access in Account, separate from shopping.
- Use the existing inbox; expose unread state without adding a new notifications page.
- Keep the shell while route code loads and preserve protected deep-link destinations.
- Keep a visible skip link on focus, clear current navigation and 44px touch targets.
- At tablet width fold the rail; on phones keep three labeled shopping destinations
  and an Account menu. Menus must support Escape and return focus.
- Keep SANDBOX visible and preserve record-specific fallback/simulation/mock labels.

### Discover: `/discover`

Question: **Which open pool fits what I need?**

1. Title and scope: Open pools; describe the number actually loaded, not the whole
   database. A failed request never reports zero availability.
2. Actions: one search/filter and a visible Make a request shortcut. The shortcut
   stays on the page and focuses the request field. It must remain reachable when
   the catalogue is long.
3. Category controls: use existing product-key grouping as a convenience; label
   counts for the filtered view. A disappearing category resets safely.
4. Product card: condition/status; modest category illustration clearly labeled as
   such; linked product name; variant; delivery zone; seat count and pool minimum
   as capacities, not current participation; closing timestamp with timezone.
5. Price: “Price set after bidding.” Never put the buyer cap, an estimate or a
   fabricated crossed-out retail price in the selling-price position.
6. Preserve the exact FR-UI-01 badge on every card. Do not invent merchant ratings,
   savings, remaining stock, number joined or verification badges.
7. Search currently filters a bounded loaded list. State that scope. The existing
   `q` endpoint can support a separately submitted full-catalogue retrieval later;
   pagination and a total count require contract work. Do not silently claim an
   exhaustive search.
8. Intake below the list: clear natural-language label, budget/location hint, two
   generic examples, Find matches, recoverable question/no-match/failed states.
   Enter remains a newline in the multiline field; submission uses the button.
9. Server proposal: product, delivery, required date, cap and firm/preferences;
   exact API notices; explicit confirmation. Confirming a request is not joining.
10. Keep manual entry reachable when AI is unavailable. AI failure must not prevent
    browsing or deterministic joining.

### Pool details and join: `/pools/:poolId`

Question: **What exactly am I entering, and what must I do now?**

1. Back to discovery; product title, variant, condition and actual pool state.
2. Product overview with included items, published delivery/returns and destination
   information where the existing template supplies them; no invented exact photo.
3. A compact published-stage strip, followed promptly by the entry action. On a
   phone, the buyer must not scroll past rules and all lot details to find the form.
4. Join form: delivery region, required-by date, maximum delivered total in USD.
   Explain the cap in dollars, including delivery, rather than exposing cents as
   implementation detail. Associate help and validation with its field.
5. Existing immutable confirmation/idempotent join remains: repeated clicks or a
   failed response retry the same confirmed request, never a fresh purchase.
6. Unknown membership shows Checking your entry; only a confirmed absence enables
   joining. A failed membership read offers Retry, never a second entry action.
7. After joining, stay on the pool. Show Your entry, current allocation, next action,
   and View entry receipt. Opening the receipt is deliberate.
8. Waitlist: show the server position, with no rank substitution. State that a
   vacancy may be offered in published order if eligibility still passes; do not
   promise this buyer the very next seat.
9. Seated status does not imply bidding is still in progress. Offer-ready and order
   states determine the next action; links never make a payment request themselves.
10. Withdraw is explicit and available only under the existing server rules. Preserve
    confirmation and server deadline checks. A receipt remains after withdrawal.
11. Timeline, lot plan and public rules follow the decision/action layer. Keep hashes
    in a disclosure. Do not hide the lots-may-differ consequence in technical proof.
12. Countdown uses server time; an absolute timestamp is the honest fallback before
    a server sample arrives. Browser time does not decide eligibility.

### Receipt within the pool

- Treat it as an **entry acknowledgement**, not a purchase invoice or capture proof.
- Use a native modal dialog for contained focus, Escape, background inertness and
  focus restoration. Keep an explicit close/back control. No automatic opening.
- Preserve the branded PDF, print fallback and unchanged signed JSON download.
- The receipt belongs to the owner; never expose salt/request hash in public lists.
- Verify phone scrolling, long references, keyboard traversal and repeat opening.

### My Pools: `/my-pools`

Question: **Does any entry need my attention, and what happens next?**

- Keep one feed and Current pools / Past entries. Reviewable offers lead current
  entries. Do not add parallel status sections or vanity summary tiles.
- Lead each record with product, variant and one readable state. Show the next
  action and deadline alongside it. References stay in Entry details.
- Use the API's waitlist position and priced-out cap/award values where available.
- Do not say “a merchant met your price” based only on an offer reference: detailed
  price and terms must be reviewed on the existing offer screen.
- CAPTURED, withdrawn, priced-out and stopped entries remain findable in history.
  REFUNDING stays visible as ongoing recovery, not a completed refund.
- A list load failure, empty account, empty current view and empty search have
  distinct recovery. No joining/approval action flashes during a read.
- Until a proposed clock read model exists, show the absolute server deadline;
  do not build a device-clock urgency countdown from `OfferRef` alone.

### Orders: `/orders`, `/orders/:buyerOrderId`

Question: **What happened to this purchase and its payment?**

- List product, merchant, variant, exact total, readable payment state, recorded
  date and published terms. One View order action; references in a disclosure.
- A total is an order amount, not proof that it was charged. CAPTURED means a
  completed capture under the state engine; order IDs/capture IDs alone do not.
- Distinguish Paid, In progress, Released and Not completed as the existing UI does.
  Keep refunding separate from refunded and a hold separate from payment.
- Render list `capture_id` directly. Keep older-response fallback reads only where
  the field is absent, not when it is explicitly null.
- Order detail uses provider statuses and server history. Do not infer a net refund
  balance or shipment completion; neither is in the contracted detail response.
- Shipment tracking exists in merchant fulfillment but is not exposed in the buyer
  order read model. Document a proposal; do not fabricate a tracking button.
- Check long product/merchant names, absent metadata, failed reference copying,
  empty filters and phone amount/action placement.

### Offer approval: `/offers/:buyerOrderId`

The A-owned checkout is an integration boundary for this pass. Preserve its route,
shipping snapshot, SDK popup and redirect fallback. A later owner-coordinated pass
should apply the same buyer tokens and visual hierarchy to this screen.

Priority order: exact product and merchant; delivered total and confirmed cap;
shipping and terms; actual fallback notice; deadline; explicit PayPal action.
Show the server's hold notice unchanged. The SDK sends only the provider order ID
to the server. Never capture/authorize from the browser or pass a client amount.
Popup failure needs retry/redirect recovery, and late approval remains server checked.

### Account, onboarding and audit

- Sign-in/signup: preserve PayPal browser binding, role guards, consented prefill,
  separate address step and intended destination. No forced reauthentication
  between ordinary buyer routes. Identity linking is not payment permission.
- PayPal settings: state linked/unlinked and revocation limits; do not claim a
  verified unique person. Do not treat unlink as deleting vault permission.
- Addresses: owner-only reusable address records, one default, explicit edit/delete,
  readable field errors. No change modifies an existing order snapshot.
- Agent settings: delegation scope, cap, expiry and ratification remain visible;
  show token once, never persist it in a prompt or browser storage. Existing
  advisory mandate limitations remain disclosed; an agent cannot pay.
- Notifications: owner-scoped existing inbox, unread count, mark-read recovery,
  useful destination and empty state; no new email, SMS or push promise.
- Public audit: receipt verification and anonymized evidence are advanced support
  for the buying journey. Keep it reachable; never call the draw “provably fair.”

## 5. API inventory and frontend implications

All paths below are existing. Arrays, nulls, units and owner checks matter as much
as the happy response. Frontend types stay generated from OpenAPI.

| Existing endpoint | Actual useful response | Design implication |
|---|---|---|
| `GET /api/v1/me` | Identity, role, PayPal-link boolean, unread count | Shell scope and role routing; no payment permission inference |
| `GET /api/v1/pools` | Bare `PoolSummary[]`: IDs, title/status/mode, product key/variant/condition, zone IDs, seats/minimum, close time | Default limit 20, maximum 100; no cursor, total, price, image or participant count; trending is server order |
| `GET /api/v1/pools/{pool_id}` | Summary plus untyped template, lot plan, timeline, rules hash | Use known template keys defensively; no payment-mode field |
| `GET .../pools/{pool_id}/events` | `pool_status`, `lot_status`, `tick` | Short transactions; server time updates presentation; reconnect must not invent a state |
| `GET .../pools/{pool_id}/rules` | `rules_document`, `rules_hash` | Load on disclosure; keep proof separate from decision |
| `POST .../intake/messages` | Session ID, clarification/confirmation/no-match, nullable question/card | Preserve context for answers; render server card and notices |
| `POST .../intake/confirm` / `manual` | Confirmed-request ID and canonical request | Confirmation precedes entry; cents remain integers |
| `POST .../pools/{pool_id}/entries` | Entry ID, replay flag, pool status, signed receipt | Stable idempotency key; free entry; keep user on pool |
| `GET .../pools/{pool_id}/entries/me` | Entry, allocation, offer, vault status/label, receipt; 404 for absence | Unknown/error is not absence; durable receipt; no credential returned |
| `DELETE .../pools/{pool_id}/entries/me` | Entry and withdrawn status | Server owns close-time eligibility; do not optimistically erase record |
| `GET /api/v1/me/entries` | Items with pool/product context, entry status, allocation, latest offer and labels | Constant-query feed; no per-card fetch; no server-now, cap before allocation or payment mode |
| `GET /api/v1/offers/{buyer_order_id}` | Product/merchant/terms, cent totals and cap, timestamps/server-now, mode-specific notices | Price review and deadline; no eligibility arithmetic in browser |
| `POST .../offers/{buyer_order_id}/continue` | Provider order ID, approval URL, UI mode | Sends shipping only; keep approval URL out of logs/reports |
| `POST .../offers/{buyer_order_id}/approved` | APPROVED/REJECTED/EXPIRED plus reason | Hint followed by server GET and checks; never a paid signal |
| `GET /api/v1/me/orders` | Items with total/status/receipt, product/pool/merchant/terms, placed_at, capture_id, labels | Named purchase feed; list metadata avoids fan-out |
| `GET /api/v1/orders/{buyer_order_id}` | State, lot state, total, history, provider statuses/reference, reason and receipt | No net balance, buyer shipment or product/merchant block contracted here |
| `GET/POST .../me/notifications[/read]` | Owner notification list/count and mark result | Existing inbox only; retain retry if mark-read fails |
| `GET/POST/PUT/DELETE .../me/addresses` | Owner address list/record, default flag; 204 delete | Private form state, no public cache or address logging |
| `GET/POST/DELETE .../me/delegations` | Metadata; new secret only once | Keep ratification and access controls intact |

### Proposed API work — separate change request, not implemented here

| Need | Smallest proposed extension | Owner / checks |
|---|---|---|
| Correct mode-specific buyer journey | Pool and private entry capability/read fields identifying applicable mode, allowed next action and server-authored notices; agree whether pre-lot mode is fixed or prospective | A+B contract decision; stamped lot mode still wins after award; no inference from process defaults or notice prose |
| Finish saved PayPal permission | Entry cap and server consent/version plus capability and vault status in owner read model | A+B; immutable request, exact consent hash, ACTIVE gate, expired/disabled recovery; never return token |
| Safe urgency in My Pools | Response-level database `server_now`, with offer-start/deadline if live countdown is required | A+B; distinguish unknown timestamp; server rechecks action |
| Exhaustive browsing | Cursor/has_more and defined ordering on pool list; typed category if categories are a product concept | B; preserve current clients or version shape; no buyer data in retrieval index |
| Better comparison | Public participant count and supported delivery summary only if required by task | B; count non-withdrawn entries; never call it seats remaining or funded buyers |
| Buyer order tracking | Owner-only shipment carrier/number and recorded status | A; actual shipment row, no invented ETA or delivered state |
| Honest order detail context | Add product, awarded merchant/terms and clearly defined payment aggregates if needed | A; snapshot provenance and capture/refund reconciliation; no client-computed net-zero claim |

No new endpoint/table/dependency is needed for the first visual and usability slice.
Do not edit contracts, generated SDKs or generated API types to make a mock fit.

## 6. Findings and disposition

These are source-backed cases. Visual findings need the browser evidence below.

| Priority | Finding and concrete consequence | Disposition |
|---|---|---|
| Critical follow-up | Primary saved-permission mode has no buyer consent/save controls; pool/entry list lacks mode/capabilities. A SUBMITTED live entry may miss ACTIVE eligibility at close. | Record open question/request; owner chose approval-flow scope; separate contract/payment task |
| High | Pool waitlist copy says the seat transfers automatically to “you” when any seated buyer declines. Later waitlisted buyers cannot all get that vacancy. | Correct to conditional published-order wording |
| High | First catalogue request failure renders the error and “No open pools” together; heading can report zero. Failure is mistaken for supply absence. | Separate failed, empty and stale states |
| High | Receipt overlay sets `aria-modal` on a div but does not contain Tab focus or restore it. Background controls remain keyboard reachable. | Native modal with close, Escape and focus return; browser check |
| Medium | Buyer plane, frame and cards are strongly blue, competing with product and action. | Buyer-only pale frame and white sheet; measure contrast |
| Medium | Product title is not linked; image and footer duplicate the destination. A text-first buyer has no title link. | Link title; preserve routes and prefetch |
| Medium | Product cards omit available zone IDs; users must open a pool to see its destination. | Add existing zone facts without inventing region coverage |
| Medium | Request form sits after the entire catalogue without a direct shortcut; multiline Enter submits unexpectedly. | In-page focus shortcut; preserve Enter newline |
| Medium | Cap help prints “60000 cents”; nearby help is not programmatically associated. | Display $600.00 USD and delivered-total meaning; descriptions on fields |
| Medium | Local catalogue filtering examines only a default 20 results yet reads like catalogue search. | Label its scope; document retrieval/paging extension |
| Medium | Review banner promises a merchant met the buyer's price using only `OfferRef`; full totals are not in that list. | State that an offer is ready; let the detail read establish terms |
| Follow-up | My Pools is a cached read without pool SSE or page polling; offer refs lack database now for countdown. | Keep timestamps honest; propose capabilities/clock before adding urgency |
| Follow-up | List order terms derive from the published pool, while the offer has award-specific terms. Better-than-minimum merchant terms may need snapshot clarification. | Confirm source/provenance in A-owned read model before altering it |
| Follow-up | Missing buyer shipment read prevents meaningful “Track delivery” actions. | Proposed contract only |
| Follow-up | Product-key prefixes act as categories; no category schema guarantees names. | Convenience filters only; no delegation/category semantics inferred |

The task is deliberately not a general security audit, a migration or an unverified
PayPal behavior change. Existing open mandate/category questions remain in progress.

## 7. Responsive and accessibility acceptance

- Desktop 1440×900: fixed quiet rail, 24px consistent gutters, white sheet, useful
  first product row; no empty metric scaffolding. Three columns only where readable.
- Tablet 768px: folded rail, two catalogue columns when each remains usable,
  controls wrap intentionally; pool form is not squeezed into a side column.
- Phone 390px and 360px: 16px content gutters, one product column, 44px actions,
  readable badge, no body horizontal scroll. Maintain useful content in the first
  screen; do not make a product illustration taller than the decision details.
- At 200% zoom/long text, preserve names, labels, amounts and actions without
  overlap. Dialog scroll is internal; closing does not lose the user's position.
- All fields have labels; help/error IDs use aria-describedby. Error handling
  preserves user input. Form submission states prevent duplicate writes.
- Focus is visible on all links/buttons; native dialog traps focus and restores it;
  Account and inbox Escape paths remain testable. Headings follow a readable order.
- Text/placeholders reach 4.5:1, large text 3:1. Controls/focus reach 3:1 against
  adjacent surfaces. State meaning appears in words, never color alone.
- Keep reduced-motion behavior. App screens gain no decorative entrances; no new
  animation or icon dependency. Illustrations retain their explicit limitations.

## 8. Implementation sequence and test map

| Slice | Changes | Acceptance evidence |
|---|---|---|
| Plan and branch | This document, T09B04 follow-up status and open question; branch from main | Documentation validation, direct diff; first commit contains plan before UI |
| Buyer frame | Scoped tokens and white sheet; reuse shared navigation without affecting other workspaces | Existing buyer shell/role tests; browser desktop/tablet/phone; contrast checks |
| Discovery | Scope/filter status, genuine error state, linked product/zone, request shortcut and multiline behavior | `discover.behavior.test.tsx`; no write on navigation, failed read is not zero |
| Pool/join | Human-readable cap and associated help; conditional waitlist; focused entry-action order | `lobby.behavior.test.tsx`; exact cents payload and idempotent replay retained |
| Receipt | Native dialog, Escape, repeat-open, focus restoration | Lobby regression and browser keyboard traversal; receipt/PDF suites unchanged |
| My Pools/Orders | Keep truthful next-action language, responsive product-led feed and amount hierarchy | `my-pools.test.tsx`, `orders.test.tsx`, order status and checkout regression suites |
| Verification | Whole frontend suite, production build, lint/types, make verify, Graphify update | Record actual output, failures and unrun checks below |
| Review | Independent UI/source review of the delivered slice; fixes and documentation | Review scope and final disposition recorded; no fabricated full-system approval |

Before implementation, capture the current app with deterministic UI-only fixtures
through its real React routes at 1440, 768 and 390px. These fixtures never contact
PayPal and are not sandbox contract-test evidence. Repeat on the built production
assets after changes; inspect full pages and keyboard states, not just thumbnails.
Use meaningful regressions for behavior. Pure CSS does not need snapshot tests
that merely restate selectors. Reuse current dependencies and components.

## 9. Delivery record

Plan created before interface edits. Implementation, browser critique, command
results, independent review and remaining work will be appended after verification.
The proposal tables above are a backlog, not a claim that every item shipped.
