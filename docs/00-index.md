# FairPool docs index

FairPool is a group-buying marketplace built for the PayPal AI Hackathon ("Build What's Next with PayPal and AI"). Buyers join a pool for free during a fixed window; a published rule fairly allocates places; merchants compete in a sealed reverse auction; each selected buyer approves an individual PayPal payment; a lot is funded only when completed PayPal captures reach the merchant's minimum. AI helps at the edges (parsing requests and quotes, flagging mismatches, rehearsal text); deterministic rules decide and humans approve every payment.

This folder is everything a human or an AI coding agent needs to build it. Two members work in parallel in twelve phases with a merge gate at the end of each.

## 1. Read order

**AI coding agents** (every task, in this order): this file, `registry.md`, `agents.md`, your task in `implementation-plan.md`, the contracts that task names, the requirements it cites in `product-spec.md`. Open `system-design.md` only to understand a rule's rationale and `fairpool-idea.md` only to settle a doubt.

**Members, day one:** this file, `product-spec.md`, `decisions.md`, `team-split.md`, `implementation-plan.md` sections 1 to 4, then every file in `contracts/`.

## 2. File map

| File | Purpose | Maintained by |
|---|---|---|
| `00-index.md` | This map | both |
| `registry.md` | Definition of every ID (I, V, P, G, R, F, D, S and the other families) | both |
| `decisions.md` | Approved departures, assumed decisions, build decisions, integration decisions INT-1 to INT-9, spike-driven switches | both |
| `product-spec.md` | Numbered requirements, idea alignment audit, challenge register, claims | both |
| `agents.md` | Rules every agent follows; the standard task prompt | both |
| `scaffold.md` | Repository layout, tooling, Make targets, import boundaries, CI, CODEOWNERS, bootstrap | Member A |
| `implementation-plan.md` | 12 phases, 12 gates, capacity check, every task with files, acceptance and tests | both (generated list; changes by pull request) |
| `team-split.md` | Roles, ownership map, flow chart, merge points, daily and gate procedures, handoffs | both |
| `testing-strategy.md` | Test layers, property tests, integration tests IT-0 to IT-11, fault matrix, checklist mapping | both |
| `spikes.md` | Spike plans S1 to S13 and the safe-run preamble | both |
| `spike-results.md` | Recorded spike results (living) | whoever runs the spike |
| `demo-and-submission.md` | Storyboard, README outline, Devpost fields, final QA | both |
| `progress.md` | Task status, gates, velocity, open questions, blockers (living) | both |
| `contracts/README.md` | Contract policy, change requests, resolution notes N1 to N14 | both |
| `contracts/db-schema.md` | Tables, enums, constraints, triggers, JSON shapes | both |
| `contracts/vault-charge.md` | The vault-and-charge payment path (`PAYMENT_MODE=vault_charge`): flow, state deltas, cap rules, token security, consent text, failure handling, tests | both |
| `contracts/flat-delivered-bids.md` | The flat delivered price rule for bids (`BID_PRICING_MODE=flat_delivered`) | both |
| `contracts/state-machines.md` | Machine-readable transitions for pools, entries, lots, buyer orders, bids | both |
| `contracts/fairness-and-hashing.md` | Byte-exact commitments, Merkle tree, ranking, receipts, audit chain, money rounding | Member B |
| `contracts/vectors/fairness_v1.json` | Test vectors every implementation must reproduce | Member B |
| `contracts/api.md` | Every HTTP endpoint, payloads, the Merchant Agent API, MCP and Zapier bridge | both |
| `contracts/domain-ports.md` | Ports, fakes, job kinds, handoff protocols | both |
| `contracts/paypal-adapter.md` | PayPal calls, payload ladder, idempotency, errors, SDK v6, MCP boundaries, contract tests | Member A |
| `contracts/ai-schemas.md` | AI tasks, guardrails, retrieval and similarity, evaluation | Member B |
| `contracts/config-and-errors.md` | Environment variables, timing profiles, rate limits, error and reason codes | both |
| `system-design.md` | Export of the design document (rationale for every layer) | owner exports; not edited by agents |
| `spike-check-runbook.md` | What the owner provides and how to run `tools/fairpool_spike_check.py` (all pending spikes in one script), and how far the script is verified | owner |
| `audit-report.md` | Full-system audit of Oct 27, 2026: what was verified, what was corrected, what only spikes can settle, schedule risk | owner |
| `fairpool-idea.md` | The complete FairPool idea: problem, users, mechanics, screens, PayPal status, claims, open items | owner; changed only by the owner |

References such as “checklist 3.4” in these files mean items in the PayPal Sandbox final verification checklist, which the owner keeps outside `docs/`. The facts it proves are recorded as V1 to V13 in `registry.md`, and the second-seller results (items 3.1 to 3.4 and 3.8) as S3 in `spike-results.md`.

## 3. Which source wins

| Question | Wins |
|---|---|
| What to build | the idea text (`fairpool-idea.md`), then `product-spec.md` and the approved departures DEP-1 to DEP-4 |
| How to build it | `contracts/` at the current `contracts-v*` tag, then `system-design.md` |
| What PayPal does | verified facts V1 to V13 and the recorded spike results, then PayPal documentation, then assumptions |
| Which integration and how | `decisions.md` section 5 and the product's official documentation named there |
| When and by whom | `implementation-plan.md` and `team-split.md` |

When sources conflict, stop and log an open question in `progress.md`; never pick silently.

## 4. Placing the files

1. Copy this whole folder to `docs/` in the repository.
2. The idea document is already in `docs/fairpool-idea.md`. Do not add other source files to `docs/`.
3. The design document is already in `docs/system-design.md`.
4. Add root `AGENTS.md` as the Codex instruction file (the pointer plus the tool-generated `## graphify` block); do not create `CLAUDE.md` (`scaffold.md` section 9).
5. Run `python tools/validate_docs.py` from the repository root (the tool is committed in T00A01).

## 5. Current state of decisions

Decided and recorded: the four departures from the idea text (DEP-1 to DEP-4), the integration decisions (INT-1 to INT-9), S2 (authorization capture works, authorize replays safely, void does not), S3 (no partner access, so the labelled single stand-in seller is in force and platform fees are unavailable). Pending spikes are listed with due gates in `spikes.md`; their switches are in `decisions.md` section 4 with safe defaults. The design decisions D1 to D11 are assumed until the members confirm them at gate IG-0.

## 6. Ground rules in one paragraph

Only the payments adapter calls PayPal, only against the Sandbox. AI proposes; rules decide; humans approve. Money is integer cents. Deadlines use the database clock. Paid means a COMPLETED capture. Search is retrieval, never a gate. No AI-callable tool can move money. Claims never exceed what was verified. Everything else is in `agents.md`.
