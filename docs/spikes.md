# Spikes

A spike is a short, disposable experiment that turns an open gate (G) into a verified fact before the design depends on it. Results go in `docs/spike-results.md`; the switch each spike sets is in `docs/decisions.md` section 4. Spikes may not change product code; they produce evidence only.

Automation: `tools/fairpool_spike_check.py` runs the Sandbox regression, the S2 follow-up and spikes S1, S4 to S13 (S3 optional) and writes a sanitized report; read `docs/spike-check-runbook.md` first. Human steps (buyer approvals, consent) stay manual and are recorded as such.

Status today (Oct 29): S2 and S3 RECORDED (Oct 20). S1, S6, S7, S10, S12 and S13 RECORDED (Oct 28-29, from the owner's Sandbox runs; see `docs/spike-results.md`). S5 and S8 PARTIALLY recorded. S4 and S9 PENDING (S9 needs the Agent API). S11 DEFERRED until the merchant OpenAPI file exists. Two spikes outside the S1 to S13 numbering were also run and recorded: the vault spike (V1 to V10, PASS with limits) and the payouts spike (BLOCKED, 403 PAYOUT_NOT_AVAILABLE). S7 to S13 were added after S3 and the integration review (`docs/decisions.md` section 5).

| Spike | Gate | Owner | Task | Due at gate | Needs the owner's hands | Sets |
|---|---|---|---|---|---|---|
| S1 | G1, G2 | Member B | T00B02 | IG-0 | Buyer consent on PayPal | `DEDUPE_MODE` |
| S2 | G3 | Member A | T01A04 (follow-up; main result recorded Oct 20) | IG-1 | none | `PAYMENT_MODE`, `AUTHORIZE_USE_REQUEST_ID` (recorded) |
| S3 | G4, G9 | Member A | recorded Oct 20 | done | none | `PAYMENT_ROUTER`, `PLATFORM_FEE_ENABLED` (recorded) |
| S4 | G8 | Member A | T02A04 | IG-2 | Buyer approval | `PAYPAL_PAYLOAD_LEVEL` |
| S5 | G5 | Member A | T03A03 | IG-3 | Public URL, buyer approval | `WEBHOOKS_ENABLED` |
| S6 | G6 | Member B | T01B04 | IG-1 | Creating sandbox accounts | `BEACON_MODE`, buyer count |
| S7 | G11 | Member B | T00B03 | IG-0 | Buyer approval | `PAYMENT_ROUTER` choice |
| S8 | G12 | Member B | T02B04 | IG-2 | Creating the Elastic project | `SEARCH_BACKEND` |
| S9 | G13 | Member B | T08B03 | IG-8 | Zapier trial and client connection | `ZAPIER_BRIDGE` |
| S10 | G14 | Member A | T03A04 | IG-3 | Connecting an AI client | `PAYPAL_MCP_VERIFICATION` |
| S11 | G15 | Member B | T03B05 | IG-3 | APIMatic trial | SDK generation outcome |
| S12 | G16 | Member A | T03A05 | IG-3 | Buyer approval for a capture | `SHIPMENT_TRACKING_ENABLED` |
| S13 | G17 | Member B | T02B05 | IG-2 | Buyer approval | `PAYPAL_APPROVAL_UI`, `PAYPAL_SDK_AUTH` |

Each spike must be recorded by its due gate; the gate's integration test (`docs/testing-strategy.md` section 3) checks it.

## Safe-run preamble (paste at the start of any spike prompt)

> Test PayPal **Sandbox only**: `api-m.sandbox.paypal.com` and `www.sandbox.paypal.com`; never call a live endpoint. Read credentials only from process-scoped environment variables or a local `.env` that is git-ignored. Never print or store tokens, secrets, `PayPal-Auth-Assertion` values, buyer passwords, full approval URLs or full payment details. Keep only sanitized facts: HTTP status, PayPal issue name, selected field names, amount, currency, debug ID. Use USD 1.00 for every payment test. If an unexpected capture or payout appears, stop, verify and clean up. Finish with one table (step, HTTP status, PayPal status or issue, debug ID, PASS or FAIL) and one line stating what the result implies for FairPool, then remind the owner to rotate shared Sandbox secrets.

## S1: Log in with PayPal (G1, G2)

1. In the Sandbox app's Log in with PayPal settings, register a web return URL (the callback in `PAYPAL_LOGIN_REDIRECT_URI`), not a native-app URL.
2. Build the authorization request with scope `openid`, a `state` and a `nonce`. (The account-attributes scope `https://uri.paypal.com/services/paypalattributes` was rejected with `invalid_scope` on Oct 28; retry it only as an optional diagnostic after the app's permissions change.)
3. Complete consent as a US personal sandbox buyer. Exchange the code server-side and call userinfo.
4. Record: scope accepted yes or no; which identifier fields are present (`sub`, `user_id`, `payer_id`; never record the values).
5. With the same buyer, approve a USD 1.00 AUTHORIZE order and compare each raw userinfo identifier with the order's `payer_id` by comparing their HMACs locally (never strip prefixes to force a match). Record equal or different.

Rule: scope accepted and IDs equal gives `DEDUPE_MODE=full`; accepted but different gives `two_keys`; failure gives `checkout_only` and `REQUIRE_PAYPAL_LINK=false`. If it fails with `invalid_scope`, record the full request shape (scopes, encoded request, registered return URL) so the cause is found, not guessed (FR-PP-02).

Recorded Oct 28: the request with the account-attributes scope returned `invalid_scope`; the diagnostic retry with `openid` only worked (code, token exchange 200, userinfo 200 with fields `sub` and `user_id`). The raw userinfo `user_id` and the checkout `payer_id` differed. Result: `DEDUPE_MODE=two_keys`, login scope `openid` only. Do not strip prefixes to force the two to match.

## S2: authorization capture (G3). RECORDED

Steps and results are in `docs/spike-results.md`. Outcome: `PAYMENT_MODE=authorize_capture`; authorize honours the request ID; void does not replay. Open questions O1 and O2 remain there.

## S3: second seller (G4, G9). RECORDED

Outcome: Partner Referrals 403, assertion 401, platform fee 422. Router A is unavailable. See `docs/spike-results.md`.

## S4: payload ladder (G8)

Run in order and stop at the first level PayPal rejects.

1. Level 1: add `custom_id` (a UUID) and `invoice_id` (unique). Replay the same create with the same `PayPal-Request-Id` and the same `invoice_id`; require 200 with the same order and **not** DUPLICATE_INVOICE_ID.
2. Level 2: add `amount.breakdown` (item_total, shipping, tax_total) and `items`; confirm PayPal accepts exactly summing amounts and rejects a mismatch.
3. Level 3: add `payment_source.paypal.experience_context` with return and cancel URLs, pay-now action and a provided shipping address with address changes disabled. Have the buyer open the approval page and confirm the address cannot be changed; GET the order and confirm the shipping address is returned.

Record the highest accepted level. Level 4 is unavailable (S3).

## S5: webhooks (G5)

1. Requires the deployed skeleton (task T01A03) with a public HTTPS listener on port 443 that stores the raw body and headers of each request.
2. Register the listener in the Sandbox app for the seven V7 event types.
3. Run a real lifecycle: create, approve, authorize, capture, refund, and a second order authorize then void. Confirm each event type arrives.
4. Verify each signature with PayPal's verify-webhook-signature call and the registered webhook ID; record SUCCESS or the failure reason.
5. Redeliver or replay one event to confirm de-duplication by event ID. Send one simulator event and record whether it verifies (P4 says simulator events are mock).

Rule: verified real events give `WEBHOOKS_ENABLED=true` for those event types; otherwise the reconciler is the only update path. Judge each event type separately: an all-types gate hides what worked.

Recorded Oct 28 (partial): authorization-created, capture-completed and capture-refunded arrived and verified; a resend delivered the same event ID twice; the simulator event arrived and verified (mock evidence); `CHECKOUT.ORDER.APPROVED` did not arrive within four minutes; void, pending and denied were not produced. Approval is therefore always confirmed by GET.

## S6: beacon and sandbox buyers (G6)

1. Choose a drand HTTP endpoint and chain; fetch the latest round, verify its signature, and record chain hash, round period and one randomness value.
2. Compute the announced round for a future time (`close_at + beacon_delay_s`) and confirm the round exists once that time passes.
3. Create six US personal sandbox buyer accounts with "Create bulk accounts" (the dashboard currently shows one US personal buyer and an India business and personal account). Log into each once and confirm it can approve a USD 1.00 order.

Rule: working drand gives `BEACON_MODE=drand`; otherwise `demo`, labelled. Record the buyer count (D11 target: six).

## S7: payee-email routing (G11), added after S3

Question: S3 showed order **creation** succeeds for a second business account's email. Does approval and authorization?

1. Create an AUTHORIZE order of USD 1.00 whose payee is the second sandbox business account (`payee.email_address` only, no assertion).
2. Have a US sandbox buyer approve it; GET the order and record the payee fields shown.
3. Authorize it; record status and debug ID; then void it.
4. Control: repeat with a payee email that is not a sandbox account and record the failure mode.

Rule: all steps pass means the owner may choose `PAYMENT_ROUTER=payee_email` for the demo (labelled sandbox-only, never described as marketplace settlement or production routing). Any failure keeps `single_seller`. Either way, record the result before gate IG-0. Add to step 3: void **and** fully refund a captured payment for that payee; a payee the app cannot void or refund is not usable.

Recorded Oct 28: the separately selected seller could receive captures, but void and refund returned `PERMISSION_DENIED`. `payee_email` is rejected; `single_seller` (the business account that owns the app) is final.

## S8: Elastic hybrid search (G12), INT-1

Official reference: Elastic docs, "Hybrid search with `semantic_text`". Timing: by gate IG-2.

1. Create an Elastic Cloud Serverless (Elasticsearch) trial project (14-day trial, extendable by 30 days per the hackathon brief; start it no earlier than the end of PH1 so the extension covers judging) or note why a local container is used instead. Create an API key limited to the fairpool index.
2. Decide the inference endpoint (the project's default Elastic Inference Service endpoint, or a Jina endpoint if the sponsor perk is used) and create it explicitly so the mapping can name an `inference_id`.
3. Create the index from `docs/contracts/ai-schemas.md` section 7: `content` text copied into `content_embedding` of type `semantic_text`.
4. Index about 20 public pool and lot documents (generic products only).
5. From Python, run the hybrid `rrf` query (match on `content` plus `semantic` on `content_embedding`) with a status filter, and a semantic-only query. Run ten messy queries ("a big 4k screen for my desk") and record whether the expected pool is in the top five.
6. Run the same ten queries against the Postgres `pg_trgm` fallback and record the difference.

Record: exact request shapes accepted (and any difference from the contract), inference endpoint used, ingest and query latency, trial start and end dates. Rule: queries work and top-five recall is at least as good as the fallback gives `SEARCH_BACKEND=elastic`; otherwise `postgres` stays and the README says so.

## S9: Zapier MCP managed mode (G13), INT-2

Official reference: docs.zapier.com/mcp (how tools work, switch modes, quickstart). Timing: during PH8, after the Agent API exists (task T07A05), by gate IG-8; start the Zapier trial in PH4 so it covers recording in PH10.

1. Create a Zapier MCP server at mcp.zapier.com and switch it to **managed mode**.
2. Add four Webhooks by Zapier actions (list pools, join pool, list entries, withdraw entry) with URL and `Authorization` header locked to the deployed Agent API and a delegation token (low cap, short expiry). Leave only body and query fields to the AI.
3. Connect an AI client (Claude custom connector or Claude Desktop) over Streamable HTTP. Confirm the tool list shows exactly the four tools and no discover or enable meta-tools.
4. Run: list pools, join with `max_total_usd`, list entries, withdraw. Confirm the locked URL and header cannot be changed by prompt.
5. Record whether the idempotency key is accepted from the body (`idempotency_key`), the task usage per call, and the exact trial expiry date.

Rule: all four tools work in managed mode gives `ZAPIER_BRIDGE=managed`. If Webhooks by Zapier cannot be locked or exposed as tools, record the reason; the FairPool MCP server (INT-3) remains the agent path and the README says the Zapier bridge was not demonstrated.

## S10: PayPal MCP read-only verification (G14), INT-6

Official reference: developer.paypal.com/ai-tools/mcp-server and the Agent tools reference. Timing: by gate IG-3.

1. Connect an AI client to the hosted sandbox MCP server (`https://mcp.sandbox.paypal.com`, SSE or HTTP, bearer credentials) or run `@paypal/mcp` with a Sandbox access token. Record the tool list.
2. Find out whether tools can be restricted to a read-only allowlist (the quickstart shows `--tools=all`; test subset values and the hosted server's options). Record the exact mechanism or that none exists.
3. With a captured order from the S2 flow, ask the client to look the order up with the get-order tool; record the argument name it needs and whether the capture amount is returned.
4. Try the list-transactions tool once and record its latency and the Transaction Search permission state; do not depend on it.

Rule: a proven read-only allowlist gives `PAYPAL_MCP_VERIFICATION=paypal_read_subset`; otherwise `fairpool_tool`. A tool call counts as successful only if the reply's own `ok` field is true, not merely because `isError` is unset.

Recorded Oct 28: hosted `/http` returned 404; hosted `/sse` listed tools but `get_order` failed with the code PAYPAL_API_SETUP_ERROR (`ok=false`, `isError` unset); the local official server restricted to five read tools read a known order and matched REST. Result: `paypal_read_subset` for the local, pinned server, inspection only.

## S11: APIMatic SDK and portal generation (G15), INT-4

Official reference: apimatic.io/pricing, docs.apimatic.io (generating SDKs, CLI), Context Plugins. Timing: by gate IG-3. Start the 14-day trial (Business features) in **PH3, not earlier**, so it also covers the final SDK generation in PH10 (task T10A04); the OpenAPI document must already exist (task T01B01).

1. Export `/merchant-api/v1/openapi.json` from the FastAPI sub-application (OpenAPI 3.1). Confirm it contains exactly the ten operations of `api.md` section 4.3 with the fixed operationIds.
2. Import it into APIMatic (or the CLI), validate, and fix warnings by editing our schemas, not the SDK.
3. Generate Python and TypeScript SDKs and the developer portal. Run a smoke script with the Python SDK against a local API: list lots, submit a bid, read progress.
4. Read APIMatic's terms for ownership and licensing of generated code and record the result; confirm the SDKs may be committed to a public MIT repository.
5. Install the ContextMatic plugin for PayPal in a coding agent and ask one PayPal Orders question to confirm it responds.

Record: endpoint count, plan or trial used and its end date, whether OpenAPI 3.1 imported directly or needed conversion, licensing result. Rule: SDKs generated and smoke test passing, committed under `sdk/`; if generation fails, record why and ship the OpenAPI document and a hand-written minimal client labelled as such.

## S12: PayPal shipment tracking (G16), INT-8

Official reference: the Agent tools reference (shipment tracking tools) and PayPal's Shipment Tracking API docs. Timing: by gate IG-3.

1. Using a captured sandbox transaction (from the S2 flow), call `POST /v2/checkout/orders/{order_id}/track` with the capture ID, a tracking number and a carrier (fictional carrier and `notify_payer=false` in tests). Record status and any error. (`POST /v1/shipping/trackers-batch` returned 403 for this app and is not used.)
2. GET the order and confirm exactly one matching tracker; repeat the request and record whether it stays one.
3. Check what a buyer or merchant can see in the sandbox.

Rule: success gives `SHIPMENT_TRACKING_ENABLED=true`; otherwise tracking is stored in FairPool only and labelled.

Recorded Oct 28: Orders v2 track returned 201, GET showed one tracker, the repeat returned 200 with one tracker; the capture was then refunded and confirmed. Not established: dashboard visibility, real carrier updates, seller protection, delivery.

## S13: JavaScript SDK v6 approval (G17), INT-7

Official reference: developer.paypal.com/sdk/js/set-up. Timing: by gate IG-2.

1. Serve a minimal page over HTTPS (the deployed skeleton) that loads `https://www.sandbox.paypal.com/web-sdk/v6/core` and calls `paypal.createInstance` with the client ID, components `["paypal-payments"]` and page type `checkout`. If this fails, repeat with a client token obtained as in `paypal-adapter.md` section 12.
2. Call `findEligibleMethods({currencyCode: "USD"})` and render `<paypal-button>`.
3. `session.start({presentationMode: "auto"}, createOrder())` where `createOrder` calls a scratch server that creates a USD 1.00 **AUTHORIZE** order and returns `{orderId}`.
4. Approve with a US sandbox buyer. Record the exact `onApprove` argument fields. On the server GET the order, authorize it (S2 endpoint) and void it.
5. Test cancel (`onCancel`) and a blocked popup (`presentationMode: "auto"` fallback).

Record: which initialisation worked (client ID or client token), the approval callback fields, any console errors. Rule: works gives `PAYPAL_APPROVAL_UI=sdk_popup` and the working `PAYPAL_SDK_AUTH`; otherwise `redirect` stays and the README says so.

Recorded Oct 28: client-ID initialisation worked on localhost; a client token for `localhost` returned 401 `invalid_domain` but worked for the owner's public tunnel hostname (900 s token). On that HTTPS tunnel, eligibility, order creation, approval, server validation, authorize and void passed; callback fields were `fundingSource`, `orderId`, `payerId`; a cancelled checkout fired `onCancel` and GET showed `CREATED` with no authorization or capture. The blocked-popup fallback is user-attested. Earlier harness failures in the first run were harness defects, not PayPal failures.
