# FairPool spike check report

- Run ID: `932009c0`; date (UTC): 2026-11-02 16:23; script v1.0.0; Python 3.12.16
- Spikes selected: core, s1, s4, s7, s2, s12, s13
- PayPal hosts used: 127.0.0.1 and 127.0.0.1 (Sandbox only; every payment USD 1.00)
- Redaction: no secret, token, password, approval URL, buyer name or email, or account ID value is written here
- Totals: BLOCKED 2, INFO 2, MANUAL 5, PASS 16

## Derived settings (apply the rules in `docs/spikes.md`; the owner confirms before changing `.env.example`)

| Setting or measurement | Value | From |
|---|---|---|
| `PAYPAL_PAYLOAD_LEVEL` | `2` | S4 |
| `SHIPMENT_TRACKING_ENABLED` | `False` | S12 |
| `PAYPAL_APPROVAL_UI` | `redirect` | S13 |

## Results by spike

### PayPal Sandbox regression (V1-V7, checklist 1.x, 6.1, 6.2)

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| host guard: only the two Sandbox hosts are used (checklist 1.1) | - | - | - | PASS | 127.0.0.1, 127.0.0.1 |
| R1 OAuth token (V1, checklist 1.2) | 200 | - | - | PASS | fields=['access_token', 'app_id', 'expires_in', 'nonce', 'scope', 'token_type'] expires_in=32400 scopes=2 |
| R2 create AUTHORIZE order, payee set (V2) | 201 | CREATED | dbg37554b6fb0 | PASS | payee_email=present merchant_id=MISSING (not required) |
| R3 replay create with the same PayPal-Request-Id: 200 and same order (V3, checklist 6.2) | 200 | - | dbgaa5d73e264 | PASS |  |
| R4a authorize before approval -> 422 ORDER_NOT_APPROVED (V4) | 422 | ORDER_NOT_APPROVED | dbga98af11bbe | PASS |  |
| R4b capture before approval is rejected (V4) | 422 | ORDER_NOT_APPROVED | dbg920776c9ce | PASS |  |
| R5 a second order gets a distinct ID (V5) | 201 | - | dbgb084ba16e6 | PASS |  |
| R6 negative test DUPLICATE_INVOICE_ID: 422 and no order created (V6, checklist 6.1) | 422 | DUPLICATE_INVOICE_ID | dbg7fae5c01d7 | PASS |  |
| R7 the seven event types of V7 are listed | 200 | - | dbg63a08e3f07 | PASS | 8 types listed |
| R8 list webhooks | 200 | - | dbg046a374f77 | PASS | 0 listeners registered |
| R9 INR is not a supported currency for Orders v2 (V12; checklist 3.7) | - | - | - | INFO | not re-tested by this script; recorded fact from the earlier run |

**Implication:** The PayPal Sandbox basics the adapter contract relies on (token, create, replay, early-authorize rejection, mock error) behave as recorded.

### S1 Log in with PayPal, scope openid (G1, G2) -> DEDUPE_MODE

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| S1 needs the buyer's consent | - | - | - | MANUAL | --non-interactive |

### S2 follow-up: authorize/capture/void/refund replays, O1, O2

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| S2 follow-up needs two buyer approvals | - | - | - | MANUAL | --non-interactive |

### S4 payload ladder (G8) -> PAYPAL_PAYLOAD_LEVEL

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| Level 1: custom_id and unique invoice_id accepted | 201 | CREATED | dbg2d4396e812 | PASS |  |
| Level 1: replay (same request ID, same invoice_id) returns 200, same order, not DUPLICATE_INVOICE_ID | 200 | - | dbgd7a1213d48 | PASS |  |
| Level 2: breakdown (item_total + shipping + tax_total) and items sum exactly: accepted | 201 | CREATED | dbg021673221a | PASS |  |
| Level 2: a mismatching breakdown is rejected | 422 | AMOUNT_MISMATCH | dbg52698ebd7b | PASS |  |
| create S4-L3 (level 3) | 201 | PAYER_ACTION_REQUIRED | dbgce93dfc622 | PASS |  |
| buyer approval of S4-L3 | - | - | - | MANUAL | --non-interactive: approval skipped |
| Level 3: payment_source.paypal.experience_context + provided address accepted | 201 | PAYER_ACTION_REQUIRED | dbgce93dfc622 | PASS | approval link rel: payer-action |
| Level 3 evidence incomplete (no approval) | - | - | - | MANUAL | level 3 stays unverified; PAYPAL_PAYLOAD_LEVEL=2 |
| highest accepted level (level 4 is unavailable per S3) | - | PAYPAL_PAYLOAD_LEVEL=2 | - | INFO |  |

**Implication:** Orders can carry payload level 2; the adapter must not send anything above it.

### S7 payee-email routing (G11): authorize, void, capture AND refund must all work

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| needs SECOND_SELLER_EMAIL | - | - | - | BLOCKED |  |

### S12 shipment tracking via Orders v2 track (G16) -> SHIPMENT_TRACKING_ENABLED

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| needs a captured sandbox transaction | - | - | - | BLOCKED | no capture available (non-interactive or approval failed) |

### S13 JavaScript SDK v6 approval (G17) -> PAYPAL_APPROVAL_UI, PAYPAL_SDK_AUTH

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| S13 needs a browser and a buyer | - | - | - | MANUAL | --non-interactive |

## Checklist mapping

| Checklist item | What | Covered by |
|---|---|---|
| 0.1 | Rotate the Sandbox secret | manual: do this after the run (see the reminders) |
| 1.1, 1.2 | Sandbox host guard, OAuth scopes | CORE |
| 2.1 to 2.3 | approve, authorize, void | S2 |
| 2.4 to 2.6 | approve, capture, refund | S2 (AUTHORIZE flow re-run; a CAPTURE-intent order is not re-tested) |
| 2.7 | cancel is not paid | S13 (cancel test) |
| 2.8, 3.5, 6.3 | pool rules against PayPal | needs the FairPool application; not covered by this script |
| 3.1 to 3.4, 3.8 | second seller gate | S3 re-probe plus S7 (a second payee is usable only if authorize, void, capture and refund all work; recorded Oct 28: it is not); full onboarding stays blocked while Partner Referrals returns 403 |
| 4.1, 4.2 | Login with PayPal account ID | S1 |
| 4.3 | payer_id only after approval | S1, S2, S4 (approval checks) |
| 5.1, 5.2 | webhook listener, signature, dedupe | S5 |
| 6.1, 6.2 | negative tests, idempotent retries | CORE, S2, S4 |

## Manual confirmations still needed

- none recorded

## After this run

- Rotate the Sandbox app secret now (checklist 0.1), and change any buyer password that was ever shown on screen or pasted anywhere.
- Delete the `.env.spike` file or keep it out of git; never commit it.
- Copy the derived settings and each spike's table into `docs/spike-results.md` and mark the spikes RECORDED in `docs/progress.md`.
