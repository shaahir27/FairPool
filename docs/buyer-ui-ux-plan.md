# FairPool buyer experience: design and implementation plan

Prepared 9 November 2026 for the PayPal AI Hackathon. Task: owner-requested
buyer follow-up to T09B04. Branch: `b/T09B04-buyer-experience`, from `main`.
The initial plan preceded implementation. Later sections record revisions and
delivery evidence in sequence.

### Current scope, 10 November 2026

| Surface | Current result | Remaining work |
|---|---|---|
| Discover | Bounded comparison cards, published terms and demand; preserved request and direct manual entry when automatic matching fails | Gemini rejects the configured API key as invalid; successful AI matching requires a corrected local key |
| Pool | Entry/outcome first, compact progress, product requirements alongside, secondary rules disclosures; actual desktop/phone inspected | Saved PayPal permission remains a separate payment-mode task |
| Manual entry | Server-provided delivery-date guidance; buyer chooses their deadline and cap | Server remains the eligibility authority |
| Public audit | Buyer checker first, explicit saved-receipt loading, local recomputation, readable checks and preserved evidence | Rank verification waits for CR-11 seed publication while bidding remains possible |
| My Pools and Orders | Product, outcome, amount and next action grouped in the shared system | No shipment-read or payment-mode API expansion in this slice |
| Offer | Product, exact total and awarded terms precede the address; deadline and notices sit beside existing approval controls; reviewed at desktop and phone | No live payment verification; full backend timing check remains open |

The old rejected layouts are historical evidence, not the current recommendation.
Latest validation and its limitations are in sections 10 and 11.

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

**Own world:** use the existing FairPool mark, self-hosted Inter, cerulean frame,
raspberry action, marigold brand detail and blue-tinted working surfaces. These are
the shared app tokens, also used by the public landing and authentication. The
buyer has no independent color variables or stylesheet. Dark blue ink carries
product facts; the stronger blue owns the navigation frame.

**Story:** find a suitable pool, understand the conditions, confirm a ceiling,
record the entry, follow the outcome and deliberately approve the exact offer.

**First viewport:** compact account/navigation frame; noun title and one sentence;
search and a direct request shortcut; the first product row. Product illustrations
are subordinate to names, conditions, price semantics and the closing deadline.

**Form:** Taste `framed-sheet`, seed `977748516`, adapted to the existing brand.
The owner's explicit preference for the shared cerulean palette overrides the
style's neutral chrome and small color budget. Use its measured frame and spacing,
with the existing blue surface roles. Product comparisons sit on the working
surface without identical outlined card boxes. No marketing hero or invented KPI row.

**Finish:** real browser checks at desktop, tablet and phone; regression tests;
documented independent review and explicit remaining limitations.

### One shared palette and stylesheet

The owner rejected the initial pale buyer-only treatment during implementation.
The final direction retains the current `index.css` tokens; buyer layout rules
live in the existing `shared/commerce.css`. There is no `buyer.css` and no
buyer-specific `--color-*` override. This makes the decision traceable to the
product's established identity, not a new palette drawn from a generic UI kit.

| Role | Target | Use |
|---|---|---|
| Frame | `#086FA5` | Shared cerulean navigation frame |
| Working sheet | `#DEEEF7` | Existing lightest blue task surface |
| Supporting surface | `#C9E6F3` / `#A7D7EF` | Existing panels and contextual bands |
| Ink | `#17364C` | Product names, amounts, primary text |
| Secondary ink | `#3A5369` | Existing readable metadata and help |
| Blue | `#005383` | Brand detail, links, progress |
| Primary action | `#BE2859`, hover `#A61F4B` | One next action, white label |
| Edge | `#73AAC9` | Existing shared structural edge, not a box around every product |
| Brand detail | `#FFC34F` | Existing marigold mark; existing light gold supports notices |
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
   such; linked product name; variant; published delivery facts; recorded
   `entry_count` where supplied; seat count and pool minimum as capacities, distinct
   from that demand count; closing timestamp with timezone.
5. Price: “Price set after bidding.” Never put the buyer cap, an estimate or a
   fabricated crossed-out retail price in the selling-price position.
6. Preserve the exact FR-UI-01 badge on every card. Do not invent merchant ratings,
   savings, remaining stock, participation counts or verification badges. Display
   the API's actual entry count, including zero; omit it for older responses that
   do not supply it. Entries are neither paid buyers nor reserved stock.
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
3. The entry action follows product facts; the published-stage strip sits with
   supporting context after the action in reading order. On a
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

The A-owned checkout was outside the initial visual slice. The later
owner-directed continuation in section 11 applies the shared buyer hierarchy
while preserving its route, shipping snapshot, SDK popup and redirect fallback.

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
| `GET /api/v1/pools` | Bare `PoolSummary[]`: IDs, title/status/mode, product key/variant/condition, zone IDs, seats/minimum, close time; CR-15 adds entry_count, delivery_regions, delivery_sla_days, min_return_days and bundle_contents | Default limit 20, maximum 100; no cursor, total, price or exact image; count is recorded demand, not paid buyers or stock; trending is server order |
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

### Read-model extension in this branch

The owner's later instruction explicitly authorizes backend changes that make
the buyer interface useful. CR-15 was recorded in a separate contract-only commit
before implementation. The public list and detail now expose existing published
delivery, returns and included-item facts, plus the count already used by trending.
It excludes withdrawn entries, reports zero accurately, exposes no entry identities,
and uses one list query instead of a per-card query. OpenAPI/types are regenerated.
No endpoint, table, migration, payment behavior or dependency is added.

### Remaining API proposals — not implemented in this pass

| Need | Smallest proposed extension | Owner / checks |
|---|---|---|
| Correct mode-specific buyer journey | Pool and private entry capability/read fields identifying applicable mode, allowed next action and server-authored notices; agree whether pre-lot mode is fixed or prospective | A+B contract decision; stamped lot mode still wins after award; no inference from process defaults or notice prose |
| Finish saved PayPal permission | Entry cap and server consent/version plus capability and vault status in owner read model | A+B; immutable request, exact consent hash, ACTIVE gate, expired/disabled recovery; never return token |
| Safe urgency in My Pools | Response-level database `server_now`, with offer-start/deadline if live countdown is required | A+B; distinguish unknown timestamp; server rechecks action |
| Exhaustive browsing | Cursor/has_more and defined ordering on pool list; typed category if categories are a product concept | B; preserve current clients or version shape; no buyer data in retrieval index |
| Buyer order tracking | Owner-only shipment carrier/number and recorded status | A; actual shipment row, no invented ETA or delivered state |
| Honest order detail context | Add product, awarded merchant/terms and clearly defined payment aggregates if needed | A; snapshot provenance and capture/refund reconciliation; no client-computed net-zero claim |

No new endpoint/table/dependency is needed for this visual and usability slice.
Do not edit contracts, generated SDKs or generated API types to make a mock fit.

## 6. Findings and disposition

These are source-backed cases. Visual findings need the browser evidence below.

| Priority | Finding and concrete consequence | Disposition |
|---|---|---|
| Critical follow-up | Primary saved-permission mode has no buyer consent/save controls; pool/entry list lacks mode/capabilities. A SUBMITTED live entry may miss ACTIVE eligibility at close. | Record open question/request; owner chose approval-flow scope; separate contract/payment task |
| High | Pool waitlist copy says the seat transfers automatically to “you” when any seated buyer declines. Later waitlisted buyers cannot all get that vacancy. | Correct to conditional published-order wording |
| High | First catalogue request failure renders the error and “No open pools” together; heading can report zero. Failure is mistaken for supply absence. | Separate failed, empty and stale states |
| High | Receipt overlay sets `aria-modal` on a div but does not contain Tab focus or restore it. Background controls remain keyboard reachable. | Native modal with close, Escape and focus return; browser check |
| Medium | Buyer plane, frame and cards have little visual separation. | Keep shared brand colors; distinguish the stronger navigation frame from the light working sheet and remove repeated outlined catalogue boxes |
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

- Desktop 1440×900: fixed quiet rail, 24px consistent gutters, light blue sheet, useful
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
| Buyer frame | Existing shared tokens and commerce stylesheet; strong blue frame and light blue working sheet, with no buyer palette | Existing buyer shell/role tests; browser desktop/tablet/phone; contrast checks |
| Public comparison data | CR-15 read-only fields from existing published rows; regenerate OpenAPI/types | `test_public_pool_comparison_uses_published_terms_and_one_list_read`, existing trending/search/privacy tests, discovery count and terms tests |
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

Initial record: 9 November 2026. The plan above began before interface edits;
the owner's later shared-palette correction and CR-15 extension are recorded in
their sections. The owner subsequently rejected the discovery and pool layouts;
section 10 supersedes those visual decisions and their earlier review verdicts.
The remaining proposal table is a backlog.

### Delivered scope and incumbent system

Discovery now distinguishes loading, failure, empty supply and filtered results;
links product names; exposes published comparison facts and real entry demand;
and offers an in-page request shortcut without changing multiline Enter behavior.
The initial pool put the entry action after product facts, formatted and associated cap
help, corrected conditional waitlist wording and opened the receipt deliberately as
a native modal. My Pools keeps truthful offer-ready language; Orders gives product,
amount and action a usable phone layout. Existing checkout and payment rules remain.

CR-15, recorded in the preceding contract-only commit under the owner's API
authorization, adds optional public
`entry_count`, `delivery_regions`, `delivery_sla_days`, `min_return_days` and
`bundle_contents` from existing published data. The list remains one query and
counts non-withdrawn entries without exposing identities. OpenAPI and frontend
types were regenerated. No endpoint, table, dependency or money logic was added.

The documenter compared `frontend/src/index.css`, `frontend/tailwind.config.js`,
`frontend/src/shared/commerce.css`, `BuyerLayout.tsx`, discovery and the pool/receipt
components against section 3. This is an extension of the incumbent system:

| Observed rule | Delivered evidence |
|---|---|
| Palette | Shared cerulean frame, light blue working sheet, raspberry action and marigold detail retain the roles in section 3; source RGB variables stay in `index.css`. |
| Typography | Self-hosted Inter for UI; JetBrains Mono for references; 28px page titles (24px on narrow screens), 18px product headings, 14px copy and 16px inputs in the shared stylesheet. |
| Structure | Shared desktop rail and folded navigation, catalogue gaps and one-column phone content; the initial catalogue column rules were revised in section 10. |
| Components | Initially flat comparison cards, later replaced by bounded cards in section 10; shared panels, controls, focus and semantic state colors remain. |
| Interaction | Native receipt focus containment/return, explicit recovery, inherited motion tokens and no decorative buyer entrances. |

`BuyerLayout` supplies only the scoped wrapper and existing navigation. There is
no buyer stylesheet or color-variable override. Shared token sources, README and
global design documentation remain unchanged; no `DESIGN.md`, `PRODUCT.md` or
palette sidecar was created for this ordinary extension.

### Verification and review

| Check | Recorded result and limits |
|---|---|
| Initial full local verification (9 November) | `make verify` exited 0: 1,347 backend tests passed, 50 deselected, 94.59% coverage; 322 frontend tests passed in 31 files. Lint, strict types, import boundaries, docs, Merchant OpenAPI and gitleaks passed. Documentation retained two pre-existing warnings about a deliberately absent test endpoint. Log: `.tmp/buyer-design/make-verify-final.log`. This predates the section 10 revisions. |
| Invocation recovery | The initial run hit Windows default-temp permission errors. A workspace-local pytest `--basetemp` resolved the invocation; no tests or assertions were weakened. The production frontend build also passed. |
| Production browser fixtures | Discover, pool, My Pools, Orders, empty and failed catalogue states at 1440, 768 and 390px: 18 page/width combinations, with viewport and full-page captures. `shared-final/screens.json` records no horizontal overflow or JavaScript errors. |
| Keyboard and receipt | At 1440, 390 and 360px: native modal/background inertness, Tab containment, Escape focus return, reopening, print, reduced motion, request focus and Account Escape were checked. Evidence: `.tmp/buyer-design/after/interactions.json` and receipt captures. |
| Initial independent finish review | `buyer_finish_review` returned **ship** for the then-captured UI/API scope after inspecting 36 main captures, six receipt captures and source. The owner's subsequent rejection supersedes its discovery/pool judgment; this verdict does not certify the later revisions. No approved comp existed and no comp-fidelity claim is made. |
| Tool availability | Standard agents substituted for the unavailable named Impeccable reviewer and documenter. Existing product docs and this plan supplied context; Impeccable context/detect binaries were unavailable. Taste inspection reported 0 FAIL / 3 WARN (wordmark font, borders, brand-color budget), retained under the incumbent identity and explicit owner direction. |

Those browser captures use deterministic fixtures through production React routes;
they are not PayPal or actual-database verification. The saved-permission gap,
mode/capability fields and other API proposals remain separate work. Retained
wordmark/border/budget warnings are recorded, not promoted into new system rules.

### Actual app demo data

The owner selected `demo-buyer-1@fairpool.test`. The existing seeder was extended
under T09A03 and run with its explicit configured-app opt-in, without a reset or
PayPal calls. Discover now has six OPEN products: monitor, headphones, kettle,
keyboard, lamp and dock. They include variants, bundles, delivery regions,
delivery/return requirements and actual entry counts of 4, 5, 2, 3, 1 and 0.
The account has eight entries (seven current, one past), an offer to review and
a captured order. Existing simulated-payment labels remain visible; seeded
captures are demonstration records, not fresh provider verification.

The discovery extension creates 15 entries through ManualIntakeService and
JoinService, each with its signed receipt. It creates no orders. A second run
against the configured app returned the same six pools, 15 entries and 15
receipts, with published rows, hashes and deadlines unchanged.

The seed review found an application-clock dependency in a reused test helper.
The new path now publishes its opening deadline from DbClock, waits only when
necessary and lets PoolService.open recheck the database wall clock under lock.
The regression failed with POOL_NOT_OPEN when the old helper's clock was two
hours ahead, then passed after removing the helper from this path. The reviewer
scored that finding resolved and returned **ship** for the fix; existing legacy
seed helper callers are outside this change.

`test_discovery_seed_is_joinable_signed_and_repeatable_without_changing_rules`
checks the clock skew, six OPEN pools, reproducible rules, signed entries,
idempotent repeat and absence of orders. The final full verification including
this additional test is recorded separately below when it finishes.

Actual authenticated app navigation was also checked at 1440 and 390px:
Discover rendered six pools, My Pools seven current entries and Orders two
records, with no horizontal overflow or JavaScript exceptions. These checks
used the selected account and configured database through localhost; they did
not approve an offer, move money or certify a hosted frontend deployment.
Evidence: `.tmp/buyer-design/actual-seeded/checks.json` and its screenshots.
The earlier fixture captures remain the controlled error/empty/keyboard evidence.

Remaining verification limits: no new Sandbox payment flow, cross-browser suite
or 200% zoom run. Saved permission and shipment read-model proposals remain
separate work. The shared `.gitignore` modification present at task start is
preserved and excluded from implementation commits.

## 10. Owner-directed readability revision (10 November 2026)

The owner rejected the initial cardless discovery layout as difficult to read,
with a screenshot showing long, equally weighted fact lines. That feedback
supersedes the earlier discovery review verdict. The revision keeps the shared
palette and groups each product in a bounded card: compact illustration and
title, price semantics, labeled participation, delivery/returns, closing time
and one View pool action. The exact joining notice remains in its own footer.
Two columns at ordinary desktop widths preserve readable line lengths; wider
screens can show three or four. Phones show one card. No new API is needed.

The owner also requested a deeper pool and audit pass, then explicitly required
inspection of the populated pages before further changes. The initial proposal
below is retained chronologically; the later actual-page correction puts the
entry first and supersedes its product-first phone order.

The audit now puts the buyer's own checker first, with recomputations alongside
on desktop and below on phones; public manual verification and required proof
remain available. Missing entry counts say unpublished. Waiting copy follows
CR-11: the public seed is withheld while any lot is PLANNED or BIDDING, and
checkpoint history is withheld while any lot is BIDDING. A recorded winning bid
is distinct from an individual delivered offer total. This layout uses existing
audit reads; the separate matching date extension is recorded below.

### Pool redesign: the decision before the dossier

Initial proposal, superseded by the populated-page inspection and correction
below. The owner's second rejection left the earlier pool layout unaccepted;
this proposal retained the shared color system:

1. Header: back to discovery, exact product title, variant/condition, actual
   status and direct Your entry/Public audit destinations. Keep technical IDs
   and capacity prose out of the title line.
2. Main desktop composition: a readable product column and one entry panel.
   Product information contains a compact illustration, included items, published
   regions and delivery/return requirements. The signed-in entry/form remains
   visually independent and can be reached without scrolling through proof.
3. Participation: explicitly distinguish recorded entries, planned pool capacity
   and aggregate minimums. Do not draw a fundraising bar from entries or imply
   that the aggregate minimum guarantees any lot funds.
4. Entry panel: server-derived close notice; region, need-by date and delivered
   cap; one confirm action; truthful no-charge/hold copy. Joined, waitlisted,
   priced-out, withdrawn, offered and failed-read states retain their current
   server-driven behavior. The receipt remains a deliberate native modal.
5. Supporting column: compact stage list, published timing, individual lot plan
   and expandable rules. Identify lots clearly rather than a sentence containing
   several capacities and UUIDs. Keep raw references inside disclosure.
6. Phone: product, entry action, then supporting evidence, with full-width facts.
   Artwork never forces included items into a narrow half-column. The entry
   shortcut stays an anchor within this page. Do not pin a tall form on screen.

The discarded alternatives are a tabbed pool workspace, which hides information
needed for the entry decision, and another long undifferentiated stack, which
repeats the failure reported by the owner. Neither introduces a useful capability.

Acceptance: clear hierarchy with real long product names; no horizontal page
scroll at 360/390/768/1440px or the supplied screenshot scale; action before proof
in reading order; explicit zero/unknown demand; keyboard access to receipt and
evidence; existing join/idempotency/status tests and a fresh screenshot review.

### Offer page: plan before the continuation

This was the next-slice plan; section 11 records its later implementation.
Scope was `frontend/src/checkout/OfferCheckout.tsx` and its page
shell. Payment protocol changes are not required or authorized by a layout choice.
The plan uses the actual OfferResponse and existing address/config endpoints.

| Layer | Planned presentation | Existing data / behavior |
|---|---|---|
| Context | Back to this pool; Review your offer; product and winning merchant | `pool_id`, `pool_title`, `product`, `merchant`; preserve the current deep link and role guard |
| Exact terms | Product identity, variant, quantity, included items, awarded delivery and return terms; show important conditions before payment | `product.*`, `terms.delivery_sla_days`, `terms.returns_days`; do not substitute the pool's published minimum for the actual award |
| Decision summary | Exact delivered total in USD; item/shipping/tax breakdown and confirmed cap directly beneath; label every amount | `totals.item_cents`, `shipping_cents`, `tax_cents`, `total_cents`, `cap_cents`; use integer cents and server totals |
| Time | Absolute review deadline and server-derived remaining time beside the next action | `offer_expires_at`, `offer_started_at`, `server_now`; when server time is missing, use the absolute timestamp instead of a device-clock countdown |
| Delivery address | Default saved address first, easy correction or new address, optional line 2; preserve edits across failed reads and provider cancellation | `/me/addresses`, existing required-field validation and shipping submission; no invented delivery destination |
| Approval | Existing PayPal SDK control or verified redirect fallback, after the address and final terms; explanation immediately beside it | `/checkout/config`, existing `PayPalButton` and server `onApprove` path; browser still posts no amounts and never captures/authorizes |
| Consequences | Mode-specific hold/capture notice, independent lot outcome, Sandbox/fallback disclosure and a subordinate decline action | `notices.hold`, `notices.lots_may_differ`, `notices.fallback`; retain existing eligibility and busy/expiry guards |
| Outcome and recovery | Read the server state after approval; hold placed, completed payment, pending, rejected, expired and declined each lead to their existing truthful next action | Existing offer reload and order navigation; approval alone never becomes Paid |

Desktop should place the product/awarded terms and address in the main column,
with the exact total and approval context together in one summary column. On a
phone, product/merchant, total/terms, address and approval read in that order.
Avoid putting the address form before the buyer can understand the offer. Avoid
separate decorative step indicators that imply a step the buyer has not completed.
No unrelated upsells, fabricated savings, extra review route or replacement payment
button is proposed. Shared commerce components and colors remain the source.

Findings recorded before implementation: the offer countdown fell back to
`new Date()` when `server_now` was absent; the intended correction was an absolute
deadline. The summary and address/payment panels divided related decision facts,
and CSS reordered the phone summary; verifying DOM reading order was part of
the redesign. Preserve the existing saved-address read-failure fallback and all
non-OFFERED states rather than replacing the page with a happy-path mockup.

Before implementation, map each existing conditional offer state and the SDK's
cancel/error/redirect paths to a named regression, then capture actual seeded
offers at desktop and phone sizes without initiating a payment. Only propose an
API change if an awarded term or required capability is actually missing from
the existing response; record a separate CR first. This section recorded the plan
only; implementation evidence follows in section 11. It adds no payment claim.

### Pool correction after inspecting the populated page (10 November 2026)

Baseline: actual buyer account and monitor pool `5ef37fbd-5fb4-48b9-9469-ebac82749fc0`, after both the pool and entry reads completed. Captures at 1427 × 801 @2x and 390 × 900 are in `.tmp/buyer-design/pool-visual-baseline/`. The phone placed the allocated seat below approximately 800px of product information. The entry panel repeated its recorded status, exposed an irrelevant UUID, nested another tinted card, and explained a draw that had already happened. The closed entry countdown attracted attention despite the current RUNNING state. These observations supersede the previous pool layout recommendation and any earlier visual approval.

Implementation scope: PoolPage, its existing rules/receipt components, the shared commerce stylesheet, lobby regressions and browser fixtures. No API or payment changes are needed for this correction.

1. Put the buyer's entry first in source and visual order. On desktop, it is the wider left column; the compact product requirements are on the right. On phones, the entry follows the product title immediately. Keep the entry-check loading and retry states in that same place, without showing an unsafe Join action.
2. Give the actual allocation or offer one clear heading and explanation. Remove the raw entry ID and repeated generic lifecycle paragraphs from the main card; preserve the signed receipt, withdrawal confirmation, offer link and errors. Do not claim merchants are currently bidding merely because a seat is allocated.
3. Show the entry countdown prominently only while entries are PUBLISHED or OPEN. The stored close timestamp remains available under pool timing after closure. Pool eligibility still comes from the server.
4. Use a compact product panel: clearly labelled illustration, delivered requirements, included items and three separately labelled participation values. Capacity is never presented as availability or stock.
5. Make progress a compact four-stage record with one explanation for the current stage. Remove repeated Done/Later paragraphs. Keep timing, lot plan and rules as quiet full-width disclosures beneath the main task; retain the public audit link.
6. Validate the actual allocated-seat page at the owner's desktop dimensions and phone width, then check open/no-entry, waiting, offer, failure and receipt states. Verify reading order, keyboard access, no overflow and no contradictory status copy. Inspect the resulting screenshots before moving to matching, audit or the planned offer redesign.

The palette and typography stay in the shared design system. This correction does not add buyer color tokens, a new stylesheet, a dependency or an endpoint.

The implemented result is captured in `.tmp/buyer-design/pool-visual-redesign/`
at the baseline's 1427 × 801 @2x and 390 × 900 sizes. The entry leads, with a
compact seat card, stage below the entry, product facts on the right and
full-width supporting disclosures. Both captures report no overflow or
JavaScript errors. Fresh independent `pool_visual_finish` review returned
**ship** for this correction; all 22 lobby regressions passed. This evidence
covers those actual monitor-pool views, not every width or possible pool state.

### Matching and audit corrections after inspection

The real demo request for available headphones returned HTTP 200 / NO_MATCH;
`ai_runs` recorded AIUnavailable. This is an external provider fallback, not
evidence that the catalogue lacks a matching product. The UI now preserves the
request, focuses selected examples and offers a direct manual pool choice from
the loaded catalogue. It fabricates no AI match, cap, region or deadline.
CR-16, recorded separately in contract commit `6fc4c1a`, exposes nullable
`latest_delivery` from the existing server calculation. After restarting a
stalled local API reload, the public endpoint returned HTTP 200 with
`2026-12-07`. The actual manual path shows that lower bound while Needed by
remains empty until the buyer chooses. Server validation remains authoritative;
no model or credential was changed.

Audit baseline captures use the production frontend and a recorded public audit
response in `.tmp/buyer-design/audit-visual-baseline/`; the actual dev route did
not finish rendering at that baseline. The visible problem was a
long technical overview before the buyer's own task on phones, then three opaque
receipt fields with no help from the buyer's already saved receipt. The correction
puts that checker first. Signed-in buyers explicitly load their own receipt
through the existing owner-only entry read and recompute locally; private values
are kept out of URLs, logs and browser storage. Public manual verification,
signature, commitments, rules and beacon evidence remain. The requested-pool
scope guard prevents a cached receipt from another pool populating the checker;
its regression failed before the fix and passed afterward.

Live verification found the monitor's seed intentionally withheld by CR-11 while
lots can still receive bids; this is not missing demo data. Waiting copy now
explains that gate. The manual-entry capture also exposed a multi-day window shown
as thousands of minutes. The existing shared countdown formatter now uses
days/hours and hours/minutes for long windows, preserving minute/second precision
for short windows and all server-clock/expiry behavior. Three regressions were
added: two failed before the three-line formatter correction, then all passed.
No additional animation or deadline rule was introduced.

### Latest revision evidence and remaining limits

The matching actual-app report at `.tmp/buyer-design/matching-actual-final/`
confirms visible fallback, preserved request, direct manual selection, an empty
Needed by field with minimum `2026-12-07`, and no overflow/JavaScript errors.
Further sanitized provider diagnostics returned HTTP 400 INVALID_ARGUMENT:
"API key not valid. Please pass a valid API key." The owner was asked to update
GEMINI_API_KEY privately in the local environment. The owner said they would
update it locally and asked to continue; the subsequent recheck still rejected
the key. These checks certify usable fallback, not a successful AI match;
credentials and models were not printed, edited or replaced by the agent.

Audit before/after fixtures remain in `audit-visual-baseline/` and
`audit-visual-redesign/`, using the production frontend with a recorded public API
response. Later actual-app desktop/phone checks at `audit-actual-final/` both
loaded the populated buyer shell with no overflow/errors. The report records
`savedReceiptLoaded: true`; local verification truthfully waits for the public
seed during bidding. Screenshots were captured before loading private receipt
values. Fresh `matching_audit_finish` review returned **ship** after the scope
fix; its independent audit/lobby/checkout/countdown run passed 51 tests.

Before the offer continuation, frontend verification passed **335 tests**, lint,
strict TypeScript and the production build. Import boundaries, documentation (0 errors / 2 existing
warnings), Merchant OpenAPI and Gitleaks pass. Graphify AST update succeeded with
8,961 nodes / 28,251 edges; optional SQL extraction remains unavailable and changed
Markdown semantics were not rebuilt.

Full `make verify` is **not green**. The initial invocation chose the wrong Windows
shell. The Git Bash run passed 1,347 backend tests with one failure: the unchanged
10,000-entry timing test took 10,840ms against 10,000ms. Its isolated no-coverage
rerun passed. The clean full retry (`make-verify-final-clean.log`) passed 1,346 with
two failures and 94.59% domain coverage: timing at 10,364ms, and a simulation-list
test that assumed its live fixture was on the default first page. The latter now
checks that the page is nonempty and entirely LIVE_SANDBOX while retaining explicit
simulation exclusion, simulation 404s and live detail/audit reads; its targeted
rerun passes and its isolated test correction received independent review.
The timing threshold and production simulation code are unchanged.
Timing remains an open verification issue, not a claim that the UI/API changes
caused it. No third full-suite pass, green gate, push or PR is claimed.

The offer-page continuation followed this checkpoint and is recorded below;
the earlier future-work status and device-clock finding are superseded by that
implementation. Shared palette and stylesheet decisions remain in force.

## 11. Offer implementation after visual inspection (10 November 2026)

After the pool, matching and audit corrections, the owner requested continuation
through pending work. Baseline captures in `.tmp/buyer-design/offer-visual-baseline/`
use the production frontend and UI-only OfferResponse fixtures: active, expired
and missing-server-clock states at desktop and phone sizes. On desktop the page
asks for an address before explaining the product; on phones CSS reverses those
regions. The summary is long, the payment decision is far below it, and the missing
clock fixture incorrectly becomes expired from the device clock.

The delivered composition preserves the focused checkout shell and shared
palette. A full-width review panel presents product, merchant, exact delivered
total, confirmed maximum, breakdown and awarded terms before the form in DOM and
visual order. Below it, delivery details and the approval panel are adjacent on
desktop and sequential on phones. The decorative checkout step strip was removed.
Sandbox fallback and the exact hold notice remain beside the decision. No new route,
API, dependency, seller claim or payment action is introduced.

Known server time drives countdown/expiry; undefined or null `server_now` shows
the absolute deadline without inventing expiry. The server still refuses late
approval. Terminal states retain product context and a readable order-status link.
Failed reads retain context with Retry; the route guard prevents old-offer data
appearing under a new order ID, while refresh preserves the current address form.
Saved-address read failure still permits manual entry. All manual edits, including
optional line 2, resist a late default-address response and clear the saved-address
selection. These are UI state corrections, not a shipping or payment contract change.

Scope: OfferCheckout, its existing page wrapper, shared commerce styles and
countdown helper, and checkout/countdown regressions. PayPalButton, adapter,
amounts, shipping payload shape, SDK callbacks and server payment protocol remain
the existing implementation. ContextMatic is not exposed in this session; the
verified repository contracts and installed PayPal routing/best-practice v6
reference define the integration boundary. Payment execution is not part of
visual verification.

### Final offer delivery evidence

The documenter checked `OfferCheckout.tsx`, `OfferCheckoutPage.tsx`, the shared
`motion.ts` countdown and `commerce.css`. Product, price and awarded terms precede
address inputs in source order; the standalone shell uses the existing shared
buyer styles. No buyer stylesheet, color override or design-system fork was added.

Five new regressions failed before the fixes, then passed. The final frontend
suite passed **341 tests in 33 files** (`frontend-final-complete.log`); lint,
strict types and the production build passed. Fresh independent
`offer_finish_review` returned **ship** and independently passed 32
checkout/countdown/PayPalButton tests. That verdict covers the reviewed offer
continuation, not a full-system or payment certification.

The additional `offer-refresh.test.tsx` regression checks the surrounding form
lifetime through a test-only SDK callback. Restoring the old early-error return
made it fail because the edited Name field disappeared; restoring the fix passed
the full suite. This proves refresh failure retains the buyer's edits without
executing a provider action.

Fixture baselines and final captures are in `offer-visual-baseline/` and
`offer-visual-final/`: active, expired and missing-server-clock offers at 1440 and
390px. The selected demo buyer's actual expired offer also rendered at desktop
and phone in `offer-actual-final/`, with no overflow or JavaScript errors. All
review images were inspected. Taste's final inspector at 1440/768/390 reported
**0 FAIL / 3 WARN**: existing border strength, brand-color coverage and the
wordmark's mixed-face treatment. These retained incumbent choices are disclosed,
not new design rules. Log: `.tmp/buyer-design/offer-final-inspector.log`.

The final Graphify AST refresh completed: **8,966 nodes / 28,261 edges**
(`graph-update-complete.log`). Optional SQL extraction is unavailable; changed
Markdown semantics were not rebuilt. Full backend verification remains **not green**:
the last full run had 1,346 passes, two failures and 94.59% domain coverage. The
pagination-assumption test correction passes its targeted check and independent
review; the unchanged timing test remains open at 10,364ms against 10,000ms.
Import boundaries, docs, Merchant OpenAPI and gitleaks passed. No live payment,
push, PR or green phase gate is claimed.

The owner replied that they would update the AI key locally, then requested
continuation. A fresh configuration diagnostic still received the same invalid-key
response; a successful automatic match has not been claimed.
