# Contracts

Contracts are the exact interfaces between modules and between the two members. They are what lets Member A and Member B work in parallel without waiting for each other's code. They are derived from `docs/system-design.md` and tightened where the design left bytes, columns or names open.

Current version: `contracts-v1.8`, tagged after CR-12. Nothing in this folder changes after that tag except through a change request. The line above this one previously still read `contracts-v1.4` although `contracts-v1.5` and `contracts-v1.6` were already recorded below; the stale number is corrected rather than relied on.

## Files

CR-7 (owner requested 2026-11-02): consented PayPal profile/email/address prefill,
encrypted temporary signup details, encrypted buyer address book and signup delivery
step. Four owner-only session endpoints support multiple addresses and one default;
checkout reuses a selected copy through its existing shipping request. Migration
0006 adds user_addresses and paypal_signups.profile_enc. T03B03 / T06B05 are affected.
No payment, fairness, account-verification or agent permission changes are included.

| File | What it fixes | Primary owner of changes |
|---|---|---|
| `db-schema.md` | Every table, column, enum, constraint, trigger | Both (migration `0001` is built by Member A) |
| `state-machines.md` | Every legal transition for pools, entries, lots, buyer orders and bids, as machine-readable YAML | Both |
| `fairness-and-hashing.md` | Byte-exact algorithms for commitments, Merkle root, ranking, receipts, audit chain, money rounding | Member B |
| `vectors/fairness_v1.json` | Test vectors every implementation (Python and browser) must reproduce | Member B |
| `api.md` | Every HTTP endpoint, auth mode, payload and error | Both |
| `domain-ports.md` | Python ports and fakes, job kinds, handoff protocol between modules | Both |
| `paypal-adapter.md` | PayPal calls, payload ladder, idempotency keys, error classes, contract tests | Member A |
| `ai-schemas.md` | AI task schemas, guardrails, evaluation file formats | Member B |
| `config-and-errors.md` | Environment variables, switches, error codes, reason codes, timing profiles | Both |

## Rules

### CR-14: The agent surface has authority but no instrument, and has never met a model caller (owner authorized 2026-11-07)

FR-AG-01, FR-IG-02 and FR-IG-04 already give an AI client a scoped delegation token, an
MCP server and a merchant key, and `test_mcp_contract.py` and `test_merchant_agent_api.py`
prove both surfaces refuse what they should. Two gaps remain, and both are about the caller
rather than the surface.

First, the token's scope, cap and expiry are set by a form, so what the buyer actually cares
about has nowhere to live. "Do not go over $520 even though my cap is $600" and "pull me out
if the pool is not filling" are not expressible in `{"pool_ids", "category"}`, and nothing
evaluates them. The agent surface is bounded but not directed, so the human ratifies a number
rather than a policy.

Second, nothing has ever exercised these surfaces with a model as the caller. Both suites
drive fixtures. Whether a model can produce a rule-legal sealed bid, and whether the boundary
holds against a caller that reads a refusal and adapts, are unmeasured — and the unmeasured
half is exactly the half the hackathon's agentic-commerce theme asks about.

The change adds one new AI task, one enum value and three keys inside an existing JSONB column.
No new endpoint, no new table, no new job kind, no new state transition, no new environment
variable — but it does need a migration, for a reason that is easy to miss.

- `ai-schemas.md` section 9 adds Task MANDATE: the model proposes scope, cap, expiry and
  stop-and-ask conditions drawn from a **closed** five-predicate vocabulary with typed
  params. It never emits executable logic, and it can never raise a cap the buyer stated. The
  cap is enforced **per entry**, which is what `agentapi/service.py` does today; nothing sums a
  delegation's caps across the several pools it may see, and §9 says so rather than implying a
  total.
- `db-schema.md` names three keys inside the existing `delegations.scope` JSONB —
  `mandate_version`, `ratification_sha256`, `conditions`. Authorization still resolves from
  `pool_ids` and `category` alone, so the new keys cannot widen a scope. **They need code, not
  only a column:** `DelegationService.create` rebuilds `scope` as exactly `{pool_ids, category}`
  and silently drops every other key, so `DelegationScope` and that normaliser must both be
  extended or a ratified mandate would be stripped before it persisted and the token would be
  minted from a gutted object.
- `ai_runs.task` is a PostgreSQL enum, `ai_task`, whose values are fixed in migration `0001`. A
  new `MANDATE` value therefore needs a numbered migration doing `ALTER TYPE ai_task ADD VALUE`.
  Because Postgres will not let a new enum value be used inside the transaction that adds it,
  the statement runs outside a transaction block. `tools/check_migrations.py` replays
  0001-to-head and so does **not** catch a missing one; the test that catches it writes a real
  MANDATE run row.
- `product-spec.md` adds FR-AI-06 and FR-AG-03; `implementation-plan.md` adds T09B06 and
  T09A06 to PH9 under gate IG-9.

What does not change, stated because it is the point: rule 22 and I1/I2 stand; no AI-callable
surface gains a payment verb; `reserved` is stamped by the server and is not model output;
the payment approval stays the human's (FR-AG-02); INT-1 to INT-9 stand; a condition is
evaluated by deterministic code from stored rows only, so no condition can require a provider
or model call to resolve.

The FR-AG-03 run uses a pool whose payments go through the fake router (I12), labels
everything simulated (FR-AI-03) and never reaches PayPal. It is evidence about the boundary,
not a payment path.

The owner also records here what this CR declines: the vault permission is **not** enabled.
DEP-5 stands, `VAULT_REAL_SAVE_ENABLED` stays `false`, and the real `POST
/v3/vault/setup-tokens` path — never live-proven, and with VC-01 to VC-06 not yet written as
runnable Sandbox tests — is not attempted in PH9. The mandate's second half is described as
architecture and evidenced by the existing adapter code, never shown as a live charge.

Abandonment rule, recorded so a partial landing cannot survive: acceptance bullet 1 of each
new task is its gate — a live model must produce a schema-valid mandate (T09B06) and a bid the
Merchant Agent API accepts and seals, with its own receipt (T09A06). R1 to R9 are evaluated at
award time, not bid time, so the bid gate proves acceptance and sealing and the rule tally comes
from running the auction afterwards. If either gate fails, the owner cancels both tasks and
withdraws CR-14 whole: section 9, the three scope keys, the enum migration, FR-AI-06, FR-AG-03
and both task rows are removed together. Neither task ships alone, because a harness
with no mandate is a script, and a mandate no agent ever used is a form.

Independent review is required before IG-9 acceptance, as for every CR.

### CR-13: The inbox exists in the database and has no way in (owner authorized 2026-11-07)

FR-UI-09 asks for an in-app inbox of seat, waitlist, loss, hold, capture and refund
events, newest first, with an unread count, and says nothing is emailed, texted or
pushed. The notifications themselves are already written: `notifications` is frozen in
migration `0001`, `modules/notify/service.py` writes one row inside the transaction that
produced the event (I10), and `GET /api/v1/me` already returns `unread_notifications`
from a count of the same rows. What is missing is a read. A signed-in buyer or merchant
has no route that lists their own rows, and no route that marks them read, so the count
`/me` reports can only ever grow.

This change adds two owner-scoped session routes and no data:

- `GET /api/v1/me/notifications` lists the caller's rows only, newest first by
  `created_at` then `id` as a stable tie-break, capped at 50 items. Each item is
  `{id, kind, payload, created_at, read_at}`; the envelope also carries `unread`, the
  same count `GET /api/v1/me` reports, computed over all of the caller's rows rather
  than the returned page. `payload` is the stored application payload, returned as
  data, not interpreted by the route.
- `POST /api/v1/me/notifications/read` marks every unread row of the caller as read with
  the database clock (I15) and returns `{marked, unread}` with `unread` always `0`.
  It is idempotent: a second call marks nothing and answers `marked: 0`, `unread: 0`.
  The CSRF check that every session POST already carries applies unchanged.

Both routes are owner-scoped by the session principal, never by a request parameter, so
another user's notifications are neither listed nor marked; the read sets no status,
writes no audit row and calls no provider. No new notification kind is introduced, no
delivery channel is added, and no AI or agent surface reaches either route. The inbox
remains retrieval: it never changes a bid, an entry, an order or a payment (I1, I2).

Affected task: **T09B05**. `notifications` already exists, so there is no migration.
**No new contract tag and no phase-gate claim is made by this change request.**

### CR-12: A date the buyer wrote is read, and a date they did not write is asked for (owner authorized 2026-11-06)

A live INTAKE run against the hosted demo failed every message that stated a date.
`ai-schemas.md` section 2 defines `required_by` as `YYYY-MM-DD or null` and requires the
server to ask when the date is unresolved, but the adapter demanded that the model's
canonical string appear **verbatim** in the buyer's message. "by Nov 30, 2026" and "by
Friday" therefore both ended the whole proposal with a retry and then the manual form:
the first because the model copied the written form the schema rejects, the second
because a weekday can never be copied as an ISO date. A message with a `$` amount and
a `USD` proposal died the same way in the currency check, whose marker list had no
dollar sign.

This row records the reading that was missing rather than a new rule. Section 2.6 still
asks for a date the pool can meet, and the schema still emits only an ISO day or null.
What changes is how a value is grounded: an explicit calendar date in any written form
(ISO, `Nov 30, 2026`, `30 November 2026`) is canonicalised and accepted when the
message states that day; a weekday or a relative phrase is not a value, so the field
goes back to null and 2.6 asks the buyer. A numeric slash date (`11/30/2026`) grounds
nothing on purpose, because two readers disagree about which number is the day. For
2.4 a currency symbol states its code as plainly as the code does, so `$650`,
`650 dollars` and `USD 650` all ground USD; a currency the message contradicts still
fails.

The question of 2.6 is a turn of its own, so grounding also reads the buyer's own
earlier messages in `history`: "by Friday" followed by "2026-11-30" states the date in
the second message and the pool, region and cap in the first. The server's own
questions are excluded from grounding on purpose — the 2.6 question quotes the pool's
latest delivery date, and that bound must never come back as if the buyer had chosen
it.

Affected tasks: **T04B01** (intake, retrieval, proposal and confirmation). No schema
shape, endpoint or table changes; `PROMPT_VERSION` moves to `phase2-gemini-v10` so the
`ai_runs` rows of the two readings are distinguishable, and all 50 labelled intake
cases were re-measured live at v10 (100% on their labelled fields, recorded as
`v10_intake_spots` in `docs/evidence/phase2/gemini.json`) so the Phase 2 evidence
still describes the shipped prompt.

### CR-11: Make the draw and the bid set verifiable without trusting FairPool's word (owner authorized 2026-11-06)

The audit story in this repository says anyone can recompute the result. A read of the
code and the contracts together says they cannot, for three reasons, and all three are
contract-level rather than incidental.

First, the public audit payload published `seed_hex` and `beacon` as soon as the close
snapshot existed — that is, while lots were still `PLANNED` or `BIDDING`. `lot_tiebreak_hash`
is `hash(seed_hex, lot_id, merchant_id)`, so any merchant who read their own pool's page
knew their exact tie-break position before pricing anything. Second, buyers' entries were
committed to a Merkle root before the seed, but bids were committed to nothing: a bid
revision or a whole bid created after the deadline produced a fresh valid receipt and no
outside observer could tell. Third, the chain that is supposed to make both auditable was
filtered to `subject_type = 'pool'`, so the bid and lot rows were invisible, and the
checkpoint was unsigned, which left "tamper-evident only to someone holding a published
checkpoint" with no anchor a third party could check.

`api.md` gains the reveal gate, `bids_root`/`bids_count` per lot, the widened checkpoint
list and a signed top-level `checkpoint` computed at read time. `fairness-and-hashing.md`
gains the bid set root rule (one leaf per bid, its highest stored revision, sorted), the
`BeaconClient.fetch` round-window enforcement, the checkpoint coverage wording, and an
explicit statement that the round's BLS signature is **not** verified because no signing
dependency is permitted here. `db-schema.md` changes `pools.beacon` from "add after
seeding" to "merge after seeding" and names why: `rules_document(pool)` rebuilds its
`beacon` sub-dict from the stored value at read time, so a replaced dict loses `source`
and `chain_hash` and the served document stops hashing to the stored `rules_hash`. One
vector block, `bid_set_case`, is added to `vectors/fairness_v1.json` so both the Python
and the browser implementation are pinned to the same bytes.

Affected tasks: **T04A04** (seed fetch and window), **T06A06** (bid sealing and the award
handoff), **T00B01** (contract and vector freeze), **T09B01** (public audit page and
verify-my-place, which is the consumer of every field above). Code lands in the following
buckets F3, F4 and F2; none of them may precede this row.

### CR-10: Useful buyer workspace read models (owner authorized 2026-11-05)

The owner explicitly authorized API additions needed to complete the buyer,
merchant and admin interfaces. This amendment adds optional presentation fields to
the existing owner-scoped buyer list responses: pool/product identity, pool lifecycle status and honesty labels on entries;
pool/product identity, merchant display, delivery/return terms, order creation time,
latest capture reference and honesty labels on orders. Existing keys remain intact; the owner-only entry history also retains the latest
terminal order. Agent live-offer filtering remains unchanged. Reads are batched,
not one query or HTTP request per card. No new table, migration, permission, payment
action or transition is introduced. The profile read endpoint is described below.
The API amendment is recorded here before its implementation, under the owner's
explicit instruction to add necessary APIs; it is not a silent contract change.

CR-10 also adds `GET /api/v1/merchant/profile` so an existing merchant can edit
the settings already stored. It returns the existing profile response plus
optional nullable `payee_email` and `paypal_merchant_id`; the POST response gains
the same fields. This is merchant-role and owner scoped, returns 404 for no profile,
and makes no PayPal call or write. The UI may fall back to the account name for a
merchant who has not created a profile yet.

The existing admin lot read gains optional nullable `pool_title`, `product_title`
and `merchant_display_name`, joined from the pool and awarded merchant in the same
read. This gives operators context before intervention without expanding their
write permissions or exposing buyer information.

1. Contracts win over code. If code and a contract disagree, the code is wrong until a change request says otherwise.
2. Frozen means frozen. A change needs a **contract change request** (CR): a pull request titled `CR: <summary>` that edits the contract, adds a row to the change log below, names every affected task, and is approved by **both** members. CRs are rare; each one costs both members time.
3. After a CR merges, tag `contracts-v1.<n>` and the affected owners update their code within 24 hours. Until they do, `main` may be red for that area; the CR author helps.
4. Tests derive from contracts: state machines are loaded from the YAML in `state-machines.md`; API routes are compared with the endpoint table in `api.md`; the migration is compared with `db-schema.md` by `alembic check`; hashing uses `vectors/fairness_v1.json`.
5. When a contract is silent, do not guess. Log an open question in `docs/progress.md` (see `AGENTS.md`).

## Contract notes (ambiguities in the design resolved here)

| ID | Resolution |
|---|---|
| N1 | REFUNDING counts as an active buyer-order status (for I8 and the one-active-order-per-entry index). Design section 6.3 omitted it from its active list. |
| N2 | A lot below its minimum size is created directly as CANCELLED at allocation (transition LS-12), as design 9.6 says; the design lifecycle diagram did not show it. |
| N3 | An ops abort of an AWARDED lot before checkout opens moves it to CANCELLED (LS-13); no money exists at that point. |
| N4 | A buyer order in APPROVED can also expire (BO-17) when its offer expiry passes before it enters AUTHORIZING (F5). Design row 13 listed only OFFERED and ORDER_CREATED. |
| N5 | AUTHORIZING moves to REJECTED (BO-20) when the authorization amount differs from the expected amount; the authorization is voided at once (design 11.5). |
| N6 | OFFERED and ORDER_CREATED move to DECLINED (BO-21, BO-22) when the buyer declines or cancels (design 11.8). |
| N7 | Every lot has `lot_order`, unique within the pool, assigned at allocation by zone order in the lot plan then lot index. Awards are processed in `lot_order` (R9). |
| N8 | `payment_router` and `payment_mode` are stamped on the lot at award and never change afterwards (design 18). |
| N9 | The re-quote attempt counter lives on `paypal_orders.attempt` (unique with the buyer order); `buyer_orders.current_attempt` points at the latest. |
| N10 | Bids are stored as `bids` (one live bid per lot and merchant) plus `bid_revisions` (every save, with receipt). |
| N11 | Byte formats for canonical JSON, commitments, Merkle tree, rank hash, receipts, bid receipts, award hash, rules hash and the audit chain are specified in `fairness-and-hashing.md`; the design left them open. |
| N12 | Waitlist refill handoff: `AllocationReadService.next_candidates` moves WAITLISTED allocations to SEATED inside the caller's transaction; checkout (Member A) orchestrates, allocation (Member B) selects. |
| N13 | Entries have status WITHDRAWN (buyer withdraws while the pool is OPEN). |
| N14 | The delivery address is collected when the buyer continues to PayPal (not at join) and stored encrypted on the buyer order; it reaches the merchant only after the lot is FUNDED. |

## Change log

### CR-15: Public pool comparison fields (owner authorized 2026-11-09)

The owner requested backend read changes where they improve the buyer experience
during the T09B04 redesign. Pool cards currently require opening each detail page
to inspect published delivery and returns, and their trending order has no visible
entry-count evidence. This additive change exposes only existing public template
facts and the aggregate already used by trending; no buyer data or price is added.

`PoolSummary` and its `PoolDetail` extension add `entry_count`, `delivery_regions`,
`delivery_sla_days`, `min_return_days` and `bundle_contents` as defined in api.md.
Counted entries exclude WITHDRAWN; the count is demand, never stock remaining,
paid buyers or the probability of selection. The public list keeps its array shape,
limits, ordering and simulation/draft exclusion. Affected tasks: T06B05 and the
owner-requested T09B04 follow-up. No new endpoint, table, migration, dependency,
payment action, eligibility rule or public search index field is introduced.

Acceptance: list/detail publish the same template facts and actual count, including
zero; withdrawals do not count; list query count stays constant as rows increase;
existing search/trending/privacy tests pass; generated OpenAPI and frontend types
are regenerated. This contract-only record precedes its implementation commit.
No merged contract tag, independent approval or phase-gate closure is claimed here.

### CR-9: The entry read returns the receipt it issued (owner authorized 2026-11-03)

The owner authorized this change request inside the Phase 6 branch while asking for the
buyer receipt screen. `POST /api/v1/pools/{pool_id}/entries` issues the signed receipt
once, and the only way to see it again was to replay the join with the original
idempotency key: a buyer who reloads in another browser, or who wants to keep a copy, had
no way to reach the proof their own entry carries. `entry_receipts` already stores every
field, `receipt_for_entry` already rebuilds the exact body for the join replay, and
`db-schema.md` freezes the table, so the gap is a missing read, not missing data.

One route gains one optional response field: `GET /api/v1/pools/{pool_id}/entries/me`
returns `receipt` beside the status it already reported. No new route, no migration, no
new error code, no change to the join, the withdrawal or the audit chain. The read is
owner-scoped and keeps the existing `404` for "no entry here", so it discloses nothing
about anyone else. The value is returned as the bytes that were signed rather than
re-serialised by the response model, because the payload text is what the Ed25519
signature covers (`fairness-and-hashing.md` section 6) — the same rule the join route
already follows. A withdrawn entry keeps its receipt: it is the record that the entry
existed. When that row is absent, which only a data-integrity fault can cause, the read
answers with `receipt: null` rather than failing beside the status it also owns.

Affected task: T06B05 (Buyer UI v1: Discover and Join). **No new contract tag and no
phase-gate claim is made by this change request.**

### CR-8: Phase 6 contract write-ups and one guard widening (owner authorized 2026-11-03)

The owner authorized this change request inside the Phase 6 branch, on the finding
that `authorize.py` maps an authorization status of `EXPIRED` or `VOIDED` to
`AUTH_FAILED` while BO-05's guard accepted only `DENIED` and a definitive 4xx, so
`engine.apply` raised `IllegalTransition` and alerted instead of settling the seat —
the blocked half of `Q-2026-11-01-18`, which the Phase 5 review carried to IG-6.
`paypal-adapter.md` section 4 already states that all three statuses mean the order is
not authorized, and `testing-strategy.md` names F10
`test_f10_authorization_expired_vacancy`, so the widening writes down the rule the rest
of the contract and the test list already assume. Two state pairs and one effect are the
only structural change: none. BO-05's guard text is reworded in `state-machines.md` and
`domain/states.py` together, which `tests/unit/test_state_machines_contract.py` compares.

The rest is documentation of readings the shipped code already took, so that the drift
stops growing. CR-8 clarifications 2 to 4 in `state-machines.md` record the
`age_guard` void, the rule that a trigger finding the row outside its `from` states
returns without a transition, and the `CHECKOUT_OPEN`-only refill
(`Q-2026-11-01-16`). `api.md` carries the mode-dependent offer notice
(`Q-2026-11-01-17`, `Q-2026-11-01-19`), the merchant profile response shape
(`Q-2026-11-02-23`) and what the order endpoint does and does not return
(`Q-2026-11-02-22`). `domain-ports.md` section 5 corrects three payload and dedupe cells
to the wire format the handlers read (`Q-2026-11-02-24`). `vault-charge.md` section 7
names the unverifiable read-back edge `modules/checkout/vault_charge.py` implements
(`Q-2026-11-01-20`). `config-and-errors.md` section 5 lists what R1 to R7 compare
(`Q-2026-11-02-21`, `Q-2026-11-02-25`).

Affected tasks: T06A01 to T06A07, T06B01 and T06B05, and the Phase 5 rows T05A03, T05A05
and T05A06 whose reviews raised most of the questions. No migration, no new job kind, no
new error or reason code, no enum change. **No new contract tag and no phase-gate claim
is made by this change request.**

### CR-6: PayPal-first buyer registration (owner authorized 2026-11-02)

The owner requested PayPal authentication before account setup, with returning
buyers keeping email/password login, and subsequently authorized committing and
pushing the changes for hosted testing. This change request covers the authentication slice of T03B03 and T06B05, across both
solo-operated lanes. It adds anonymous browser-bound signup attempts, migration
0005, three public signup endpoints and mandatory PayPal proof for public registration.
It does not change payment approval, pool eligibility or the future agent lane.
No new contract tag or phase-gate claim is made by this change request.

| Version | Date | Change | Approved by |
|---|---|---|---|
| contracts-v1.8 | 2026-11-06 | CR-12: `required_by` is read from an explicit calendar date in any written form and canonicalised, an ungroundable date becomes the section 2.6 question instead of a failed proposal, and a currency symbol grounds its code in 2.4. Affects T04B01 | @shaahir27 (owner) after independent agent review; delivered on `main` under the AGENTS.md section 6 solo-operation note |
| contracts-v1.7 | 2026-11-06 | CR-11: audit-page reveal gate for `seed_hex`/`beacon`/`audit_checkpoints`, per-lot `bids_root` and `bids_count`, a signed read-time `checkpoint`, checkpoint coverage over the `pool`, `lot` and `bid` subjects, `BeaconClient.fetch` round-window enforcement, `pools.beacon` changed from add to merge, and the `bid_set_case` vector. Affects T04A04, T06A06, T00B01, T09B01 | @shaahir27 (owner) after independent agent review; delivered on `main` under the AGENTS.md section 6 solo-operation note |
| contracts-v1 | 2026-10-30 | Initial freeze after full review; corrections C1-C15 and status consolidation recorded | @shaahir27 (owner) after independent agent review |

| contracts-v1.1 | 2026-10-31 | Phase 2 provider, payment identity, rules vector/envelope, shipment association and evidence validation | @shaahir27 (owner) after independent review; merged into `main` and tagged |
| contracts-v1.4 | 2026-11-01 | Phase 4: whitelisted `admin.force_award` (LS-14), vault-aware LS-06 funding guard, nullable `awards.bid_revision_id`, `intake_proposals`, `lots.refill_waves`, `LotView.pending_wait_s`/`capture_grace_s`, and the API bodies for cancelled, force-award and reconciler-run. Affects T04A01 to T04A06, T04B01, T04X01 | @shaahir27 (owner) approved with the Phase 4 plan |
| contracts-v1.3 | 2026-11-01 | Phase 2 AI acceptance: 95% extraction threshold with bounded non-critical error and human-review fallback, safety checks absolute, contradictory demo cases may resolve to review (owner decision), v5-v8 validator revisions with a fail-closed capacity guard. Affects T02B03 and T09B02 | @shaahir27 (owner) after independent review; findings dispositioned in `docs/progress.md` |
| contracts-v1.2 | 2026-11-01 | CR-3, Phase 3: `confirmed_requests` and `vault_setup_attempts` tables plus migration 0003, `oauth_states` session binding, `vault_tokens.cap_cents` widened to bigint, entry-window trigger on `clock_timestamp()`, `Clock.db_wall_now`, the `PaymentVault` and `PayPalIdentity` ports with attempt-scoped vault keys, join idempotency and rate-limit semantics, new `RULES_MISMATCH` and `INTEGRITY_ERROR` codes with `VAULT_SETUP_TTL_S`, `VAULT_REAL_SAVE_ENABLED`, `OAUTH_STATE_TTL_S`, `SEARCH_TIMEOUT_MS`, the deterministic-manual-confirmation and public-key/close-audit pull-forwards, and the honest S1/S5 webhook-verification states | @shaahir27 (owner) after independent agent review |

### Phase 2 AI acceptance CR (approved 2026-11-01)

The owner requested 95% extraction accuracy as the Phase 2 acceptance threshold.
The amendment allows bounded noncritical extraction errors and safe human-review
fallbacks, while retaining safety checks, demo-case requirements and provider
availability. The owner additionally accepted the recorded v4 three-run baseline
with v5 spot checks for the narrowly scoped capacity-validation change. The model,
schema and dataset must match; the v5 spots cover all intake and quote cases plus
the known reconciliation review case. Independent review found a single-label
capacity ambiguity; v6 adds a fail-closed guard, separately verified by two live
conflict spots. A second review found ambiguity-marked definite quantities; v7
rejects them. A third review found punctuation and unit variants; v8 handles
those even when the model omits its ambiguity marker. Each has two separate live
conflict spots; accepted v4/v5 outputs are revalidated offline under v8. Other version
changes require reevaluation. Affected tasks:
T02B03 and T09B02; affected files: `ai-schemas.md`, the evaluator and IG-2 gate.
Owner approved on 2026-11-01, including one decision this review forced: **a
contradictory demo case may end in human review instead of a definite rejection**,
because review is the safe outcome when the quote itself is contradictory. The
evidence records 41 reconcile rows in review, 19 of them demo cases, and four of
those four expected a definite rejection under the old rule; that count is disclosed
in `docs/evidence/phase2/README.md` rather than hidden by the threshold.

Three corrections to what this CR first claimed, found by independent review:
v5 to v8 are **validator** revisions - the system prompt text is unchanged, and the
fingerprint field is a combined gate version, not a prompt history; the recorded
"two live conflict spots" per version prove that the model **declines** to state a
definite capacity, not that the guard fires, so guard coverage is proved by the
deterministic tests that feed a definite value for every published variant (sentence
break, en dash, parentheses, ampersand, "pcs", a spelled-out number, a bare
"quantity" ambiguity, and the originally recorded "4 or 9" forms); and the v4
baseline holds 479 distinct live calls, not 480, because one row is duplicated
across runs 1 and 3.

This CR is tagged `contracts-v1.3`.

### Phase 2 change request (owner-approved implementation plan, 2026-10-31)

Scope: T02A01 to T02A04 and T02B01 to T02B05. The owner approved Gemini,
shipment association, request identity, rules envelope/vector and grounded AI flags.
The existing ports and endpoint paths remain unchanged. Independent review is
required before gate acceptance. No historical spike evidence or migration 0001 changes.

- Gemini uses `google-genai`, `GEMINI_API_KEY`, `AI_MODEL_PARSE` and `AI_MODEL_SIM`.
  Default model: `gemini-3.5-flash-lite`; compatible Gemini names are configurable.
  No tools, 20-second calls, SDK retries disabled and one validation retry.
  Use supported generation parameters; temperature is omitted for Gemini 3.x.
- Vault charge has one logical `vc:<buyer_order_id>` identity, with separate
  UUIDv5 HTTP keys derived from `vc:<buyer_order_id>:create` and `:capture`.
- Rules reads return `{rules_document, rules_hash}`; the hash covers the document
  alone, according to the existing canonical JSON algorithm and fixed vector.
- Migration 0002 requires the captured buyer order to belong to the shipment lot.
- Reconciliation evidence must occur in the input and relate to the named field.
  Unsupported/ambiguous claims require review; no model-written accusation is shown.

The owner authorized one intermediate contract commit. The contract-only amendment
is merged into `main` and tagged `contracts-v1.1`; the implementation continues on
`phase-2`. The tag marks the contract version only; IG-2 acceptance remains open.
### contracts-v1.5 (2026-11-02, CR-5, Phase 5)

- `GET /api/v1/offers/{buyer_order_id}` gains four optional keys:
  `offer_started_at`, `server_now`, `pool_id`, `pool_title`. The countdown and
  progress ring are rendered from the server clock (I15) and every handler still
  re-checks `offer_expires_at`.
- `GET /api/v1/orders/{buyer_order_id}` gains five optional keys: `pool_id`,
  `lot_id`, `placed_at`, `reject_reason`, `receipt`. `reject_reason` is one of the
  seven buyer-order codes, so the redirect path can explain a rejection that was
  previously stored and never returned. `receipt` is the owner's own typed entry
  receipt, verifiable against `/api/v1/public/keys`.
- `vectors/fairness_v1.json` gains two additive ranking cases,
  `bid_ranking_case` and `capacity_case`; no earlier vector changed.
- `config-and-errors.md` states the order in which R1 to R9 are applied and which
  of them need seated entries or awards. No reason code was added or renamed.
- No migration: every field the new keys read already exists in `0001`-`0004`.
