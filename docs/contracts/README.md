# Contracts

Contracts are the exact interfaces between modules and between the two members. They are what lets Member A and Member B work in parallel without waiting for each other's code. They are derived from `docs/system-design.md` and tightened where the design left bytes, columns or names open.

Current version: `contracts-v1.3`, tagged after the Phase 2 AI acceptance change request. Nothing in this folder changes after that tag except through a change request.

## Files

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

| Version | Date | Change | Approved by |
|---|---|---|---|
| contracts-v1 | 2026-10-30 | Initial freeze after full review; corrections C1-C15 and status consolidation recorded | @shaahir27 (owner) after independent agent review |

| contracts-v1.1 | 2026-10-31 | Phase 2 provider, payment identity, rules vector/envelope, shipment association and evidence validation | @shaahir27 (owner) after independent review; merged into `main` and tagged |
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
