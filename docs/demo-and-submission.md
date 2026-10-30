# Demo and submission

Hackathon: "Build What's Next with PayPal and AI" (Devpost). Submissions close **Thu Nov 12, 12:00 pm PT (Nov 13, 1:30 am IST)**. Nothing can be edited after the deadline. We submit in PH11, one day before the deadline (task T11X01). Judging runs Dec 1 to Dec 15; judges may judge from the description, images and video alone, so the video and README carry as much weight as the code, and a machine may read the repository (`docs/product-spec.md` FR-HK-01 to FR-HK-06).

## 1. What must be submitted

| Requirement (from the hackathon brief) | How we meet it | Task |
|---|---|---|
| Application integrating PayPal using the free Sandbox, plus an AI tool or model | FairPool: PayPal Vault (setup token, payment token) with Orders v2 charges and refunds (authorize, capture and void in the fallback mode), webhooks, PayPal JavaScript SDK v6 (fallback approval), local PayPal MCP read-only inspection, Orders v2 shipment tracking; Claude for intake, quote parsing and reconciliation | all |
| Text description of features and functionality | Devpost description from the README | T10A03 |
| Tools used: which AI tools or models and how | Claude (intake, quote parsing, offer reconciliation, simulation text); Elastic (retrieval); Zapier MCP and our MCP server (agentic interface); APIMatic (SDKs and plugin); PayPal MCP and SDK | T10A03 |
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

## 3. Three-minute storyboard (hard limit 3:00; target 2:50)

Each beat names the screen and the proof it gives. Beats marked optional are cut first if the recording runs long; none of them changes the product.

| Time | Beat | Shows | Requirement |
|---|---|---|---|
| 0:00 to 0:12 | The problem and the idea in one sentence | Title card with the pool-card badge text | FR-UI-01 |
| 0:12 to 0:32 | Headless join: a buyer's AI client joins a pool through the Zapier managed-mode bridge (or the FairPool MCP server), then lists its entry | Client prompt, tool calls, entry and receipt; the notice that a human still approves payment | FR-IG-02, FR-IG-03, FR-AG-01 |
| 0:32 to 0:47 | Pool closes; public audit page shows the committed list, root, beacon seed (or the DEMO SEED label), lot split; verify-my-place | Audit page | FR-AD-01, FR-SL-07 |
| 0:47 to 1:10 | Merchant Demand Board: a lot appears; the merchant pastes a quote; AI proposes fields; reconciliation flags an extra bundle item; the merchant corrects and confirms; a second merchant bot bids through the generated Python SDK (a terminal snippet); award | Console and terminal | FR-AI-04, FR-AI-02, FR-IG-04, FR-IG-05 |
| 1:10 to 1:50 | Vault mode (primary): the buyer saved PayPal at join with the cap shown (say that FairPool, not PayPal, enforces the cap and that PayPal's screen shows no amount); after the award the merchant Active Bids tracker shows charges attempted against the MOQ, then captures; lot FUNDED; one charge is shown failing (simulated decline) and refilled from the waitlist. Fallback mode: Action Required with the countdown, approve in the popup, hold placed | Real Sandbox charges (a Sandbox buyer approves saving PayPal once, beforehand) | FR-IG-06, FR-UI-02, FR-UI-05 |
| 1:50 to 2:15 | Lot 2: one buyer lets the window expire, the waitlist refills; another lot misses its minimum and ends with void then refund and net zero | Ops view and orders tab | FR-CK-03, FR-FN-05 |
| 2:15 to 2:35 | Fulfillment: shipping CSV, mark shipped with tracking (PayPal tracker if S12 passed); in the merchant's Claude connected to the PayPal MCP server (or the verification endpoint), ask to verify the lot and see the totals match | Fulfillment tab, Claude | FR-IG-07, FR-IG-08, FR-UI-06 |
| 2:35 to 2:50 | Labelled simulation at 10,000 entries; limits we state (not provably fair, one account per linked PayPal account, sandbox only); roadmap | Simulation banner, slide | FR-AI-03, FR-SM-01, FR-SL-06 |
| 2:50 to 3:00 | Close with the repository link | Title card | FR-HK-01 |

If S9 (Zapier) did not pass, the second beat uses the FairPool MCP server and says so. If S13 did not pass, the approval beat uses the redirect and says so. If S12 did not pass, tracking is shown inside FairPool and labelled.

## 4. Rehearsal procedure

1. `make demo-reset`, then `make demo-seed` (admin, merchants, catalog, one pool template, sandbox buyer references).
2. Check each external dependency before recording: Zapier trial active (started in PH4), APIMatic trial active (started in PH3), Elastic project active, Sandbox buyers funded, webhook listener registered (if S5 passed).
3. Run the storyboard end to end twice (task T10X01 then T10X02). The second run must complete with no manual database intervention.
4. Record screens at 1080p, speak over the capture, no music. Upload to YouTube as public. Open the link while logged out.

## 5. README outline (task T09X01; Member A writes the PayPal, operations and run sections, Member B the product, fairness, AI, search and agent sections)

1. What FairPool is and who it is for, in plain language, with the three-minute video link.
2. How it works: join free, published rule, fair draw, sealed bids, individual PayPal approval, funding by captures.
3. How PayPal is used: Orders v2 lifecycle with idempotency, JavaScript SDK v6, webhooks and reconciler, PayPal MCP verification, shipment tracking; what was verified in the Sandbox and what was not.
4. How AI is used: intake, quote parsing, offer reconciliation, simulation; the guardrails (AI proposes, rules decide, humans approve); the measured evaluation table.
5. Sponsor and tool use, honestly: Elastic (retrieval only), Zapier MCP (managed mode, trial-limited), our MCP server, APIMatic (SDKs, ContextMatic plugin), Render.
6. Honest limits: Sandbox only; one stand-in seller and why; platform fee and marketplace settlement unavailable; auditable not provably fair; account-level duplicate control; tax simulated; no brand data.
7. Run it: prerequisites, environment variables (names), `make setup`, `make dev`, the hosted URL.
8. Tests: layers, how to run them, the sandbox contract tests.
9. Architecture diagram and a pointer to `docs/`.
10. Roadmap: platform approval and multi-seller settlement, partial capture tiers, emergent pools, India-domestic checkout with local providers.

## 6. Devpost fields

Project name and tagline; description (features, who it is for, why it matters); built with (languages, frameworks, PayPal APIs, Claude, Elastic, Zapier MCP, APIMatic, Render); try-it links (hosted URL, repository); video; images (audit page, merchant console, checkout, tracker); tools-used statement (which AI tools or models and how). Copy claims only from `docs/product-spec.md` section 3.

## 7. Final QA checklist (task T11X01)

1. Repository is public; License is detected in About; the README renders; no secret in the diff or history (full-history scan).
2. Clean-clone run works from the README instructions; the hosted URL works logged out.
3. CI is green on `main`; tags `contracts-v1` and `rc1` exist.
4. Video is public, under 3:00, no trademarks or music, labels visible.
5. Devpost text matches the product exactly: every claim is backed by a requirement and a passing test; fallbacks are disclosed.
6. All switches in `docs/decisions.md` section 4 are filled and match the deployed environment.
7. Sponsor trials were active during recording; the README states which parts depend on a trial or plan.
8. Submission saved in PH11; a screenshot of the submission page is stored by the owner.
9. Hosting stays up through judging: `api`, `worker` and Postgres are on paid Render plans (BD-05), not free ones, and the hosted URL is re-opened logged out once a week until the winners are announced.
10. Judge access: the README says how a judge approves a payment (a Sandbox personal buyer account they create, or a dedicated demo buyer whose login is given only through Devpost's private testing-instructions field if it offers one). Sandbox buyer passwords never appear in the repository, README or video; change any password that was ever shown on screen.

## 8. After submission (task T11X02)

Open the repository, license, video and Devpost page while logged out; confirm links; do not push changes that alter the submitted behaviour. Only fixes for infringing or personal-data material are allowed after the deadline.
