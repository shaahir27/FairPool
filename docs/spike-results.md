# Spike results

Living file. One section per spike. Record sanitized facts only: HTTP status, PayPal status or issue name, field names, amounts, debug IDs. Never record secrets, tokens, assertion values, passwords, full approval URLs or full payment details. When a spike is recorded, update the switch in `docs/decisions.md` section 4 in the same pull request.

Status: RECORDED, PARTIAL, PENDING or DEFERRED.

## S2: authorization capture and idempotency (G3). RECORDED Oct 20, 2026

Run by the owner's local agent against the PayPal Sandbox only, USD 1.00 per test, the captured payment fully refunded afterwards.

| Step | HTTP | PayPal status or issue | Result |
|---|---|---|---|
| Create AUTHORIZE order 1 (Prefer: return=representation) | 201 | CREATED | PASS |
| GET order 1 after buyer approval | 200 | APPROVED; payer country US; payee shown as a merchant ID; amount USD 1.00 | PASS |
| Authorize order 1 | 201 | COMPLETED (see open question O1) | PASS |
| Replay authorize with the same PayPal-Request-Id | 200 | same result, idempotent | PASS |
| Capture the authorization | 201 | COMPLETED | PASS |
| GET capture | 200 | COMPLETED | PASS |
| Replay capture with the same request ID | 200 | COMPLETED; single capture confirmed | PASS |
| Full refund of the capture | 201 | COMPLETED | PASS |
| GET refund | 200 | COMPLETED | PASS |
| Replay refund with the same request ID | 200 | COMPLETED | PASS |
| Authorize order 2 | 201 | COMPLETED (see O1) | PASS |
| Void the authorization | 200 | VOIDED, with a body | PASS |
| Replay void with PayPal-Request-Id | 422 | UNPROCESSABLE_ENTITY | PASS (behaviour recorded) |
| Replay void without PayPal-Request-Id | 422 | UNPROCESSABLE_ENTITY | PASS (behaviour recorded) |
| Capture after void | 422 | AUTHORIZATION_VOIDED | PASS |

**Findings**

1. G3 passed: authorize, then capture the authorization, then refund works end to end. `PAYMENT_MODE=authorize_capture`.
2. Authorize honours `PayPal-Request-Id` on replay (200, same result): `AUTHORIZE_USE_REQUEST_ID=true`.
3. Void does **not** replay: a second void returns 422 whether or not a request ID is sent. Void is therefore GET-before-act. A 422 on void is treated as already voided only after a GET shows the authorization VOIDED.
4. Void returned 200 with a body (observed), consistent with V8; handle 204 too (P2).
5. Capturing a voided authorization returns 422 AUTHORIZATION_VOIDED, so a void is effective and a later capture cannot succeed.
6. After approval, GET order showed the payee as a merchant ID. V2 observed no `payee.merchant_id` on the create response. Verify the payee by whichever of email or merchant ID is present, require at least one to match, and reject any that is present and mismatched. Never require merchant ID to be present (checklist 3.4).

**Open questions from S2**

- O1: The report lists the authorize response status as COMPLETED. V8 noted the **order** status reads COMPLETED after authorize or void. Confirm which field was read. The contract reads the authorization object's own status (`purchase_units[0].payments.authorizations[0].status`) and expects `CREATED`. If the authorization object itself reads something else, record the exact value here before task T04A02 hardens the guard. The final verification checklist (items 2.2 and 2.3) recorded the authorization status as `CREATED` and the order status as `COMPLETED` in the Oct 20 AUTHORIZE run; the S2 record still has to say which field its COMPLETED came from.
- O1 resolution (recorded Oct 27, 2026 from the final verification checklist, items 2.2 and 2.3): the authorization object's own status was `CREATED` and the **order** status was `COMPLETED` after authorize and after void. So the COMPLETED in the table above is the order status and the contract's rule is correct: never read the order status as a payment signal; the authorization object must read `CREATED`. Task T01A04 still re-confirms this in code against the Sandbox.
- O2: Record the exact issue name in the void replay 422 body (the report shows only the error name UNPROCESSABLE_ENTITY).

## S3: second seller via Partner Referrals (G4, G9). RECORDED Oct 20, 2026

| Step | HTTP | PayPal status or issue | Result |
|---|---|---|---|
| Partner Referrals onboarding and consent | 403 | NOT_AUTHORIZED | FAIL |
| Create AUTHORIZE order to the second seller, no assertion (control) | 201 | CREATED; payee email shown; merchant_id MISSING | PASS (creation only) |
| Create AUTHORIZE order with PayPal-Auth-Assertion | 401 | invalid_subject | FAIL |
| Platform fee on the purchase unit (control) | 422 | UNSUPPORTED_PAYMENT_INSTRUCTION | FAIL |
| Create order to a non-onboarded payee (control) | 201 | CREATED | PASS (creation only) |

**Findings**

1. G4 failed: this Sandbox app has no partner or marketplace permission, so Router A (platform multi-seller) is unavailable. Under DEP-4 the labelled fallback applies: `PAYMENT_ROUTER=single_seller`.
2. G9 failed: platform fee is unsupported. `PLATFORM_FEE_ENABLED=false`; revenue is roadmap text (D9 resolved).
3. Order **creation** succeeds for another payee email, but creation proves nothing about approval or authorization. That is the open question spike S7 answers.
4. No change to payload ladder expectations: level 4 (assertion and platform fee) is unavailable.

## S7: payee-email routing to a second sandbox business account (G11). RECORDED Oct 28, 2026

Added after S3. See `docs/spikes.md`. Decision rule: if approve, authorize and void succeed for an order whose payee is the second business account by email alone, the owner decides whether the demo uses `PAYMENT_ROUTER=payee_email` (labelled sandbox-only). If it fails, `single_seller` stays.

**Result (RECORDED Oct 28, 2026).** The separately selected seller could receive captures, but void and refund returned `PERMISSION_DENIED`. Partner Referrals returned 403. `payee_email` is rejected; `PAYMENT_ROUTER=single_seller` is final. No further PayPal calls are needed for PH0.

## S1: Log in with PayPal (G1, G2). RECORDED Oct 28, 2026

Record: scope accepted yes or no; account ID present in userinfo yes or no; equal to the approved order's payer_id yes or no. Then set `DEDUPE_MODE`.

**Result (RECORDED Oct 28, 2026).** The account-attributes scope was rejected with `invalid_scope`; `openid` only worked (code and token exchange 200, userinfo 200 with `sub` and `user_id`). The raw userinfo `user_id` and the checkout `payer_id` differ, so no prefix stripping is used. `DEDUPE_MODE=two_keys`. Limits: this does not prove one human per account and does not prove cross-app portability.

## S4: payload ladder (G8). PENDING

Record the highest accepted level: custom_id and invoice_id replay (level 1), breakdown with items (level 2), experience_context with provided address locked (level 3). Then set `PAYPAL_PAYLOAD_LEVEL`.

## S5: webhook listener (G5). PARTIAL Oct 28, 2026

Record: public HTTPS listener reachable on 443; real lifecycle events received; signature verification result; duplicate delivery handling. Then set `WEBHOOKS_ENABLED`.

## S6: beacon and sandbox buyers (G6). RECORDED Oct 29, 2026

Record: beacon endpoint and chain used, round period, a verified round value; number of US personal sandbox buyer accounts created (target six, D11). Then set `BEACON_MODE`.

## S8: Elastic hybrid search (G12). PARTIAL Oct 28, 2026

Record: request shapes accepted, inference endpoint, latencies, top-five recall against the Postgres fallback, trial dates. Then set `SEARCH_BACKEND`.

## S9: Zapier MCP managed mode (G13). PENDING

Record: tool list shown to the client, locked fields confirmed, idempotency key handling, task usage per call, trial expiry date. Then set `ZAPIER_BRIDGE`.

## S10: PayPal MCP read-only verification (G14). RECORDED Oct 28, 2026

Record: tool list, allowlist mechanism or its absence, get-order argument name and output, list-transactions latency and permission state. Then set `PAYPAL_MCP_VERIFICATION`.

## S11: APIMatic SDK and portal generation (G15). DEFERRED

Record: endpoint count, plan or trial and end date, OpenAPI 3.1 import result, generated languages, smoke-test result, licensing of generated code, ContextMatic plugin check.

## S12: PayPal shipment tracking (G16). RECORDED Oct 28, 2026

Record: request and response status, per-item errors, read-back result, idempotency, what buyer or merchant can see. Then set `SHIPMENT_TRACKING_ENABLED`.

## S13: JavaScript SDK v6 approval (G17). RECORDED Oct 28, 2026

Record: which initialisation worked (client ID or client token), `onApprove` fields, cancel and blocked-popup behaviour, console errors. Then set `PAYPAL_APPROVAL_UI` and `PAYPAL_SDK_AUTH`.


## Owner Sandbox runs, recorded Oct 28, 2026 (from `FAIRPOOL_BUILD_HANDOFF.md`)

These are results from real PayPal Sandbox calls and browser actions by the owner (USD 1.00 payments, no production endpoint). They qualify integrations and accounts; they do not test a FairPool application, which does not exist yet. Where a generated report and this section disagree, this section wins. Evidence files are listed in the handoff and are not part of this folder.

| Spike | Recorded result | Switch it sets | Not established |
|---|---|---|---|
| S1 Login | Account-attributes scope: `invalid_scope`. `openid` only: code, token exchange 200, userinfo 200 (fields `sub`, `user_id`). Same buyer's checkout: US, expected payee and amount, a `payer_id`. Raw `user_id` and `payer_id` differ | `DEDUPE_MODE=two_keys`; login scope `openid` | One person per account; cross-login stability; cross-app portability |
| S2 follow-up | AUTHORIZE, capture, full refund and authorize/void work for the app-owning seller. `order.status=COMPLETED` after authorize is not payment; check the capture, and a completed refund reverses it. Resource-specific idempotency keys retained | unchanged | O2 void-replay issue name not restated in the handoff |
| S5 webhooks | Verified: authorization-created, capture-completed, capture-refunded. Resend delivered the same event ID twice. Simulator verified (mock). Order-approved not delivered in 4 minutes. Temporary webhook removed (204) | `WEBHOOKS_ENABLED` per type, GET stays authoritative | Void, pending, denied; why approval was absent |
| S6 | Public beacon signature checks succeeded | `BEACON_MODE` (owner flips when complete) | Six distinct buyer approvals (pending) |
| S7 routing | A separate seller received captures; void and refund returned `PERMISSION_DENIED`. Partner Referrals 403 | `PAYMENT_ROUTER=single_seller`, `payee_email` rejected | Marketplace routing, fees, assertion |
| S8 | Hybrid search over sample data succeeded | `SEARCH_BACKEND` stays `postgres` until compared | FairPool matching; comparison with the fallback |
| S9 | Zapier MCP authentication succeeded | `ZAPIER_BRIDGE=off` | The four actions (need the Agent API) |
| S10 MCP | Hosted `/http` 404; hosted `/sse` lists tools, `get_order` returns `ok=false` the code PAYPAL_API_SETUP_ERROR with `isError` unset. Local `@paypal/mcp` 1.8.1 on toolkit 1.11.0 with five read tools read a known order and matched REST | `PAYPAL_MCP_VERIFICATION=paypal_read_subset` (local, inspection only) | The other four read tools were listed, not exercised; a read-only token |
| S11 | Deferred: no merchant API or OpenAPI file exists; do not fabricate a spec | SDK outcome open | Everything |
| S12 tracking | Orders v2 `POST .../track`: 201, GET shows one tracker, repeat 200 still one. Legacy batch endpoint 403. Capture refunded and confirmed | `SHIPMENT_TRACKING_ENABLED=true` | Dashboard visibility, carrier updates, delivery |
| S13 SDK v6 | Client ID worked on localhost. Client token: localhost 401 `invalid_domain`, public tunnel hostname 200. On the tunnel: eligibility, create, approve, server validation, authorize, void passed; cancel fired `onCancel`, order stayed `CREATED`. Blocked-popup fallback user-attested | `PAYPAL_APPROVAL_UI=sdk_popup`, `PAYPAL_SDK_AUTH=client_id` (T02B05 repeats approval with client ID on the deployed page) | Fastlane; production approval |

Cleanup facts: two earlier captures hit by failed void/refund attempts were refunded manually; later captures were refunded and confirmed by API. The handoff's harness fixes (approval emitted only after authorize and void finish, callbacks accepted only for orders the harness created, order identity in the authorize idempotency key, client-token form fields encoded correctly, pending refunds read rather than resubmitted under a new key) are test-run protections; production needs durable operation records and reconciliation after crashes.

Still open with no code needed: the six-buyer run. Everything else open needs the FairPool application, the Agent API or the merchant API.


## Final available Sandbox verification, recorded Oct 29, 2026 (from the owner's report of the same date)

The report separates completed tests from configuration blockers and unbuilt behaviour; it does not certify production readiness. Where it differs from the Oct 28 table above, this section wins.

| Capability | Result | Boundary |
|---|---|---|
| Authorize, capture, refund, void (app-associated seller) | PASS | Actual lifecycle calls and GETs |
| S6 six distinct US buyer accounts | PASS | Six USD 1.00 orders APPROVED, six distinct payer IDs, no authorization or capture; accounts, not six humans |
| S1 basic Login | PASS | Two sign-ins returned matching opaque identifiers for the tested account and app; not one human per account, not cross-app portability |
| Account-attributes Login scope | BLOCKED | Earlier `invalid_scope`; needs fresh app configuration and consent |
| S13 SDK v6 | PASS | Client-ID flow and public-domain client-token flow; blocked-popup fallback user-attested |
| Vault saving and off-session charging | PASS with limits | Merchant-scoped; 16 completed USD 1.00 captures, all refunded and refunds GET-confirmed; no token portability to another seller |
| Deleted or revoked saved permission | PASS with limits | Later order attempts rejected with a generic 403 PERMISSION_DENIED; token-specific cause not diagnosed |
| Vault consent screen | PASS for observation | Merchant and future-payment wording seen, **no purchase amount visible**; final setup GET failed, cancellation status unknown; no exchange or charge in that inspection |
| Real low-balance off-session decline | BLOCKED | The buyer was asked to add funding during setup; no off-session decline reached |
| Simulated funding decline | PASS (simulated) | Negative-testing header gave 422 INSTRUMENT_DECLINED; order stayed unpaid |
| Natural setup-token expiry | NOT TESTED | Needs elapsed time |
| Orders v2 tracking | PASS | Create, read and retry; fictional tracking is not delivery proof |
| Webhooks | PASS for a subset | Real authorization, capture, refund and vault token events verified; order-approved not observed in the window |
| Local PayPal MCP | PASS for tested reads | Known order and refund matched REST; dispute list returned zero cases |
| MCP single dispute and shipment reads | NOT TESTED | No existing dispute or compatible tracking identifier; none fabricated |
| Hosted PayPal MCP business read | FAIL | Order tool returned PAYPAL_API_SETUP_ERROR; local MCP and REST work |
| Second seller: onboarding, assertion, lifecycle, platform fee | BLOCKED | Partner Referrals 403 NOT_AUTHORIZED; needs a configured Sandbox Platform app and seller consent |
| Payouts | BLOCKED | First create returned 403 PAYOUT_NOT_AVAILABLE; stopped as required; completion, item reads and replay controls not reached |
| Elastic and public randomness | PASS (sample integration) | Sample search and beacon verification only |
| Zapier actions and APIMatic | BLOCKED | The Agent API, merchant API and OpenAPI file do not exist |
| AI, auction, allocation, waitlist, concurrency | NOT TESTED | The FairPool application is not built |

Cleanup facts: all 16 vault captures were refunded and the three exchanged payment tokens deleted; this phase created no new capture; some approved-but-unpaid orders and unapproved temporary setup tokens remain (no money reserved). Production eligibility, real settlement, inventory, delivery and commercial and legal permissions are unverified. Rotate shared Sandbox secrets after testing.
