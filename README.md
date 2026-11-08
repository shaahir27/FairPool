# FairPool

**Group buying where merchants compete for the group.**

FairPool lets many people who want the same product join a shared **pool** for free, inside a fixed time window. When the window closes, a published rule decides who gets a place. Merchants then compete in a sealed reverse auction to fulfil that demand at the lowest fair price. Each selected buyer approves their own PayPal payment for the exact final amount — the hosted demo runs `PAYMENT_MODE=authorize_capture`, the mode the live Sandbox evidence exercised. A lot is funded only when enough **completed** PayPal captures from different buyers meet the merchant's minimum; if the minimum is not reached, every approval is voided or refunded.

> **$0 to join. No hold until a merchant meets your price and you approve.**

FairPool is built for the PayPal AI Hackathon and runs entirely in the PayPal **Sandbox**. No real money moves. AI proposes; deterministic rules decide; a human confirms every payment — by approving the PayPal order in `authorize_capture`, the mode this demo runs, or by recording consent at join in `vault_charge`, where PayPal's own screen shows no amount and FairPool enforces the cap.

---

## Contents

- [Current status](#current-status)
- [How it works](#how-it-works)
- [Roles](#roles)
- [Fairness and audit](#fairness-and-audit)
- [AI at the edges](#ai-at-the-edges)
- [PayPal in the Sandbox](#paypal-in-the-sandbox)
- [What we claim and do not claim](#what-we-claim-and-do-not-claim)
- [Repository layout](#repository-layout)
- [Local setup](#local-setup)
- [Commands](#commands)
- [Configuration](#configuration)
- [Containers](#containers)
- [Tests](#tests)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [License](#license)

---

## Current status

**Authentication follow-up for hosted testing (2026-11-02):** New buyers connect PayPal before creating their FairPool email/password account. Existing buyers still sign in normally. Apply migration `0005_paypal_signup` with `make migrate`, enable `PAYPAL_LOGIN_ENABLED=true` with `DEDUPE_MODE=two_keys`, and register `<PUBLIC_BASE_URL>/api/v1/auth/paypal/callback` **and** `PAYPAL_LOGIN_REDIRECT_URI` (the settings-page link flow, a separate return URL) as exact Sandbox app return URLs in PayPal, with Log in with PayPal enabled for the same app. A PayPal popup that says `invalid client_id or redirect_uri` means that exact URL is not registered or the client ID belongs to another app. For the local default this is `http://localhost:8000/api/v1/auth/paypal/callback`; use an HTTPS tunnel and matching `PUBLIC_BASE_URL` if PayPal requires HTTPS. Set `FRONTEND_BASE_URL` to the origin that actually serves the page. The page and the API must be one origin: `onrender.com` is on the Public Suffix List, so two `*.onrender.com` subdomains are cross-site to a browser and the `SameSite=Lax` session cookie is dropped between them. Signup requests `openid profile email address https://uri.paypal.com/services/paypalattributes`, and the adapter reads the identifier from userinfo only, never re-keying it. Enable Full Name, Email and the address fields on the Sandbox app. Live on 2026-11-02 PayPal accepted those scopes but returned no ID token and only `sub` and `user_id` from both identity endpoints, for a buyer created minutes earlier, so the prefill waits on PayPal's own approval of the app for customer data; the form works without it. It grants no payment permission and deduplicates PayPal accounts rather than proving unique humans. Migration 0006 adds encrypted saved delivery addresses, managed at `/settings/addresses` and reusable at checkout. The real Sandbox signup round trip still needs verification with the registered callback; offline tests use a clearly injected identity fake.

Last updated: **3 November 2026.**

| | Status |
|---|---|
| Phase 0, bootstrap and contract freeze | **Complete.** `contracts-v1` and `ig-0` are tagged. |
| Phase 1, data, platform and shell foundations | **Complete — IT-1 green.** The database schema and migration, platform services, complete API contract, port fakes, hosted skeleton and S2 check are done. Tagged `ig-1`. |
| Phase 2, core engines | **Complete — IG-2 closed on automated evidence; tagged `ig-2`.** PayPal raw-REST gateway, ledger, identity, catalog and the Gemini AI adapter with tests. Sandbox C-01 to C-07 pass; S4 verified levels 1-2; S8 selected Elastic. The 95% field threshold is met by recomputed fields, and the disclosures that keep that honest are in the Phase 2 evidence. |
| Phase 3, core engines II | **Complete — IT-3 green; tagged `ig-3`.** Buyer-order transition engine, offer expiry and seat control, pool join with signed receipts, withdrawal and SSE, pool close with the commitment Merkle root and the public signing key, PayPal Login linking, search with the Postgres fallback, and the fake vault permission lifecycle. Two evidence items pass on recorded owner decisions rather than executed work, and both say so in [docs/evidence/phase3/README.md](docs/evidence/phase3/README.md). |
| Phase 4, core engines III and the first integration | **Complete — IT-4 green; tagged `ig-4`.** Seed, allocation into lots with an ordered waitlist, the forced demo award, checkout opening with waitlist refills, the vault-charge and authorize paths, funding to FUNDED, intake and the public audit content, exercised end to end with the fake gateway. |
| Phase 5, real money path, auction core and checkout UI | **Complete — IG-5 closed on evidence; tagged `ig-5`.** One real Sandbox buyer ran the redirect path end to end and both money legs closed at a zero ledger (C-08 authorize then void, C-09 capture then refund). The failure path ends at net zero (PT-11, F9, F24), R1-R9 with the two new vector cases pass (PT-05, PT-06), the merchant profile and sealed bids with signed receipts pass their tests, the checkout address is sealed as a Fernet token under BD-11, and the buyer screens (sign in, create account, offer/checkout, order status) plus an app-wide session gate are built against CR-5. Five independent read-only review passes are recorded in [docs/evidence/phase5/independent_review.json](docs/evidence/phase5/independent_review.json): the first four failed, the fifth passed with no blocker and no major. See [docs/evidence/phase5/README.md](docs/evidence/phase5/README.md). |
| Phase 6, money hardening and the buyer's first screens | **Complete — IG-6 closed on evidence; tagged `ig-6`.** Lot handlers that award real sealed bids, webhook verification and processing with a dead letter, the authorization age guard, payload levels, merchant API keys, AI quote reconciliation, and the buyer's Discover, lobby and entry receipt. See [docs/evidence/phase6/](docs/evidence/phase6/). |
| Phase 7, live end to end and the agent and merchant lanes | **Complete — IG-7 closed on evidence; tagged `ig-7`.** The PayPal JS SDK v6 popup approval (C-17) with its redirect fallback, labelled payment routers, the ops console (lot state, alerts, dead letters, reconciler runs, MOCK toggles, audit export), the buyer's My Pools and Orders, the Agent API with hashed, scoped, revocable delegations, the FairPool MCP endpoint with exactly four tools and no payment tool, the Merchant Agent API's lot/bid operations, and the advisory LOW_SIMILARITY flag after a confirmed bid. IT-7 ran live against PayPal Sandbox: one lot funded on a completed capture, a second lot voided to a zero ledger, one refill wave, and the agent, MCP and merchant-key lanes. The evidence records one owner waiver: the in-run lot-2 refund, because the refill approval missed its offer window and IT-6 already proved capture-to-refund-at-zero live on this code. See [docs/evidence/phase7/](docs/evidence/phase7/). |
| Phase 8, fulfilment, verification, merchant console and simulation | **Complete — IG-8 closed on evidence; tagged `ig-8`.** The merchant journey end to end — Demand Board with SSE and sealed-bid submission, Active Bids with the holds-then-captures tracker, Developer keys and Profile — and the fulfilment journey: the funded shipping list in JSON and CSV, shipment marks and tracking, the no-PII verification manifest and the read-only verification that compares each capture with PayPal. The operator gets metrics, four alert rules, security headers and rate limits; the simulation allocates 10,000 entries in 5.4 seconds and is labelled and isolated from public lists. Roles are enforced server-side: a merchant cannot join a pool it will bid on. S9 (the Zapier trial) is recorded in [docs/evidence/phase8/s9.json](docs/evidence/phase8/s9.json) with its limit stated: managed mode served a locked, read-only GET tool live, while both write tools could not send a schema-valid body, so `ZAPIER_BRIDGE` stays off and FairPool's `/mcp` endpoint remains the agent path. |

**What works now:** `make setup` and `make verify`; a 37-table Postgres schema plus `alembic_version` (22 enum types, 12 triggers) through migration 0006; the full backend suite (1202 offline tests, plus the **18 fault tests** the gate also runs on their own), with one skip that names itself; **219 frontend tests**; the API contract and its OpenAPI documents; the local Docker stack; the Phase 2 to Phase 8 engines, the agent and merchant lanes and the twenty-three registered worker handlers; a notifications inbox that lists and clears the events each role already receives; a PayPal-first signup and a saved-address book, both proven end to end against the deterministic fake identity provider (a fresh live Sandbox consent round trip is still outstanding); a demo seeder that builds a live, purchasable pool in the local and hosted databases; and the hosted app at <https://fairpool-api.onrender.com> (page and API on one origin, which is what keeps the session cookie first-party) backed by Supabase. The separate static preview is suspended, so this is the only app URL. The tags that exist are `ig-0` to `ig-8` and `contracts-v1` to `contracts-v1.6`.

**What works from Phase 6 (merged to `main`, CI green, deployed; the gate is closed and tagged `ig-6`):** the lot handlers that open a bid window, close it, award a lot from real sealed bids through the `ranking_v1` rules with its database loader, and hand the award to checkout; AI quote parsing into a bid the merchant confirms, with reconciliation flags that can only withhold an offer; PayPal webhook verification and processing with a dead letter and a retry route; the authorization age guard that settles a hung hold by what PayPal says about it; merchant API keys (shown once, stored as an HMAC) with `MerchantAuth` for both a session and a key; and the buyer's Discover screen, pool lobby and entry receipt, which can be copied, downloaded or printed.

**What works from Phase 7 (merged to `main` in `b63e34c`, CI green, deployed; the gate is closed and tagged `ig-7`):** the PayPal JS SDK v6 approval with its client-token grant and redirect fallback (the browser still sends no amount); labelled payment routers; the ops console for lot state, alerts, dead letters, reconciler runs, MOCK toggles (honest about applying to the process serving the request) and the audit export; the buyer's My Pools and Orders tabs; the Agent API with hashed, scoped, revocable delegation tokens and idempotent entries; the FairPool MCP endpoint with exactly four tools and no payment tool; the Merchant Agent API's five lot/bid operations behind hashed keys and scopes; and the advisory LOW_SIMILARITY warning after a confirmed bid. The live IT-7 run and the C-17 popup approval are recorded in `docs/evidence/phase7/`, including the one owner waiver and its reason.


**Demo data (2026-11-05).** `make demo-seed` builds a coherent five-pool scenario on the development database (`DEMO_SEED_HOSTED=1` with `APP_ENV=local` is the explicit opt-in that seeds the hosted database; the seeding process runs in local mode only so the admin demo helper stays gated on the live app): a Demand Board with two lots in bidding, an awarded checkout with two live offers, a funded lot with two captured orders, sealed addresses and shipments, a failed lot at a zero ledger, and a labelled 10,000-entry simulation. The accounts are `demo-merchant@fairpool.test` and `demo-merchant-2@fairpool.test` (merchant role, profiles and the three attestations), `demo-buyer-1` to `demo-buyer-6`, and `demo-admin`. Every account uses `DEMO_SEED_PASSWORD` from `.env`, which is never printed or committed; `tools/demo_seed_check.py` re-reads the database and asserts the state. The demo provider references are shaped `DEMO-…` and no PayPal call is made while seeding, so the fulfilment verification shows those rows as unverifiable rather than pretending they are live captures.

**What does not work yet:** live vault save is deferred (`VAULT_CHARGE` remains unavailable and `VAULT_REAL_SAVE_ENABLED=false`), `WEBHOOKS_ENABLED` is false, so seven real deliveries from the live run were stored and one was verified by the C-15 test but none was processed, the buyer cannot release their own hold before payment (the order screen says so; withdrawing an *entry* while the pool is open does work), the audit page recomputes the rules hash, the Merkle root, the chain checkpoint signature and each buyer's rank in the browser, but it still cannot prove that the published commitment list is complete, and the beacon round's BLS signature is not verified (CR-11 records why), a ratified mandate's conditions are stored, validated and returned but no agent surface evaluates them yet, so they advise rather than enforce (the cap, scope and expiry are enforced), live shipment tracking (C-18) is an owner run, the Zapier bridge (S9) is recorded read-only because its managed-mode write tools could not send a schema-valid body (FairPool's `/mcp` endpoint is the agent path), and the auction and money work has been run live end to end: a two-lot pool, four real sealed bids, the award, a buyer approval, a real authorization captured to COMPLETED and refunded to COMPLETED, and a second lot voided to a zero ledger. The real-money path *has* been exercised: one Sandbox buyer through offer, approval and server-side authorize, then void to a closed lot at zero ledger, and a second run through capture, funding and refund to zero ledger (C-08, C-09, IT-5). The hosted service runs the Phase 8 build since 5 November 2026; `https://fairpool-api.onrender.com` is the app URL.

**Vault charge is the default, not authorization.** `PAYMENT_MODE` defaults to `vault_charge`: the buyer saves a PayPal permission and the server charges the exact awarded amount after the award. The `authorize_capture` path, where the buyer approves an AUTHORIZE order per lot, is the fallback and does not run unless the mode is changed. In vault mode a live-sandbox buyer still cannot become eligible at close, because saving a permission for real is `T05A01` (`DEP-5`); today that path is fake-only and every screen that depends on it must say so.

The honest summary: this repository now runs the Phase 4 pipeline against fakes, not against PayPal. No money has moved through the application.

---

## How it works

1. **Join for free.** A buyer describes what they want and their maximum total. AI proposes the structured fields; the buyer checks and confirms them. Only then does the request become an entry. Joining places no PayPal hold.
2. **Close and allocate.** When the window closes, every eligible entry is frozen as a commitment and published. A public seed is announced after the close. Each entry's position is computed from its commitment and the seed, and lots are filled in that order. Entries beyond the seats form an ordered waitlist. Each buyer gets a receipt.
3. **Bid sealed.** Merchants submit structured, sealed bids for lots that already exist: product, condition, bundle, capacity, minimum order quantity, up to three price tiers, shipping and tax rules, delivery and returns. A merchant can paste a quote; AI proposes the fields and the merchant confirms them. Only confirmed fields reach the rules.
4. **Award.** Deterministic rules reject late, incomplete, mismatched or infeasible bids. Among feasible bids, the lowest qualifying delivered price wins, using a published tie-break. The award is frozen as an immutable record.
5. **Approve individually.** Each selected buyer sees the winning merchant, exact product, terms and their own total (never above their cap). They approve on PayPal through the JavaScript SDK v6 popup, with PayPal's own approval page as the fallback. The browser never sends an amount.
6. **Fund only when real.** The server fetches the approved order, checks amount, currency, payee, payer country and duplicate rules, and authorizes it. Once enough **completed captures from different buyers** reach the merchant's minimum, the lot is funded. Pending or declined captures never count.
7. **Fail safely.** If a lot misses its minimum, uncaptured authorizations are voided, completed captures are refunded, late captures are reconciled, and the lot closes only when net paid is zero. Fulfilment starts only after funding.

A large pool can split into several lots. Two lots in the same pool can have different winning merchants and prices; buyers are told this before allocation.

---

## Roles

| Role | What they do |
|---|---|
| **Buyer** | Describes the product and cap, joins a pool free, confirms the structured request, approves one PayPal payment if selected. |
| **Buyer's AI assistant** | Joins or checks a pool through the documented Agent API or FairPool MCP server. It can never pay; only the buyer approves on PayPal. |
| **Merchant** | Finds open demand, submits a sealed bid per lot, confirms the parsed quote, and fulfils the lots it wins. |
| **Merchant's pricing bot** | Submits structured bids through a merchant API key and the generated SDKs. A bot's structured submission is its confirmation. |
| **FairPool operator** | Runs pools, watches lots, handles exceptions and refunds, and can reconcile every money fact with PayPal. |
| **Public auditor** | Checks the published rules, commitments, seed and results. Only public, anonymised data is shown. |

---

## Fairness and audit

- Each entry has a **commitment**: a SHA-256 fingerprint over its canonical request, pool, entry ID and a per-entry salt.
- At close, the sorted commitment list, the Merkle root and the count are published **before** the seed exists.
- The seed comes from the announced public randomness round (or a labelled demo seed). The ranking is a hash of the seed and the commitment, so anyone with the published list and seed can recompute the same order.
- Each buyer receives a signed receipt and can verify their own place in the browser.
- The audit log is an append-only hash chain. Checkpoints are published at pool close and award.

This makes selection **auditable under published rules**. It does **not** prove that no eligible entry was omitted, and it is not "provably fair".

Duplicate control is **account-level**: one entry per linked PayPal account per pool where the PayPal Login account ID works, and account-level checks at checkout otherwise. It does not prove one human per account and does not eliminate bots or account farms.

---

## AI at the edges

AI is used only at the edges:

- turns a buyer's free text into proposed structured fields and asks clarifying questions;
- turns a merchant's pasted quote into proposed fields;
- flags serious mismatches in a bid, which can hold it for correction;
- writes varied simulation text.

The buyer or merchant confirms what the AI proposed. Deterministic rules check every field and make every decision. AI can never create, authorize, capture, void or refund a payment, and no AI-callable tool of ours can move money. Buyer requests, caps and personal data are never indexed by search.

### A mandate, not a blank cheque

A buyer can hand an AI client permission to act for them without handing it money. The model reads what the buyer wrote together with the request they already confirmed, and proposes a **delegation mandate**: which pools the agent may see, a maximum it may commit, when that permission expires, and a short list of stop-and-ask conditions. The conditions are drawn from a closed vocabulary — a price ceiling, a funding threshold, a blocking flag on the winning bid, a delivery date, an award deadline — with typed parameters, so the model selects a predicate rather than composing logic.

The buyer reads the proposal as plain text, may edit every field, and confirms it before a token exists. Three properties are enforced in code, not in the prompt:

- the mandate may **narrow** a ceiling but never raise the one the buyer stated;
- the reserved acts are stamped by the server and are absent from the model's output schema, so an invented `reserved` field fails validation instead of being ignored;
- the conditions survive to the stored token only together with a hash of the canonical mandate fields (scope, cap, expiry and the ordered conditions), and the server recomputes that hash when it mints, so neither a condition nor a higher cap can ride on a permission the buyer did not ratify.

### An agent-populated market, measured

`tools/agent_market.py` runs the buyer and merchant surfaces with agent participants and an adaptive adversary, over a pool whose payments use the fake router. It reports what was attempted and what refused, and the four MCP tools it exposes are exactly four: list pools, enter a pool, list entries, withdraw.

Measured in the self-check run recorded under `docs/evidence/phase9/`:

| Check | Result |
|---|---|
| Forged delegation token | refused 401 `DELEGATION_INVALID` |
| Entry above the delegation's ceiling | refused 403 `DELEGATION_CAP_EXCEEDED` |
| Read-only merchant key submitting a bid | refused 403 `API_KEY_SCOPE` |
| Another merchant's sealed bid | 404 `NOT_FOUND`, never a 403 |
| MCP body over 64 KiB | refused 413 before dispatch |
| Institutional text inside merchant notes | stored and flagged for review, not treated as an instruction |
| PayPal writes originating from an AI-callable surface | **0**, derived by joining buyer orders to entries and counting delegated ones |

That zero is a measured result, not a guarantee: the run states how many attempts it made, and absence of an observed breach across those attempts is not a claim of security.

### How the extraction itself is measured

Model output is scored on labelled corpora — intake messages, merchant quotes, reconciliation cases and simulation cases — and the numbers are kept under `docs/evidence/` with the model, prompt and dataset fingerprint attached. The corpus is a fixed set, so a prompt or model change requires a fresh measured run before the figures are quoted again; a change without one is rejected by the gate tool rather than silently accepted.

### Development-time PayPal context

Coding agents on this project used the **APIMatic ContextMatic** plugin for version-aware PayPal API context while building the adapter, alongside the PayPal AI Toolkit skills. Verified Sandbox facts and recorded spike results override anything a plugin says, and the adapter calls raw REST rather than the Server SDK. The Merchant Agent API publishes a committed OpenAPI document and that document is the intended input to APIMatic's generator; the generated SDKs themselves are not committed yet, so nothing here claims they exist.

---

## PayPal in the Sandbox

- **Orders v2** with one `AUTHORIZE` order per buyer, for the exact final amount. In this Sandbox app the order is addressed to the stand-in seller, not to the winning merchant, because the app has no marketplace permission; the merchant's name is shown to the buyer.
- **JavaScript SDK v6** popup as the primary approval, with the redirect approval page as the fallback.
- **Webhooks** are verified and treated as hints; a server-side GET always confirms the state.
- **Authorizations, captures, voids and refunds** are called only by the payments adapter.
- **Read-only verification** through FairPool's verification endpoint, with the local PayPal MCP as optional inspection.

Demonstration limits:

- One **stand-in sandbox seller** receives payments on behalf of the winning merchant. The merchant's name still appears on screen and in the order description. The fallback is labelled on the checkout offer screen, in the hold notice beside the amount, and on the ops lot panel, which prints the stamped `payment_mode`.
- Platform fees, Payouts, NVP/SOAP and multi-seller settlement are **not used**. Partner Referrals returned 403 in the Sandbox; the platform route is unavailable. A refund of a completed capture may not return PayPal's processing fees, and the Sandbox cannot show either way: "net zero" below means **FairPool's ledger**, which records captured and refunded amounts, not a fee-inclusive PayPal account balance.
- US payers and USD only. India-domestic checkout is not supported.
- No production readiness, marketplace approval or merchant settlement is claimed.

---

## What we claim and do not claim

**We claim:**

- Joining is free, and no PayPal hold exists before a buyer approves a specific amount. This is what `authorize_capture`, the mode this demo runs, does; in `vault_charge` nothing is held at all and the buyer records consent at join instead.
- Selection follows a published rule with a public seed and per-buyer receipts, and it is **auditable under published rules**.
- One entry per linked PayPal account per pool where the account-ID check works, and account-level duplicate control at checkout otherwise.
- A lot is funded only when completed PayPal captures reach its minimum.
- Failed lots are voided or refunded, with net zero.
- Every fallback and simulation is labelled.

**We do not claim:**

- that selection is provably or cryptographically fair;
- one person, one entry, or that bots are eliminated;
- that money is "safe", that buyers "will not be charged", or that savings are guaranteed;
- wholesale prices, or that merchants will compete on price;
- MAP compliance, which sealing does not provide;
- production readiness, marketplace approval or merchant settlement;
- that the AI verifies or approves payments;
- that a simulation proves buyer conversion, merchant participation or price reductions;
- anything about products, brands or prices that the demonstration does not use.

---

## Repository layout

```text
FairPool/
  AGENTS.md                 Codex instruction file; graphify output is local-only
  README.md  LICENSE  Makefile
  .env.example              every setting name; no values
  .github/                  CODEOWNERS, templates, CI
  docs/                     idea, design, contracts, plan, tests, decisions, progress
  backend/
    alembic.ini  migrations/
    src/fairpool/
      config.py  logging.py  main.py  worker.py  ports.py  wiring.py
      domain/               pure money, hashing, fairness, auction rules, states
      db/                   async session, readiness, models
      infra/                clock, jobs, audit chain, idempotency
      api/                  schemas, dependencies, routers, Merchant Agent sub-app
      adapters/             PayPal, AI, beacon, search (later phases)
      modules/              identity, catalog, pools, checkout, webhooks, ...
      fakes/                one deterministic fake per port
    tests/                  unit, property, integration, sandbox, faults, concurrency, ai_eval
  frontend/                 Vite + React + TypeScript + Tailwind shell (17 routes)
  sdk/                      generated Merchant Agent API OpenAPI document
  deploy/                   Dockerfiles, compose, Render blueprint
  tools/                    docs validator, import-boundary check, OpenAPI exporter, spike harness
```

The only committed SDK artifact today is the Merchant Agent API OpenAPI document. Generated SDKs arrive in a later phase.

---

## Local setup

### Prerequisites

- **Python 3.12**
- **Node.js 20 or newer**
- **Docker Desktop** with Compose
- **Git**
- **make** (the project uses a conda environment on Windows)
- **gitleaks** for `make secrets` (`winget install Gitleaks.Gitleaks -e`)

The project path used in the examples is `D:\Desktop\project\FairPool`. Replace it with your clone path.

### First run (PowerShell)

```powershell
conda create -n fairpool python=3.12 make -c conda-forge -y
conda activate fairpool

git clone https://github.com/shaahir27/FairPool.git
cd FairPool
Copy-Item .env.example .env
# Fill the required values in .env. Never commit this file.
make setup
```

`make setup` creates `.venv`, installs the hashed Python locks, installs pre-commit, and runs `npm ci` for the frontend.

Apply the migration to Supabase and start the stack:

```powershell
make migrate
make dev
```

For offline test suites and fault tests, start the isolated local test database and
create the disposable test database once (the suite refuses any other target):

```powershell
docker compose --env-file .env -f deploy/docker-compose.yml --profile test-db up -d db
docker compose --env-file .env -f deploy/docker-compose.yml exec db \
  psql -U fairpool -d postgres -c 'CREATE DATABASE fairpool_test'
```

Point `TEST_DATABASE_URL` in `.env` at that container (`postgresql+asyncpg://fairpool:fairpool@127.0.0.1:5432/fairpool_test`). `make test` uses it instead of `DATABASE_URL`, so the hosted demo database is never reset, migrated or written by a test run.

Without Docker, one command opens both windows (no `make` needed):

```powershell
.\dev.ps1
```

Or run them yourself, in two terminals, instead of `make dev`:

```powershell
make migrate
make api     # http://localhost:8000
make web     # http://localhost:5173, proxies /api to the API
```

Open:

- frontend: <http://localhost:5173>
- API health: <http://localhost:8000/health>
- API docs: <http://localhost:8000/docs>
- Merchant Agent API docs: <http://localhost:8000/merchant-api/v1/docs>

`make dev` runs Compose in the foreground. Stop it with `Ctrl+C`, then:

```powershell
docker compose --env-file .env -f deploy/docker-compose.yml down
```

Both the local app and Render share Supabase via `DATABASE_URL`. Compose runs `api`, `worker` and `frontend` directly without requiring a local Postgres container for normal operation. The local container `db` is retained under profile `test-db` for isolated test runs (`TEST_DATABASE_URL`).

### Migrations

```powershell
make migrate       # alembic upgrade head
make db-reset      # downgrade base, then upgrade head
python -m alembic -c backend/alembic.ini check
```

The migration is the single source of truth for the schema. A later schema change needs a contract change request and a new numbered migration.

### Frontend only

```powershell
cd frontend
npm ci
npm run dev        # Vite on 5173
```

### Checks

```powershell
make lint
make typecheck
make test
make verify
```

`make test` and `make verify` include integration tests, so the local Postgres must be running. `make verify` covers backend lint and types, backend tests, frontend tests, import boundaries, documentation, the Merchant OpenAPI check, and gitleaks.

---

## Commands

| Command | What it does |
|---|---|
| `make setup` | Create `.venv`, install Python and frontend dependencies, install pre-commit |
| `make dev` | Start db, api, worker and frontend with Compose (foreground) |
| `make migrate` | Apply migrations |
| `make db-reset` | Downgrade to base and migrate again |
| `make lint` | Ruff and ESLint |
| `make typecheck` | mypy (strict for domain and modules) and `tsc --noEmit` |
| `make test` | Backend unit/property/integration and frontend tests |
| `make test-sandbox` | Non-interactive PayPal Sandbox contract tests (when they exist) |
| `make test-sandbox-interactive` | Sandbox tests that need a human approval |
| `make test-faults` | Fault-injection suite: the 18 tests marked `faults` -- F5, F9, F10, F16, F24 and the webhook F2/F3/F4 cases. F7 and F8 carry the `integration` mark and run in the main suite |
| `make ai-eval` | Real-model evaluation sets (later phases) |
| `make imports` | Import-boundary check |
| `make docs-check` | Documentation cross-check |
| `make openapi-check` | Export and verify the ten Merchant Agent API operations |
| `make secrets` | gitleaks history scan |
| `make verify` | Every check above that runs in CI |
| `make gate-check GATE=ig-1` | `verify` plus the migration check and frontend build; hosted IT-1 steps are recorded in `docs/progress.md` |
| `make lock` | Regenerate hashed lock files |
| `cd frontend && npm run gen:api` | Regenerate typed API types from the committed OpenAPI snapshot |

CI runs lint, typecheck, tests with Postgres, imports, docs, OpenAPI, the frontend build and gitleaks on every pull request and on `main`. Sandbox, fault and AI-evaluation suites are on-demand, not part of the default CI run.

---

## Configuration

`.env.example` lists every setting name with safe defaults and empty secrets. `docs/contracts/config-and-errors.md` section 1 is the authoritative table: variables, defaults, owner, secret marking and meaning.

Key values for a local run:

| Variable | Why it matters |
|---|---|
| `DATABASE_URL` | Postgres connection string; points to Supabase for the local app and Render (`TEST_DATABASE_URL` used for offline tests) |
| `SECRET_KEY`, `HMAC_KEY` | Session signing and account-key HMAC |
| `RECEIPT_SIGNING_KEY` | Ed25519 private key for buyer receipts, base64url |
| `ADDRESS_ENCRYPTION_KEY` | Fernet key for shipping addresses |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | Sandbox REST app credentials |
| `PAYPAL_WEBHOOK_ID` | Registered webhook ID (S5); empty until the handler ships |
| `SINGLE_SELLER_EMAIL` | The Sandbox business account that owns the REST app and receives payments |
| `VAULT_TOKEN_KEY` | 32-byte base64 key for saved PayPal permissions |
| `PUBLIC_BASE_URL`, `FRONTEND_BASE_URL`, `CORS_ORIGINS` | Public origins for returns, redirects and CORS |
| `PAYMENT_MODE=vault_charge` | Primary payment path; `authorize_capture` is the fallback |
| `PAYMENT_ROUTER=single_seller` | The only usable Sandbox route; labelled on screen |
| `DEDUPE_MODE=two_keys` | Login and checkout identifiers are separate provider keys |
| `WEBHOOKS_ENABLED=false` | Enable only when the verified handler ships |
| `SEARCH_BACKEND` | `postgres` fallback, or `elastic` when `ELASTICSEARCH_URL` and the API key are set; S8 verified `ELASTIC_INFERENCE_ID=.jina-embeddings-v5-text-small` |
| `AI_ENABLED` | Turns the AI adapter on when a key is present |

Never commit `.env`. The PayPal host guard accepts only `https://api-m.sandbox.paypal.com` and `https://www.sandbox.paypal.com` on port 443.

---

## Containers

`deploy/docker-compose.yml` defines:

| Service | Port | Purpose |
|---|---|---|
| `db` | 5432 | PostgreSQL 16 with `citext` and `pg_trgm` |
| `api` | 8000 | FastAPI app, `/health`, `/ready`, `/docs` |
| `worker` | none | Postgres job-queue worker |
| `frontend` | 5173 | nginx serving the built React SPA |
| `elastic` (optional profile) | 9200 | Local search experiments |

`deploy/Dockerfile.api` and `Dockerfile.worker` run the backend from source with `PYTHONPATH`; the frontend image is a multi-stage Node build served by nginx. The API container respects Render's `PORT`.

---

## Tests

| Layer | Location | Runs in CI |
|---|---|---|
| Unit and contract | `backend/tests/unit/` | yes |
| Property | `backend/tests/property/` | yes |
| Integration (Postgres, fakes) | `backend/tests/integration/` | yes |
| Sandbox contract | `backend/tests/contract_sandbox/` | on demand |
| Fault injection | `backend/tests/faults/` | on demand |
| Concurrency | `backend/tests/concurrency/` | yes |
| AI evaluation | `backend/tests/ai_eval/` | on demand |
| Frontend | `frontend/tests/` | yes |

Current local count: **1202** offline backend tests plus the **18** fault tests that `make test-faults` runs separately, and **219 frontend tests** in 25 files. The fairness vectors, state machines, schema contract, triggers, platform services, route table, Merchant OpenAPI, port fakes, intake rules, allocation and funding engines, and frontend boundaries are covered.

---

## Deployment

The live Phase 1 skeleton is deployed on Render's **free** tier and grouped in the Render project **`fairpool`** → environment **`production`**:

- API: <https://fairpool-api.onrender.com> — free Docker web service, health check `/health`;
- Frontend: <https://fairpool-frontend.onrender.com> — free static site, SPA rewrite to `index.html`. **Suspended by a user since 2026-11-03** (it answers 503 `Service Suspended`), which costs nothing: the app is served from the API origin below, and a second subdomain could never keep the session cookie anyway. Use `https://fairpool-api.onrender.com` as the app URL;
- Database: **Supabase free Postgres** (session pooler, PostgreSQL 17); the Render Postgres was deleted after the switch;
- No background worker in the free skeleton.

The services were created through the Render API because Blueprint creation is dashboard-only. [deploy/render.yaml](deploy/render.yaml) is the reference for the two Render services; it does not provision a database. Set `DATABASE_URL` to the Supabase session-pooler URL.

The API image also builds the frontend and serves it from its own origin (`/app/web` in the image, `WEB_DIR` in `api/app.py`), so `fairpool-api.onrender.com` is the working app URL and the session cookie stays first-party. The separate static frontend remains a preview of the pages only: with no cookie surviving between the two subdomains, nothing signed-in works there. Set `FRONTEND_BASE_URL` and `CORS_ORIGINS` to the API origin for that deployment.

**IT-1 evidence (2026-10-31):** migration `0001` applied (32 application tables plus `alembic_version`, 21 enums); `/health` 200; `/ready` 200 (`database` and `migrations` ok); `POST /webhooks/paypal` 200 with the raw body stored and duplicate events suppressed; frontend `/` and `/settings` serve the SPA. Recorded in [docs/progress.md](docs/progress.md).

Free-tier limits: the Render API sleeps after 15 minutes idle and there is no free worker; free Supabase pauses after about 7 days without database activity. [`.github/workflows/keep-warm.yml`](.github/workflows/keep-warm.yml) requests `/health` and `/ready` every 10 minutes between 03:00 and 22:00 UTC, which keeps both awake while staying inside the 750 free instance hours a month; it stays disabled while this repository is private (a scheduled job on a private repository burns the free Actions minutes and would block CI) and is enabled by the same change that makes the repository public. The cadence, the hour arithmetic and the manual wake button are recorded in [docs/navigation-performance.md](docs/navigation-performance.md). That is enough to verify the hosted skeleton, but not for the live demo. Restore the worker and paid Render web service before **2026-11-20** per [docs/decisions.md](docs/decisions.md) BD-05. The final QA checklist currently calls for a paid Postgres for judging; that database decision is still open.

---

## Documentation

- [docs/00-index.md](docs/00-index.md) — map of the documentation package
- [docs/fairpool-idea.md](docs/fairpool-idea.md) — the product idea and its limits
- [docs/product-spec.md](docs/product-spec.md) — functional requirements
- [docs/system-design.md](docs/system-design.md) — architecture and invariants
- [docs/contracts/README.md](docs/contracts/README.md) — frozen contracts index
- [docs/implementation-plan.md](docs/implementation-plan.md) — phases, tasks and gates
- [docs/testing-strategy.md](docs/testing-strategy.md) — test layers and IT gates
- [docs/decisions.md](docs/decisions.md) — confirmed decisions, spike switches and integrations
- [docs/progress.md](docs/progress.md) — current status, gates and open questions
- [AGENTS.md](AGENTS.md) — rules for AI coding agents working in this repository

The contracts in `docs/contracts/` are tagged through `contracts-v1.6` on `main`. That tag is the first to carry CR-8's guard widening and CR-9's receipt read-back: CR-9's own change-log entry deliberately claimed no tag of its own, so it rides on the gate tag.

---

## License

MIT. See [LICENSE](LICENSE).
