<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark) and (prefers-reduced-motion: no-preference)" srcset="docs/assets/readme/fairpool-logo-dark.gif">
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/fairpool-logo-dark.svg">
    <source media="(prefers-reduced-motion: no-preference)" srcset="docs/assets/readme/fairpool-logo.gif">
    <img src="docs/assets/readme/fairpool-logo.svg" alt="FairPool" width="520" height="136">
  </picture>
</p>

# A guide to FairPool

Hi! Welcome to FairPool. This guide explains the idea, takes you through the app, and helps you run it yourself. If you're new here, start below; the setup commands are a little further down.

**Group buying where merchants compete for the group.**

FairPool brings together people who want the same product, gives merchants a way to bid for that demand, and lets each selected buyer approve their own PayPal payment. Joining a pool is free. Buyers set their maximum delivered price before joining; they see the merchant, exact total and terms before approving a payment.

The idea starts with a familiar problem: you want one item, but the better offer depends on buying several. Other people may want the same thing, yet organizing the group, including everyone's payments, is another job entirely. Merchants face the other side of that problem: interest is easy to count, but actual orders are harder to count on. FairPool gives both sides a shared process, from a published entry window through to a funded order.

Built for the [PayPal AI Hackathon](https://paypalaihackathon.devpost.com/). This is a **Sandbox prototype**: PayPal uses test accounts and test funds. No real money moves.

**[Open FairPool](https://fairpool-api.onrender.com/)** · [Source](https://github.com/shaahir27/FairPool) · [Product idea](docs/fairpool-idea.md) · [Technical docs](docs/00-index.md)

**Demo video:** [Watch the FairPool walkthrough on YouTube](https://www.youtube.com/watch?v=fwvTbB2_Rmk).

## Start here

- **Take a tour.** Read [the walkthrough](#try-the-demo) and [the current limits](#current-limits).
- **Run it locally.** Start with [local setup](#local-setup), then [demo data](#demo-data).
- **Read the code.** See [PayPal](#how-paypal-is-used), [AI](#how-ai-is-used), [architecture](#architecture) and [verification](#tests-and-verification).
- **Connect an agent or API client.** Start with [ways to participate](#ways-to-participate-browser-api-or-mcp), then [APIs and generated SDKs](#apis-and-generated-sdks).

## Why we're building this

Imagine you want one monitor. A merchant could offer a better unit price for a larger order, but you cannot commit to buying twenty. Nineteen other people may want the same thing; their demand is scattered across searches, shopping carts and messages. There is no shared order for the merchant to price, and nobody wants the job of collecting everyone's money.

The merchant has the opposite problem: stock and a possible bulk price, but little certainty about how many buyers will actually follow through. An expression of interest is different from an order the merchant can fulfil. FairPool gathers compatible requests into published pools, then lets merchants compete for clearly defined lots with product, delivery and return requirements. Each buyer keeps their own price ceiling and approves their own final total.

Those requests and merchant quotes usually arrive as ordinary messages. AI helps turn them into terms people can review. A buyer who wants an assistant to participate also needs a clear permission: which pools it can use, how much it can commit, and when that access ends.

Scarce products add a race to click. In a first-come release, a faster connection, an automated checkout or repeated accounts can take places before other buyers have a chance. FairPool collects entries during a fixed window and ranks eligible entries after closing under published rules. Joining earlier gives no priority. Signed receipts and the public audit help buyers check their own inclusion and the published result. Duplicate control operates at account level; it does not establish one person per account or eliminate bots.

There is also a payment coordination problem. Buyers need to know what happens if the group falls short; merchants need completed payments before shipping. FairPool separates joining, approval, authorization and capture. Joining costs nothing, approval is for a specific offer, and a lot becomes funded only after enough captures complete. If funding fails, the workflow releases holds and refunds captures. At the implementation level, approvals, expiry jobs and payment retries can race with one another. Locked seat checks, database deadlines and idempotent payment requests keep those concurrent actions within the same published rules.

That is the idea: make individual demand visible as a group, give merchants a concrete order to bid for, and keep each buyer's consent and payment traceable through the outcome. The [idea document](docs/fairpool-idea.md) explains the original problem and the design in more depth.

## How it works

Let's follow a purchase from the first request to the final outcome. You'll see two terms throughout the app: a **pool** is the group of people interested in a product; a **lot** is a fulfilment group within that pool. Each lot has its own bid, minimum and outcome.

1. **Find a pool.** Browse published products or describe what you want. AI proposes a matching pool and structured requirements; you review them. A manual form is available too.
2. **Join for free.** Confirm one unit, your maximum total including shipping and tax, and your delivery requirements. You receive a signed entry receipt. Joining creates no PayPal payment or hold.
3. **Allocate places.** Every eligible entry submitted before the published cutoff is considered under the same rule. Arriving earlier gives no priority. The pool closes, its entry commitments are frozen, and a seeded ranking assigns places and an ordered waitlist.
4. **Let merchants bid.** A pool can contain several fulfilment groups, called **lots**. Merchants submit sealed bids for each lot. Deterministic rules reject bids that violate firm requirements and rank qualifying bids.
5. **Review your offer.** A selected buyer sees the winning merchant, product, delivered total, delivery and return terms, and an approval deadline. A buyer whose cap is too low is priced out; a released place can go to the waitlist.
6. **Approve on PayPal.** The hosted demo uses `PAYMENT_MODE=authorize_capture`: each buyer approves an individual order for the exact amount, and the server verifies it before placing a hold. Captures follow the lot's funding rules. **FUNDED** means enough completed captures from distinct buyers have reached the merchant's minimum—not merely that enough people joined or approved.
7. **Fulfil or unwind.** A funded lot opens its shipping workflow. If funding fails, outstanding authorizations are voided and completed captures are refunded. Buyers can follow the recorded outcome in Orders.

For example, several buyers may want the same monitor but set different price limits. A merchant can offer a delivered price for a minimum number of buyers. A winning bid does not oblige every entrant to buy: the allocation, each buyer's cap, their approval and the lot's completed payments still matter. Different lots in one pool can finish with different merchants, prices or outcomes.

## Try the demo

Start with the buyer journey. You can explore the other workspaces once the pool, offer and order screens make sense.

Open **[fairpool-api.onrender.com](https://fairpool-api.onrender.com/)**. The frontend and API share this origin so sign-in works with first-party cookies. A free Render instance may need time to wake after inactivity.

| Workspace | What to explore |
|---|---|
| Buyer | Discover and Join, a pool's product and entry details, My Pools, offer review, Orders, saved addresses and agent permissions |
| Merchant | Demand Board, sealed quote submission, Active Bids, funding progress, fulfilment, verification and API keys |
| Operator (maintainer-only) | Pool creation, lot progress, job/reconciliation controls, alerts and audit exports; no public operator login |
| Public audit | Published rules, entry commitments, draw/lot evidence, tamper checks and the buyer's receipt checker |

A useful first tour is **Discover → View pool → Your entry / product requirements → Public audit**, then **My Pools → offer or order status**. The discovery cards distinguish recorded demand, capacity and the merchant minimum; an open pool has no awarded price yet.

Use the buyer or merchant sign-in link below for the workspace you want to explore. These are shared FairPool test accounts with seeded activity; changes are visible to other reviewers.

| Workspace | FairPool email | Public demo password |
|---|---|---|
| [Buyer sign in](https://fairpool-api.onrender.com/login) | `demo-buyer-1@fairpool.test` | `FairPool-demo-US-2026!` |
| [Merchant sign in](https://fairpool-api.onrender.com/login?role=merchant) | `demo-merchant@fairpool.test` | `FairPool-demo-US-2026!` |

**Creating an account or trying checkout? Use a US-based PayPal Sandbox personal buyer account.** FairPool's demo is configured for **US payers and USD** (`ALLOWED_PAYER_COUNTRIES=US`); an account from another country will fail its payer-country check. In the [PayPal developer dashboard](https://developer.paypal.com/dashboard/), create a Sandbox **Personal** account with **United States** as its country, then use that account's Sandbox email and password when PayPal opens. The FairPool logins above are separate from PayPal credentials. Never enter your real PayPal login into this demo.

New-buyer registration goes through PayPal connection and depends on the configured Sandbox login app. Connecting identifies an account; approving a payment is a separate step. Seeded historical orders illustrate states; they are not evidence that those particular orders reached PayPal. Follow an available live offer for an actual Sandbox approval.

The hosted demo includes discovery windows through **January 12, 2027**, varied product bundles and delivery regions, signed entries, seated and waitlisted examples, and confirmed bids from two demo merchants. Simulated funded/refunded history is available too. These are seeded examples, rather than evidence of customer demand or merchant stock.

## Ways to participate: browser, API or MCP

You can use FairPool yourself in the browser, write a client against the HTTP API, or let an AI assistant use the MCP tools. These are ways into the same pool and entry rules. An agent acts for your buyer account; it is not another buyer and gets no extra place.

| Route | Who it suits | Connection and credentials |
|---|---|---|
| Browser | Someone browsing, joining, approving an offer or managing orders | Sign in to the app; session cookie and CSRF protection |
| Buyer HTTP API | A script, custom integration or agent that can make HTTP calls | `/agent/v1` with a buyer delegation token |
| Buyer MCP | An AI assistant with Streamable HTTP and OAuth support | `/mcp`: browser consent with PKCE S256; the access token is the same buyer delegation (manual bearer fallback available) |
| Merchant HTTP API / SDK | A merchant's own client or pricing bot | `/merchant-api/v1` with a scoped merchant API key |

### First, give a buyer client limited permission

Sign in as a buyer and open **Agent settings** (`/settings/agents`) → **Connect an agent**. Add the shown MCP URL in a compatible client and choose Connect there. Its unauthenticated request discovers FairPool’s authorization server, registers a public client, and opens the browser consent page. Review the registered client name and redirect URI, describe the product, budget and time limit, review the automatically matched pools and proposed cap and expiry, then ratify the mandate and approve or deny. PKCE S256 binds the single-use code to the client; no token copying is needed. Tokens expire without refresh, and reconnecting requires consent again.

Connections show a name, public prefix, active/expired/revoked status and last-used time. Revoke from the same screen. **Propose with AI** finds public open candidate pools from your intent and prepares an editable mandate; you can also choose pools yourself. The short review shows the permissions before approval. Detailed fields and the manual token path stay behind optional controls, and an unavailable or refused proposal opens the manual editor. It authorizes no payment. For a client without OAuth, use the labelled **Manual token fallback**: select scope, set cap and expiry, ratify, and store the once-shown token securely. FairPool stores only its HMAC.

A buyer token is different from your FairPool password, a merchant API key and a PayPal credential. Put it in your client's private connection settings or secret store, never in a prompt, repository, screenshot or shared transcript. Both buyer interfaces enforce the token's owner, pool/category scope, cap, expiry and revocation. A scoped token cannot read or withdraw an entry outside its allowed pools.

**Custom stop-and-ask conditions are advisory in this build.** They are validated and included in the ratified mandate, but the agent endpoints do not evaluate them. An assistant that ignores a condition is still bounded by the enforced scope, cap and expiry. Do not rely on a condition to stop a join; narrow or revoke the token instead.

### When no pool matches

After an intake no-match, choose **Notify me when a pool forms**, confirm the canonical product, condition, variant, bundle and delivery region, and explicitly consent. Declining records nothing. **Discover → Forming demand** shows only product fields and aggregate interest counts. Signals are private PostgreSQL records; they carry no budget, raw message or address and are never indexed in search.

At the published threshold (five distinct active buyers by default), `demand.sweep` proposes one **DRAFT** pool through the ordinary pool service. An operator reviews it under **Ops → Demand proposals** and publishes or rejects it. Publication is never automatic. Holders receive in-app notifications when it is proposed and published; publication schedules the normal opening, and they still join separately. **My Pools → Interests** lists active interests and lets the buyer cancel. The default signal lifetime is 30 days; renewed consent can renew an expired signal.

For synthetic local demo signals, set `DEMO_SEED_DEMAND=1` when explicitly running `tools/demo_seed.py`. With the default threshold, it adds one proposed draft and one cluster just below threshold using demo buyers; repeated runs reuse their signals. This flag does not publish a pool and does not add a PayPal call.

### Participate directly through the buyer API

Use `Authorization: Bearer` with the delegation token. Store it privately as `FAIRPOOL_AGENT_TOKEN` in the environment used by your client; the example deliberately contains no token value.

```bash
FAIRPOOL_BASE_URL=https://fairpool-api.onrender.com
curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${FAIRPOOL_AGENT_TOKEN}" \
  "${FAIRPOOL_BASE_URL}/agent/v1/pools?limit=5"
```

| Action | HTTP request |
|---|---|
| Find open pools within your scope | `GET /agent/v1/pools?q=monitor&limit=5` |
| Join a pool | `POST /agent/v1/entries` |
| Read your entries and available offer links | `GET /agent/v1/entries` |
| Read one of your entries | `GET /agent/v1/entries/{entry_id}` |
| Withdraw an eligible entry | `POST /agent/v1/entries/withdraw` with `entry_id` |

For a join, send a stable `Idempotency-Key` header and this body, replacing the placeholders with a real open pool and your chosen delivery date:

```json
{
  "pool_id": "REPLACE_WITH_POOL_UUID",
  "request": {
    "delivery": {"region": "NY"},
    "required_by": "YYYY-MM-DD",
    "max_total_usd": "600.00",
    "firm": [],
    "preferences": []
  }
}
```

The amount is your maximum delivered price, not a quoted pool price. Supply exactly one of `max_total_usd` (a decimal string) or `max_total_cents` (an integer). Pick a delivery date consistent with the pool's published requirements. Reuse the same idempotency key only when retrying the same request; reusing it with changed terms is a conflict. A first join returns 201; a replay or existing entry returns 200. The response includes the entry/allocation state and, when an offer exists, a `checkout_url` for you to open in the browser.

### Participate through an MCP-connected assistant

FairPool supports **Streamable HTTP** MCP with browser-based OAuth consent: add `https://fairpool-api.onrender.com/mcp` (or `http://localhost:8000/mcp` locally) to a compatible client and follow **Connect an agent** above. For clients without OAuth, the **Manual token fallback** supplies a buyer delegation token for a private `Authorization: Bearer` header. Let the client perform initialization and tool discovery, and keep the token out of prompts and logs.

This is **FairPool's MCP server**, which manages buyer participation. It is separate from the optional read-only PayPal MCP used for merchant payment inspection.

The server exposes four tools:

| MCP tool | What it does | Important input |
|---|---|---|
| `list_pools` | Finds open pools within the delegation's scope | Optional `q` and `limit` (1-20) |
| `enter_pool` | Submits a buyer entry through the same HTTP API validation | `pool_id`, `delivery_region`, your price limit, `required_by`, `idempotency_key` |
| `list_entries` | Reads the buyer's entries, allocation and human checkout link | Optional `pool_id` or `entry_id` |
| `withdraw_entry` | Withdraws the buyer's eligible entry before closing | `entry_id` |

An assistant's `enter_pool` arguments look like this. They are flat tool arguments, unlike the nested HTTP join body above:

```json
{
  "pool_id": "REPLACE_WITH_POOL_UUID",
  "delivery_region": "NY",
  "required_by": "YYYY-MM-DD",
  "max_total_usd": "600.00",
  "idempotency_key": "REPLACE_WITH_STABLE_REQUEST_ID"
}
```

A useful instruction is: "Find an open monitor pool within my approved scope. Show me its delivery and return requirements before entering, keep my price limit, and bring me the offer link when one is available." The token belongs in connection settings, not in that instruction. Check the tool result: an HTTP 200 JSON-RPC response can still carry `result.isError=true` and an application error. That is a refused action, not a successful join.

**Payment remains yours to approve.** Neither the direct buyer API nor the MCP tools creates a PayPal order or approves, authorizes, captures, voids or refunds a payment. When an offer is ready, the assistant hands you its `checkout_url`; sign in and review it yourself. The server's normal payment workflow takes over after your approval. Agents cannot turn an entry into a payment by asking another MCP tool.

### Merchants participate through a separate API

A merchant creates scoped keys in **Developer API** in the merchant workspace. Use those keys with `/merchant-api/v1`, directly or through the [generated Python and TypeScript clients](sdk/README.md). A buyer delegation token is not a merchant key, and the four buyer MCP tools do not submit merchant bids.

The ten merchant operations cover finding lots, submitting/reading bids, funding progress, fulfilment, shipments and read-only verification. Bid submission is `PUT /merchant-api/v1/lots/{lot_id}/bid`, requires an `Idempotency-Key`, and requires `confirmed: true`: the bot's structured submission is its confirmation. Merchant ownership, scopes and the same sealed-bid rules still apply. See the [operation and scope table](docs/contracts/api.md#43-merchant-agent-api-int-9-fr-ig-04) and [SDK quickstart](sdk/README.md).

### Client compatibility

Focused tests exercise delegation ownership/revocation/expiry, scope and cap enforcement, exact money parsing, idempotent joins/withdrawals, merchant-key permissions, sealed bid access and the mounted MCP handshake/tool calls. They use an isolated database and fake providers; they do not establish compatibility with every AI client or demonstrate a real payment.

The MCP endpoint uses a custom JSON-RPC/SSE transport. Use a client with Streamable HTTP and OAuth support, or a private bearer header for the manual token path, and verify its connection before relying on it. The four-tool path is tested; compatibility with every MCP client is not guaranteed. The managed Zapier write bridge is disabled (`ZAPIER_BRIDGE=off`); use FairPool MCP for buyer participation.

Always include `required_by` in entry requests, including MCP calls, as the examples above do. Although the MCP tool marks it optional, the shared entry API requires a delivery date. No delivery date is invented on your behalf.

## How PayPal is used

PayPal is part of the group-funding workflow, rather than a payment button added after the purchase decision:

- **Orders v2:** one server-created order per buyer, addressed to the configured Sandbox payee. The server checks the approved order, payer, payee, amount, currency, deadline and seat before authorization.
- **JavaScript SDK v6:** buyer approval in a popup, with a redirect fallback. The browser sends no payment amounts and does not authorize or capture.
- **Authorization, capture, void and refund:** only the server-side payment adapter can make these calls. Stable request IDs and reconciliation handle retries. An order status alone never proves payment; a completed capture does.
- **Webhooks and reconciliation:** signatures and duplicate events are checked; events prompt a resource fetch rather than serving as payment proof. Webhook processing is implemented but disabled in the hosted blueprint. The reconciliation path remains available.
- **Shipment tracking and verification:** tracking can be submitted after fulfilment. A merchant can compare recorded captures with PayPal through the read-only verification endpoint and download a manifest without buyer personal data.

The current integration uses **one stand-in Sandbox seller** (`PAYMENT_ROUTER=single_seller`). The app lacks marketplace partner access, so the winning merchant's identity is shown while payments go to that configured seller. Checkout and operations screens disclose this fallback. Platform fees and multi-seller settlement are unavailable.

Real Sandbox evidence includes authorization/void, capture/refund, SDK popup approval and funding flows. Start with [Phase 5](docs/evidence/phase5/README.md), [Phase 7](docs/evidence/phase7/) and the [end-to-end rehearsal evidence](docs/evidence/phase10/rehearsal_1.json). Those records distinguish executed provider calls, deterministic tests and configuration decisions. A refund restores FairPool's captured-minus-refunded ledger; this is not a claim about PayPal processing fees or a fee-inclusive account balance.

The [webhook evidence](docs/evidence/phase6/webhook_delivery.json) records genuine Sandbox deliveries, including void and refund events. One completed-capture delivery passed the provider-signature contract test. Processing remained disabled during that run; reconciliation and timers drove the payment workflow.

## How AI is used

A buyer's assistant can find and join pools under a permission the buyer has reviewed. A merchant's pricing bot can submit sealed bids through the Merchant Agent API or generated SDKs. Both use the same rules as the browser: deterministic checks decide eligibility and awards, and the buyer still approves the PayPal payment.

Google Gemini, through `google-genai`, helps people prepare those instructions and offers:

| Task | What AI contributes | What decides the result |
|---|---|---|
| Buyer intake | Extracts product, delivery needs and maximum price; proposes a match or clarification | Schema validation, pool rules and the buyer's confirmation |
| Merchant quote parsing | Extracts structured fields from a pasted quote | Merchant review and the deterministic bid rules |
| Offer reconciliation | Flags product or requirement mismatches, with explanations | Deterministic eligibility checks; a blocking flag can withhold an offer for correction |
| Delegation mandate | The buyer-facing Propose with AI action prepares pool scope, ceiling, expiry and stop-and-ask conditions; failures return the manual editor | Buyer edits and ratifies the fields before OAuth consent or manual token creation; scope, cap, expiry and revocation are enforced; custom conditions remain advisory |
| Simulation text | Produces varied rehearsal messages | Isolated simulation machinery; never a real payment |

AI output uses closed JSON schemas. Invalid output is retried once, then the user falls back to a manual form. Inputs are treated as untrusted data. AI cannot qualify, accept or change a bid, choose a winner, or move money. No FairPool AI-callable surface can create a PayPal order, authorize, capture, void or refund. Search indexes public pool and lot documents, never buyer requests, caps or personal data.

Grounding checks reject unsupported amounts, dates and quoted terms. The adapter's attempt records in `ai_runs` carry the task, model, prompt/schema version, input hash, output or error, latency and token counts, within the caller's transaction. The Elastic path also uses embeddings for public-demand retrieval and an advisory wrong-product check; a `LOW_SIMILARITY` warning never changes a bid's eligibility. The current hosted demo uses PostgreSQL retrieval.

### Recorded evaluation

These are results on a fixed labelled corpus, **not a promise of accuracy on new requests**. “Clean” measures the evaluation's structural/guardrail checks; it does not mean a proposal needs no human review.

The table counts 320 case evaluations across two runs of 160 labelled cases. The report records 354 model attempts including retries; the clean totals describe the final evaluated results.

<!-- eval-table-start -->
| Task | Case evaluations | Clean | Field accuracy | Cases left for review |
|---|---|---|---|---|
| INTAKE | 100 | 100/100 | 100.0% | 0 |
| QUOTE | 60 | 60/60 | 100.0% | 0 |
| RECONCILE | 120 | 120/120 | 100.0% | 23 |
| SIM_TEXT | 40 | 40/40 | 100.0% | 0 |

Injection and quoted-instruction cases: **32/32 clean** across the two runs. Recorded model: `gemini-3.5-flash-lite`; prompt: `phase2-gemini-v10`; dataset fingerprint begins `02acc35721fe`. [Full results and outputs](docs/evidence/phase9/gemini.json).
<!-- eval-table-end -->

Separate [live mandate checks](docs/evidence/phase9/live_mandate.json) passed three cases, including an injected instruction: outputs were schema-valid, caps were not raised, and scope stayed within the supplied candidates. A [live quote-to-bid check](docs/evidence/phase9/live_bid.json) used Gemini to parse a quote, then submitted it through the Merchant Agent API and received a sealed-bid receipt. These are recorded checks, not guarantees about every future model response.

The [agent-market boundary report](docs/evidence/phase9/agent_market.json) is **SIMULATED**, using FakeAI and the fake payment router. Across six boundary attempts it recorded zero observed breaches and zero PayPal writes from AI-callable surfaces. Invalid credentials, excessive caps, insufficient key scope, sealed-bid access and oversized messages were rejected; injected merchant notes were stored as data and flagged for review. A separate [participation check](docs/evidence/phase9/agent_participation_followup.json) verifies actual buyer/merchant tool results and fails its exit status when participation fails. The boundary report alone does not establish a successful buyer join. These measurements are separate from live-model and live-payment evidence.

The [10,000-entry simulation](docs/evidence/phase8/sim_10k.json) measured **5,386 ms** against its 10,000 ms bound on local PostgreSQL. Its timed path uses bulk database writes and Python ranking, with no AI calls, job execution or payments. This is an isolated simulation benchmark, not hosted checkout throughput. Running it requires the maintainer-only operator API; the recorded report is available without an operator login.

## Allocation and public audit

Each confirmed entry has a commitment: a fingerprint derived from its canonical request and a private salt. At close, FairPool publishes the frozen commitment list, count and Merkle root. A seed determines the reproducible ranking. Buyers retain signed receipts and can check their own entry in the browser without submitting receipt values to the public audit endpoint.

The audit page separates published rules, entry-list checks, the draw, lots and supporting evidence. Seed and bid evidence remain withheld while relevant bidding windows are open; a checker waiting for that reveal is not a failed verification. The demo uses a labelled **DEMO SEED**. The beacon adapter also supports an announced public randomness round.

This is **auditable under published rules**. It does **not** prove that no eligible entry was omitted, and it is not "provably fair".

Duplicate control is **account-level**: one entry per linked PayPal account per pool where the PayPal Login account ID works, and account-level checks at checkout otherwise. It does not prove one human per account and does not eliminate bots or account farms.

## Local setup

This section takes you from a fresh clone to a running app. There are a few credentials to configure, but you can also choose the offline profile to explore without calling PayPal or Gemini.

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

**Set `PAYMENT_MODE=authorize_capture` explicitly.** The template/code default is `vault_charge`, but real saved-payment permission setup is disabled. Changing the setting does not change the mode already stamped into an awarded lot.

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

To add a longer demo calendar after the base accounts exist, preview it and then append it:

```bash
python tools/demo_calendar.py --dry-run
python tools/demo_calendar.py
```

This adds 24 discovery pools across 12 generic products over the next two calendar months, plus four short entry windows that lead into merchant bidding. Entries have varied US delivery regions and price limits, signed receipts, complete product bundles and 30-day return requirements. Buyer 6 remains available for fresh joins in the regular calendar. The tool creates no payment orders, changes no account passwords and leaves existing published rules and financial history intact. Repeating the same day's calendar reuses its pools and entries. Like the base seeder, it defaults to loopback; an operator must explicitly set `DEMO_SEED_HOSTED=1` to target the configured hosted database, and should inspect the dry run first.

## Architecture

Once you've tried the app, this is where to look under the hood.

FairPool is a modular Python backend, a React/TypeScript frontend and a PostgreSQL-backed job worker. The database holds deadlines, state, idempotency records, audit facts and queued work. Pure domain rules are separated from orchestration and external adapters.

### Runtime and persistence

```mermaid
flowchart TB
    subgraph Clients["People and agent clients"]
        Web["React + TypeScript UI<br/>Buyer, merchant, operator, public audit"]
        BuyerAgent["Buyer assistant<br/>Agent API / Streamable HTTP MCP"]
        MerchantAgent["Merchant client<br/>Generated Python / TypeScript SDK"]
    end

    HTTP["FastAPI entry points<br/>/api/v1 - /mcp - /merchant-api/v1<br/>Session + CSRF or scoped token/key"]
    Modules["Application workflows<br/>Identity, intake, pools, allocation, bids<br/>Checkout, fulfilment, agents and audit"]
    Rules["Pure domain rules - no I/O<br/>Published ranking, bid eligibility, caps<br/>Legal transitions and integer-cent money"]
    DB[("PostgreSQL<br/>Application state + database clock<br/>Durable jobs, ledger, audit and idempotency")]
    Worker["Separate worker process<br/>Claims due jobs and runs handlers<br/>Reconciliation scheduler enqueues sweeps"]

    Web -->|"Same-origin requests / SSE"| HTTP
    BuyerAgent -->|"Revocable buyer delegation"| HTTP
    MerchantAgent -->|"Scoped merchant API key"| HTTP
    HTTP --> Modules
    Worker -->|"Run registered application handlers"| Modules
    Modules --> Rules
    Modules <-->|"Reads; locked transactional writes"| DB
    Worker -->|"Claim / retry queued work"| DB
```

### Provider boundaries

The workflows call providers through adapters. These paths have different permissions and purposes:

```mermaid
flowchart LR
    Modules["Application workflows<br/>Called by the API or worker"]
    Payment["PayPal adapters<br/>Payment lifecycle, identity<br/>Tracking and read-only verification"]
    AI["Gemini adapter<br/>Closed schemas, validation, retry<br/>Proposals require confirmation"]
    Search["Public demand retrieval / indexing<br/>Pool and lot documents only<br/>Postgres fallback"]
    Beacon["Seed adapter<br/>Labelled demo seed<br/>or announced drand round"]
    Fake["Isolated fake payment router<br/>Simulation, demo seeding<br/>and offline use"]

    Modules --> Payment --> Sandbox["PayPal Sandbox<br/>Individual buyer orders"]
    Modules --> AI --> Gemini["Google Gemini"]
    Modules --> Search --> Elastic["Elasticsearch<br/>Public demand index"]
    Modules --> Beacon --> Drand["drand beacon<br/>When configured"]
    Modules --> Fake
```

Read the first view from the clients down to the workflows, then use the second to follow an external call. Both the HTTP handlers and worker use the application modules; neither the UI nor an agent gets a direct route to the payment adapter. The domain layer has no I/O. A state transition records its audit facts and next job in the same transaction, while external calls are handled through adapters and their idempotency/recovery rules.

There is also a browser-to-PayPal approval step outside the server diagram: the SDK opens a popup (or uses the redirect fallback) for the buyer to approve. That does not move authorization or capture logic into the browser. Server-side code verifies the approved order and performs authorization, capture, void or refund through the adapter. Verified webhook hints, when enabled, return through the API and prompt a server-side GET. AI proposes fields; it has no payment tools. Search retrieves public demand and never decides whether a buyer or bid qualifies.

**Deployment:** local development uses the API, Vite and a separate worker; Compose supplies the API, built UI and worker. The free Render deployment bundles the built React UI into the API service and uses Supabase PostgreSQL. The API and worker run together through `python -m fairpool.serve` while the web instance is awake. Its profile uses individual approval, one stand-in seller, a demo seed and disabled webhook processing. The diagram shows the implemented architecture, including configurable providers; it does not mean every optional path is enabled on the hosted demo.

The wiring lives in [wiring.py](backend/src/fairpool/wiring.py); [worker.py](backend/src/fairpool/worker.py) owns job execution and the reconciliation schedule. [The app factory](backend/src/fairpool/api/app.py) mounts the application API, merchant sub-app, MCP endpoint and built frontend.

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
- **Generated clients:** [Python and TypeScript SDKs](sdk/README.md), generated with APIMatic from [the Merchant OpenAPI document](sdk/merchant-openapi.json). Generation instructions and SDK source are included under `sdk/`. Do not edit generated clients by hand.

### Tools and sponsor integrations

| Tool | Actual use and dependency |
|---|---|
| PayPal | Sandbox Orders, SDK approval, payment lifecycle, identity, tracking and read-only verification |
| Google Gemini | Structured proposals for intake, quotes, reconciliation, mandates and simulation text; requires a working key and model access |
| Elastic | Optional public demand retrieval and advisory product similarity; requires a configured Elastic service and suitable permissions. The hosted demo uses PostgreSQL retrieval |
| APIMatic | Generated Merchant API clients in Python and TypeScript. SDK source is included; regeneration requires APIMatic account/plan access. ContextMatic supplied separate development-time PayPal API context |
| PayPal AI Toolkit / read-only PayPal MCP | Development guidance and optional merchant inspection; neither runs in the backend payment path |
| Zapier MCP | Managed-mode GET requests were tested, but write tools could not supply the required body. The bridge is disabled (`ZAPIER_BRIDGE=off`); use FairPool MCP for buyer participation |
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

The [Render blueprint](deploy/render.yaml) builds the frontend into the API image and serves both on one origin, backed by Supabase. The API image starts a supervised worker beside the web process, so due jobs and reconciliation can run while the service is awake. If either process exits, the supervisor stops its sibling and exits so the container can restart. Both processes pause when the free instance sleeps; deadlines still use the database clock, so expired windows are rechecked after waking. Free hosting can produce cold starts, and keep-warm requests do not guarantee continuous processing. The hosted demo uses PostgreSQL retrieval against Supabase; Elasticsearch is an optional provider that requires its own configuration and permissions.

| Symptom | Check |
|---|---|
| Startup rejects settings | Fill the required `.env` values and generate valid keys. Select `authorize_capture` explicitly |
| No products in discovery | Seed the local database; only open pools appear. Check that the API and seeder target the same database |
| Find matches fails or asks for manual input | Check Gemini key, model access and quota. An exported environment variable overrides `.env`; restart the API after changing it. The manual path remains available |
| Pool or offer never progresses | Run the worker against your local app database and check stored deadlines; check that the deployed API image starts `fairpool.serve` and its worker; the free service pauses both processes while asleep |
| PayPal reports an invalid client/return URL | Confirm Sandbox app credentials and exact registered return URLs; signup and account linking use different callbacks |
| Sign-in disappears | Keep frontend/API on the documented same origin in deployment; use Vite's proxy locally |
| Tests reject the database | Set `TEST_DATABASE_URL` to a loopback database ending in `_test`; run the provisioning helper |
| `make` cannot find Bash on Windows | Pass the full Git Bash path as shown in prerequisites; a bare `SHELL=bash` can be interpreted by the wrong shell |

## Current limits

Before you rely on a demo result, here's what this build can and cannot show. The labels in the app matter: a seeded example, a simulation and a real Sandbox call are different kinds of evidence.

- **Sandbox, US payers, USD, one unit per entry.** No production checkout, platform fee, multi-seller settlement or India-domestic payment support.
- **Individual approval is required.** The hosted demo uses `authorize_capture`; real PayPal saved-payment permission setup is disabled (`VAULT_REAL_SAVE_ENABLED=false`). Fake vault tests do not establish a live save-and-charge experience.
- **Join rate limiting is per API process**, not a global distributed limit; adding API processes can multiply the effective allowance.
- **Custom mandate conditions are advisory.** Scope, cap, expiry and revocation are enforced, but agent endpoints do not evaluate stop-and-ask predicates.
- **Funding and refunds are asynchronous.** A pending capture is not payment, and requesting a refund is not the same as observing it complete. The app reports recorded states.
- **Hosted webhook processing is disabled.** The API and worker run together while the free instance is awake. A sleeping instance cannot process jobs until it wakes; a keep-warm request is not a guarantee of continuous operation.
- **AI needs its configured provider.** Parsing requires a working Gemini key, accessible model and available quota. Individual requests may need clarification or manual entry. The hosted demo uses PostgreSQL retrieval.

**We do not claim:** guaranteed savings, wholesale pricing, production readiness, merchant settlement, "one person, one entry", or that a simulated market proves real buyer conversion. The allocation and account-control limits are described above.

## Documentation and contribution

Start with [the docs index](docs/00-index.md). The [idea](docs/fairpool-idea.md) explains why the product exists; [requirements](docs/product-spec.md) define its scope; [contracts](docs/contracts/README.md) define API/state/data behavior; [decisions](docs/decisions.md) explain approved departures; [progress](docs/progress.md) records outstanding work. The [demo and submission runbook](docs/demo-and-submission.md) holds the recording plan.

For contributors, read [AGENTS.md](AGENTS.md) and [team ownership](docs/team-split.md) before changing code. Keep secrets out of source, logs, screenshots and issues. Use a disposable test database, preserve payment boundaries, and document contract changes before implementing them.

## License

[MIT](LICENSE). Generated merchant SDKs include their own MIT license files. Third-party services remain subject to their respective terms.
