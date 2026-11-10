# FairPool

**Group buying where merchants compete for the group.**

FairPool brings together people who want the same product, gives merchants a way to bid for that demand, and lets each selected buyer approve their own PayPal payment. Joining a pool is free. Buyers set their maximum delivered price before joining; they see the merchant, exact total and terms before approving a payment.

An individual buyer usually cannot promise the volume that makes a bulk offer worthwhile. A merchant cannot tell whether a collection of interested people will actually buy. FairPool connects those two sides through a published entry window, an auditable allocation rule, sealed merchant bids and a minimum funding threshold.

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/). This is a **Sandbox prototype**: PayPal uses test accounts and test funds. No real money moves.

**[Open FairPool](https://fairpool-api.onrender.com/)** · [Source](https://github.com/shaahir27/FairPool) · [Product idea](docs/fairpool-idea.md) · [Technical docs](docs/00-index.md)

**Demo video:** YouTube link coming after the final recording. <!-- Replace with the public YouTube URL before submission. -->

## Start here

- **Trying the app?** Read [the walkthrough](#try-the-demo) and [the current limits](#current-limits).
- **Running it yourself?** Start with [local setup](#local-setup), then [demo data](#demo-data).
- **Reviewing the implementation?** See [PayPal](#how-paypal-is-used), [AI](#how-ai-is-used), [architecture](#architecture) and [verification](#tests-and-verification).
- **Building an agent integration?** See [APIs and generated SDKs](#apis-and-generated-sdks).

## How it works

1. **Find a pool.** Browse published products or describe what you want. AI proposes a matching pool and structured requirements; you review them. A manual form is available too.
2. **Join for free.** Confirm one unit, your maximum total including shipping and tax, and your delivery requirements. You receive a signed entry receipt. Joining creates no PayPal payment or hold.
3. **Allocate places.** Every eligible entry submitted before the published cutoff is considered under the same rule. Arriving earlier gives no priority. The pool closes, its entry commitments are frozen, and a seeded ranking assigns places and an ordered waitlist.
4. **Let merchants bid.** A pool can contain several fulfilment groups, called **lots**. Merchants submit sealed bids for each lot. Deterministic rules reject bids that violate firm requirements and rank qualifying bids.
5. **Review your offer.** A selected buyer sees the winning merchant, product, delivered total, delivery and return terms, and an approval deadline. A buyer whose cap is too low is priced out; a released place can go to the waitlist.
6. **Approve on PayPal.** The hosted demo uses `PAYMENT_MODE=authorize_capture`: each buyer approves an individual order for the exact amount, and the server verifies it before placing a hold. Captures follow the lot's funding rules. **FUNDED** means enough completed captures from distinct buyers have reached the merchant's minimum—not merely that enough people joined or approved.
7. **Fulfil or unwind.** A funded lot opens its shipping workflow. If funding fails, outstanding authorizations are voided and completed captures are refunded. Buyers can follow the recorded outcome in Orders.

For example, several buyers may want the same monitor but set different price limits. A merchant can offer a delivered price for a minimum number of buyers. A winning bid does not oblige every entrant to buy: the allocation, each buyer's cap, their approval and the lot's completed payments still matter. Different lots in one pool can finish with different merchants, prices or outcomes.

## Try the demo

Open **[fairpool-api.onrender.com](https://fairpool-api.onrender.com/)**. The frontend and API share this origin so sign-in works with first-party cookies. The old separate static preview is not the app URL. A free Render instance may need time to wake after inactivity.

| Workspace | What to explore |
|---|---|
| Buyer | Discover and Join, a pool's product and entry details, My Pools, offer review, Orders, saved addresses and agent permissions |
| Merchant | Demand Board, sealed quote submission, Active Bids, funding progress, fulfilment, verification and API keys |
| Operator | Pool creation, lot progress, job/reconciliation controls, alerts and audit exports |
| Public audit | Published rules, entry commitments, draw/lot evidence, tamper checks and the buyer's receipt checker |

A useful first tour is **Discover → View pool → Your entry / product requirements → Public audit**, then **My Pools → offer or order status**. The discovery cards distinguish recorded demand, capacity and the merchant minimum; an open pool has no awarded price yet.

Existing demo users sign in with their FairPool credentials. The seeded buyer is `demo-buyer-1@fairpool.test`; its password is supplied privately by the operator, never in this repository. New-buyer registration goes through PayPal connection and depends on the configured Sandbox login app. A PayPal connection identifies an account; it does not grant payment permission.

To approve a payment, use a **US PayPal Sandbox personal buyer account**, not your real PayPal login. Create test accounts through the [PayPal developer dashboard](https://developer.paypal.com/dashboard/). Seeded historical orders illustrate states; they are not evidence that those particular orders reached PayPal. Follow an available live offer for an actual Sandbox approval.

## How PayPal is used

PayPal is part of the group-funding workflow, rather than a payment button added after the purchase decision:

- **Orders v2:** one server-created order per buyer, addressed to the configured Sandbox payee. The server checks the approved order, payer, payee, amount, currency, deadline and seat before authorization.
- **JavaScript SDK v6:** buyer approval in a popup, with a redirect fallback. The browser sends no payment amounts and does not authorize or capture.
- **Authorization, capture, void and refund:** only the server-side payment adapter can make these calls. Stable request IDs and reconciliation handle retries. An order status alone never proves payment; a completed capture does.
- **Webhooks and reconciliation:** signatures and duplicate events are checked; events prompt a resource fetch rather than serving as payment proof. Webhook processing is implemented but disabled in the hosted blueprint. The reconciliation path remains available.
- **Shipment tracking and verification:** tracking can be submitted after fulfilment. A merchant can compare recorded captures with PayPal through the read-only verification endpoint and download a manifest without buyer personal data.

The current integration uses **one stand-in Sandbox seller** (`PAYMENT_ROUTER=single_seller`). The app lacks marketplace partner access, so the winning merchant's identity is shown while payments go to that configured seller. Checkout and operations screens disclose this fallback. Platform fees and multi-seller settlement are unavailable.

Real Sandbox evidence includes authorization/void, capture/refund, SDK popup approval and funding flows. Start with [Phase 5](docs/evidence/phase5/README.md), [Phase 7](docs/evidence/phase7/) and the [current rehearsal record](docs/evidence/phase10/rehearsal_1.json). Those records distinguish executed provider calls, deterministic tests and owner decisions. A refund restores FairPool's captured-minus-refunded ledger; this is not a claim about PayPal processing fees or a fee-inclusive account balance.

## How AI is used

Google Gemini, through `google-genai`, turns conversational input into proposals that the rest of the application can validate:

| Task | What AI contributes | What decides the result |
|---|---|---|
| Buyer intake | Extracts product, delivery needs and maximum price; proposes a match or clarification | Schema validation, pool rules and the buyer's confirmation |
| Merchant quote parsing | Extracts structured fields from a pasted quote | Merchant review and the deterministic bid rules |
| Offer reconciliation | Flags product or requirement mismatches, with explanations | Deterministic eligibility checks; a blocking flag can withhold an offer for correction |
| Delegation mandate | Proposes an agent's pool scope, ceiling, expiry and stop-and-ask conditions | Buyer edits and ratifies it; server-side scope/cap checks enforce it |
| Simulation text | Produces varied rehearsal messages | Isolated simulation machinery; never a real payment |

AI output uses closed JSON schemas. Invalid output is retried once, then the user falls back to a manual form. Inputs are treated as untrusted data. AI cannot qualify, accept or change a bid, choose a winner, or move money. No FairPool AI-callable surface can create a PayPal order, authorize, capture, void or refund. Search indexes public pool and lot documents, never buyer requests, caps or personal data.

### Recorded evaluation

These are results on a fixed labelled corpus, **not a promise of accuracy on new requests**. “Clean” measures the evaluation's structural/guardrail checks; it does not mean a proposal needs no human review.

<!-- eval-table-start -->
| Task | Runs | Clean | Field accuracy | Cases left for review |
|---|---|---|---|---|
| INTAKE | 100 | 100/100 | 100.0% | 0 |
| QUOTE | 60 | 60/60 | 100.0% | 0 |
| RECONCILE | 120 | 120/120 | 100.0% | 23 |
| SIM_TEXT | 40 | 40/40 | 100.0% | 0 |

Injection and quoted-instruction cases: **32/32 clean** across the two runs. Recorded model: `gemini-3.5-flash-lite`; prompt: `phase2-gemini-v10`; dataset fingerprint begins `02acc35721fe`. [Full results and outputs](docs/evidence/phase9/gemini.json).
<!-- eval-table-end -->

The [agent-market boundary report](docs/evidence/phase9/agent_market.json) is a **SIMULATED** run using FakeAI and the fake payment router. Its refusal counts describe observed attempts, not a security guarantee. They are separate from the live-model and live-payment evidence.

## Allocation and public audit

Each confirmed entry has a commitment: a fingerprint derived from its canonical request and a private salt. At close, FairPool publishes the frozen commitment list, count and Merkle root. A seed determines the reproducible ranking. Buyers retain signed receipts and can check their own entry in the browser without submitting receipt values to the public audit endpoint.

The audit page separates published rules, entry-list checks, the draw, lots and supporting evidence. Seed and bid evidence remain withheld while relevant bidding windows are open; a checker waiting for that reveal is not a failed verification. The demo uses a labelled **DEMO SEED**. The beacon adapter also supports an announced public randomness round.

This is **auditable under published rules**. It does **not** prove that no eligible entry was omitted, and it is not "provably fair".

Duplicate control is **account-level**: one entry per linked PayPal account per pool where the PayPal Login account ID works, and account-level checks at checkout otherwise. It does not prove one human per account and does not eliminate bots or account farms.

## Local setup

Run commands from the repository root unless a step says otherwise. Use a **separate local database** for development and a disposable database for tests; a normal checkout does not need access to our hosted database.

### 1. Install prerequisites and dependencies

You need **Python 3.12**, **Node.js 20+ with npm**, **Git**, **GNU Make**, **Bash**, and **PostgreSQL 16+** (or Docker with Compose to run it). Install **gitleaks** for the full verification command. Python and npm dependencies are locked in the repository.

The commands below use Bash on Linux. Confirm that `python --version` reports 3.12 before setup; select another interpreter with `PYTHON=python3.12` if needed. On macOS, replace `make` with `make SHELL=/bin/bash`. On Windows, install Git for Windows and Make, use Git Bash, and replace **every** `make` invocation with `make 'SHELL=C:/Progra~1/Git/bin/bash.exe'` (adjust the path if Git is installed elsewhere). Bare `SHELL=bash` is not reliable with Windows Make. For example, Windows setup is `make 'SHELL=C:/Progra~1/Git/bin/bash.exe' setup PYTHON=python`.

```bash
git clone https://github.com/shaahir27/FairPool.git
cd FairPool
cp .env.example .env
make setup PYTHON=python
```

Setup creates `.venv`, installs the hashed backend dependency locks, installs pre-commit and runs `npm ci`. Its test-database provisioning step may report SKIP until Postgres and the environment are configured below.

Activate the environment in each terminal:

```bash
source .venv/bin/activate
# Windows / Git Bash: source .venv/Scripts/activate
```

### 2. Configure your local environment

Edit `.env` privately. Start with these local settings; the database credentials below are local development values only:

```dotenv
APP_ENV=local
POSTGRES_USER=fairpool
POSTGRES_DB=fairpool
POSTGRES_PASSWORD=fairpool
DATABASE_URL=postgresql+asyncpg://fairpool:fairpool@127.0.0.1:5432/fairpool
TEST_DATABASE_URL=postgresql+asyncpg://fairpool:fairpool@127.0.0.1:5432/fairpool_test
PAYMENT_MODE=authorize_capture
PAYMENT_ROUTER=single_seller
VAULT_REAL_SAVE_ENABLED=false
SEARCH_BACKEND=postgres
BEACON_MODE=demo
PUBLIC_BASE_URL=http://localhost:8000
FRONTEND_BASE_URL=http://localhost:5173
CORS_ORIGINS=http://localhost:5173
```

**Set `PAYMENT_MODE=authorize_capture` explicitly.** The template/code default is `vault_charge`, whose real saved-permission flow is not shipped. Changing the setting does not change the mode already stamped into an awarded lot.

Fill these required values too:

| Setting | Value to provide |
|---|---|
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | Your Sandbox REST app credentials |
| `SINGLE_SELLER_EMAIL` | The US Sandbox business seller used as the payee |
| `GEMINI_API_KEY` | A working Gemini key when `AI_ENABLED=true` |
| `AI_MODEL_PARSE`, `AI_MODEL_SIM` | Accessible model IDs; the recorded evaluation uses the template's `gemini-3.5-flash-lite` |
| `SECRET_KEY`, `HMAC_KEY`, `RECEIPT_SIGNING_KEY`, `ADDRESS_ENCRYPTION_KEY`, `VAULT_TOKEN_KEY` | Independent private keys; generate them below |
| `DEMO_SEED_PASSWORD` | A private password you choose if you want the demo accounts |

This command fills only **empty** key settings in `.env`, directly in the file, without printing their values. It preserves keys you already supplied:

```bash
python - <<'PY'
import base64
import secrets
from pathlib import Path

path = Path('.env')
names = {'SECRET_KEY', 'HMAC_KEY', 'RECEIPT_SIGNING_KEY',
         'ADDRESS_ENCRYPTION_KEY', 'VAULT_TOKEN_KEY'}
lines = path.read_text(encoding='utf-8-sig').splitlines()
for index, line in enumerate(lines):
    name, separator, value = line.partition('=')
    if separator and name in names and (not value.strip() or value.lstrip().startswith('#')):
        lines[index] = name + '=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
assert names <= {line.partition('=')[0] for line in lines}, 'Missing key settings'
path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
PY
```

For a **local offline exploration**, use `PAYMENT_ROUTER=fake`, `AI_ENABLED=false`, and keep `SEARCH_BACKEND=postgres`. Settings still require nonempty `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`; local dummy values are sufficient in this fake profile. It cannot demonstrate real PayPal approval or live AI. Do not present fake/seeded outcomes as provider evidence.

For PayPal signup/linking, enable `PAYPAL_LOGIN_ENABLED=true` only after configuring Log in with PayPal on the same Sandbox app. Register both the signup return `<PUBLIC_BASE_URL>/api/v1/auth/paypal/callback` and the linking return in `PAYPAL_LOGIN_REDIRECT_URI` (default `/api/v1/paypal/login/callback`). If PayPal requires HTTPS, use a tunnel and update the origins and registered returns together. Identity/address prefill depends on the fields PayPal actually returns.

For Elastic, set `SEARCH_BACKEND=elastic`, its URL, API key and inference endpoint. PostgreSQL retrieval remains the fallback. All remaining settings are listed in [configuration and errors](docs/contracts/config-and-errors.md); `.env.example` contains the app template. `TEST_DATABASE_URL` and `DEMO_SEED_PASSWORD` are tooling settings you add separately.

### 3. Start Postgres and apply migrations

If you are using the included Docker database:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml --profile test-db up -d db
```

Wait for it to become healthy, then:

```bash
python tools/ensure_test_db.py
make migrate
```

The provisioning helper creates only the loopback `*_test` database; migrations above apply to `DATABASE_URL`. The test suite manages its own test schema. For an existing Postgres server, create the app database and enable `citext` and `pg_trgm`; the Docker initialization script already installs these in the app database. See [deploy/db-init.sql](deploy/db-init.sql).

### 4. Run the app and worker

Use three terminals, each at the repository root with the virtual environment activated:

```bash
# Terminal 1: API
make api

# Terminal 2: browser UI
make web

# Terminal 3: scheduled jobs and reconciliation
python -m fairpool.worker
```

Open **[localhost:5173](http://localhost:5173)**. Vite proxies `/api` to port 8000. API documentation is at [localhost:8000/docs](http://localhost:8000/docs); `/health` checks liveness and `/ready` checks database/migration readiness. The worker is needed for deadlines, allocation, auction and payment jobs to progress automatically. `dev.ps1` starts only the API and UI; start the worker separately.

Alternatively, Compose runs the API, worker and frontend together:

```bash
make dev
```

When `DATABASE_URL` points to the included database from **inside a container**, replace `127.0.0.1` with the Compose hostname `db`. Start that database with its profile first. Configure the host-run migration command with its loopback URL; the container and host use different hostnames for the same database. Compose does not apply migrations automatically. Stop the stack with `docker compose --env-file .env -f deploy/docker-compose.yml down`; keep its volume if you want to retain data.

## Demo data

The seeder builds a useful set of buyer, merchant and operator examples: six discovery products with varied entry counts, bidding lots, an offer, funded/refunded history, shipments and an isolated 10,000-entry simulation.

For the local database configured above, add `DEMO_SEED_PASSWORD` to `.env`, then run:

```bash
make demo-seed
python tools/demo_seed_check.py
```

The default seed target is the loopback **`fairpool`** database derived from `TEST_DATABASE_URL`. It uses fake payment/AI implementations and makes no PayPal calls. Demo accounts include `demo-buyer-1@fairpool.test`, `demo-merchant@fairpool.test` and `demo-admin@fairpool.test`; use your private `DEMO_SEED_PASSWORD`. See [the seeder](tools/demo_seed.py) for the complete account list and scenario.

A repeat run reuses its own records and refreshes interactive windows; it does not extend already-published discovery windows. Old seed data may therefore need a deliberate reset for a fresh rehearsal. `make demo-reset` is destructive: inspect [the reset tool](tools/demo_reset.py) before using it. Hosted seeding requires the explicit `DEMO_SEED_HOSTED=1` opt-in and is not part of local setup. Do not run a worker pointed at the hosted database just to explore the code.

## Architecture

FairPool is a modular Python backend, a React/TypeScript frontend and a PostgreSQL-backed job worker. The database holds deadlines, state, idempotency records, audit facts and queued work. Pure domain rules are separated from orchestration and external adapters.

```mermaid
flowchart LR
    Browser[Buyer / merchant / operator UI] --> API[FastAPI]
    Agents[Buyer Agent API and MCP clients] --> API
    Merchants[Merchant API / generated SDKs] --> API
    API --> DB[(PostgreSQL)]
    API --> AI[Gemini proposals]
    API --> Search[Elastic / Postgres retrieval]
    Worker[Job worker and reconciler] --> DB
    API --> Adapter[Payment adapter]
    Worker --> Adapter
    Adapter --> Sandbox[PayPal Sandbox]
```

| Path | What lives there |
|---|---|
| `frontend/src/` | Landing, buyer, checkout, audit, merchant and operator screens; shared API client and UI |
| `backend/src/fairpool/domain/` | Pure allocation, auction, hashing, money and state rules |
| `backend/src/fairpool/modules/` | Application workflows: pools, intake, bidding, checkout, identity, fulfilment, agents and simulation |
| `backend/src/fairpool/adapters/` | PayPal REST, Gemini, beacon and search integrations |
| `backend/src/fairpool/api/` | HTTP routes, schemas, authentication and Merchant Agent API |
| `backend/src/fairpool/db/`, `infra/` | Models, sessions, database clock, jobs, audit and idempotency |
| `backend/migrations/` | Versioned Alembic schema migrations |
| `backend/tests/`, `frontend/tests/` | Unit, integration, property, concurrency, UI, fault and Sandbox tests |
| `sdk/`, `samples/` | Merchant OpenAPI, generated Python/TypeScript SDKs and integration examples |
| `deploy/` | Docker images, Compose and Render blueprint |
| `tools/` | Seeders, verification, evaluation, rehearsal and submission tools |
| `docs/` | Product intent, requirements, contracts, decisions and dated evidence |

Money is stored as integer cents. Deadlines use the database clock. State changes use explicit transitions, locks and transactionally recorded jobs/audit facts. Synthetic simulation entities never reach PayPal. [System design](docs/system-design.md) explains the boundaries; [AGENTS.md](AGENTS.md) contains contributor rules.

### APIs and generated SDKs

- **Application API:** `/api/v1`; generated browser types come from [frontend/openapi.json](frontend/openapi.json).
- **Buyer Agent API:** scoped, revocable delegation tokens for pool discovery and entry management. FairPool's Streamable HTTP MCP endpoint is `/mcp`. Agents have no payment tools.
- **Merchant Agent API:** ten operations under `/merchant-api/v1`, with scoped API keys, sealed-bid rules and idempotency. Local interactive docs: `http://localhost:8000/merchant-api/v1/docs`.
- **Generated clients:** [Python and TypeScript SDKs](sdk/README.md), generated with APIMatic from [the Merchant OpenAPI document](sdk/merchant-openapi.json). Do not edit generated clients by hand. APIMatic's hosted developer portal generation is still blocked; no portal is claimed.

### Tools and sponsor integrations

| Tool | Actual use and dependency |
|---|---|
| PayPal | Sandbox Orders, SDK approval, payment lifecycle, identity, tracking and read-only verification |
| Google Gemini | Structured proposals for intake, quotes, reconciliation, mandates and simulation text; requires a working key and model access |
| Elastic | Public demand retrieval and advisory product similarity; PostgreSQL fallback keeps retrieval available |
| APIMatic | Generated merchant clients; ContextMatic supplied development-time PayPal API context. Regeneration depends on APIMatic account/plan access |
| PayPal AI Toolkit / read-only PayPal MCP | Development guidance and optional merchant inspection; neither runs in the backend payment path |
| Zapier MCP | Trialled managed-mode integration. The recorded GET tool worked, but write tools could not send a valid body; `ZAPIER_BRIDGE=off`. Use FairPool MCP instead |
| Render / Supabase | Hosted app and PostgreSQL, respectively |
| GitHub Actions | CI and an optional keep-warm workflow |

## Tests and verification

With the local Postgres running and `TEST_DATABASE_URL` pointing to the disposable loopback `*_test` database:

```bash
make verify
```

This runs Ruff/ESLint, strict backend/frontend type checks, default backend and frontend tests, import boundaries, documentation, Merchant OpenAPI drift checks and a full-history gitleaks scan. GitHub CI additionally builds the frontend, checks migration drift and exercises Compose. Sandbox credentials are not needed by the default test suite.

| Command | Purpose |
|---|---|
| `make test` | Default backend suite and frontend tests |
| `make test-faults` | Explicit fault-injection suite |
| `make test-sandbox` | Provider contract tests against real PayPal Sandbox; requires configured credentials |
| `make test-sandbox-interactive` | Provider tests requiring human approval |
| `make ai-eval EVAL_RPM=10` | Live-model evaluation; consumes provider quota |
| `python tools/agent_market.py --self-check --out .tmp/agent_market_report.json` | Isolated, labelled agent-market boundary check with fake providers |
| `python tools/export_merchant_openapi.py --check` | Check the committed Merchant OpenAPI document |
| `python -m alembic -c backend/alembic.ini check` | Check model/migration drift on the configured app database |
| `cd frontend && npm run gen:api` | Regenerate browser types from the committed frontend OpenAPI snapshot |

Run provider suites only after reading [the testing strategy](docs/testing-strategy.md) and their fixture requirements. Some interactive Sandbox cases require explicit operator opt-ins; inspect [the contract-test fixtures](backend/tests/contract_sandbox/conftest.py) before running them. These tests create Sandbox resources and can move test funds. Default tests refuse a remote or non-test database.

[CI runs](https://github.com/shaahir27/FairPool/actions) are the current test status. [Evidence](docs/evidence/) records the environment, scope and limitations of earlier runs; it does not replace testing a new revision.

## Hosting and troubleshooting

The [Render blueprint](deploy/render.yaml) builds the frontend into the API image and serves both on one origin, backed by Supabase. The free hosted configuration has **no background worker**: do not expect deadlines and reconciliation to progress as they do in a local stack with the worker running. Operator-triggered processing is required. A keep-warm workflow exists, but is intended to be enabled after the repository becomes public; cold starts remain possible.

| Symptom | Check |
|---|---|
| Startup rejects settings | Fill the required `.env` values and generate valid keys. Select `authorize_capture` explicitly |
| No products in discovery | Seed the local database; only open pools appear. Check that the API and seeder target the same database |
| Find matches fails or asks for manual input | Check Gemini key, model access and quota. An exported environment variable overrides `.env`; restart the API after changing it. The manual path remains available |
| Pool or offer never progresses | Run the worker against your local app database and check stored deadlines; the hosted free service has no worker |
| PayPal reports an invalid client/return URL | Confirm Sandbox app credentials and exact registered return URLs; signup and account linking use different callbacks |
| Sign-in disappears | Keep frontend/API on the documented same origin in deployment; use Vite's proxy locally |
| Tests reject the database | Set `TEST_DATABASE_URL` to a loopback database ending in `_test`; run the provisioning helper |
| `make` cannot find Bash on Windows | Pass the full Git Bash path as shown in prerequisites; a bare `SHELL=bash` can be interpreted by the wrong shell |

## Current limits

- **Sandbox, US payers, USD, one unit per entry.** No production checkout, platform fee, multi-seller settlement or India-domestic payment support.
- **Individual approval is the demonstrated payment flow.** Real PayPal saved-permission setup is not shipped (`VAULT_REAL_SAVE_ENABLED=false`). Fake vault tests do not establish a live save-and-charge experience.
- **Join rate limiting is per API process**, not a global distributed limit; adding API processes can multiply the effective allowance.
- **Funding and refunds are asynchronous.** A pending capture is not payment, and requesting a refund is not the same as observing it complete. The app reports recorded states.
- **Hosted webhook processing is disabled; the free deployment has no worker.** Local worker-driven and live Sandbox evidence should not be mistaken for unattended hosted operation.
- **AI and search need their configured providers.** Local AI preflight passed after the key replacement on November 10; the recorded stale Windows user variable and hosted-key follow-up still need operator attention. See [progress](docs/progress.md).
- **The final rehearsal and video are still in progress.** Generated SDKs exist; the APIMatic portal does not. Repository visibility will be changed to public by the owner before submission.

**We do not claim:** guaranteed savings, wholesale pricing, production readiness, merchant settlement, "one person, one entry", or that a simulated market proves real buyer conversion. The allocation and account-control limits are described above.

Next steps are to finish and record the end-to-end rehearsal, verify hosted provider configuration, and complete the public submission. Longer-term work includes approved marketplace onboarding/settlement and a verified saved-payment flow; these are future work, not features of this build.

## Documentation and contribution

Start with [the docs index](docs/00-index.md). The [idea](docs/fairpool-idea.md) explains why the product exists; [requirements](docs/product-spec.md) define its scope; [contracts](docs/contracts/README.md) define API/state/data behavior; [decisions](docs/decisions.md) explain approved departures; [progress](docs/progress.md) records outstanding work. The [demo and submission runbook](docs/demo-and-submission.md) holds the recording plan.

For contributors, read [AGENTS.md](AGENTS.md) and [team ownership](docs/team-split.md) before changing code. Keep secrets out of source, logs, screenshots and issues. Use a disposable test database, preserve payment boundaries, and document contract changes before implementing them.

The [official hackathon requirements](https://paypalaihackathon.devpost.com/#requirements) call for a working PayPal-and-AI project, usable setup instructions or a hosted build, tool-use disclosure, a public licensed repository and a public YouTube demo under three minutes. This README documents the build; the final video link above and Devpost submission remain to be completed. The owner will make the repository public before submission.

## License

[MIT](LICENSE). Generated merchant SDKs include their own MIT license files. Third-party services remain subject to their respective terms.
