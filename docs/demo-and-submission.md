# Demo and submission

Hackathon: "Build What's Next with PayPal and AI" (Devpost). Submissions close **Thu Nov 12, 12:00 pm PT (Nov 13, 1:30 am IST)**. Nothing can be edited after the deadline. We submit in PH11, one day before the deadline (task T11X01). Judging runs Dec 1 to Dec 15; judges may judge from the description, images and video alone, so the video and README carry as much weight as the code, and a machine may read the repository (`docs/product-spec.md` FR-HK-01 to FR-HK-06).

## 1. What must be submitted

| Requirement (from the hackathon brief) | How we meet it | Task |
|---|---|---|
| Application integrating PayPal using the free Sandbox, plus an AI tool or model | FairPool: PayPal Vault (setup token, payment token) with Orders v2 charges and refunds (authorize, capture and void in the fallback mode), webhooks, PayPal JavaScript SDK v6 (fallback approval), local PayPal MCP read-only inspection, Orders v2 shipment tracking; Google Gemini (`gemini-3.5-flash-lite` through `google-genai`) for intake, quote parsing and reconciliation | all |
| Text description of features and functionality | Devpost description from the README | T10A03 |
| Tools used: which AI tools or models and how | Google Gemini via `google-genai` (intake, quote parsing, offer reconciliation, simulation text); Elastic (retrieval); Zapier MCP and our MCP server (agentic interface); APIMatic (SDKs and plugin); PayPal MCP and SDK. The merchant's separate Claude assistant, connected to the PayPal MCP for the read-only verification beat, is the merchant's own tool, not a FairPool dependency | T10A03 |
| Functional demo: run instructions or hosted URL; a mockup does not count | Hosted Render URL plus `docker compose` instructions | T09A03, T10A02 |
| Public repository with an open-source license detectable in About | MIT `LICENSE` at the root | T10A02 |
| Demo video under 3 minutes, public on YouTube, running on its intended device, no third-party trademarks or copyrighted music | Section 3 | T10B02 |
| English | All materials | T10A03 |

Also remember: projects built with financial or preferential support from PayPal or Devpost can be disqualified; do not accept funding or commercial licences from them.

## 2. Demo data rules

- Generic products only ("27-inch 4K monitor", "robot vacuum"). No brand, console or game names anywhere on screen, in data, in prompts shown on screen or in audio (FR-HK-06).
- Real Sandbox amounts only. No invented totals such as pool sizes in the millions.
- Every fallback or simulated element is labelled on screen (`SANDBOX`, `FALLBACK: single stand-in seller`, `SIMULATED`, `DEMO SEED`, `MOCK`). The video narration says in one sentence that one test seller stands in for the winning merchant because the Sandbox app has no marketplace permission (DEP-4).
- Nothing in the video may contain a real secret, token, full approval URL or buyer password.
- The CR-14 agent-market beat is a labelled simulation: its pool uses the fake payment router, its participants are synthetic and it never reaches PayPal (I12). The narration says so in one clause and the report on screen carries the SIMULATED label. Its refusal counts are stated as measured results, never as a security guarantee.

## 3. Three-minute storyboard (hard limit 3:00; target 2:50)

The table below is a rehearsal/coverage outline; it is not proof that every beat is currently live or must be squeezed into one take. Seeded fake-router orders are not real PayPal footage, the current UI writes mandates manually, and public rank evidence may wait until bidding closes. Planning a cut does not complete T10X01, T10X02 or T10B02, or waive their execution requirements.

Each beat names the screen and the proof it gives. Beats marked optional are cut first if the recording runs long; none of them changes the product.

| Time | Beat | Shows | Requirement |
|---|---|---|---|
| 0:00 to 0:12 | The problem and the idea in one sentence | Title card with the pool-card badge text | FR-UI-01 |
| 0:12 to 0:32 | Headless join: a buyer's AI client joins a pool through the FairPool MCP server (S9 recorded Zapier's managed-mode write tools unable to send a schema-valid body, so the bridge is off and the MCP path is the one shown), then lists its entry | Client prompt, tool calls, entry and receipt; the notice that a human still approves payment | FR-IG-02, FR-IG-03, FR-AG-01 |
| 0:32 to 0:47 | Pool closes; public audit page shows the committed list, root, beacon seed (or the DEMO SEED label), lot split; verify-my-place | Audit page | FR-AD-01, FR-SL-07 |
| 0:47 to 1:10 | Merchant Demand Board: a lot appears; the merchant pastes a quote; AI proposes fields; reconciliation flags an extra bundle item; the merchant corrects and confirms; a second merchant bot bids through the generated Python SDK (a terminal snippet); award | Console and terminal | FR-AI-04, FR-AI-02, FR-IG-04, FR-IG-05 |
| 1:10 to 1:50 | **Authorize mode (what the hosted demo runs, `PAYMENT_MODE=authorize_capture`):** Action Required with the countdown, approve in the SDK popup, hold placed, then captured once the group is real; the Active Bids tracker shows holds against the MOQ first, then completed captures; lot FUNDED; one buyer lets the window expire and the waitlist refills. Vault mode is shown only as a labelled screen, never as a live charge: saving a permission for real is unshipped (`VAULT_REAL_SAVE_ENABLED=false`, DEP-5), so a live buyer there rejects `VAULT_MISSING` | Real Sandbox approvals and captures by a Sandbox buyer — the path IT-5, C-08 and C-09 proved | FR-CK-03, FR-UI-02, FR-UI-05 |
| 1:50 to 2:02 | Lot 2 misses its minimum and ends with void then refund and net zero. The expired-window refill is not repeated here; beat 5 already showed it | Ops view and orders tab | FR-CK-03, FR-FN-05 |
| 2:02 to 2:22 | **CR-14, the agentic beat:** buyer agents holding ratified mandates join over the FairPool MCP server while merchant agents bid through the Merchant Agent API, and one adversarial agent tries to exceed a cap, enter an out-of-scope pool and read another merchant's sealed bid. On screen: the report's attempt count, its refusals by production code, and zero PayPal writes from any AI-callable surface. Narration is one sentence — the agents did everything except pay — and the run is labelled SIMULATED | A terminal running `tools/agent_market.py`, then the report | FR-AG-03, FR-AI-06, FR-AG-02 |
| 2:22 to 2:37 | Fulfillment: shipping CSV, mark shipped with tracking (PayPal tracker if S12 passed); in the merchant's Claude connected to the PayPal MCP server (or the verification endpoint), ask to verify the lot and see the totals match | Fulfillment tab, Claude | FR-IG-07, FR-IG-08, FR-UI-06 |
| 2:37 to 2:50 | Labelled simulation at 10,000 entries; limits we state (not provably fair, one account per linked PayPal account, sandbox only); roadmap | **A terminal, not a screen:** `POST /api/v1/admin/sim/run` and the `sim_runs` result rows. There is no simulation page in `frontend/src`, so do not narrate one | FR-AI-03, FR-SM-01, FR-SL-06 |
| 2:50 to 3:00 | Close with the repository link | Title card | FR-HK-01 |

If S9 (Zapier) did not pass, the second beat uses the FairPool MCP server and says so. If S13 did not pass, the approval beat uses the redirect and says so. If S12 did not pass, tracking is shown inside FairPool and labelled. If T10A04 does not pass, the second bid in beat 4 uses the documented Merchant Agent API call and the narration does not say "generated SDK"; no SDK claim appears in the README, the Devpost text or the video.

## 4. Rehearsal procedure

1. Use `make demo-reset` and `make demo-seed` only against a disposable loopback demo database. Local and Render now share Supabase, whose existing signed/payment history must be preserved; use the [append-only calendar instructions](../README.md#demo-data) for that database. Confirm `GET /api/v1/checkout/config` and the ops lot panel agree with the blueprint. Payment mode and routing are frozen at award: use a fresh correctly configured pool after a mode change, without relabelling historical lots.
2. Check the configured Gemini key/model access, funded US Sandbox buyers and current payment settings. The hosted release uses PostgreSQL retrieval, so Elastic access is needed only when demonstrating the Elastic path. Committed SDKs run without APIMatic generation access; check trial/plan access if regenerating them. Webhook processing remains disabled in the hosted blueprint. The Zapier bridge is off after S9's managed-mode write failures, so the demo does not depend on its trial.
3. Run the storyboard end to end twice (task T10X01 then T10X02). The second run must complete with no manual database intervention.
4. Record screens at 1080p, speak over the capture, no music. Upload to YouTube as public. Open the link while logged out.

### Recording runbook (T10B02)

This reset-based pre-flight is for a **disposable loopback database only**, from the repository root. For the shared Supabase demo, preserve existing history and use the append-only procedure above. Every applicable command must succeed before recording starts:

1. `make demo-reset` prints the before counts and `after: 0 rows across counted tables`.
2. `make demo-seed` rebuilds the five-lot scenario; `python tools/demo_seed_check.py` prints `ALL CHECKS PASSED`.
3. `python tools/agent_market.py --self-check --out .tmp/agent_market_report.json` prints `breaches_succeeded: 0` and `paypal_writes_from_ai_surface: 0`.
4. `GET /api/v1/checkout/config` and the ops lot panel agree on the stamped `payment_mode`.

On-screen labels, by beat: `SANDBOX` where a PayPal approval or capture is shown; `FALLBACK: single stand-in seller` on the checkout offer and the hold notice; `SIMULATED` on the agent-market report and the 10,000-entry simulation; `DEMO SEED` on the audit beacon; `MOCK` only if a mock toggle is armed. The narration says once that one test seller stands in for the winning merchant, and that the CR-14 market is simulated.

Wording for the two labelled beats: "Every participant here is an agent; nothing in this market can reach PayPal." and "This is a labelled simulation; refusal counts are measured results, not a security guarantee."

Do not show: `.env`, any token, key or cookie, a full PayPal approval URL, buyer passwords, or the database connection string. Blur or cut any address field.

## 5. README outline (task T09X01; Member A writes the PayPal, operations and run sections, Member B the product, fairness, AI, search and agent sections)

1. What FairPool is and who it is for, in plain language, with the three-minute video link.
2. How it works: join free, published rule, fair draw, sealed bids, individual PayPal approval, funding by captures.
3. How PayPal is used: Orders v2 lifecycle with idempotency, JavaScript SDK v6, webhooks and reconciler, PayPal MCP verification, shipment tracking; what was verified in the Sandbox and what was not.
4. How AI is used: intake, quote parsing, offer reconciliation, simulation, the buyer delegation mandate (CR-14) and the agent-populated market run; the guardrails (AI proposes, rules decide, humans approve, and no AI-callable surface can move money); the measured evaluation table and the boundary report, each stated as a measured result rather than a guarantee.
5. Sponsor and tool use, honestly: Elastic (retrieval only), Zapier MCP (managed mode, trial-limited), our MCP server, APIMatic (SDKs, ContextMatic plugin), Render.
6. Honest limits: Sandbox only; one stand-in seller and why; platform fee and marketplace settlement unavailable; auditable not provably fair; account-level duplicate control; tax simulated; no brand data.
7. Run it: prerequisites, environment variables (names), `make setup`, `make dev`, the hosted URL.
8. Tests: layers, how to run them, the sandbox contract tests.
9. Architecture diagram and a pointer to `docs/`.
10. Roadmap: platform approval and multi-seller settlement, partial capture tiers, emergent pools, India-domestic checkout with local providers.

## 6. Devpost fields

Project name and tagline; description (features, who it is for, why it matters); built with (languages, frameworks, PayPal APIs, Google Gemini, Elastic, Zapier MCP, APIMatic, Render); try-it links (hosted URL, repository); video; images (audit page, merchant console, checkout, tracker); tools-used statement (which AI tools or models and how). Copy claims only from `docs/product-spec.md` section 3.

## 7. Final QA checklist (task T11X01)

1. Repository is public; License is detected in About; the README renders; no secret in the diff or history (full-history scan).
2. Clean-clone run works from the README instructions; the hosted URL works logged out.
3. CI is green on `main`; tags `contracts-v1` and `rc1` exist.
4. Video is public, under 3:00, no trademarks or music, labels visible.
5. Devpost text matches the product exactly: every claim is backed by a requirement and a passing test; fallbacks are disclosed.
6. All switches in `docs/decisions.md` section 4 are filled and match the deployed environment.
7. Sponsor trials were active during recording; the README states which parts depend on a trial or plan.
8. Submission saved in PH11; a screenshot of the submission page is stored by the owner.
9. Hosting uses the recorded $0 setup: a free Render web service and Supabase project. `.github/workflows/keep-warm.yml` has a 10-minute cadence, 03:00-22:00 UTC, and is intended to be enabled after the repository becomes public; it is not an uptime guarantee. Re-open the hosted URL logged out once a week until winners are announced. The API image supervises its API and worker together; jobs and reconciliation run while the service is awake and pause when it sleeps. Database-clock deadlines are rechecked after waking. State cold-start/sleep risks in the README. BD-05's paid-plan rule is recorded as superseded for this submission.
10. Judge access: the README says how a judge approves a payment (a Sandbox personal buyer account they create, or a dedicated demo buyer whose login is given only through Devpost's private testing-instructions field if it offers one). Sandbox buyer passwords never appear in the repository, README or video; change any password that was ever shown on screen.

## 8. After submission (task T11X02)

Open the repository, license, video and Devpost page while logged out; confirm links; do not push changes that alter the submitted behaviour. Only fixes for infringing or personal-data material are allowed after the deadline.
