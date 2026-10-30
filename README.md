# FairPool

**Group buying where merchants compete for the group.**

FairPool lets many people who want the same product join a shared **pool** for free, inside a fixed time window. When the window closes, a published rule decides who gets a place. Merchants then compete in a sealed reverse auction to fulfil that demand at the lowest fair price. Each selected buyer approves their own PayPal payment for the exact final amount. A lot is funded only when enough **completed** PayPal captures from different buyers meet the merchant's minimum; if the minimum is not reached, every approval is voided or refunded.

> **$0 to join. No hold until a merchant meets your price and you approve.**

FairPool is built for the PayPal AI Hackathon and runs entirely in the PayPal **Sandbox**. No real money moves. AI proposes; deterministic rules decide; humans approve every payment.

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

Last updated: **30 October 2026.**

| | Status |
|---|---|
| Phase 0, bootstrap and contract freeze | **Complete.** `contracts-v1` and `ig-0` are tagged. |
| Phase 1, data, platform and shell foundations | **In progress.** The database schema and migration, platform services, complete API contract, port fakes and frontend shell are in the repository. The hosted skeleton and the final S2 PayPal check are pending before IG-1. |
| Phase 2 and later | Planned. See [docs/implementation-plan.md](docs/implementation-plan.md). |

**What works now:** `make setup`, `make verify`, the 32-table Postgres migration, the 287 backend tests and 14 frontend tests, the API contract and its OpenAPI documents, the local Docker stack, and the placeholder frontend shell.

**What does not work yet:** no buyer can join a pool, no merchant can bid, no offer or checkout exists, no PayPal call is made by the application, and no AI call runs. The new API handlers are stubs that fail with the standard error envelope until later phases replace them. The frontend pages are labelled Phase 1 placeholders.

The honest summary: this repository is the foundation and the frozen contract, not a live marketplace.

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

---

## PayPal in the Sandbox

- **Orders v2** with one `AUTHORIZE` order per buyer, addressed to the winning merchant.
- **JavaScript SDK v6** popup as the primary approval, with the redirect approval page as the fallback.
- **Webhooks** are verified and treated as hints; a server-side GET always confirms the state.
- **Authorizations, captures, voids and refunds** are called only by the payments adapter.
- **Read-only verification** through FairPool's verification endpoint, with the local PayPal MCP as optional inspection.

Demonstration limits:

- One **stand-in sandbox seller** receives payments on behalf of the winning merchant. The merchant's name still appears on screen and in the order description, and the fallback is labelled wherever it matters.
- Platform fees, Payouts, NVP/SOAP and multi-seller settlement are **not used**. Partner Referrals returned 403 in the Sandbox; the platform route is unavailable.
- US payers and USD only. India-domestic checkout is not supported.
- No production readiness, marketplace approval or merchant settlement is claimed.

---

## What we claim and do not claim

**We claim:**

- Joining is free, and no PayPal hold exists before a buyer approves a specific amount.
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

Start the database, apply the migration, and start the stack:

```powershell
docker compose --env-file .env -f deploy/docker-compose.yml up -d db
make migrate
make dev
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

The local `.env` points `DATABASE_URL` at `127.0.0.1` so host-side Alembic and tests can use it. Compose overrides `DATABASE_URL` to the `db` service inside the containers.

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
| `make test-faults` | Fault-injection suite (later phases) |
| `make ai-eval` | Real-model evaluation sets (later phases) |
| `make imports` | Import-boundary check |
| `make docs-check` | Documentation cross-check |
| `make openapi-check` | Export and verify the ten Merchant Agent API operations |
| `make secrets` | gitleaks history scan |
| `make verify` | Every check above that runs in CI |
| `make gate-check GATE=ig-1` | `verify` plus the migration check and frontend build; hosted steps are manual |
| `make lock` | Regenerate hashed lock files |
| `cd frontend && npm run gen:api` | Regenerate typed API types from the committed OpenAPI snapshot |

CI runs lint, typecheck, tests with Postgres, imports, docs, OpenAPI, the frontend build and gitleaks on every pull request and on `main`. Sandbox, fault and AI-evaluation suites are on-demand, not part of the default CI run.

---

## Configuration

`.env.example` lists every setting name with safe defaults and empty secrets. `docs/contracts/config-and-errors.md` section 1 is the authoritative table: variables, defaults, owner, secret marking and meaning.

Key values for a local run:

| Variable | Why it matters |
|---|---|
| `DATABASE_URL` | Postgres connection string; host `127.0.0.1` locally, overridden to `db` inside Compose |
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
| `SEARCH_BACKEND=postgres` | Postgres trigram fallback unless S8/T02B04 selects Elastic |
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
| Concurrency | `backend/tests/concurrency/` | later phases |
| AI evaluation | `backend/tests/ai_eval/` | on demand |
| Frontend | `frontend/tests/` | yes |

Current local count: **287 backend tests** and **14 frontend tests**. The fairness vectors, state machines, schema contract, triggers, platform services, route table, Merchant OpenAPI, port fakes, webhook stub and frontend boundaries are covered.

---

## Deployment

The production blueprint is [deploy/render.yaml](deploy/render.yaml):

- a Docker web service for the API, a background worker and a managed PostgreSQL 16 database;
- a static frontend built from `frontend/`;
- public HTTPS on 443 for the webhook listener and the SDK domain;
- every secret set in the Render dashboard, never in the file.

Per [docs/decisions.md](docs/decisions.md) BD-05, the demo uses paid instances. Free web services sleep, workers have no free type, and free Postgres expires after 30 days, which would break timers, webhooks and the job queue before judging ends.

**Current deployment status:** the hosted skeleton is not recorded yet. The owner must create the Blueprint, enter the secrets, run the migration once against the external database URL, and set `PUBLIC_BASE_URL`, `FRONTEND_BASE_URL` and `CORS_ORIGINS`. The hosted URL will be recorded in [docs/progress.md](docs/progress.md) when that is done.

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
- [docs/agents.md](docs/agents.md) — rules for AI coding agents working in this repository

The contracts in `docs/contracts/` are frozen at `contracts-v1`. Any change needs a contract change request and a new tag.

---

## License

MIT. See [LICENSE](LICENSE).
