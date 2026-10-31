# Contracts

Contracts are the exact interfaces between modules and between the two members. They are what lets Member A and Member B work in parallel without waiting for each other's code. They are derived from `docs/system-design.md` and tightened where the design left bytes, columns or names open.

Current version: `contracts-v1`, tagged at task T00X01 (gate IG-0). Nothing in this folder changes after that tag except through a change request.

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

| proposed contracts-v1.1 (unmerged) | 2026-10-31 | Phase 2 provider, payment identity, rules vector/envelope, shipment association and evidence validation | Owner-approved plan; independent review corrections applied; not yet merged |

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

The owner subsequently authorized exactly one intermediate commit. Keep the three-commit
phase budget; independently review and commit the contract-only amendment first.
A commit is not represented as a merged pull request or passed acceptance gate.
