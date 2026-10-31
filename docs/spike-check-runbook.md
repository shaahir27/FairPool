# Spike check runbook

`tools/fairpool_spike_check.py` is one script that runs the Sandbox regression, the S2 follow-up and spikes S1, S4 to S13 (S3 optionally), applies the rules in `spikes.md`, and writes `spike_out/spike_report.md` and `.json`. It talks only to the PayPal Sandbox hosts (it refuses any other PayPal host), moves only USD 1.00 per payment, never writes a secret, token, password, approval URL, buyer name, email or account ID into the report, and at the end voids every leftover authorization and refunds every leftover capture, including after Ctrl-C.

## What you must provide

| # | You provide | Needed for | Where it goes |
|---|---|---|---|
| 1 | PayPal Sandbox app client ID and secret (use the **rotated** secret; checklist 0.1) | everything PayPal | `.env.spike` |
| 2 | `SINGLE_SELLER_EMAIL`: the sandbox business account that owns the app | every order (payee) | `.env.spike` |
| 3 | At least one sandbox **personal US** buyer. Six different ones for S6 (create them in bulk in the dashboard). Use a private window and log out between buyers. | S1, S2, S4, S7, S12, S13 (one); S6 (six) | typed in the browser only, never into the script |
| 4 | `SECOND_SELLER_EMAIL`: a second sandbox business account | S7 | `.env.spike` |
| 5 | Log in with PayPal enabled on the Sandbox app with a **web** return URL, privacy policy URL and user agreement URL registered (scope `openid`; the account-attributes scope was rejected in S1) | S1 | `PAYPAL_LOGIN_REDIRECT_URI` |
| 6 | Negative testing available on the business account (the mock-error header) | core R6 | dashboard |
| 7 | A public HTTPS URL on port 443 that forwards to your machine's port 8787 (a quick tunnel such as Cloudflare or ngrok) | S5 | `WEBHOOK_PUBLIC_URL` |
| 8 | Elastic Cloud Serverless trial project URL and an API key that can create, delete, write and read `fairpool-*` indices and list inference endpoints (if listing is refused, set `ELASTIC_INFERENCE_ID`) | S8 | `.env.spike` |
| 9 | Zapier account on the 14-day Professional trial, an MCP server with the four locked Webhooks by Zapier actions, and its connection token | S9 | ZAPIER_MCP_TOKEN |
| 10 | APIMatic account or trial, `npm install -g @apimatic/cli`, `apimatic auth login`, and the merchant `openapi.json` (task T01B01) | S11 | `OPENAPI_JSON_PATH` |
| 11 | Python 3.10+, `pip install -r tools/spike_check_requirements.txt`, Node 18+ with `npx`, a browser, free ports 8787 and 8788 | all | your machine |
| 12 | About 90 minutes at the keyboard: roughly 17 buyer approvals (S6 six, S2 two, S7 two, S1, S4, S13 and the cancel test) and one consent | the human steps | you |

## How to run

1. `python -m venv .venv && . .venv/bin/activate && pip install -r tools/spike_check_requirements.txt`
2. `cp tools/spike_check.env.example .env.spike` and fill it in.
3. `python tools/fairpool_spike_check.py check-env` shows READY or the exact missing item for every spike. No network calls.
4. `python tools/fairpool_spike_check.py run` runs everything that is ready, in this order: core, S6, (S5 listener starts here), S1, S4, S7, S2 (keeps its capture), S12, S10, S2 refund phase, S13, S8, S9, S11; then S5 is evaluated from the real events the earlier steps produced. It asks before each stage. Add `--only s4,s13`, `--skip s9`, `--with-s3`, `--non-interactive` (human steps recorded as MANUAL) or `--no-confirm` as needed.
5. Send `spike_out/spike_report.md` (it is already redacted). The derived-settings table, each spike's table and the implication lines go into `spike-results.md`.
6. Rotate the Sandbox secret again and change any buyer password that appeared on screen.

## What it does not cover

The vault spike (V1 to V10) and the payouts spike were run by the owner outside this script; their results are in `spike-results.md` (Oct 29 table). The script still tests the authorization-first fallback path.

## What it cannot do yet (it reports BLOCKED, not PASS)

- S9 live calls need the deployed Agent API (T07A05); until then it checks the tool list (exactly four tools, no meta-tools, no URL or header exposed), and the task usage, trial expiry, locked-URL override and idempotency stay in "Manual confirmations".
- S11 SDK smoke test needs the running API; the script checks the OpenAPI document (3.1, exactly the ten operations), runs the APIMatic CLI, checks that both generated SDKs expose all ten operations and that the Python files compile.
- S13 runs a local page on `http://localhost` unless you set S13_PUBLIC_URL to an https tunnel to port 8788; a client token needs that public hostname (`localhost` returns 401 `invalid_domain`). The deployed page is rechecked in task T02B05.
- S3 full onboarding stays blocked while Partner Referrals returns 403 (`--with-s3` re-probes it).
- Checklist 2.8, 3.5 and 6.3 need the FairPool application itself.

## How far the script itself is verified (read this)

Verified: the script's logic runs end to end against local mock servers (PayPal, Elastic, drand, MCP) with no unexpected failures and no leaked values (the mocks were written from the docs, so they prove the script's logic, not PayPal's behaviour; the owner's Oct 28 Sandbox runs are the live evidence, and the script was updated to match them); the MCP clients work against the official MCP SDK 1.x and 2.x; the drand check verifies the real published quicknet round 1000 and rejects a tampered one; the S10 allowlist probe was run against the real `@paypal/mcp` package. Not verified: it has never been run against live PayPal, Elastic, Zapier or APIMatic services, and the S13 page has not been run in a real browser. Two rows are expected to FAIL on the recorded behaviour: S7's void and refund for a second seller (`PERMISSION_DENIED`). A first-run FAIL can therefore be a real finding or a mismatch between the script and a live service; check the HTTP status and issue name in the row before deciding. Rows marked "user-attested" are your confirmation, not machine evidence.

Optional self-test of the script: `pip install "mcp<2"` then `python tools/spike_check_tests/test_branches.py` and `test_end_to_end.py` (set MCP_REF_PYTHON to a Python with `mcp<2`).
