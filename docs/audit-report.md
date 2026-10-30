# Audit report, Oct 27, 2026

Scope: every file in this folder, the PayPal Sandbox final verification checklist, the owner's integration notes, and the products' official documentation. This is a documentation package: it contains no application code, so API calls and integrations are checked at contract level. No scope was removed.

## 1. Checked and correct

| Area | How it was checked | Result |
|---|---|---|
| Docs structure | `tools/validate_docs.py` (IDs, task lists, requirement coverage, env variables, endpoints) | 0 errors, 0 warnings |
| Fairness vectors | Recomputed every value from `fairness-and-hashing.md`: canonical JSON, 5 request hashes and commitments, sorted list, Merkle root and proof, ranking order, demo seed, Ed25519 key and signature, 2-row audit chain, tax and mean rounding, tie-breaks, tier case | All pass |
| Idempotency keys | Recomputed the UUIDv5 namespace and both example keys in `paypal-adapter.md` | Match |
| State machines | Parsed all 5 machines: no duplicate IDs, no bad states, every non-initial state reachable, nothing leaves a terminal state, every job kind exists in `domain-ports.md`; enum lists equal the DB schema | Pass. `ELIGIBLE` has no exit by design (it hands over to allocation status, documented) |
| Design export | `system-design.md` compared with the uploaded v1 file | Identical before the one-line P1 fix |
| PayPal JS SDK v6 | Script URL, `createInstance` (client ID or client token), `createPayPalOneTimePaymentSession`, `onApprove/onCancel/onError`, v5 to v6 mapping | Matches PayPal docs; S13 still decides auth mode |
| PayPal Agent Toolkit | `create_order` takes items and currency only; `pay_order` captures; refund, get_order and shipment tools exist | Matches INT-5: not used in the payment path |
| PayPal MCP | Sandbox host, local `@paypal/mcp`, read tools present | Matches INT-6 (path detail corrected below) |
| Zapier MCP | Connect URL, agentic vs managed mode, locked fields, 2 tasks per call | Matches INT-2 |
| Elastic | `semantic_text`, `copy_to`, RRF retriever | Matches INT-1 (query-leg note added) |
| Hackathon rules | Deadline, 3-minute public YouTube video, public repo with license, functional demo, English, no PayPal/Devpost funding | `demo-and-submission.md` covers every item. Nov 12 12:00 pm PT = Nov 13 1:30 am IST is correct (PST) |
| Claude model names | `claude-sonnet-5-5`, `claude-haiku-5-5` | Valid |

## 2. Corrected

| File | Problem | Fix |
|---|---|---|
| `registry.md`, `system-design.md` (P1) | Said the honor period is 29 days. PayPal: authorization valid 29 days, honor period 3 days, later capture needs reauthorization and can be declined | Reworded. The existing 48 h deadline and 60 h age guard already keep captures inside 3 days |
| `config-and-errors.md` | Same point, vague | Explains why no reauthorization is needed |
| `spike-results.md`, `progress.md` (O1) | Open question answerable from the checklist | Recorded: authorization status `CREATED`, order status `COMPLETED` after authorize and void |
| `decisions.md` BD-05, `scaffold.md` section 11 | Render free tier would break the product: sleeps after 15 min, no free workers, free Postgres deleted 30 days after creation (before Dec 15 judging ends) | Paid instances required until winners are announced |
| `decisions.md` INT-4 | APIMatic prices and limits conflict across sources | Wording made source-independent; generate SDKs while trial or plan is active |
| `decisions.md` INT-6 | PayPal MCP HTTP path differs between PayPal docs (`/http`) and the registry (`/mcp`) | S10 records the one that answers |
| `decisions.md` INT-1 | Semantic leg documented as `match` and as `semantic` | S8 records which works |
| `demo-and-submission.md` | No check that hosting survives judging; no judge access note | QA items 9 and 10 added |
| `tools/validate_docs.py` | Three false-positive warnings | Exempted |

## 3. Your integration notes versus the design

The pasted sponsor and PayPal tool notes contain statements that the official documentation does not support; `decisions.md` section 5 already overrides them correctly, and this audit confirms those overrides. In short: the Agent Toolkit cannot create an AUTHORIZE order with a payee and request ID, so deterministic code creates orders; Elastic is used for retrieval, not as a requirement gate; `/v1/merchant/quote/submit` does not exist (the route is `PUT /merchant-api/v1/lots/{lot_id}/bid`); the SDK v6 popup captures nothing in the browser; the PayPal MCP is read-only.

## 4. Not settled by documents (only live runs can settle)

PayPal Login account ID (S1), payee-email routing (S7), payload ladder (S4), webhooks (S5), beacon (S6), Elastic (S8), Zapier (S9), PayPal MCP allowlist (S10), APIMatic generation (S11), shipment tracking (S12), SDK v6 approval (S13). A second seller via Partner Referrals failed (S3), so the labelled single-seller router stays in force, and checklist items 3.1 to 3.4, 3.8 and 5.1 to 5.2 remain open. Rotate the Sandbox secret and change the buyer password that appeared in a screenshot (checklist 0.1, security rules).

## 5. Schedule risk (decision for the owner)

The plan budgets 22 working days and about 29 person-days per member. From Oct 27 to a Nov 11 submission is about 15 working days, and `progress.md` shows nothing started. That needs roughly 1.9 to 2.0 times the speed the task sizes assume. No scope was changed. Decide early which items move, using the plan's own order in `implementation-plan.md` section 4.

## 6. Spike check script (added Oct 28, 2026)

`tools/fairpool_spike_check.py` automates the Sandbox regression, the S2 follow-up and S1, S4 to S13 (S3 optional); `docs/spike-check-runbook.md` lists exactly what the owner must provide. Verified here: logic against local mocks (0 failures, no leaked values); MCP clients against the official SDK 1.x and 2.x; drand BLS check against the real published quicknet round 1000 (tampered round rejected); allowlist probe against the real `@paypal/mcp` package (the version actually used in the owner's runs is 1.8.1 on `@paypal/agent-toolkit` 1.11.0; an earlier note here wrongly attributed 1.11.0 to `@paypal/mcp`). Not verified: any live PayPal, Elastic, Zapier or APIMatic call, and the S13 page in a real browser.

Findings from building it: the local PayPal MCP server restricts tools with `--tools=orders.get,disputes.list,disputes.get,shipment.get,payments.getRefunds` (confirmed by the owner's Oct 28 runs and recorded in `spike-results.md` and INT-6); `ZAPIER_BRIDGE` takes only `off` or `managed`; with `payment_source` set, PayPal returns the approval link as `payer-action`, not `approve`.

## 7. Owner Sandbox runs incorporated (Oct 28, 2026)

The owner's `FAIRPOOL_BUILD_HANDOFF.md` (real PayPal Sandbox calls) overturned several design assumptions, and the docs were changed to match. Changed: Login scope `openid` only and `DEDUPE_MODE=two_keys`; `payee_email` rejected and `single_seller` final (S7); Orders v2 `POST .../track` replaces the legacy tracker call, which returns 403 (S12); webhooks are hints for three verified event types and approval is always confirmed by GET (S5); SDK v6 popup is the primary approval UI, client ID chosen with a deployed-page repeat required (S13); the PayPal MCP is the local, pinned, read-only server for inspection only, and a client must check the reply's own `ok` field because the hosted server returned `ok=false` with `isError` unset (S10). Details: `spike-results.md` (Oct 28 table), `decisions.md` section 4, `contracts/paypal-adapter.md`.

Important caution: the script's mock servers were written from the earlier docs, so their passes only show the script's logic works. They do not show PayPal behaves that way. The handoff, not the mocks, is the live evidence. The spike script and its mocks were updated to the recorded behaviour and all three test suites pass.

Still open without code: the six-buyer approval run. Still open and needing FairPool code: pool rules, allocation, refund-on-minimum-failure, concurrency, webhook de-duplication inside the app, the Zapier actions (Agent API) and APIMatic generation (merchant OpenAPI file).

## 8. Vault-and-charge and flat delivered bids (Oct 29, 2026)

The owner's Oct 29 verification report recorded the vault spike (PASS with limits), payouts (BLOCKED) and the platform route (BLOCKED), and completed S6. The docs now carry two owner decisions: `PAYMENT_MODE=vault_charge` as the primary payment path (`contracts/vault-charge.md`; authorization-first stays as the fallback) and `BID_PRICING_MODE=flat_delivered` (`contracts/flat-delivered-bids.md`). Changes: transitions BO-23 to BO-27, job `order.vault_charge`, adapter methods for setup token, payment token, delete and `charge_vault`, table `vault_tokens`, config rows and error codes, API endpoints, FR amendments, a plan change set (C1), demo and test additions, and an agent rule on token handling.

Corrections to the proposal: the cap is FairPool's own rule (PayPal has no per-permission maximum); the Agent Toolkit cannot convert a setup token, so deterministic code does it; the flat-rate "math problem" did not exist (shipping and tax were already local table lookups) and lots are per zone, not grouped by Elastic.

Risks the docs now state: no hold means a charge can fail at close; a refund of a completed capture may not return PayPal's fees; the consent screen shows no amount; real low-balance decline and natural setup-token expiry were not tested; settlement of the winning merchant is manual; legal permission to charge later and to hold other parties' funds is unverified. The spike script (`tools/fairpool_spike_check.py`) does not cover the vault or payouts spikes; those were run by the owner and are recorded in `spike-results.md`.
