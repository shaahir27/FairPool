# Implementation plan

This is the build plan for FairPool: 12 phases (PH0 to PH11), each ending in a merge gate (IG-0 to IG-11) with an integration acceptance test (IT-0 to IT-11, defined in `docs/testing-strategy.md`). Every task has an owner, size, dependencies, files to read first, files to touch, acceptance criteria and named tests. The task list is the single source for `docs/team-split.md` and `docs/progress.md`; `tools/validate_docs.py` checks that all three agree.

How to use it: take a task whose dependencies are merged, read the files named in "Read first", change only the paths named in "Create or change" (and only paths your member owns, `docs/team-split.md` section 2), prove every acceptance bullet with the named tests, then open a pull request titled `<TASK-ID>: ...` (`AGENTS.md` section 6).

## 1. Principles

1. **Contracts first.** `contracts-v1` is frozen at gate IG-0. After that, members work in parallel against ports, fakes, jobs and HTTP contracts, not against each other's unmerged code.
2. **Cross-member dependencies are only on earlier phases.** A task may depend on another member's task only if that task is in an earlier phase (merged at an earlier gate). Tasks owned by both members (`AB`) may depend on same-phase tasks. The one exception is `T00A01`: it merges first, at the start of PH0, and everyone branches from it.
3. **Every phase ends with a merge.** Both lanes merge to `main` before the gate's integration test runs. Nothing from the next phase merges until the gate passes (hotfixes excepted, `docs/team-split.md` section 8).
4. **Payments before polish.** The money path (gateway, buyer-order engine, funding, failure, reconciler) is built and tested with fakes before it touches the Sandbox, and verified on the Sandbox before any UI depends on it.
5. **Spikes before bets.** Every open gate (G) has a spike scheduled before the first task that depends on its result; results go to `docs/spike-results.md` and the switches in `docs/decisions.md` section 4.
6. **UI is contract-first.** Frontend tasks depend only on the frontend scaffold (T01B03) and the API schemas (T01B01). They may be coded early against the contract with a mock server, and are integrated at the gate that names their backend.
7. **Nothing is dropped silently.** If the plan slips, the owner decides what moves, in writing, in `docs/decisions.md` (section 5 below).

## 2. Phases at a glance

| Phase | Name | Gate | Integration test |
|---|---|---|---|
| PH0 | Bootstrap and contract freeze | IG-0 | IT-0 |
| PH1 | Data, platform and shell foundations | IG-1 | IT-1 |
| PH2 | Core engines I: PayPal gateway, ledger, identity, catalog, AI adapter | IG-2 | IT-2 |
| PH3 | Core engines II: buyer-order engine, seat control, join, search, PayPal Login, pool close | IG-3 | IT-3 |
| PH4 | Core engines III and the first integration | IG-4 | IT-4 |
| PH5 | Real PayPal path, auction core and merchant foundation | IG-5 | IT-5 |
| PH6 | Money completion and auction to checkout | IG-6 | IT-6 |
| PH7 | Live end to end and the agent and merchant lanes | IG-7 | IT-7 |
| PH8 | Fulfillment, verification, merchant console and simulation | IG-8 | IT-8 |
| PH9 | Hardening, evaluation and feature freeze | IG-9 | IT-9 |
| PH10 | Rehearsals and release candidate | IG-10 | IT-10 |
| PH11 | Submission | IG-11 | IT-11 |

## 3. Gates

A gate passes only when its integration test passes, `make gate-check GATE=ig-<n>` is green, the tag is pushed, and both members have merged everything in the phase.

| Gate | Tag | After phase | What must be merged |
|---|---|---|---|
| IG-0 | `ig-0` | PH0 | T00A01, T00A02, T00A03, T00A04, T00B01, T00B02, T00B03, T00X01 |
| IG-1 | `ig-1` | PH1 | T01A01, T01A02, T01A03, T01A04, T01B01, T01B02, T01B03, T01B04 |
| IG-2 | `ig-2` | PH2 | T02A01, T02A02, T02A03, T02A04, T02B01, T02B02, T02B03, T02B04, T02B05 |
| IG-3 | `ig-3` | PH3 | T03A01, T03A02, T03A03, T03A04, T03A05, T03B01, T03B02, T03B03, T03B04, T03B05 |
| IG-4 | `ig-4` | PH4 | T04A01, T04A02, T04A03, T04B01, T04B02, T04B03, T04B04, T04X01 |
| IG-5 | `ig-5` | PH5 | T05A01, T05A02, T05A03, T05B01, T05B02, T05B03 |
| IG-6 | `ig-6` | PH6 | T06A01, T06A02, T06A03, T06A04, T06B01, T06B02, T06B03, T06B04, T06B05 |
| IG-7 | `ig-7` | PH7 | T07A01, T07A02, T07A03, T07A04, T07B01, T07B02, T07B03, T07B04, T07B05, T07X01 |
| IG-8 | `ig-8` | PH8 | T08A01, T08A02, T08A03, T08A04, T08A05, T08A06, T08B01, T08B02, T08B03, T08B04, T08B05 |
| IG-9 | `ig-9` | PH9 | T09A01, T09A02, T09A03, T09A04, T09B01, T09B02, T09B03, T09B04, T09X01, T09X02 |
| IG-10 | `ig-10` | PH10 | T10A01, T10A02, T10A03, T10A04, T10B01, T10B02, T10X01, T10X02 |
| IG-11 | `ig-11` | PH11 | T11X01, T11X02 |

Integration tests in one line each (full text in `docs/testing-strategy.md` section 3):

| ID | Acceptance |
|---|---|
| IT-0 | On a clean clone `make setup` and `make verify` are green and `tools/validate_docs.py` and `tools/check_imports.py` run in CI; tag `contracts-v1` exists with its change-log row; secrets are rotated (T00A02); the two dev-time plugins are installed in both members' coding agents with versions recorded; spike results S1 and S7 are recorded and the matching switches in `docs/decisions.md` are filled (S3 is already recorded) |
| IT-1 | `alembic upgrade head` and `alembic check` pass and every trigger and unique index in `db-schema.md` has a test; Clock, JobQueue, AuditLog (chain equals the vectors) and IdempotencyStore pass; the hosted URL serves `/health` and the webhook stub returns 200 and stores the raw body; the route-table and Merchant OpenAPI contract tests pass; every port has a fake with a behaviour test; the frontend builds and its boundary lint passes; S2 follow-up (O1, O2) and S6 are recorded |
| IT-2 | Gateway Sandbox tests C-01 to C-07 pass and the request-ID examples reproduce; the fake router's failure injection works; PT-09 passes for the ledger; register, login and roles work; publishing a pool computes the rules hash from the vectors and enqueues its jobs; the AI adapter validates, retries once and imports nothing from payments; S4, S8 and S13 are recorded |
| IT-3 | PT-07, PT-10 and PT-12 pass for the buyer-order engine and seat control; 200 parallel joins by one account give one entry and receipts verify; search returns the same shape from the Postgres backend (and Elastic if S8 passed) and PT-14 passes; PayPal Login behaves per `DEDUPE_MODE`; pool close publishes commitments and the root and late joins are impossible; S5, S10, S11 and S12 are recorded and the APIMatic trial started in PH3 |
| IT-4 | Pipeline test with `FakePaymentRouter` and `FakeAI`: create and publish a pool; 12 users join through intake (some caps low enough to be priced out); close; demo seed; allocate two lots and a waitlist; force-award; `lot.open_checkout` creates offers and refills priced-out seats from the waitlist; all authorizations are captured by the sweep and the lot is FUNDED; the audit chain verifies; the public audit payload recomputes with the vectors; the real `AllocationReadService` and `MerchantDirectory` are wired through `wiring.py` |
| IT-5 | One real Sandbox buyer through the app on the redirect path: offer, approval, server-side authorize, then void (and capture then refund in a second run) with the ledger equal to PayPal GETs; the checkout UI shows notices and labels; the failure path with the fake router ends at net zero (PT-11); the auction rules engine reproduces the vectors; merchant profile and sealed bids with receipts pass their tests |
| IT-6 | Real Sandbox: authorizations are captured by the sweep and the lot is FUNDED; a second lot misses its minimum and ends with void then refund at net zero; webhooks are verified (if S5 passed) or the reconciler is the only path; payload ladder at the S4 level; bids go through quote parsing with merchant confirmation and reconciliation flags; lot handlers award and open checkout from real bids; merchant API keys and MerchantAuth pass PT-15; Buyer UI v1 completes an entry through the receipt |
| IT-7 | Full live flow with at least three real Sandbox buyers: entries, close, seed, allocation, two lots; a merchant bids through the console with a pasted quote and a second merchant through an API key; award; checkout with the SDK popup (if S13 passed) or redirect; one offer expires and refills; lot 1 is FUNDED; lot 2 ends with void then refund at net zero; the agent API and the FairPool MCP server join, list and withdraw an entry; the merchant-lane search and the LOW_SIMILARITY flag work; the ops console shows both lots; no manual database edits |
| IT-8 | Fulfillment CSV, shipments (tracker submitted if S12 passed), the verification manifest and the live verification endpoint work for a FUNDED lot; the PayPal MCP read-only verification (or the endpoint) confirms totals; the merchant console tabs work against the real backend; the Merchant Agent API has ten operations; observability, security and rate limits pass; a simulation pool of 10,000 entries allocates in under 10 seconds; S9 is recorded |
| IT-9 | All test layers are green: the fault suite F1 to F30 (F17 and F18 as disclosed limits), the Sandbox contract suite C-01 to C-18, concurrency and property suites and the AI evaluation baseline; the public audit page and verify-my-place reproduce the vectors; the README draft is complete; feature freeze, after which only fixes merge |
| IT-10 | Two consecutive clean end-to-end rehearsals from `make demo-reset` with no manual database intervention; SDKs generated and smoke-tested; Devpost text drafted; the demo video recorded; tag `rc1` |
| IT-11 | Submission verified: repository, license, video and links open while logged out; Devpost fields complete; no edits after the deadline |

## 4. Capacity check (computed from the task sizes)

Sizes are agent-assisted person-days: S = 0.25, M = 0.5, L = 1, XL = 1.5. Each member has one person-day per working day, and the plan allows 22 working days in total (PH0 to PH11). Tasks owned by both members count half to each.

| Phase | Days | Member A load | Member B load |
|---|---|---|---|
| PH0 | 2 | 1.25 (62%) | 1.75 (88%) |
| PH1 | 2 | 2.00 (100%) | 1.75 (88%) |
| PH2 | 2 | 2.00 (100%) | 2.00 (100%) |
| PH3 | 2 | 2.25 (112%) | 2.00 (100%) |
| PH4 | 2 | 3.00 (150%) | 3.25 (162%) |
| PH5 | 2 | 2.50 (125%) | 2.50 (125%) |
| PH6 | 2 | 3.00 (150%) | 3.50 (175%) |
| PH7 | 2 | 3.25 (162%) | 4.00 (200%) |
| PH8 | 2 | 3.50 (175%) | 3.50 (175%) |
| PH9 | 1 | 3.00 (300%) | 3.75 (375%) |
| PH10 | 2 | 2.50 (125%) | 2.00 (100%) |
| PH11 | 1 | 0.38 (38%) | 0.38 (38%) |
| **Total** | 22 | **28.62 (130%)** | **30.38 (138%)** |

**What this means, stated plainly.** At these sizes the full scope needs about 130% of Member A's capacity and 138% of Member B's. The break-even velocity factor is 0.77 for Member A and 0.72 for Member B: if agent-assisted work is that much faster than the sizes assume, the plan fits; if not, it does not. The crunch window is PH8 and PH9. No task has been removed to make the numbers look better.

**Schedule position on Oct 27, 2026 (no scope removed).** The plan budgets 22 working days. The Devpost deadline is Nov 12, 12:00 pm PT (Nov 13, 1:30 am IST) and submission is planned for Nov 11, which leaves about 15 working days from Oct 27. At the sizes above that is roughly 1.9 times the speed the sizes assume for Member A and 2.0 times for Member B. Nothing is cut here; the owner decides in writing in `docs/decisions.md` (rule below). Measure velocity in the first two phases and decide at IG-2, not IG-4, if the plan is started late.

**Change set C1 (Oct 29, 2026): `PAYMENT_MODE=vault_charge` and `BID_PRICING_MODE=flat_delivered`.** No task is added or removed; these task texts are overridden as follows, and the contracts `vault-charge.md` and `flat-delivered-bids.md` win over any older task wording. The owner re-estimates at IG-1 (the vault adapter, token encryption and consent UI add work; the approval UI and capture sweep shrink in vault mode).
- T03A01: the transition engine also implements BO-23 to BO-27.
- T03A02: in vault mode there is no offer expiry timer; `seat_locked_until` covers the charge only.
- T03B01: joining needs the consent text, the cap and an ACTIVE saved permission (`vault_tokens`, encrypted with `VAULT_TOKEN_KEY`); an entry without it is rejected at close.
- T04A01: in vault mode `lot.open_checkout` creates every seat's order in OFFERED and enqueues `order.vault_charge` with `VAULT_CHARGE_CONCURRENCY`.
- T04A02, T04A03 (fake router): implement `charge_vault`, the precheck and the funding trigger on completed captures; the authorize and capture-sweep path stays for the fallback mode.
- T04X01: the first integration runs pool to charged lot in vault mode.
- T05A01, T05A02, T05A03: the real path saves PayPal by redirect, charges with the saved permission, and the failure path refunds every completed capture and deletes the saved permissions; the UI shows Save PayPal, Charged and Charge failed. Contract tests VC-01 to VC-06 run here.
- T05B02, T06B02, T06B03, T08B01: bid validation enforces the flat delivered price (shipping table and itemised tax rejected).
- T06A04: only payload level 1 is needed in flat mode (no breakdown); keep the ladder for the fallback.
- T06B05, T07B01: Buyer UI shows the consent text, the cap, the saved-PayPal step and, later, Charged or Charge failed.
- T07A01: the SDK v6 approval is the fallback path only.

**How we manage it**

1. **Measure early.** At gates IG-2 and IG-4 each member records planned versus actual days for the phase in `docs/progress.md` (Velocity log). The plan is re-estimated at IG-4 with real velocity.
2. **Pull forward.** When a member is blocked waiting for the other's merge, they start any unblocked UI task (contract-first) or spike instead of idling.
3. **Protect the critical path.** Order of protection when time runs short, highest first: the money path (T02A01 to T06A03), the pool, allocation and auction path (T03B01 to T06B03), the buyer and merchant surfaces, the agentic and verification surfaces, polish.
4. **Decision rule.** If the measured velocity at IG-4 shows the remaining work does not fit, the owner decides in writing which candidates below to move, in this order of least product loss per day saved. Nothing moves without that entry.

Candidates for the owner's decision (none is applied): (1) T09A04 top-up after FUNDED, a stretch item not in the idea text; (2) the Elastic backend inside T03B02 and T07B05, keeping the Postgres search (the retrieval interface does not change); (3) T08B03 and T08B05, the Zapier bridge, keeping the FairPool MCP server as the agentic path; (4) T08A04, the PayPal MCP copilot, keeping the verification endpoint; (5) T10A04, SDK generation, shipping the OpenAPI document and a hand-written minimal client; (6) the simulation scale in T08B04, 2,000 instead of 10,000 entries.

## 5. Integration traceability

| Decision | What it adds | Spikes | Tasks |
|---|---|---|---|
| INT-1 Elastic | Hybrid search for intake candidates, demand board and agents; advisory similarity | S8 | T02B04, T03B02, T07B05, T09B02 |
| INT-2 Zapier MCP | Managed-mode bridge to the Agent API | S9 | T08B03, T08B05 |
| INT-3 FairPool MCP | Four-tool MCP server | none | T07B03 |
| INT-4 APIMatic | Plugin at development time; Merchant SDKs and portal | S11 | T00A01, T03B05, T10A04 |
| INT-5 Agent Toolkit | Not in the payment path; development plugin only | none | T00A01 |
| INT-6 PayPal MCP | Read-only verification, manifest, verification endpoint | S10 | T03A04, T08A01, T08A04 |
| INT-7 JS SDK v6 | Popup approval with redirect fallback | S13 | T02B05, T07A01 |
| INT-8 Shipment tracking | Tracker submission after shipping | S12 | T03A05, T08A01 |
| INT-9 Merchant Agent API | Ten-operation key-authenticated API | none | T01B01, T06B04, T07B04, T08A03, T08B02 |

## 6. Requirement coverage

Every FR in `docs/product-spec.md` is covered by at least one task (checked by `tools/validate_docs.py`):

| Requirement | Tasks |
|---|---|
| FR-AD-01 | T00B01, T03B04, T04B04, T09B01 |
| FR-AD-02 | T01A02 |
| FR-AG-01 | T07B02, T07B03 |
| FR-AG-02 | T07B02 |
| FR-AI-01 | T02B03, T04B01 |
| FR-AI-02 | T06B02 |
| FR-AI-03 | T08B04 |
| FR-AI-04 | T06B01 |
| FR-AI-05 | T09B02 |
| FR-AU-01 | T05B01, T06B03 |
| FR-AU-02 | T05B02, T06B01 |
| FR-AU-03 | T05B01, T05B02 |
| FR-AU-04 | T05B03 |
| FR-AU-05 | T05B03 |
| FR-AU-06 | T05B03, T06B03 |
| FR-AU-07 | T05B03 |
| FR-CK-01 | T04A01, T05A02 |
| FR-CK-02 | T04A01, T05A02, T07A01 |
| FR-CK-03 | T03A02, T07A02 |
| FR-CK-04 | T03A01, T06A03 |
| FR-CK-05 | T04A02, T05A01 |
| FR-FN-01 | T02A02, T04A02, T05A01 |
| FR-FN-02 | T04A03, T06A01, T07X01 |
| FR-FN-03 | T06A02 |
| FR-FN-04 | T04A03, T05A03, T06A01, T09A04 |
| FR-FN-05 | T05A03, T06A01 |
| FR-FN-06 | T05A02, T07A03 |
| FR-FN-07 | T00B03, T02A02, T06A01, T07A03 |
| FR-FN-08 | T02A03, T06A03, T09A01 |
| FR-HK-01 | T00A01, T10A02, T11X01 |
| FR-HK-02 | T00A01, T00A04, T01A03, T01B03, T09A03, T10A02, T11X01 |
| FR-HK-03 | T09X01, T11X01 |
| FR-HK-04 | T10B02, T10X01, T10X02, T11X01, T11X02 |
| FR-HK-05 | T10A03, T11X01 |
| FR-HK-06 | T09B04, T10B02 |
| FR-ID-01 | T02B01 |
| FR-ID-02 | T03B03 |
| FR-ID-03 | T03B01, T03B03 |
| FR-ID-04 | T04A02 |
| FR-ID-05 | T02B01, T08A06 |
| FR-IG-01 | T02B04, T03B02, T07B05 |
| FR-IG-02 | T07B03 |
| FR-IG-03 | T08B03, T08B05 |
| FR-IG-04 | T01B01, T06B04, T07B04, T08A03 |
| FR-IG-05 | T03B05, T10A04 |
| FR-IG-06 | T02B05, T07A01 |
| FR-IG-07 | T03A04, T08A01, T08A04 |
| FR-IG-08 | T03A05, T08A01 |
| FR-IG-09 | T00A01, T09X01 |
| FR-IN-01 | T04B01 |
| FR-IN-02 | T04B01 |
| FR-IN-03 | T04B01, T06B05 |
| FR-IN-04 | T03B01 |
| FR-IN-05 | T04B01 |
| FR-IN-06 | T04B01 |
| FR-IN-07 | T02B02 |
| FR-IN-08 | T04B01 |
| FR-LT-01 | T02B02, T04B03 |
| FR-LT-02 | T04B03 |
| FR-LT-03 | T02B02, T06B03 |
| FR-LT-04 | T04A01, T04B03, T04X01 |
| FR-LT-05 | T04B03, T06A04 |
| FR-LT-06 | T02B02 |
| FR-OP-01 | T07A04 |
| FR-OP-02 | T08A05 |
| FR-PP-01 | T02A01, T05A01, T06A04, T09A02 |
| FR-PP-02 | T00B02 |
| FR-PP-03 | T09B04, T09X01 |
| FR-PP-04 | T09X01 |
| FR-PP-05 | T00A02, T10A02 |
| FR-PP-06 | T00A03, T08A06 |
| FR-SL-01 | T02B02, T06B05 |
| FR-SL-02 | T03B01 |
| FR-SL-03 | T07B02 |
| FR-SL-04 | T02B02, T03B04 |
| FR-SL-05 | T04B03 |
| FR-SL-06 | T09B01 |
| FR-SL-07 | T00B01, T04B02 |
| FR-SM-01 | T08B04 |
| FR-UI-01 | T06B05 |
| FR-UI-02 | T07A01, T07B01 |
| FR-UI-03 | T07B01 |
| FR-UI-04 | T07B05, T08B01 |
| FR-UI-05 | T08B02 |
| FR-UI-06 | T08A01, T08A02 |
| FR-UI-07 | T06B04, T08B02 |
| FR-UI-08 | T01B03, T09B04 |

## 7. Sizing and conventions

Sizes: S = 0.25 day, M = 0.5, L = 1, XL = 1.5 (agent-assisted). Task IDs: `T` + two-digit phase + owner letter (A, B or X for both) + two-digit number. Branches: `a/<TASK-ID>-slug` or `b/<TASK-ID>-slug`. A STRETCH task is in the plan but not required for the idea's functionality; it is still scheduled and tested if done.

## PH0: Bootstrap and contract freeze (gate IG-0)

**Goal.** Both members can start parallel work: repository, secrets, skeleton, CI and the shared pure library exist; contracts are frozen as `contracts-v1`; the two spikes that shape the design (S1 login, S7 payee routing) are recorded.

**Entry condition.** The docs folder is placed in the repository; the owner has the Sandbox account and the plugin accounts.

**Exit.** IT-0: On a clean clone `make setup` and `make verify` are green and `tools/validate_docs.py` and `tools/check_imports.py` run in CI; tag `contracts-v1` exists with its change-log row; secrets are rotated (T00A02); the two dev-time plugins are installed in both members' coding agents with versions recorded; spike results S1 and S7 are recorded and the matching switches in `docs/decisions.md` are filled (S3 is already recorded).

**Watch.** Everyone branches from T00A01, so it merges first; contract questions found late; S1 and S7 need the owner's hands.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T00A01 | A | S | none | Repository bootstrap |
| T00A02 | A | S | none | Secrets hygiene |
| T00A03 | A | S | T00A01 | API and worker skeleton, settings, host guard |
| T00A04 | A | S | T00A01 | Containers, CI and repo tools |
| T00B01 | B | L | T00A01 | Pure domain library with shared vectors |
| T00B02 | B | S | none | Spike S1 Log in with PayPal |
| T00B03 | B | S | none | Spike S7 payee-email routing |
| T00X01 | AB | M | none | Contract review and freeze |

### T00A01: Repository bootstrap

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH0. **Merge gate:** IG-0. **Depends on:** none.
- **Read first:** scaffold.md §1, §8, §9, §10; AGENTS.md §4a.
- **Create or change:** repository root, `.github/**`, `Makefile`, `pyproject.toml`, `docs/` copy, `LICENSE`.
- **Acceptance:** Structure from scaffold.md section 1 exists; docs/ copied (including fairpool-idea.md and system-design.md); `make setup` and `make verify` pass on a clean clone; LICENSE (MIT) detected by GitHub; CODEOWNERS, templates and the root AGENTS.md Codex instruction file in place (no CLAUDE.md); the coding agent environment(s) have the ContextMatic and PayPal AI Toolkit plugins installed with versions recorded in progress.md; the graphify skill for Codex is installed and the tool-generated `## graphify` block is in AGENTS.md.
- **Tests that prove it:** `make setup`; `make verify`; GitHub shows the MIT license.
- **Requirements and invariants:** FR-HK-01, FR-HK-02, FR-IG-09.

### T00A02: Secrets hygiene

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH0. **Merge gate:** IG-0. **Depends on:** none.
- **Read first:** AGENTS.md §3 rule 2; config-and-errors.md §1.
- **Create or change:** `.env.example`, `.pre-commit-config.yaml`, `.gitleaks.toml`, `backend/src/fairpool/logging.py`.
- **Acceptance:** Sandbox REST secret rotated and the buyer password changed; unused NVP and SOAP credentials disabled; `.env.example` has names only; gitleaks runs in pre-commit and CI; the log redaction filter has a test.
- **Tests that prove it:** `tests/unit/test_log_redaction.py`; gitleaks CI job.
- **Requirements and invariants:** FR-PP-05, I14.

### T00A03: API and worker skeleton, settings, host guard

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH0. **Merge gate:** IG-0. **Depends on:** T00A01.
- **Read first:** config-and-errors.md §1; paypal-adapter.md §1; scaffold.md §1.
- **Create or change:** `backend/src/fairpool/{config,main,worker,logging}.py`, `api/app.py`, `api/errors.py`.
- **Acceptance:** App factory with /health and /ready; worker loop; typed Settings for every variable in config-and-errors.md; any host other than the two PayPal Sandbox hosts raises ForbiddenHost; JSON logs with correlation IDs.
- **Tests that prove it:** `tests/unit/test_host_guard.py`; `tests/unit/test_settings.py`.
- **Requirements and invariants:** FR-PP-06, I14.

### T00A04: Containers, CI and repo tools

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH0. **Merge gate:** IG-0. **Depends on:** T00A01.
- **Read first:** scaffold.md §3, §5, §6; testing-strategy.md §1.
- **Create or change:** `deploy/**`, `.github/workflows/ci.yml`, `tools/**`, `Makefile`.
- **Acceptance:** Dockerfiles and docker-compose bring up db, api, worker and frontend; GitHub Actions run every job in scaffold.md section 6; tools/check_imports.py, tools/validate_docs.py and tools/export_merchant_openapi.py exist and run in make verify.
- **Tests that prove it:** CI is green; `tests/unit/test_check_imports.py`; `tests/unit/test_validate_docs.py`.
- **Requirements and invariants:** FR-HK-02.

### T00B01: Pure domain library with shared vectors

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH0. **Merge gate:** IG-0. **Depends on:** T00A01.
- **Read first:** fairness-and-hashing.md (all); state-machines.md; `contracts/vectors/fairness_v1.json`; testing-strategy.md PT-03 to PT-07.
- **Create or change:** `backend/src/fairpool/domain/**`, `backend/tests/unit/test_fairness_vectors.py`.
- **Acceptance:** money, canonical JSON, hashing, commitments, Merkle with proofs, rank, tier resolution, bid ranking and the state-machine tables loaded from state-machines.md; every value in vectors/fairness_v1.json reproduced; PT-03, PT-04, PT-05 and PT-07 pass.
- **Tests that prove it:** `test_fairness_vectors`; PT-03; PT-04; PT-05; PT-07.
- **Requirements and invariants:** FR-SL-07, FR-AD-01, I11.

### T00B02: Spike S1 Log in with PayPal

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH0. **Merge gate:** IG-0. **Depends on:** none.
- **Read first:** spikes.md S1; paypal-adapter.md; config-and-errors.md.
- **Create or change:** `docs/spike-results.md` (S1 section); `docs/decisions.md` §4 `DEDUPE_MODE`.
- **Acceptance:** S1 recorded in spike-results.md; DEDUPE_MODE set in decisions.md.
- **Tests that prove it:** results recorded with sanitized facts only.
- **Requirements and invariants:** G1, G2, FR-PP-02.

### T00B03: Spike S7 payee-email routing

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH0. **Merge gate:** IG-0. **Depends on:** none.
- **Read first:** spikes.md S7; decisions.md §4.
- **Create or change:** `docs/spike-results.md` (S7 section); owner decision in `docs/decisions.md` §4.
- **Acceptance:** S7 recorded; the owner records the PAYMENT_ROUTER decision in decisions.md.
- **Tests that prove it:** results recorded; decision recorded.
- **Requirements and invariants:** G11, FR-FN-07.

### T00X01: Contract review and freeze

- **Owner:** Both members. **Size:** M (0.5 day). **Phase:** PH0. **Merge gate:** IG-0. **Depends on:** none.
- **Read first:** all files in docs/contracts/; spikes.md; decisions.md §4.
- **Create or change:** docs/contracts/README.md (change log); docs/decisions.md §4; git tag `contracts-v1`.
- **Acceptance:** Both members read every file in docs/contracts/ and docs/spikes.md; each question is closed or becomes a change request; the decisions.md section 4 rows for S1, S2, S3 and S7 are filled; tag `contracts-v1` pushed; change-log row completed.
- **Tests that prove it:** review only; the tag exists and the change-log row is filled.
- **Requirements and invariants:** I9, I10.

## PH1: Data, platform and shell foundations (gate IG-1)

**Goal.** Schema migration 0001 and the database triggers; jobs, audit chain and idempotency; a deployed HTTPS skeleton; API schemas with the route-table test and the Merchant API OpenAPI skeleton; every port has a fake; the frontend shell builds.

**Entry condition.** IG-0 passed and `contracts-v1` tagged.

**Exit.** IT-1: `alembic upgrade head` and `alembic check` pass and every trigger and unique index in `db-schema.md` has a test; Clock, JobQueue, AuditLog (chain equals the vectors) and IdempotencyStore pass; the hosted URL serves `/health` and the webhook stub returns 200 and stores the raw body; the route-table and Merchant OpenAPI contract tests pass; every port has a fake with a behaviour test; the frontend builds and its boundary lint passes; S2 follow-up (O1, O2) and S6 are recorded.

**Watch.** Migration triggers are fiddly; Render HTTPS and the webhook stub are prerequisites for S5 and S13; fakes can drift from the ports.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T01A01 | A | L | T00A01 | Database foundation and migration 0001 |
| T01A02 | A | M | T01A01 | Platform services |
| T01A03 | A | S | T00A03, T00A04 | Deploy the skeleton to Render |
| T01A04 | A | S | T00A02 | Spike S2 follow-up |
| T01B01 | B | M | T00B01 | API schemas, route-table test and Merchant API OpenAPI |
| T01B02 | B | M | T00A01, T00B01 | Port fakes and award fixture |
| T01B03 | B | M | T00A01 | Frontend scaffold |
| T01B04 | B | S | none | Spike S6 beacon and sandbox buyers |

### T01A01: Database foundation and migration 0001

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH1. **Merge gate:** IG-1. **Depends on:** T00A01.
- **Read first:** db-schema.md (all); fairness-and-hashing.md §8; scaffold.md §1.
- **Create or change:** `backend/migrations/**`, `backend/src/fairpool/db/**`, per-module `models.py`.
- **Acceptance:** Alembic configured; migration 0001 creates every extension, enum, table, index, trigger and constraint in db-schema.md; `alembic upgrade head` on an empty database and `alembic check` pass; one test per trigger and unique index.
- **Tests that prove it:** `tests/unit/test_schema_contract.py`; `tests/integration/test_triggers.py`; `alembic check`.
- **Requirements and invariants:** I10, I12, I15.

### T01A02: Platform services

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH1. **Merge gate:** IG-1. **Depends on:** T01A01.
- **Read first:** domain-ports.md §1, §2, §5; fairness-and-hashing.md §8; config-and-errors.md §1.
- **Create or change:** `backend/src/fairpool/infra/**`, `fakes/{clock,jobs,audit,idempotency}.py`.
- **Acceptance:** Clock, JobQueue (claim with SKIP LOCKED, concurrency and dedupe keys, backoff), AuditLog (hash chain matching the vectors) and IdempotencyStore implemented per domain-ports.md, each with its fake and tests.
- **Tests that prove it:** `tests/unit/test_jobs.py`; `tests/unit/test_audit_chain.py`; `tests/unit/test_idempotency.py`.
- **Requirements and invariants:** FR-AD-02, I10, I15.

### T01A03: Deploy the skeleton to Render

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH1. **Merge gate:** IG-1. **Depends on:** T00A03, T00A04.
- **Read first:** scaffold.md §11; paypal-adapter.md §8.
- **Create or change:** `deploy/render.yaml`; the `/webhooks/paypal` stub route.
- **Acceptance:** Hosted HTTPS URL serves /health; POST /webhooks/paypal stub stores the raw body and headers and returns 200; URL recorded in progress.md.
- **Tests that prove it:** hosted `/health` returns 200; stub returns 200 and stores the raw body.
- **Requirements and invariants:** FR-HK-02.

### T01A04: Spike S2 follow-up

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH1. **Merge gate:** IG-1. **Depends on:** T00A02.
- **Read first:** spike-results.md open questions O1 and O2; paypal-adapter.md §4.
- **Create or change:** `docs/spike-results.md`.
- **Acceptance:** Open questions O1 and O2 in spike-results.md answered with the exact authorization field read and the void-replay issue name.
- **Tests that prove it:** answers recorded.
- **Requirements and invariants:** G3.

### T01B01: API schemas, route-table test and Merchant API OpenAPI

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH1. **Merge gate:** IG-1. **Depends on:** T00B01.
- **Read first:** api.md (all); config-and-errors.md §4; scaffold.md §1.
- **Create or change:** `api/schemas.py`, `api/deps.py`, `api/merchant_api/app.py`, `tools/export_merchant_openapi.py`.
- **Acceptance:** Pydantic models for every payload in api.md; the route-table test equals the endpoint table; the Merchant Agent API sub-app exports an OpenAPI document with exactly the ten operations and fixed operationIds (test_merchant_openapi_contract).
- **Tests that prove it:** `tests/unit/test_api_contract.py`; `tests/unit/test_merchant_openapi_contract.py`.
- **Requirements and invariants:** FR-IG-04.

### T01B02: Port fakes and award fixture

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH1. **Merge gate:** IG-1. **Depends on:** T00A01, T00B01.
- **Read first:** domain-ports.md (all); fairness-and-hashing.md.
- **Create or change:** `backend/src/fairpool/ports.py`, `fakes/**` (except those Member A writes in T01A02, T02A02, T02A03).
- **Acceptance:** A fake for every port in domain-ports.md with behaviour tests; make_award_fixture helper including waitlist and priced-out cases.
- **Tests that prove it:** `tests/unit/test_fakes_behaviour.py`.
- **Requirements and invariants:** I10.

### T01B03: Frontend scaffold

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH1. **Merge gate:** IG-1. **Depends on:** T00A01.
- **Read first:** scaffold.md §1, §5 rule 8, §12; product-spec.md FR-UI-01 to FR-UI-08.
- **Create or change:** `frontend/**`.
- **Acceptance:** Vite React TypeScript Tailwind app with routing for every route in scaffold.md section 12, generated API client, shared label components, stub pages per area and the eslint boundary rule for area imports; tsc, eslint and build pass.
- **Tests that prove it:** `tsc`, eslint and build pass; boundary lint test.
- **Requirements and invariants:** FR-HK-02, FR-UI-08.

### T01B04: Spike S6 beacon and sandbox buyers

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH1. **Merge gate:** IG-1. **Depends on:** none.
- **Read first:** spikes.md S6; config-and-errors.md §1.
- **Create or change:** `docs/spike-results.md` (S6 section).
- **Acceptance:** S6 recorded; BEACON_MODE set; six US personal sandbox buyers created and each approves a USD 1.00 order.
- **Tests that prove it:** six US personal sandbox buyers each approve a USD 1.00 order.
- **Requirements and invariants:** G6, F27.

## PH2: Core engines I: PayPal gateway, ledger, identity, catalog, AI adapter (gate IG-2)

**Goal.** The raw-REST PayPal gateway with request-ID derivation and error classes; routers and the fake gateway with failure injection; the ledger; accounts and sessions; pool templates with the rules hash; the AI adapter with run logging. Spikes S4, S8 and S13 recorded.

**Entry condition.** IG-1 passed: schema, platform services, fakes and the shell are on `main`.

**Exit.** IT-2: Gateway Sandbox tests C-01 to C-07 pass and the request-ID examples reproduce; the fake router's failure injection works; PT-09 passes for the ledger; register, login and roles work; publishing a pool computes the rules hash from the vectors and enqueues its jobs; the AI adapter validates, retries once and imports nothing from payments; S4, S8 and S13 are recorded.

**Watch.** Gateway fidelity against the Sandbox; AI model names; keeping the rules hash identical to the vectors.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T02A01 | A | L | T00A02, T00A03 | PayPal gateway (raw REST) |
| T02A02 | A | M | T02A01 | Payment routers and fake gateway |
| T02A03 | A | S | T01A01, T01A02 | Ledger service |
| T02A04 | A | S | T02A01 | Spike S4 payload ladder |
| T02B01 | B | M | T01A01, T01A02, T00B01, T01B02 | Identity and notifier |
| T02B02 | B | M | T02B01 | Catalog, pool templates, admin publish and rules |
| T02B03 | B | M | T01B02 | AI adapter and run logging |
| T02B04 | B | S | none | Spike S8 Elastic hybrid search |
| T02B05 | B | S | T01A03 | Spike S13 JavaScript SDK v6 |

The owner-approved Phase 2 execution amendment (2026-10-31) replaces the planned
Anthropic dependency with Gemini via google-genai, adds the seven foundation
repairs and migration 0002, and requires the 160-case/three-run adversarial gate.
Execution follows payment gateway/router/ledger, identity/catalog, Gemini, then
spikes/evidence. Keep exactly three commits, with one authorized intermediate
instructions/contracts commit. Current verified and pending outcomes are recorded
in `evidence/phase2/README.md`; external pending checks cannot close IG-2.

### T02A01: PayPal gateway (raw REST)

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH2. **Merge gate:** IG-2. **Depends on:** T00A02, T00A03.
- **Read first:** paypal-adapter.md (all); config-and-errors.md §1; spike-results.md S2.
- **Create or change:** `adapters/paypal/{gateway,token,keys,errors}.py`, `tests/contract_sandbox/**`.
- **Acceptance:** Implements every PayPalGateway method in paypal-adapter.md including the tracker call; token cache; request-ID derivation reproduces the documented examples; error classes of section 7; sanitized logs; unit tests with recorded fixtures; sandbox tests C-01 to C-07 pass.
- **Tests that prove it:** `tests/unit/test_request_ids.py`; `tests/unit/test_error_classes.py`; sandbox C-01 to C-07.
- **Requirements and invariants:** FR-PP-01, I9, I14.

### T02A02: Payment routers and fake gateway

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH2. **Merge gate:** IG-2. **Depends on:** T02A01.
- **Read first:** paypal-adapter.md §9; domain-ports.md; config-and-errors.md §1.
- **Create or change:** `adapters/paypal/{routers,fake_gateway,fault}.py`, `fakes/payments.py`.
- **Acceptance:** FakePaymentRouter with failure injection (deny authorize, decline or pend capture, timeout after send, drop webhooks); SingleSellerRouter with its label; payee_email and platform routers present but disabled; router chosen by PAYMENT_ROUTER.
- **Tests that prove it:** `tests/unit/test_routers.py`; `tests/unit/test_fake_gateway_failures.py`.
- **Requirements and invariants:** FR-FN-01, FR-FN-07, I12.

### T02A03: Ledger service

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH2. **Merge gate:** IG-2. **Depends on:** T01A01, T01A02.
- **Read first:** domain-ports.md §2 (Ledger); db-schema.md (ledger_entries); state-machines.md.
- **Create or change:** `modules/ledger/**`.
- **Acceptance:** record, net_paid_cents and completed_capture_count per domain-ports.md; a duplicate key returns False; PT-09 passes.
- **Tests that prove it:** PT-09; `tests/unit/test_ledger_idempotency.py`.
- **Requirements and invariants:** FR-FN-08, I4, I5.

### T02A04: Spike S4 payload ladder

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH2. **Merge gate:** IG-2. **Depends on:** T02A01.
- **Read first:** spikes.md S4; paypal-adapter.md §5.
- **Create or change:** `docs/spike-results.md` (S4); `docs/decisions.md` §4.
- **Acceptance:** S4 recorded; PAYPAL_PAYLOAD_LEVEL set in decisions.md.
- **Tests that prove it:** highest accepted payload level recorded.
- **Requirements and invariants:** G8.

### T02B01: Identity and notifier

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH2. **Merge gate:** IG-2. **Depends on:** T01A01, T01A02, T00B01, T01B02.
- **Read first:** api.md §1; db-schema.md (identity tables); config-and-errors.md §3, §4.
- **Create or change:** `modules/identity/**`, `modules/notify/**`, `api/routers/auth.py`.
- **Acceptance:** register, login, logout, sessions, CSRF and roles; the Notifier writes notifications surfaced by /me; tests.
- **Tests that prove it:** `tests/integration/test_auth.py`; `tests/unit/test_csrf.py`.
- **Requirements and invariants:** FR-ID-01, FR-ID-05.

### T02B02: Catalog, pool templates, admin publish and rules

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH2. **Merge gate:** IG-2. **Depends on:** T02B01.
- **Read first:** db-schema.md (pools); fairness-and-hashing.md §7; api.md; product-spec.md FR-LT-03.
- **Create or change:** `modules/catalog/**`, `modules/pools/{admin,rules}.py`, `api/routers/admin_pools.py`.
- **Acceptance:** Admin create, publish and cancel; rules document and rules_hash match the vectors; publish enqueues pool.open, pool.close and search.index; the lots-may-differ disclosure is in the rules; search_text derived.
- **Tests that prove it:** `tests/unit/test_rules_hash_vectors.py`; `tests/integration/test_publish_enqueues_jobs.py`.
- **Requirements and invariants:** FR-IN-07, FR-SL-01, FR-SL-04, FR-LT-01, FR-LT-03, FR-LT-06.

### T02B03: AI adapter and run logging

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH2. **Merge gate:** IG-2. **Depends on:** T01B02.
- **Read first:** ai-schemas.md (all); domain-ports.md AiRunLogger; AGENTS.md §8.
- **Create or change:** `adapters/ai/**`, `modules/intake/run_log.py`.
- **Acceptance:** AIClient with Gemini and Fake implementations; AiRunLogger writes ai_runs; schema validation, one retry, input limits and untrusted wrapping; no payments imports.
- **Tests that prove it:** `tests/unit/test_ai_schema_validation.py`; `tests/unit/test_ai_no_payments_imports.py`.
- **Requirements and invariants:** FR-AI-01, I2.

### T02B04: Spike S8 Elastic hybrid search

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH2. **Merge gate:** IG-2. **Depends on:** none.
- **Read first:** spikes.md S8; ai-schemas.md §7.
- **Create or change:** `docs/spike-results.md` (S8 section).
- **Acceptance:** S8 recorded; SEARCH_BACKEND set.
- **Tests that prove it:** request shapes and recall recorded.
- **Requirements and invariants:** G12, FR-IG-01.

### T02B05: Spike S13 JavaScript SDK v6

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH2. **Merge gate:** IG-2. **Depends on:** T01A03.
- **Read first:** spikes.md S13; paypal-adapter.md §12.
- **Create or change:** `docs/spike-results.md` (S13 section); scratch page not committed.
- **Acceptance:** S13 recorded; PAYPAL_APPROVAL_UI and PAYPAL_SDK_AUTH set.
- **Tests that prove it:** initialisation mode and callback fields recorded.
- **Requirements and invariants:** G17, FR-IG-06.

## PH3: Core engines II: buyer-order engine, seat control, join, search, PayPal Login, pool close (gate IG-3)

**Goal.** The buyer-order transition engine and seat control; idempotent pool join with signed receipts; the search service with the Postgres fallback and, if S8 passed, Elastic; PayPal Login per the S1 outcome; pool close with commitments. Spikes S5, S10, S11 and S12 recorded.

**Entry condition.** IG-2 passed: gateway, ledger, identity, catalog and AI adapter are merged.

**Exit.** IT-3: PT-07, PT-10 and PT-12 pass for the buyer-order engine and seat control; 200 parallel joins by one account give one entry and receipts verify; search returns the same shape from the Postgres backend (and Elastic if S8 passed) and PT-14 passes; PayPal Login behaves per `DEDUPE_MODE`; pool close publishes commitments and the root and late joins are impossible; S5, S10, S11 and S12 are recorded and the APIMatic trial started in PH3.

**Watch.** Concurrency in join and seat control; APIMatic trial must start in PH3; webhook spike needs the deployed URL.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T03A01 | A | L | T02A03, T00B01 | Buyer-order transition engine |
| T03A02 | A | M | T03A01 | Offer expiry and seat control |
| T03A03 | A | S | T01A03 | Spike S5 webhooks |
| T03A04 | A | S | none | Spike S10 PayPal MCP read-only verification |
| T03A05 | A | S | none | Spike S12 shipment tracking |
| T03B01 | B | M | T02B01, T02B02, T00B01 | Pool join, receipts and events |
| T03B02 | B | M | T02B02, T02B04 | Search service and indexer |
| T03B03 | B | M | T02B01, T00B02 | PayPal Login link flow |
| T03B04 | B | S | T03B01 | Pool close |
| T03B05 | B | S | T01B01 | Spike S11 APIMatic generation |

### T03A01: Buyer-order transition engine

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** T02A03, T00B01.
- **Read first:** state-machines.md (buyer_order); db-schema.md; domain-ports.md; AGENTS.md rule 11.
- **Create or change:** `modules/checkout/engine.py`.
- **Acceptance:** Whitelist from state-machines.md enforced; row lock; audit, ledger and job in one transaction; IllegalTransition raised and alerted; PT-07 and PT-10 pass.
- **Tests that prove it:** PT-07; PT-10; `tests/unit/test_illegal_transitions.py`.
- **Requirements and invariants:** FR-CK-04, I10.

### T03A02: Offer expiry and seat control

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** T03A01.
- **Read first:** state-machines.md BO-15 to BO-17; domain-ports.md §5; registry I7.
- **Create or change:** `modules/checkout/expiry.py` (`offer.expire`).
- **Acceptance:** offer.expire respects the AUTHORIZING lock (I7); vacancy counter and lot.refill enqueue; PT-12 passes.
- **Tests that prove it:** PT-12; F5 test.
- **Requirements and invariants:** FR-CK-03, I7, I8, F5.

### T03A03: Spike S5 webhooks

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** T01A03.
- **Read first:** spikes.md S5; paypal-adapter.md §8.
- **Create or change:** `docs/spike-results.md` (S5 section).
- **Acceptance:** Listener registered for the seven event types; real lifecycle events verified or the failure recorded; WEBHOOKS_ENABLED set.
- **Tests that prove it:** verification result and event delivery recorded.
- **Requirements and invariants:** G5.

### T03A04: Spike S10 PayPal MCP read-only verification

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** none.
- **Read first:** spikes.md S10; paypal-adapter.md §13.
- **Create or change:** `docs/spike-results.md` (S10 section).
- **Acceptance:** S10 recorded; PAYPAL_MCP_VERIFICATION set.
- **Tests that prove it:** tool list, allowlist result and get-order argument recorded.
- **Requirements and invariants:** G14, FR-IG-07.

### T03A05: Spike S12 shipment tracking

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** none.
- **Read first:** spikes.md S12; paypal-adapter.md §4.
- **Create or change:** `docs/spike-results.md` (S12 section).
- **Acceptance:** S12 recorded; SHIPMENT_TRACKING_ENABLED set.
- **Tests that prove it:** tracker result recorded.
- **Requirements and invariants:** G16, FR-IG-08.

### T03B01: Pool join, receipts and events

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** T02B01, T02B02, T00B01.
- **Read first:** db-schema.md (pool_entries); fairness-and-hashing.md §3, §6; api.md entries; product-spec.md FR-SL-02.
- **Create or change:** `modules/pools/{join,receipts,events}.py`, `api/routers/entries.py`.
- **Acceptance:** Idempotent join, unique keys, database-clock cutoff, commitment and signed receipt, withdraw, SSE endpoint; PT-13 and the 200-parallel-joins test pass.
- **Tests that prove it:** PT-13; `tests/concurrency/test_join_200_parallel.py`; F14; F15.
- **Requirements and invariants:** FR-SL-02, FR-IN-04, FR-ID-03, F14, F15.

### T03B02: Search service and indexer

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** T02B02, T02B04.
- **Read first:** ai-schemas.md §7; domain-ports.md Search; config-and-errors.md §1; spikes.md S8.
- **Create or change:** `adapters/search/**`, `modules/search/**`, the admin reindex route.
- **Acceptance:** SearchService and SearchIndexer with the Postgres trigram backend and, if S8 passed, the Elastic backend; search.index handler; reindex endpoint; PT-14 passes; only public documents are indexed.
- **Tests that prove it:** PT-14; `tests/integration/test_search_fallback.py`.
- **Requirements and invariants:** FR-IG-01.

### T03B03: PayPal Login link flow

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** T02B01, T00B02.
- **Read first:** spikes.md S1; db-schema.md paypal_links; api.md paypal login; product-spec.md FR-ID-02.
- **Create or change:** `modules/identity/paypal_login.py`, `api/routers/paypal_login.py`.
- **Acceptance:** Code flow with state and nonce per the S1 outcome; disclosure screen; relink rules; HMAC account key; behaviour per DEDUPE_MODE.
- **Tests that prove it:** `tests/integration/test_login_modes.py`; F16.
- **Requirements and invariants:** FR-ID-02, FR-ID-03, F16.

### T03B04: Pool close

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** T03B01.
- **Read first:** state-machines.md pool and entry; fairness-and-hashing.md §3; domain-ports.md §5.
- **Create or change:** `modules/pools/close.py`.
- **Acceptance:** pool.close sweeps eligibility, builds commitments and the Merkle root, publishes the list and writes the audit checkpoint; late joins are impossible even if the job runs late.
- **Tests that prove it:** `tests/integration/test_close_commitments.py`; late-join test.
- **Requirements and invariants:** FR-SL-04, FR-AD-01, I15.

### T03B05: Spike S11 APIMatic generation

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH3. **Merge gate:** IG-3. **Depends on:** T01B01.
- **Read first:** spikes.md S11; api.md §4.3; decisions.md INT-4.
- **Create or change:** `docs/spike-results.md` (S11 section); scratch SDK output not committed.
- **Acceptance:** S11 recorded; trial started in PH3; licensing of generated code noted.
- **Tests that prove it:** generation result, trial dates and licensing recorded.
- **Requirements and invariants:** G15, FR-IG-05.

## PH4: Core engines III and the first integration (gate IG-4)

**Goal.** Checkout opening, approval checks, authorization and the funding sweep against the fake router; intake; seed and allocation with the real AllocationReadService; the public audit endpoint; the first real wiring of both members' code through `wiring.py`.

**Entry condition.** IG-3 passed.

**Exit.** IT-4: Pipeline test with `FakePaymentRouter` and `FakeAI`: create and publish a pool; 12 users join through intake (some caps low enough to be priced out); close; demo seed; allocate two lots and a waitlist; force-award; `lot.open_checkout` creates offers and refills priced-out seats from the waitlist; all authorizations are captured by the sweep and the lot is FUNDED; the audit chain verifies; the public audit payload recomputes with the vectors; the real `AllocationReadService` and `MerchantDirectory` are wired through `wiring.py`.

**Watch.** First merge of both lanes' modules: port mismatches surface here; the heaviest phase for both members.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T04A01 | A | M | T03A01 | lot.open_checkout handler |
| T04A02 | A | L | T02A02, T03A01 | Approval checks and authorization flow (fake router) |
| T04A03 | A | L | T02A03, T03A01, T04A02 | Funding trigger and capture sweep (fake router) |
| T04B01 | B | L | T02B02, T02B03, T03B02 | Intake pipeline |
| T04B02 | B | M | T03B04, T01B04 | Beacon adapter and pool.seed |
| T04B03 | B | L | T04B02 | Allocation and AllocationReadService |
| T04B04 | B | S | T03B04, T04B03 | Public audit endpoint and keys |
| T04X01 | AB | L | T04A01, T03A02, T04B03 | First integration: pool to checkout |

### T04A01: lot.open_checkout handler

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH4. **Merge gate:** IG-4. **Depends on:** T03A01.
- **Read first:** domain-ports.md §6; state-machines.md LS-05; db-schema.md lots, buyer_orders.
- **Create or change:** `modules/checkout/open_checkout.py`.
- **Acceptance:** Creates OFFERED orders for seated entries within seats using FakeAllocationRead and FakeMerchantDirectory; sets deadlines; schedules offer.expire and lot.try_fund; PT-08 passes.
- **Tests that prove it:** PT-08; `tests/integration/test_open_checkout.py`.
- **Requirements and invariants:** FR-CK-01, FR-CK-02, FR-LT-04, I8.

### T04A02: Approval checks and authorization flow (fake router)

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH4. **Merge gate:** IG-4. **Depends on:** T02A02, T03A01.
- **Read first:** paypal-adapter.md §6; state-machines.md BO-01 to BO-05, BO-18 to BO-20; product-spec.md FR-CK-05.
- **Create or change:** `modules/checkout/{approval,authorize}.py`.
- **Acceptance:** FR-CK-05 checks including payee, country and payer-key rules; order.authorize takes the lock, authorizes with the key and reads the authorization object's status; an unknown outcome stays AUTHORIZING; rejected orders never authorize.
- **Tests that prove it:** `tests/integration/test_authorize_flow.py`; F1; F5; F6.
- **Requirements and invariants:** FR-CK-05, FR-ID-04, FR-FN-01, F1, F6.

### T04A03: Funding trigger and capture sweep (fake router)

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH4. **Merge gate:** IG-4. **Depends on:** T02A03, T03A01, T04A02.
- **Read first:** state-machines.md LS-06, LS-07, BO-06 to BO-11; paypal-adapter.md §4; config-and-errors.md `CAPTURE_BUFFER`.
- **Create or change:** `modules/checkout/funding.py`.
- **Acceptance:** Trigger with CAPTURE_BUFFER; sweep with a concurrency limit; PENDING handling; FUNDED only when completed captures from distinct buyers reach the MOQ; PT-09 passes.
- **Tests that prove it:** PT-09; F7; F8.
- **Requirements and invariants:** FR-FN-02, FR-FN-04, I5, F8.

### T04B01: Intake pipeline

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH4. **Merge gate:** IG-4. **Depends on:** T02B02, T02B03, T03B02.
- **Read first:** ai-schemas.md §2; api.md intake; product-spec.md FR-IN-*.
- **Create or change:** `modules/intake/**`, `api/routers/intake.py`.
- **Acceptance:** Candidate retrieval through the search service, AI parse, deterministic validation per ai-schemas.md, ambiguity loop, server-rendered confirmation card, manual form, and confirm writes the canonical request.
- **Tests that prove it:** `tests/integration/test_intake_validation.py`; F19.
- **Requirements and invariants:** FR-IN-01, FR-IN-02, FR-IN-03, FR-IN-05, FR-IN-06, FR-IN-08, FR-AI-01, F19.

### T04B02: Beacon adapter and pool.seed

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH4. **Merge gate:** IG-4. **Depends on:** T03B04, T01B04.
- **Read first:** fairness-and-hashing.md §4; domain-ports.md Beacon; spikes.md S6.
- **Create or change:** `adapters/beacon/**`, `modules/pools/seed.py`.
- **Acceptance:** drand and demo beacon clients with fakes; pool.seed requeues while unavailable; the seed is stored with the beacon response.
- **Tests that prove it:** `tests/integration/test_seed_waits.py`; F27.
- **Requirements and invariants:** FR-SL-07, F27.

### T04B03: Allocation and AllocationReadService

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH4. **Merge gate:** IG-4. **Depends on:** T04B02.
- **Read first:** fairness-and-hashing.md §5; domain-ports.md §4.1; state-machines.md; db-schema.md allocations, lots.
- **Create or change:** `modules/allocation/**`.
- **Acceptance:** pool.allocate orders per zone, forms lots with lot_order, cancels undersized lots and creates the waitlist; real AllocationReadService including next_candidates; PT-01 and PT-02 pass.
- **Tests that prove it:** PT-01; PT-02; `tests/integration/test_allocation_lots.py`.
- **Requirements and invariants:** FR-SL-05, FR-LT-01, FR-LT-02, FR-LT-04, FR-LT-05, I11.

### T04B04: Public audit endpoint and keys

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH4. **Merge gate:** IG-4. **Depends on:** T03B04, T04B03.
- **Read first:** api.md §3 public audit; fairness-and-hashing.md.
- **Create or change:** `api/routers/public.py`.
- **Acceptance:** GET public audit and keys per api.md; no personal data, salts or caps.
- **Tests that prove it:** `tests/integration/test_public_audit_no_pii.py`.
- **Requirements and invariants:** FR-AD-01.

### T04X01: First integration: pool to checkout

- **Owner:** Both members. **Size:** L (1 day). **Phase:** PH4. **Merge gate:** IG-4. **Depends on:** T04A01, T03A02, T04B03.
- **Read first:** domain-ports.md §6; testing-strategy.md IT-4.
- **Create or change:** `backend/src/fairpool/wiring.py`, the admin force-award route, `tests/integration/test_pipeline_fakes.py`.
- **Acceptance:** Real AllocationReadService and MerchantDirectory wired into checkout through wiring.py; force-award helper; IT-1 passes.
- **Tests that prove it:** IT-4.
- **Requirements and invariants:** FR-LT-04, I8.

## PH5: Real PayPal path, auction core and merchant foundation (gate IG-5)

**Goal.** The first real Sandbox buyer through the app on the redirect path; the checkout UI; the failure path with the fake router; merchant profile; sealed bids with receipts; the auction rules engine.

**Entry condition.** IG-4 passed: the pipeline test with fakes is green.

**Exit.** IT-5: One real Sandbox buyer through the app on the redirect path: offer, approval, server-side authorize, then void (and capture then refund in a second run) with the ledger equal to PayPal GETs; the checkout UI shows notices and labels; the failure path with the fake router ends at net zero (PT-11); the auction rules engine reproduces the vectors; merchant profile and sealed bids with receipts pass their tests.

**Watch.** Real PayPal behaviour differing from the fake; sealing and receipts.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T05A01 | A | L | T04A02, T04X01 | Real PayPal path for one buyer (redirect) |
| T05A02 | A | L | T01B03 | Checkout UI |
| T05A03 | A | M | T04A03, T02A03 | Failure path and compensating refund (fake router) |
| T05B01 | B | M | T02B01 | Merchant profile and onboarding states |
| T05B02 | B | L | T05B01, T04B03 | Bid API with receipts and sealing |
| T05B03 | B | L | T00B01, T04B03 | Auction rules engine |

### T05A01: Real PayPal path for one buyer (redirect)

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH5. **Merge gate:** IG-5. **Depends on:** T04A02, T04X01.
- **Read first:** paypal-adapter.md §5, §6; state-machines.md BO-01 to BO-04; api.md checkout; product-spec.md FR-FN-01.
- **Create or change:** `modules/checkout/{create_order,return_handler}.py`, `api/routers/checkout.py`.
- **Acceptance:** Level 0 order create, redirect approval, return handler with FR-CK-05 checks, server-side authorize with the seat lock and ledger writes on the real Sandbox using force-award; IT-5 passes.
- **Tests that prove it:** IT-5 with a real buyer; C-08; C-09 (manual).
- **Requirements and invariants:** FR-PP-01, FR-FN-01, FR-CK-05.

### T05A02: Checkout UI

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH5. **Merge gate:** IG-5. **Depends on:** T01B03.
- **Read first:** api.md offers and orders; scaffold.md §12; product-spec.md FR-CK-01.
- **Create or change:** `frontend/src/checkout/**`.
- **Acceptance:** Offer disclosure page with notices and labels, order status page, withdraw and fallback labels; exports OfferCheckout and OrderStatusCard through checkout/index.ts.
- **Tests that prove it:** frontend unit tests; manual check with a real order.
- **Requirements and invariants:** FR-CK-01, FR-CK-02, FR-FN-06.

### T05A03: Failure path and compensating refund (fake router)

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH5. **Merge gate:** IG-5. **Depends on:** T04A03, T02A03.
- **Read first:** state-machines.md LS-08 to LS-10, BO-12 to BO-14; paypal-adapter.md §4; testing-strategy.md PT-11.
- **Create or change:** `modules/checkout/failure.py`.
- **Acceptance:** FAILING closes new offers, voids every AUTHORIZED authorization, refunds every COMPLETED capture, waits for PENDING captures and refunds any that complete; FAILED_CLOSED only at net zero; PT-11 passes.
- **Tests that prove it:** PT-11; F9; F24.
- **Requirements and invariants:** FR-FN-05, FR-FN-04, I5, F9, F24.

### T05B01: Merchant profile and onboarding states

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH5. **Merge gate:** IG-5. **Depends on:** T02B01.
- **Read first:** db-schema.md merchants; api.md merchant profile; product-spec.md FR-AU-03.
- **Create or change:** `modules/merchants/**`, `api/routers/merchant.py`.
- **Acceptance:** Profile, attestations with timestamps, demo onboarding status and merchant role checks.
- **Tests that prove it:** `tests/integration/test_merchant_profile.py`.
- **Requirements and invariants:** FR-AU-01, FR-AU-03.

### T05B02: Bid API with receipts and sealing

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH5. **Merge gate:** IG-5. **Depends on:** T05B01, T04B03.
- **Read first:** db-schema.md bids; fairness-and-hashing.md §6; api.md merchant bids; state-machines.md bid.
- **Create or change:** `modules/auction/bids.py`.
- **Acceptance:** Save revisions with signed receipts; sealed access (owner and engine only); target quantity and evidence fields; late bids rejected by database time.
- **Tests that prove it:** `tests/integration/test_bid_sealing.py`; PT-15 (bids).
- **Requirements and invariants:** FR-AU-02, FR-AU-03.

### T05B03: Auction rules engine

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH5. **Merge gate:** IG-5. **Depends on:** T00B01, T04B03.
- **Read first:** fairness-and-hashing.md §10, §11; db-schema.md awards; product-spec.md FR-AU-04 to FR-AU-07.
- **Create or change:** `domain/auction_rules.py`, `modules/auction/rules.py`.
- **Acceptance:** R1 to R9, tier resolution, feasibility, ranking and capacity across lots reproduce the vectors; PT-05 and PT-06 pass.
- **Tests that prove it:** PT-05; PT-06; the vectors.
- **Requirements and invariants:** FR-AU-04, FR-AU-05, FR-AU-06, FR-AU-07.

## PH6: Money completion and auction to checkout (gate IG-6)

**Goal.** The real funding sweep and the real failure path (void then refund); webhooks and the reconciler; the payload ladder and encrypted shipping address; quote parsing and reconciliation flags; lot handlers that award and open checkout; merchant API keys; Buyer UI v1.

**Entry condition.** IG-5 passed.

**Exit.** IT-6: Real Sandbox: authorizations are captured by the sweep and the lot is FUNDED; a second lot misses its minimum and ends with void then refund at net zero; webhooks are verified (if S5 passed) or the reconciler is the only path; payload ladder at the S4 level; bids go through quote parsing with merchant confirmation and reconciliation flags; lot handlers award and open checkout from real bids; merchant API keys and MerchantAuth pass PT-15; Buyer UI v1 completes an entry through the receipt.

**Watch.** Unknown-outcome handling; award handoff timing between the two lanes.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T06A01 | A | L | T05A01, T04A03, T05A03 | Funding sweep and failure path on the real Sandbox |
| T06A02 | A | M | T03A03, T02A01 | Webhooks |
| T06A03 | A | L | T05A01, T02A03 | Reconciler and unknown-outcome resolution |
| T06A04 | A | M | T05A01, T02A04 | Payload ladder levels and shipping address |
| T06B01 | B | M | T05B02, T02B03 | Quote parsing and confirmation |
| T06B02 | B | M | T05B02, T05B03 | AI offer reconciliation and flags |
| T06B03 | B | L | T05B03, T04A01 | Lot handlers: bid_open, bid_close, award |
| T06B04 | B | M | T05B01 | Merchant API keys and MerchantAuth |
| T06B05 | B | L | T01B03, T01B01 | Buyer UI v1: Discover and Join |

### T06A01: Funding sweep and failure path on the real Sandbox

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH6. **Merge gate:** IG-6. **Depends on:** T05A01, T04A03, T05A03.
- **Read first:** paypal-adapter.md §4; state-machines.md LS-06 to LS-10; decisions.md `PAYMENT_MODE`.
- **Create or change:** `modules/checkout/{funding,failure}.py` wired to the real gateway.
- **Acceptance:** Capture of authorizations, FUNDED, and FAILING with void and refund ending at net zero; mode per decisions.md.
- **Tests that prove it:** IT-6: capture, void, refund end at net zero; C-09; C-10.
- **Requirements and invariants:** FR-FN-02, FR-FN-04, FR-FN-05, FR-FN-07.

### T06A02: Webhooks

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH6. **Merge gate:** IG-6. **Depends on:** T03A03, T02A01.
- **Read first:** paypal-adapter.md §8; db-schema.md webhook_events; spikes.md S5.
- **Create or change:** `modules/webhooks/**`, `api/routers/webhooks.py`.
- **Acceptance:** Ingest, signature verification per S5, dedupe, webhook.process maps events and fetches the resource, dead-letter list, all behind WEBHOOKS_ENABLED.
- **Tests that prove it:** F2; F3; F4; C-15.
- **Requirements and invariants:** FR-FN-03, F2, F3, F4.

### T06A03: Reconciler and unknown-outcome resolution

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH6. **Merge gate:** IG-6. **Depends on:** T05A01, T02A03.
- **Read first:** paypal-adapter.md §7; domain-ports.md job `reconciler.sweep`; state-machines.md.
- **Create or change:** `modules/reconciler/**`.
- **Acceptance:** reconciler.sweep heals stale states, resolves AUTHORIZING and CAPTURING unknowns, polls PENDING captures, enforces the age guard, and refunds late captures after a failed lot.
- **Tests that prove it:** F1; F9; F10.
- **Requirements and invariants:** FR-FN-08, FR-CK-04, F1, F9, F10.

### T06A04: Payload ladder levels and shipping address

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH6. **Merge gate:** IG-6. **Depends on:** T05A01, T02A04.
- **Read first:** paypal-adapter.md §5; db-schema.md buyer_orders.shipping_enc; spikes.md S4.
- **Create or change:** `adapters/paypal` payload ladder, `modules/checkout/continue.py`.
- **Acceptance:** Levels 1 to 3 enabled up to PAYPAL_PAYLOAD_LEVEL; address collected at continue and stored encrypted; exact per-buyer totals.
- **Tests that prove it:** C-14; `tests/unit/test_payload_levels.py`.
- **Requirements and invariants:** FR-LT-05, FR-PP-01.

### T06B01: Quote parsing and confirmation

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH6. **Merge gate:** IG-6. **Depends on:** T05B02, T02B03.
- **Read first:** ai-schemas.md §3; api.md merchant quote; state-machines.md BS-01 to BS-03.
- **Create or change:** `modules/auction/quote.py`.
- **Acceptance:** Paste a quote, AI proposes fields, the merchant confirms; unconfirmed fields never enter the auction (BS-01, BS-03).
- **Tests that prove it:** `tests/integration/test_quote_confirm.py`; F20.
- **Requirements and invariants:** FR-AI-04, FR-AU-02.

### T06B02: AI offer reconciliation and flags

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH6. **Merge gate:** IG-6. **Depends on:** T05B02, T05B03.
- **Read first:** ai-schemas.md §4; state-machines.md BS-04, BS-05, BS-10; product-spec.md FR-AI-02.
- **Create or change:** `modules/auction/reconcile.py`.
- **Acceptance:** RECONCILE task; a BLOCKING flag moves the bid to FLAGGED (R7); ops review hold when AI is unavailable; injected-instruction cases do not change outcomes.
- **Tests that prove it:** `tests/ai_eval` smoke; F20; a test that AI never qualifies an offer.
- **Requirements and invariants:** FR-AI-02, F20.

### T06B03: Lot handlers: bid_open, bid_close, award

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH6. **Merge gate:** IG-6. **Depends on:** T05B03, T04A01.
- **Read first:** domain-ports.md §5, §6; state-machines.md LS-01 to LS-04; fairness-and-hashing.md §10, §11; db-schema.md awards.
- **Create or change:** `modules/auction/handlers.py`.
- **Acceptance:** Handlers per domain-ports.md; award snapshot, router and mode stamped, priced-out marking, no-bid cancellation, lot.open_checkout enqueued; serialized in lot_order.
- **Tests that prove it:** `tests/integration/test_award_handoff.py`; R9 ordering test.
- **Requirements and invariants:** FR-AU-01, FR-AU-06, FR-LT-03.

### T06B04: Merchant API keys and MerchantAuth

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH6. **Merge gate:** IG-6. **Depends on:** T05B01.
- **Read first:** db-schema.md merchant_api_keys; api.md §4.2, §4.3; domain-ports.md MerchantAuth.
- **Create or change:** `modules/merchants/api_keys.py`, `api/routers/merchant_keys.py`, `api/deps.py`.
- **Acceptance:** Create, list and revoke keys (shown once, HMAC stored, scopes); MerchantAuth for sessions and keys; API_KEY_INVALID and API_KEY_SCOPE behaviour; PT-15 for bids.
- **Tests that prove it:** PT-15; `tests/unit/test_api_key_hash.py`.
- **Requirements and invariants:** FR-IG-04, FR-UI-07.

### T06B05: Buyer UI v1: Discover and Join

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH6. **Merge gate:** IG-6. **Depends on:** T01B03, T01B01.
- **Read first:** api.md intake, entries, pools; product-spec.md FR-UI-01; scaffold.md §12.
- **Create or change:** `frontend/src/buyer/{discover,lobby,receipt}/**`.
- **Acceptance:** Login and register; Tab 1 with the prompt bar, the trending pool grid with the exact badge, the confirmation card, join, pool lobby with countdown and the receipt page.
- **Tests that prove it:** frontend unit tests; exact badge text test.
- **Requirements and invariants:** FR-UI-01, FR-IN-03, FR-SL-01.

## PH7: Live end to end and the agent and merchant lanes (gate IG-7)

**Goal.** SDK popup approval; refill orchestration; labelled routers; ops console; Buyer UI v2; the agent API with delegations; the FairPool MCP server; the Merchant Agent API sub-app; merchant-lane search with the advisory similarity flag; the first live end-to-end run with three or more real buyers.

**Entry condition.** IG-6 passed. The Zapier trial has been running since PH4.

**Exit.** IT-7: Full live flow with at least three real Sandbox buyers: entries, close, seed, allocation, two lots; a merchant bids through the console with a pasted quote and a second merchant through an API key; award; checkout with the SDK popup (if S13 passed) or redirect; one offer expires and refills; lot 1 is FUNDED; lot 2 ends with void then refund at net zero; the agent API and the FairPool MCP server join, list and withdraw an entry; the merchant-lane search and the LOW_SIMILARITY flag work; the ops console shows both lots; no manual database edits.

**Watch.** The live end-to-end test is where lane integration errors show; keep the Zapier trial window in mind.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T07A01 | A | L | T05A01, T05A02, T02B05 | JavaScript SDK v6 approval |
| T07A02 | A | M | T03A02, T04B03 | Refill orchestration |
| T07A03 | A | S | T00B03, T05A01 | Routers per S3 and S7 |
| T07A04 | A | L | T06A01, T06A02 | Ops console v1 |
| T07B01 | B | L | T06B05 | Buyer UI v2: My Pools and Orders |
| T07B02 | B | L | T03B01, T04B01 | Agent API and delegations |
| T07B03 | B | M | T07B02 | FairPool MCP server |
| T07B04 | B | M | T05B02, T06B04 | Merchant Agent API sub-app: lots and bids |
| T07B05 | B | M | T03B02, T05B02 | Search in the merchant lane and advisory similarity |
| T07X01 | AB | L | T06A01, T07A02, T06B03 | Live end-to-end integration |

### T07A01: JavaScript SDK v6 approval

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T05A01, T05A02, T02B05.
- **Read first:** paypal-adapter.md §12; api.md §4.1; spikes.md S13; state-machines.md BO-02.
- **Create or change:** `modules/checkout/sdk.py`, `frontend/src/checkout/PayPalButton.tsx`.
- **Acceptance:** Config and client-token endpoints, approved and cancelled callbacks, OfferCheckout button using presentationMode auto with redirect fallback; the browser sends no amounts; C-17 passes.
- **Tests that prove it:** C-17; a test that the browser sends no amount; F5 through the callback.
- **Requirements and invariants:** FR-IG-06, FR-CK-02, FR-UI-02.

### T07A02: Refill orchestration

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T03A02, T04B03.
- **Read first:** domain-ports.md §6 refill; state-machines.md vacancy rule; fairness-and-hashing.md §5.
- **Create or change:** `modules/checkout/refill.py`.
- **Acceptance:** lot.refill with vacancy count, wave limit, refill cutoff and next_candidates; never invites more than vacancies.
- **Tests that prove it:** PT-08; `tests/integration/test_refill_waves.py`.
- **Requirements and invariants:** FR-CK-03, I8.

### T07A03: Routers per S3 and S7

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T00B03, T05A01.
- **Read first:** paypal-adapter.md §9; decisions.md §4; spike-results.md S7.
- **Create or change:** `adapters/paypal/routers.py` (labels).
- **Acceptance:** single_seller live with its label; payee_email stays NotEnabled (S7 rejected it on Oct 28: void and refund were denied); platform stays NotEnabled; labels appear in API notices.
- **Tests that prove it:** `tests/unit/test_router_labels.py`.
- **Requirements and invariants:** FR-FN-07, FR-FN-06.

### T07A04: Ops console v1

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T06A01, T06A02.
- **Read first:** api.md admin; product-spec.md FR-OP-01; paypal-adapter.md §10.
- **Create or change:** `modules/checkout/ops.py`, `api/routers/admin_ops.py`, `frontend/src/ops/**`.
- **Acceptance:** Lot state view, dead letters, reconciler run, mock toggles with MOCK labels, alerts, abort and audit export.
- **Tests that prove it:** `tests/integration/test_ops_views.py`.
- **Requirements and invariants:** FR-OP-01.

### T07B01: Buyer UI v2: My Pools and Orders

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T06B05.
- **Read first:** api.md me/orders; product-spec.md FR-UI-02, FR-UI-03.
- **Create or change:** `frontend/src/buyer/{my-pools,orders}/**`.
- **Acceptance:** Tab 2 with Pending, Waitlist (position #N) and Action Required embedding OfferCheckout; Tab 3 with receipts from /me/orders.
- **Tests that prove it:** frontend unit tests.
- **Requirements and invariants:** FR-UI-02, FR-UI-03.

### T07B02: Agent API and delegations

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T03B01, T04B01.
- **Read first:** api.md §4.4; db-schema.md delegations; ai-schemas.md; product-spec.md FR-AG-*.
- **Create or change:** `modules/agentapi/**`, `api/routers/agent.py`.
- **Acceptance:** Agent endpoints including the flat list and withdraw, search, max_total_usd and body idempotency key; delegation tokens hashed, scoped and revocable; same validator as the web flow; no payment endpoint; OpenAPI docs and a sample agent script.
- **Tests that prove it:** `tests/integration/test_agent_api.py`; F15; PT-16.
- **Requirements and invariants:** FR-AG-01, FR-AG-02, FR-SL-03, F15.

### T07B03: FairPool MCP server

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T07B02.
- **Read first:** api.md §4.5; AGENTS.md rule 22.
- **Create or change:** `modules/mcp/**`.
- **Acceptance:** MCP endpoint with exactly the four tools and delegation-token auth; test_mcp_contract and PT-16 pass; a real AI client joins, lists and withdraws.
- **Tests that prove it:** `tests/unit/test_mcp_contract.py`; PT-16.
- **Requirements and invariants:** FR-IG-02, FR-AG-01.

### T07B04: Merchant Agent API sub-app: lots and bids

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T05B02, T06B04.
- **Read first:** api.md §4.3; db-schema.md bids.
- **Create or change:** `api/merchant_api/{app,routes_lots_bids}.py`.
- **Acceptance:** Sub-app mounted at /merchant-api/v1 with list_lots, get_lot, submit_bid, list_bids and get_bid; idempotent submit_bid with confirmed true; OpenAPI at the documented path.
- **Tests that prove it:** `tests/unit/test_merchant_openapi_contract.py`; PT-15.
- **Requirements and invariants:** FR-IG-04.

### T07B05: Search in the merchant lane and advisory similarity

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T03B02, T05B02.
- **Read first:** ai-schemas.md §7; domain-ports.md Search; db-schema.md bid_flags.
- **Create or change:** `modules/search/similarity.py`, `modules/auction/flags.py`.
- **Acceptance:** Demand Board and merchant lots search; LOW_SIMILARITY WARNING flag after confirmed revisions; Elastic index sync verified; PT-14 passes.
- **Tests that prove it:** PT-14; `tests/integration/test_similarity_flag.py`.
- **Requirements and invariants:** FR-IG-01, FR-UI-04.

### T07X01: Live end-to-end integration

- **Owner:** Both members. **Size:** L (1 day). **Phase:** PH7. **Merge gate:** IG-7. **Depends on:** T06A01, T07A02, T06B03.
- **Read first:** testing-strategy.md IT-7; demo-and-submission.md §3.
- **Create or change:** `tests/integration` live checklist and scripts.
- **Acceptance:** IT-2 passes with at least three real Sandbox buyers.
- **Tests that prove it:** IT-7.
- **Requirements and invariants:** FR-FN-02.

## PH8: Fulfillment, verification, merchant console and simulation (gate IG-8)

**Goal.** Fulfillment export, shipments and tracking, the verification manifest and live verification; the PayPal MCP verification path; Merchant Agent API operations for fulfillment; the merchant console tabs; observability; security; the simulation engine; Zapier spike S9 and setup notes.

**Entry condition.** IG-7 passed.

**Exit.** IT-8: Fulfillment CSV, shipments (tracker submitted if S12 passed), the verification manifest and the live verification endpoint work for a FUNDED lot; the PayPal MCP read-only verification (or the endpoint) confirms totals; the merchant console tabs work against the real backend; the Merchant Agent API has ten operations; observability, security and rate limits pass; a simulation pool of 10,000 entries allocates in under 10 seconds; S9 is recorded.

**Watch.** Many independent surfaces at once; the UI work must stay contract-first.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T08A01 | A | L | T06A01, T06B04, T03A05 | Fulfillment backend: progress, fulfillment, shipments, manifest, verification |
| T08A02 | A | M | T01B03 | Fulfillment tab UI |
| T08A03 | A | M | T07B04, T08A01 | Merchant Agent API: fulfillment, shipments, manifest and verification routes |
| T08A04 | A | M | T08A01, T03A04 | PayPal MCP verification copilot |
| T08A05 | A | M | T01A03 | Observability |
| T08A06 | A | M | T06A02, T07A01 | Security pass |
| T08B01 | B | L | T01B03, T01B01 | Merchant console UI I: Demand Board and bid submission |
| T08B02 | B | L | T08B01 | Merchant console UI II: Active Bids and Developer API |
| T08B03 | B | S | T07B02 | Spike S9 Zapier MCP managed mode |
| T08B04 | B | L | T04B03, T02A02 | Simulation engine |
| T08B05 | B | S | T08B03 | Zapier bridge setup and documentation |

### T08A01: Fulfillment backend: progress, fulfillment, shipments, manifest, verification

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T06A01, T06B04, T03A05.
- **Read first:** api.md §4.2; db-schema.md shipments; paypal-adapter.md §4, §13; decisions.md INT-6, INT-8.
- **Create or change:** `modules/fulfillment/**`, `api/routers/merchant_fulfillment.py`.
- **Acceptance:** Endpoints per api.md section 4.2 with the LOT_NOT_FUNDED rules; shipments.submit through the adapter when enabled; the manifest has no personal data; the verification endpoint makes read-only GETs; PT-15 for these routes.
- **Tests that prove it:** `tests/integration/test_fulfillment_gates.py`; PT-15; C-18.
- **Requirements and invariants:** FR-IG-07, FR-IG-08, FR-UI-06.

### T08A02: Fulfillment tab UI

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T01B03.
- **Read first:** api.md §4.2; scaffold.md §12.
- **Create or change:** `frontend/src/merchant-fulfillment/**`.
- **Acceptance:** Shipping CSV download, mark shipped, manifest download and verification result, honest labels; exports FulfillmentTab.
- **Tests that prove it:** frontend unit tests.
- **Requirements and invariants:** FR-UI-06.

### T08A03: Merchant Agent API: fulfillment, shipments, manifest and verification routes

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T07B04, T08A01.
- **Read first:** api.md §4.3.
- **Create or change:** `api/merchant_api/routes_fulfillment.py`.
- **Acceptance:** Five operations (get_lot_progress, get_lot_fulfillment, submit_shipments, get_verification_manifest, get_lot_verification) added to the sub-app with merchant_key auth and scopes; test_merchant_openapi_contract passes with ten operations; the OpenAPI document is frozen.
- **Tests that prove it:** `tests/unit/test_merchant_openapi_contract.py` with ten operations.
- **Requirements and invariants:** FR-IG-04.

### T08A04: PayPal MCP verification copilot

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T08A01, T03A04.
- **Read first:** paypal-adapter.md §13; spikes.md S10; decisions.md INT-6.
- **Create or change:** the README verification section draft in `docs/progress.md` notes; `modules/fulfillment` verification path.
- **Acceptance:** Per S10: read-only allowlist configuration and documented prompts, or the verification endpoint as the documented path; a funded lot verified from a real AI client; no write tool reachable.
- **Tests that prove it:** `tests/integration/test_verification_endpoint.py`; manual check from a real AI client.
- **Requirements and invariants:** FR-IG-07.

### T08A05: Observability

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T01A03.
- **Read first:** testing-strategy.md §1; product-spec.md FR-OP-02.
- **Create or change:** `backend/src/fairpool/infra/metrics.py`, alert rules.
- **Acceptance:** Metrics endpoint, funnel counters and alert rules for rejected transitions, amount mismatches, unknown outcomes and dead letters.
- **Tests that prove it:** `tests/unit/test_alert_rules.py`.
- **Requirements and invariants:** FR-OP-02.

### T08A06: Security pass

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T06A02, T07A01.
- **Read first:** AGENTS.md §3; config-and-errors.md §3; product-spec.md FR-ID-05.
- **Create or change:** rate-limit and header middleware in `api/app.py`, dependency lockfiles.
- **Acceptance:** Rate limits, CSRF checks, security headers, pinned dependencies, log redaction tests, sandbox-host guard tests, API key and token handling review.
- **Tests that prove it:** `tests/unit/test_rate_limits.py`; `tests/unit/test_security_headers.py`; log redaction.
- **Requirements and invariants:** FR-PP-06, FR-ID-05, I14.

### T08B01: Merchant console UI I: Demand Board and bid submission

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T01B03, T01B01.
- **Read first:** api.md merchant routes; product-spec.md FR-UI-04.
- **Create or change:** `frontend/src/merchant/{demand,bid}/**`.
- **Acceptance:** Server-sent events feed of lots in BIDDING, search, quote paste and bid form with confirmation, results; no other merchant's data visible.
- **Tests that prove it:** frontend unit tests.
- **Requirements and invariants:** FR-UI-04.

### T08B02: Merchant console UI II: Active Bids and Developer API

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T08B01.
- **Read first:** api.md merchant progress and api-keys; product-spec.md FR-UI-05, FR-UI-07.
- **Create or change:** `frontend/src/merchant/{bids,developer}/**`.
- **Acceptance:** Active Bids with Pending, In Checkout tracker (holds then captures, refills, countdown) and Lost or Failed with reason codes; Developer API tab with keys shown once, scopes, rate limits and SDK links.
- **Tests that prove it:** frontend unit tests.
- **Requirements and invariants:** FR-UI-05, FR-UI-07.

### T08B03: Spike S9 Zapier MCP managed mode

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T07B02.
- **Read first:** spikes.md S9; api.md §4.6; decisions.md INT-2.
- **Create or change:** `docs/spike-results.md` (S9 section).
- **Acceptance:** S9 recorded; trial started in PH4; ZAPIER_BRIDGE set.
- **Tests that prove it:** tool list, locked fields, task usage and trial expiry recorded.
- **Requirements and invariants:** G13, FR-IG-03.

### T08B04: Simulation engine

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T04B03, T02A02.
- **Read first:** product-spec.md FR-SM-01, FR-AI-03; ai-schemas.md §5; domain-ports.md; paypal-adapter.md §9.
- **Create or change:** `modules/sim/**`, `api/routers/admin_sim.py`.
- **Acceptance:** SIMULATION pools with the fake router, seeded generator, LLM text variety, SIMULATED banner everywhere and 10,000-entry allocation under 10 seconds.
- **Tests that prove it:** PT-16 (sim imports); `tests/integration/test_sim_10k.py`.
- **Requirements and invariants:** FR-AI-03, FR-SM-01, I12.

### T08B05: Zapier bridge setup and documentation

- **Owner:** Member B. **Size:** S (0.25 day). **Phase:** PH8. **Merge gate:** IG-8. **Depends on:** T08B03.
- **Read first:** api.md §4.6; spikes.md S9.
- **Create or change:** `docs/spike-results.md` (S9 setup notes, copied into the README by T09X01).
- **Acceptance:** Managed-mode server configured per api.md section 4.6; setup, locked fields, trial dates and limits documented for the README; recording configuration saved.
- **Tests that prove it:** setup notes complete and recording configuration saved.
- **Requirements and invariants:** FR-IG-03.

## PH9: Hardening, evaluation and feature freeze (gate IG-9)

**Goal.** Fault-injection suite, complete Sandbox contract suite, concurrency and property suites, AI evaluation, public audit page with verify-my-place, UI polish, README draft and demo tooling; feature freeze.

**Entry condition.** IG-8 passed.

**Exit.** IT-9: All test layers are green: the fault suite F1 to F30 (F17 and F18 as disclosed limits), the Sandbox contract suite C-01 to C-18, concurrency and property suites and the AI evaluation baseline; the public audit page and verify-my-place reproduce the vectors; the README draft is complete; feature freeze, after which only fixes merge.

**Watch.** One day for a very large amount of verification work: the highest-risk phase in the plan.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T09A01 | A | L | T06A03, T06A02 | Fault-injection suite |
| T09A02 | A | M | T02A01, T05A01 | Sandbox contract suite complete |
| T09A03 | A | M | T01A03 | Deployment hardening and demo tooling |
| T09A04 | A | S | T06A01 | STRETCH: top-up after FUNDED |
| T09B01 | B | L | T00B01, T01B01 | Public audit page and verify-my-place |
| T09B02 | B | L | T04B01, T06B01, T06B02 | AI evaluation sets and runner |
| T09B03 | B | M | T06B03, T03B01 | Concurrency and property suites for pools, allocation and auction |
| T09B04 | B | M | T07B01, T08B01, T08B02 | UI polish and honesty copy |
| T09X01 | AB | L | T09A02, T09B02 | README full draft |
| T09X02 | AB | M | T07X01 | Feature freeze and IT-3 |

### T09A01: Fault-injection suite

- **Owner:** Member A. **Size:** L (1 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T06A03, T06A02.
- **Read first:** testing-strategy.md §4; state-machines.md.
- **Create or change:** `backend/tests/faults/**`.
- **Acceptance:** Tests F1 to F30 per testing-strategy.md; worker kill mid-sweep and database restart pass.
- **Tests that prove it:** F1 to F30 tests.
- **Requirements and invariants:** FR-FN-08, F1, F23.

### T09A02: Sandbox contract suite complete

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T02A01, T05A01.
- **Read first:** paypal-adapter.md §11.
- **Create or change:** `backend/tests/contract_sandbox/**`, the approval helper under `tools/`.
- **Acceptance:** C-01 to C-18 implemented with markers and the approval helper; run instructions documented.
- **Tests that prove it:** C-01 to C-18.
- **Requirements and invariants:** FR-PP-01.

### T09A03: Deployment hardening and demo tooling

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T01A03.
- **Read first:** scaffold.md §3, §11; demo-and-submission.md §4.
- **Create or change:** `Makefile` demo targets, `deploy/render.yaml`, seed scripts.
- **Acceptance:** Render config final; make demo-seed and make demo-reset; environment docs; reset leaves no state.
- **Tests that prove it:** `make demo-reset` then `make demo-seed` on a clean database.
- **Requirements and invariants:** FR-HK-02.

### T09A04: STRETCH: top-up after FUNDED

- **Owner:** Member A. **Size:** S (0.25 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T06A01.
- **Read first:** api.md; state-machines.md; decisions.md.
- **Create or change:** `modules/checkout/topup.py` (STRETCH).
- **Acceptance:** Late authorizations are captured immediately while seats remain until fund_deadline.
- **Tests that prove it:** `tests/integration/test_topup.py`.
- **Requirements and invariants:** FR-FN-04.

### T09B01: Public audit page and verify-my-place

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T00B01, T01B01.
- **Read first:** fairness-and-hashing.md §6; api.md §3 public audit; product-spec.md FR-AD-01, FR-SL-06.
- **Create or change:** `frontend/src/audit/**`.
- **Acceptance:** The page shows rules, commitments, root, beacon, lots and award; the widget recomputes commitment, proof and rank in the browser and reproduces the vectors.
- **Tests that prove it:** frontend vectors test; verify-my-place widget test.
- **Requirements and invariants:** FR-AD-01, FR-SL-06.

### T09B02: AI evaluation sets and runner

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T04B01, T06B01, T06B02.
- **Read first:** ai-schemas.md §6, §7.
- **Create or change:** `backend/tests/ai_eval/**`.
- **Acceptance:** About 50 intake, 30 quote and 30 reconcile cases; metrics and retrieval recall; README table; baseline stored; zero injected instructions change an outcome.
- **Tests that prove it:** `make ai-eval`; baseline stored.
- **Requirements and invariants:** FR-AI-05, F19, F20.

### T09B03: Concurrency and property suites for pools, allocation and auction

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T06B03, T03B01.
- **Read first:** testing-strategy.md §2.
- **Create or change:** `backend/tests/property/**`, `backend/tests/concurrency/**`.
- **Acceptance:** PT-01, PT-02, PT-05, PT-06, PT-13 and PT-15 complete; join and refill races pass.
- **Tests that prove it:** PT-01, PT-02, PT-05, PT-06, PT-13, PT-15.
- **Requirements and invariants:** F14, F15, F16.

### T09B04: UI polish and honesty copy

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T07B01, T08B01, T08B02.
- **Read first:** product-spec.md FR-UI-08; demo-and-submission.md §2.
- **Create or change:** `frontend/src/**`.
- **Acceptance:** Empty and error states, mobile layout, accessibility basics, labels for sandbox, fallback, simulated and mock, and no brand names.
- **Tests that prove it:** label tests; mobile layout checks.
- **Requirements and invariants:** FR-UI-08, FR-PP-03, FR-HK-06.

### T09X01: README full draft

- **Owner:** Both members. **Size:** L (1 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T09A02, T09B02.
- **Read first:** demo-and-submission.md §5.
- **Create or change:** `README.md`.
- **Acceptance:** Sections per demo-and-submission.md; PayPal and AI usage, honest limits, fallback labels, the AI evaluation table and the ContextMatic plugin mention.
- **Tests that prove it:** README renders; every section of §5 present.
- **Requirements and invariants:** FR-HK-03, FR-PP-03, FR-PP-04, FR-IG-09.

### T09X02: Feature freeze and IT-3

- **Owner:** Both members. **Size:** M (0.5 day). **Phase:** PH9. **Merge gate:** IG-9. **Depends on:** T07X01.
- **Read first:** testing-strategy.md IT-9.
- **Create or change:** git tags.
- **Acceptance:** IT-3 passes; only fixes merge after this gate.
- **Tests that prove it:** IT-9.
- **Requirements and invariants:** I13.

## PH10: Rehearsals and release candidate (gate IG-10)

**Goal.** Two full rehearsals from a clean reset, defect fixes, repository cleanup, SDK and portal generation, Devpost text and the demo video; tag `rc1`.

**Entry condition.** IG-9 passed; only fixes merge.

**Exit.** IT-10: Two consecutive clean end-to-end rehearsals from `make demo-reset` with no manual database intervention; SDKs generated and smoke-tested; Devpost text drafted; the demo video recorded; tag `rc1`.

**Watch.** A rehearsal that needs a manual database edit restarts the count; APIMatic and Zapier trials must still be active.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T10A01 | A | M | T10X01 | Fixes from rehearsal 1 (payments, ops, fulfillment) |
| T10A02 | A | M | T09A03 | Repository cleanup and compliance |
| T10A03 | A | M | T09X01 | Devpost text |
| T10A04 | A | M | T08A03 | Merchant SDKs and developer portal |
| T10B01 | B | M | T10X01 | Fixes from rehearsal 1 (product, UI, agent lane) |
| T10B02 | B | L | T10X02 | Demo video |
| T10X01 | AB | M | T09X01, T09X02 | Rehearsal 1 |
| T10X02 | AB | M | T10A01, T10B01 | Rehearsal 2 clean run |

### T10A01: Fixes from rehearsal 1 (payments, ops, fulfillment)

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH10. **Merge gate:** IG-10. **Depends on:** T10X01.
- **Read first:** defect list in `docs/progress.md`.
- **Create or change:** paths owned by Member A.
- **Acceptance:** All Member A defects closed or consciously deferred in progress.md.
- **Tests that prove it:** a regression test per defect.
- **Requirements and invariants:** none directly.

### T10A02: Repository cleanup and compliance

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH10. **Merge gate:** IG-10. **Depends on:** T09A03.
- **Read first:** demo-and-submission.md §7.
- **Create or change:** repository-wide cleanup, `LICENSE`, dependency pins.
- **Acceptance:** License detected; full-history secret scan clean; README run instructions verified on a clean clone; CI green; dependencies pinned.
- **Tests that prove it:** clean-clone run; full-history gitleaks.
- **Requirements and invariants:** FR-HK-01, FR-HK-02, FR-PP-05.

### T10A03: Devpost text

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH10. **Merge gate:** IG-10. **Depends on:** T09X01.
- **Read first:** demo-and-submission.md §6; product-spec.md §3.
- **Create or change:** Devpost draft kept in `docs/progress.md` (Submission notes).
- **Acceptance:** Description, tools used (AI, PayPal and sponsor tools and how), run instructions and honest limits.
- **Tests that prove it:** owner review.
- **Requirements and invariants:** FR-HK-05.

### T10A04: Merchant SDKs and developer portal

- **Owner:** Member A. **Size:** M (0.5 day). **Phase:** PH10. **Merge gate:** IG-10. **Depends on:** T08A03.
- **Read first:** api.md §4.3; spikes.md S11; decisions.md INT-4.
- **Create or change:** `sdk/**`.
- **Acceptance:** APIMatic generates the Python and TypeScript SDKs and the portal from the frozen OpenAPI; the smoke script passes; sdk/ committed with its README and licensing note; make sdk documented.
- **Tests that prove it:** SDK smoke script.
- **Requirements and invariants:** FR-IG-05.

### T10B01: Fixes from rehearsal 1 (product, UI, agent lane)

- **Owner:** Member B. **Size:** M (0.5 day). **Phase:** PH10. **Merge gate:** IG-10. **Depends on:** T10X01.
- **Read first:** defect list in `docs/progress.md`.
- **Create or change:** paths owned by Member B.
- **Acceptance:** All Member B defects closed or consciously deferred in progress.md.
- **Tests that prove it:** a regression test per defect.
- **Requirements and invariants:** none directly.

### T10B02: Demo video

- **Owner:** Member B. **Size:** L (1 day). **Phase:** PH10. **Merge gate:** IG-10. **Depends on:** T10X02.
- **Read first:** demo-and-submission.md §2, §3.
- **Create or change:** video stored outside the repository; link recorded in `docs/progress.md`.
- **Acceptance:** Under 3:00, public on YouTube, follows the storyboard, no trademarks or music, generic products and labels visible.
- **Tests that prove it:** checks in demo-and-submission.md §7.
- **Requirements and invariants:** FR-HK-04, FR-HK-06.

### T10X01: Rehearsal 1

- **Owner:** Both members. **Size:** M (0.5 day). **Phase:** PH10. **Merge gate:** IG-10. **Depends on:** T09X01, T09X02.
- **Read first:** demo-and-submission.md §3, §4.
- **Create or change:** defect list in `docs/progress.md`.
- **Acceptance:** Full live Sandbox storyboard from demo-reset; defects listed in progress.md.
- **Tests that prove it:** rehearsal log.
- **Requirements and invariants:** FR-HK-04.

### T10X02: Rehearsal 2 clean run

- **Owner:** Both members. **Size:** M (0.5 day). **Phase:** PH10. **Merge gate:** IG-10. **Depends on:** T10A01, T10B01.
- **Read first:** demo-and-submission.md §3, §4.
- **Create or change:** git tag `rc1`.
- **Acceptance:** Second full run from reset with no manual database intervention; IT-4 passes; tag rc1.
- **Tests that prove it:** IT-10.
- **Requirements and invariants:** FR-HK-04.

## PH11: Submission (gate IG-11)

**Goal.** Final checks and submission one day before the Nov 12, 12:00 pm PT deadline (Nov 13, 1:30 am IST); post-submit verification.

**Entry condition.** IG-10 passed.

**Exit.** IT-11: Submission verified: repository, license, video and links open while logged out; Devpost fields complete; no edits after the deadline.

**Watch.** Do not change behaviour after submitting; the deadline is a hard stop.

| ID | Owner | Size | Depends on | Task |
|---|---|---|---|---|
| T11X01 | AB | M | T10X02, T10A02, T10A03, T10A04, T10B02 | Final checks and submit |
| T11X02 | AB | S | T11X01 | Post-submit verification |

### T11X01: Final checks and submit

- **Owner:** Both members. **Size:** M (0.5 day). **Phase:** PH11. **Merge gate:** IG-11. **Depends on:** T10X02, T10A02, T10A03, T10A04, T10B02.
- **Read first:** demo-and-submission.md §7.
- **Create or change:** Devpost submission.
- **Acceptance:** The checklist in demo-and-submission.md section 7 is complete; submitted in PH11.
- **Tests that prove it:** checklist complete.
- **Requirements and invariants:** FR-HK-01, FR-HK-02, FR-HK-03, FR-HK-04, FR-HK-05.

### T11X02: Post-submit verification

- **Owner:** Both members. **Size:** S (0.25 day). **Phase:** PH11. **Merge gate:** IG-11. **Depends on:** T11X01.
- **Read first:** demo-and-submission.md §8.
- **Create or change:** none.
- **Acceptance:** Repo, license, video and links open while logged out; submission snapshot saved; no edits after the deadline.
- **Tests that prove it:** links open while logged out.
- **Requirements and invariants:** FR-HK-04.
