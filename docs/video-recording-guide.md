# FairPool: recording guide and spoken script

Prepared November 10, 2026 for the PayPal AI Hackathon. Target export: **2:50**, with a ten-second margin before three minutes. This guide is based on the current frontend and a read-only check of the local recording database. It does not claim that a new video, Codex connection or payment run was completed while writing the plan.

## 1. What the video needs to prove

Show a working desktop product, a specific buyer/merchant problem, meaningful Gemini assistance, individual PayPal Sandbox approval and the resulting funding state. The official requirements ask for a short public YouTube demo, functional access, source/license and tool-use disclosure; the judging criteria also assess implementation, design, impact, idea and presentation. Keep the product journey central. [Requirements](https://paypalaihackathon.devpost.com/#requirements), [official rules, sections 4 and 6](https://paypalaihackathon.devpost.com/rules).

Use English. Export under three minutes. Avoid unlicensed music/material and unrelated third-party branding; obtain permission where required. Keep the existing SANDBOX, fallback and simulation labels visible. Submit the public video URL on Devpost and replace the README placeholder. The owner will make the repository public before submission. Deadline: November 12, 2026, noon Pacific / November 13, 1:30 a.m. India time.

## 2. Recording environment and current readiness

Use the **local rehearsal stack**, not the hosted free service for automatic timing/payment progression:

- Browser UI: `http://localhost:5180`.
- API: `http://localhost:8001`; the Vite proxy targets this API.
- MCP endpoint: `http://localhost:8001/mcp`.
- A separate worker must drain the local app's jobs. API health/readiness and the UI on these ports returned 200 during this review.
- The working public URL, `https://fairpool-api.onrender.com/`, goes on the closing frame. Its free configuration has no worker; do not imply the local worker is running there.

Before starting a worker, privately verify `DATABASE_URL` is the intended **loopback demo database named `fairpool`**, not Supabase and not `fairpool_test`. Use the existing README setup and private local recording environment. API and worker must both use `PAYMENT_ROUTER=single_seller`, `PAYMENT_MODE=authorize_capture`, `AI_ENABLED=true`, the correct origins, valid Sandbox credentials and a working Gemini key. Restart them after changing environment values. An inherited old Gemini variable can override `.env`; the rehearsal evidence records that hazard.

The application commands, after the correct local environment is loaded, are:

```powershell
# API terminal, from the repository root:
.venv/Scripts/python.exe -m uvicorn --app-dir backend/src fairpool.main:app --host 127.0.0.1 --port 8001

# Worker terminal, same environment and database:
.venv/Scripts/python.exe -m fairpool.worker

# Frontend terminal:
$env:VITE_API_PROXY = "http://localhost:8001"
Set-Location frontend
npm.cmd run dev -- --port 5180
```

Use the existing processes if already configured correctly; do not start duplicate workers or servers. Keep terminals/configuration off the recording. Do not change published deadlines or edit money/state rows to make a shot happen.

### Snapshot checked for this plan

| Scenario | Actual state at inspection | Recording use |
|---|---|---|
| Six discovery products | OPEN; Buyer 6 has not joined them | Fresh request/join demonstration |
| `27-inch 4K monitor` | RUNNING pool, two BIDDING lots | Genuine merchant bidding; live payment take after award |
| Monitor lot `35a0ea42...` | 2 seats, minimum 2; Buyers 2 and 5 seated | Preferred main checkout/funding story |
| Monitor lot `c12caf2b...` | 3 seats, minimum 1; Buyers 6, 4 and 1 seated | A different lot; do not substitute its minimum for the two-seat story |
| `Wireless over-ear headphones` | Offers exist for Buyers 1 and 2, but the lot router is `fake` | UI illustration only; not real PayPal footage |
| `Walnut standing desk` | FUNDED using fake seeded captures | Seeded example only; not real funding evidence |
| `Ergonomic chair` | FAILED_CLOSED, Buyer 2 REFUNDED / Buyer 3 VOIDED, fake router | Short, explicitly seeded failure example |

IDs, ranks, winners and deadlines can change after reset or worker processing. Match by product, lot reference, seats and minimum before filming. **The live payment take is not ready merely because a seeded offer is visible.** Finish actual monitor bidding and obtain valid new offers first. Router/mode are stamped at award: changing runtime settings cannot turn an existing fake lot into a real one.

The discovery monitor with adjustable stand and the already-bidding monitor are **different pools**. The script explicitly introduces the latter as a separate pool. Do not edit them into an apparent continuous allocation of the fresh discovery entry.

## 3. Which login to use

All FairPool demo-account passwords come from your private `DEMO_SEED_PASSWORD`. Do not put it in a public script or video. A FairPool login is not the PayPal login used in checkout.

| Browser/client profile | FairPool login | Start URL | Job in the recording |
|---|---|---|---|
| Public | No login | `/` | Opening product shot |
| Buyer request + Codex | `demo-buyer-6@fairpool.test` | `/login`, then `/discover` | Fresh AI request, scoped delegation, first MCP join and receipt |
| Buyer payment A | `demo-buyer-2@fairpool.test` | `/login`, then `/my-pools` | Monitor two-seat offer; first Sandbox approval; audit receipt; seeded refunded example |
| Buyer payment B | `demo-buyer-5@fairpool.test` | `/login`, then `/my-pools` | Second monitor approval for the same two-seat lot |
| Merchant A | `demo-merchant@fairpool.test` | `/login?role=merchant` | Quote import, bid review/confirmation, Active Bids |
| Merchant B, if it wins | `demo-merchant-2@fairpool.test` | `/login?role=merchant` | Use for funded tracker/fulfilment if the actual award belongs to this merchant |
| Operator, off-camera | `demo-admin@fairpool.test` | `/login`, then `/ops/lots` | Inspect stamped router/mode and operational state; no need to include this login in the final video |

Use separate Chrome profiles or separate browsers. Ordinary tabs share the FairPool session, and multiple incognito windows may share one session too. Pre-sign in off-camera; do not spend the three-minute video typing passwords or switching accounts.

For the two payment profiles, pre-sign in to **two distinct US PayPal Sandbox personal accounts**. Call them Sandbox Buyer A and Sandbox Buyer B in your private notes. Use the account that belongs with each FairPool connection, if linked. Do not use a seller account, a real-money account or the same Sandbox payer twice for one pool. PayPal credentials stay private and are not `DEMO_SEED_PASSWORD`.

## 4. Prepare the shots before recording

### A. Fresh buyer request and Codex access

1. In Buyer 6's profile, open **Agent settings** at `/settings/agents`.
2. Under **Create agent access**, select only the OPEN `27-inch 4K monitor with adjustable stand` pool. Use maximum per entry USD 600, an expiry that covers the recording, and any conditions you can actually satisfy. Ratify the mandate and click **Create delegation**.
3. Copy the token into private client setup, then **Hide token**. Never record token creation/copying. This frontend explicitly says AI-proposed mandates are unavailable; the mandate is manually written and ratified. Do not narrate an AI-generated mandate screen that does not exist.
4. Check Buyer 6 still has no entry in this discovery pool. If a dry run already joined it, do not pretend the next call is a first join. Use an available unjoined pool/account, or accurately label the replay as an existing-entry response.
5. On `/discover`, click **Make a request** to reach the prompt. Suggested input:

   > I want a new 27-inch 4K monitor with an adjustable stand and power cable, delivered to New York by December 15, 2026. My maximum total, including shipping and tax, is $600.

6. Click **Find matches**. Inspect the proposed pool, region, date, maximum and requirements. If the model asks a question, answer it honestly. Do not narrate a successful AI match over a manual fallback.
7. Click **Confirm and continue**. For the Codex-first join take, stop before the lobby's **Confirm and join** button. Codex will make the first entry; return to the browser and refresh afterwards.

If the date or pool is no longer suitable, replace it with a valid date after the pool's **Latest delivery the pool allows**. The maximum is a buyer cap, not a claimed product price.

### B. Connect Codex privately

Use the OpenAI Docs skill's official [MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) and [CLI reference](https://learn.chatgpt.com/docs/developer-commands). The installed CLI checked here is `codex-cli 0.164.0`, whose `mcp add --help` supports a Streamable HTTP URL and bearer-token environment variable. PowerShell blocks the npm `.ps1` wrapper on this machine; use `codex.cmd`.

Run setup **before** recording, from the terminal that will launch the recording Codex session:

```powershell
$privateToken = Read-Host "FairPool buyer delegation token" -AsSecureString
$env:FAIRPOOL_AGENT_TOKEN = [System.Net.NetworkCredential]::new("", $privateToken).Password
codex.cmd mcp add fairpool-demo --url http://localhost:8001/mcp --bearer-token-env-var FAIRPOOL_AGENT_TOKEN
codex.cmd
```

The command stores the environment-variable name in Codex configuration, not the token value. Launch a fresh Codex session that inherits the variable. An already-open desktop/IDE process does not automatically receive a new shell variable. Use a clean recording conversation/workspace so source files, `.env` and unrelated chats do not appear on screen. No OAuth login to FairPool MCP is required; this is buyer delegation bearer auth.

First ask Codex:

> Use only the fairpool-demo MCP tools. Do not read local files, inspect environment variables, change code or make shell/network calls. List the monitor pools my delegation allows. Show the selected pool's requirements, then stop before joining.

Confirm the actual connection lists `list_pools`, `enter_pool`, `list_entries`, `withdraw_entry`. Then, for the recorded entry, give the exact pool ID from that result and the confirmed buyer terms:

> Enter pool [POOL_ID] for delivery region NY, required by 2026-12-15, with maximum total USD 600.00. Use the stable idempotency key recording-monitor-entry-1. Then list my entries and show the returned entry and checkout hint. Do not approve or request any payment.

Replace the pool/date if the live confirmation card differs. Tokens never belong in the prompt. The tool's delivery date must be supplied even though the advertised MCP schema marks it optional; the shared API requires it. A successful JSON-RPC HTTP response can still contain `result.isError=true`: that is a failed tool action. Verify an entry ID and the returned buyer record, not just an HTTP 200.

Return to Buyer 6's pool page, refresh, and click **View entry receipt**. The receipt confirms entry, not payment or a guaranteed place. Keep the public receipt view on screen; do not expand/download salt, signature or signed JSON for the video.

**Codex readiness gate:** the installed command shape and the four-tool implementation are checked, but a new authenticated Codex-client round trip was not run for this planning task. FairPool's custom transport still has the recorded SDK compatibility question. If the actual connection cannot complete, stop this take. The safe alternate edit uses the browser's **Confirm and join** and omits the claim that Codex joined. A working Gemini-and-PayPal product can still be shown; do not substitute a typed/fabricated tool result.

### C. Merchant quote and genuine award

1. Merchant A opens **Demand Board** at `/merchant/demand`.
2. Find the existing monitor lot with **2 seats / minimum 2**, reference beginning `35a0ea42` in the inspected snapshot. The displayed product heading may read **Monitor 27 4k**. Match the lot reference and counts, not the similar title alone.
3. Click **Prepare a bid**. Expand **Import an existing quote (optional)**, paste the quote and click **Parse quote**.
4. Suggested draft quote, with the real validity timestamp filled before parsing:

   > New monitor-27-4k monitors, including monitor, stand and power cable. I can supply 5 units in total; target quantity 2 for this lot; minimum order 2. Delivered price USD 470 per unit for 2 or more, including shipping and tax. Shared inventory capacity 5 across lots. Delivery within 7 days to US-EAST, including NY, NJ and PA. Returns 30 days. Valid until [VALID_UNTIL_UTC]. Stock is reserved for this offer; this is a Sandbox demonstration.

5. Choose a validity timestamp covering the published bid/funding/capture windows. Review every proposed field: product reference, NEW condition, bundle, available quantity, target quantity **2**, MOQ **2**, capacity, delivered tier, shipping/tax included, delivery/returns and expiry. Correct proposals before confirming. The USD 470 figure is a suggested bid input, not a guaranteed winner or pre-existing awarded price.
6. Click **Review bid**, inspect the confirmation, then **Save and confirm bid**. Capture the **Sealed bid receipt** and open **Active Bids**. A stored draft or parsing result is not an eligible confirmed bid.
7. Any competing merchant uses its own account/key. Do not claim a competitor's price was read while bids are sealed. Do not force Merchant A to win for the video; use the actual awarded merchant for later shots.
8. Wait for the real published bidding windows and the worker. The seeded monitor bid window is six hours, not a three-minute timer. Earlier lots must also be decided before later awards. Record in separate takes and cut the waiting time with an honest **After the published bidding window** caption. Never alter published rules/deadlines in SQL or use a forced award as if it were competitive selection.
9. Before capturing a PayPal take, the operator checks the awarded lot at `/ops/lots`: router **single_seller**, mode **authorize_capture**, valid offers for Buyers 2 and 5, and no MOCK/SIMULATED result. If it stamped `fake`, use a fresh properly configured recording scenario; do not relabel it or modify a terminal/stamped lot to look live.

The frontend has no pool-creation screen. `/ops` provides monitoring/recovery, not a create-pool wizard. If the current published schedule is unsuitable, preparing a new short-window scenario is an operator/backend task before filming; this guide does not invent an admin button or silently reset your existing data.

### D. Audit, payments and funding

1. After all relevant bidding windows have closed, Buyer 2 opens the monitor pool through **My Pools -> View pool / Review offer -> Back to your pool**, then **Public audit**. Use `/audit/<pool_id>` if a direct bookmark is easier.
2. Click **Use my saved receipt**, then **Recompute my place** when available. The receipt must belong to this pool. While bidding is open, the seed/evidence may be intentionally withheld: do not show a waiting result as successful rank verification.
3. Buyer 2 opens **My Pools -> Review offer** for the two-seat monitor lot. Show the exact delivered total, merchant, cap and terms. Select a saved test delivery address off-camera; crop/mask the address area in the final edit.
4. Continue via the PayPal button, or **Continue to PayPal** if the recorded redirect fallback is used. Approve the Sandbox order as Personal Buyer A. Keep the address/login/full URL out of the capture. The redirect is supported; do not say a popup worked if you used redirect.
5. Show the returned order state. Approval is not capture. A verified authorization places a hold; capture/funding come from the server and worker.
6. In Buyer 5's separate profile, approve its offer for the **same lot** with distinct Personal Buyer B. Both approvals must complete before their actual deadlines. Do not reuse an expired/completed offer or a captured order as if making a new approval.
7. Let the worker finish. Record **FUNDED** only after the tracker reports the required **completed captures**, not merely approvals/holds. Use the actual totals displayed; do not edit in USD 940 unless the actual awarded/captured total is USD 940.
8. In the actual winner's merchant profile, open **Active Bids** and the lot tracker, then **Fulfillment -> Awarded lot -> Payment verification -> Verify payments**. Capture the live verification result if it matches. If it differs or fails, stop and resolve it; never overlay a successful result.
9. Scroll directly to verification; do not expose shipping rows, addresses, CSV contents or full payment references. Do not click **Record shipments** with invented tracking just to get a success badge.

### E. Failure example and closing frame

Buyer 2 opens **Orders**, filters for the seeded **Ergonomic chair** refund, and opens **View order**. Keep its SIMULATED/fake-router label and add **Seeded failure example** if needed. The narration explicitly calls it seeded. Buyer 3 has the companion VOIDED example if you want an alternate shot. Neither is new real-PayPal refund evidence.

End with FairPool branding, the hosted URL and repository/README link. Add a small factual tools line: **PayPal Orders v2 + SDK v6 / Gemini / FairPool MCP / APIMatic-generated merchant SDKs**. Mention Elastic as a demonstrated search integration only if the recorded run actually used it. Do not advertise the disabled Zapier write bridge, a generated portal that does not exist, or live vault charging.

## 5. Edit timeline - exactly 2:50

The final cut is deliberately not a continuous three-minute execution of published windows. Record the product operating, preserve meaningful status transitions, then trim idle/provider wait time. Pre-sign in and record role changes as cuts.

| Time | Profile / route | What to capture |
|---|---|---|
| 00:00-00:12 | Public `/` | FairPool wordmark and real landing product UI; avoid the landing's illustrative prices as transaction proof |
| 00:12-00:36 | Buyer 6 `/discover` -> pool | Prompt -> Find matches -> real confirmation card -> Confirm and continue; stop before browser join for the Codex-first take |
| 00:36-00:49 | Codex, Buyer 6 delegation -> browser receipt | Real enter_pool/list_entries result; then refreshed View entry receipt. Hide credentials |
| 00:49-01:15 | Merchant A `/merchant/demand` -> `/merchant/bids` | Separate already-bidding monitor lot; Prepare a bid -> Parse quote -> Review bid -> Save and confirm bid -> sealed receipt |
| 01:15-01:29 | Buyer 2 `/audit/<pool_id>` | After bidding closes: Use my saved receipt -> Recompute my place; public checks and limits |
| 01:29-02:04 | Buyer 2, then Buyer 5 `/my-pools` -> `/offers/<id>` | Actual offer review, Sandbox approval, returned authorization; brief second distinct buyer approval. Keep one-seller fallback visible |
| 02:04-02:22 | Winning merchant `/merchant/bids`, `/merchant/fulfillment` | Completed captures -> FUNDED -> Verify payments result |
| 02:22-02:37 | Buyer 2 `/orders` | Separate seeded refunded chair example, visibly labelled |
| 02:37-02:50 | FairPool closing frame | Value, actual tool use, hosted app + README/source links |

## 6. Read-aloud script

About 283 words. Speak naturally at roughly 120-135 words per minute and let the screen actions use the remaining time. These time slots include short pauses; read it aloud once with a stopwatch before recording. Spoken timing has not been measured from an actual recording.

### 00:00-00:12 | The problem

Buying together takes more than collecting interest. Buyers need control over payment, and merchants need real demand. That's the problem FairPool is built around.

### 00:12-00:36 | Buyer request

I ask for a monitor and set my maximum delivered price. Gemini turns that into fields I can check: the product, delivery date and price limit. I confirm those details. Joining a pool costs nothing and places no PayPal hold.

### 00:36-00:49 | Codex participation

Codex submits the request through FairPool's MCP tools. Its buyer delegation limits the pools, price and expiry. It can join and check entries, but it cannot pay.

### 00:49-01:15 | Merchant bid

This separate monitor pool is already taking bids. A merchant pastes a quote, Gemini proposes structured terms, and the merchant reviews and confirms them. Bids stay sealed. Fixed rules, including the buyers' requirements, decide which qualifying offer wins.

### 01:15-01:29 | Public audit

After bidding closes, I use my saved receipt to check my entry and rank. Selection is auditable under published rules, with the limits explained here.

### 01:29-02:04 | Individual PayPal approvals

Now I review the winning merchant, exact delivered total and return terms. I approve on PayPal myself. This demo uses the Sandbox and one stand-in seller. A second selected buyer approves separately. The server verifies each approved order before placing a hold. Only completed captures fund the group.

### 02:04-02:22 | Funding and verification

The merchant can now see the funded lot. Payment verification reads the orders from PayPal and compares completed captures with the recorded total. Fulfilment becomes available after funding.

### 02:22-02:37 | Failure outcome

If a group fails to fund, authorizations are voided and completed captures are refunded. This separate failure example is seeded and labelled; it illustrates the recorded outcome.

### 02:37-02:50 | Close

FairPool connects buyer demand, merchant competition and individual PayPal approval. Gemini helps prepare the details. Try the working demo or run it from our README.

## 7. Capture order and practical editing

Record the buyer/Codex and merchant-bid takes while the relevant pools are open. Record audit/payment/funding only after the actual award is ready. The final edit follows the table above; it does not need to match the order in which the files were captured.

Use numbered clips: `01-landing`, `02-buyer-request`, `03-codex-entry`, `04-merchant-bid`, `05-public-audit`, `06-paypal-buyer2`, `07-paypal-buyer5`, `08-funded-verification`, `09-seeded-refund`, `10-close`. Store videos outside the Git repository. Do not record configuration screens, passwords, new tokens, devtools headers, `.env`, the full PayPal approval URL or shipping details.

Capture the desktop app at 1920x1080, readable zoom and normal pointer speed. Record each action at normal speed; cut idle waits and account switching rather than speeding through text. Use short captions for role changes, the separate bidding pool and the real published-window jump. Keep the actual status/total readable for a few seconds. A clean voice-over and screen sound are enough; music is unnecessary.

If a take runs long, remove any Developer API/SDK tour, operations console, notification inbox, address settings, shipment entry and 10k simulation before cutting the actual Gemini confirmation, human PayPal approval, completed-capture result or required disclosures. The simulation/agent-market report is an optional appendix clip, clearly SIMULATED, not a substitute for a real Sandbox payment.

For a separate longer walkthrough, cover Developer API with an existing hidden key, read-only OpenAPI/SDK links, saved addresses, Profile attestations, inbox, fulfilment and operator recovery. Those are useful screens but do not fit a coherent three-minute main story.

## 8. Frontend review and inclusion map

Review method: traversed all 89 source files under `frontend/src` (21,003 lines at this revision) using TypeScript AST analysis of routes, page controls and API calls, then inspected the critical request, bid, checkout, role/session and audit logic directly. The static inventory includes shared components, hooks, CSS and error/loading branches; it is not a claim that every branch was exercised in a browser. Live read-only browser checks verified Buyer 6 Discover/My Pools/Agent settings and Merchant A Demand Board/Active Bids/Developer API on port 5180. Account roles, seat assignments, routers and offer states were read from the local database without changing them.

| Frontend area | Current contents / controls | Filming decision |
|---|---|---|
| Landing | Join a pool; Open merchant area; illustrative scroll walkthrough and honest demo limits | Brief opener; sample prices are not evidence |
| Login / signup | Role-aware Sign in; PayPal-first registration, connected/details steps | Pre-sign in; exclude signup/identity prefill dependency |
| Discover | Open pools, filters/search, Make a request, Find matches, confirmation card, manual fallback | Main AI request take |
| Pool lobby | Product/terms, entry confirmation, Confirm and join, receipt modal, progress, rules/lot disclosures | Show actual receipt after Codex join; no second join |
| Entry receipt | Entry acknowledgement, Print, public audit link, Signed proof JSON | Show acknowledgement; avoid private proof material |
| My Pools | Current pools/Past entries, search, Review offer/View order/View pool | Main navigation into actual offer |
| Orders / order status | Status filters, payment and group progress, receipt, recorded activity | Actual capture status plus labelled failure example |
| Offer checkout / PayPalButton | Delivered total/cap/terms, saved address, SDK/redirect, decline/cancel, terminal/expired states | Main real approval take; omit private data |
| PayPal settings | Link/check/revoke identity connection | Off-camera only; not a saved-charge permission |
| Address book | Add/edit/default/remove saved delivery addresses | Prepare a test address off-camera |
| Agent settings | Manual ratified mandate, selected pools, per-entry cap, UTC expiry, conditions, one-time token/revoke | Prepare before filming; no AI-proposed-mandate claim |
| Public audit | Rules/list/seal checks, receipt loader, rank recomputation, draw/lots, limits/evidence | Capture after reveal, with correct buyer/pool receipt |
| Merchant Demand Board / composer | Prepare a bid, quote import, Parse quote, typed fields, Review bid, Save and confirm bid, receipt | Main merchant AI + confirmation take |
| Active Bids / tracker | Account-owned bids, group/status filters, holds/captures, MOQ, refill and funding state | Show completed captures / FUNDED |
| Fulfillment | Awarded lot selector, gated shipping/CSV, shipments, verification manifest and Verify payments | Verification section only in main cut |
| Developer API | Scoped keys shown once, revoke, API document, quickstart | Longer walkthrough/optional source end card; no token exposure |
| Merchant Profile | Identity/payment fields and three attestations | Preflight; no paid marketplace-onboarding claim |
| Ops | Overview alerts, Lots, Recovery, Audit trail, Sandbox controls | Off-camera preparation/inspection only |
| Shared shell | Role gates, workspace links, inbox, honesty labels, caching/loading/errors, responsive navigation | Keep correct role and labels visible; trim loading waits honestly |

Primary source anchors: [routes](../frontend/src/App.tsx), [buyer login/settings](../frontend/src/buyer/pages.tsx), [Discover](../frontend/src/buyer/discover/DiscoverPage.tsx), [pool lobby](../frontend/src/buyer/lobby/PoolPage.tsx), [bid composer](../frontend/src/merchant/demand/BidComposer.tsx), [checkout](../frontend/src/checkout/OfferCheckout.tsx), [PayPal button](../frontend/src/checkout/PayPalButton.tsx), [audit](../frontend/src/audit/AuditPage.tsx), [fulfilment](../frontend/src/merchant-fulfillment/FulfillmentPage.tsx), [seed accounts/scenarios](../tools/demo_seed.py), [earlier live rehearsal](evidence/phase10/rehearsal_1.json), [corrected participation evidence](evidence/phase9/agent_participation_followup.json).

## 9. Final checks before uploading

- Watch the export at normal speed: runtime below 3:00; narration and shown action agree; no hidden cuts imply a different pool or fake capture became a real payment.
- Real Gemini response, real buyer approval, actual completed captures and real read-only verification are visible where claimed. Seeded failure and demo seed labels remain explicit.
- Different Sandbox payer accounts approved the two-seat lot; the merchant shown at fulfilment really won it. No forced status or invented PayPal result appears.
- Secrets, personal addresses, full approval URLs and detailed payment references are absent or masked. Inspect every frame around profile switches and downloads.
- No unshipped vault charge, disabled Zapier write bridge, universal MCP compatibility, guaranteed savings, human uniqueness or production-readiness claim.
- Upload publicly on YouTube; verify while logged out; put the link in Devpost and the README. Keep the working build/setup accessible for judging. See the [submission runbook](demo-and-submission.md) for the rest of the submission.

This plan does not run a reset, issue a delegation, place a bid, approve/authorize/capture/refund a payment or change deployment settings. Those are recording preparation/actions for the operator and human participants, not work performed by drafting this guide.
