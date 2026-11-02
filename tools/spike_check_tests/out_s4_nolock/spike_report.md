# FairPool spike check report

- Run ID: `f4bdb424`; date (UTC): 2026-11-02 16:23; script v1.0.0; Python 3.12.16
- Spikes selected: core, s4
- PayPal hosts used: 127.0.0.1 and 127.0.0.1 (Sandbox only; every payment USD 1.00)
- Redaction: no secret, token, password, approval URL, buyer name or email, or account ID value is written here
- Totals: FAIL 1, INFO 2, PASS 18

## Derived settings (apply the rules in `docs/spikes.md`; the owner confirms before changing `.env.example`)

| Setting or measurement | Value | From |
|---|---|---|
| `PAYPAL_PAYLOAD_LEVEL` | `2` | S4 |

## Results by spike

### PayPal Sandbox regression (V1-V7, checklist 1.x, 6.1, 6.2)

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| host guard: only the two Sandbox hosts are used (checklist 1.1) | - | - | - | PASS | 127.0.0.1, 127.0.0.1 |
| R1 OAuth token (V1, checklist 1.2) | 200 | - | - | PASS | fields=['access_token', 'app_id', 'expires_in', 'nonce', 'scope', 'token_type'] expires_in=32400 scopes=2 |
| R2 create AUTHORIZE order, payee set (V2) | 201 | CREATED | dbg3ba008d6e3 | PASS | payee_email=present merchant_id=MISSING (not required) |
| R3 replay create with the same PayPal-Request-Id: 200 and same order (V3, checklist 6.2) | 200 | - | dbgb0cfcbc55c | PASS |  |
| R4a authorize before approval -> 422 ORDER_NOT_APPROVED (V4) | 422 | ORDER_NOT_APPROVED | dbgc7530458e7 | PASS |  |
| R4b capture before approval is rejected (V4) | 422 | ORDER_NOT_APPROVED | dbg8674fda6d3 | PASS |  |
| R5 a second order gets a distinct ID (V5) | 201 | - | dbg1468802a9e | PASS |  |
| R6 negative test DUPLICATE_INVOICE_ID: 422 and no order created (V6, checklist 6.1) | 422 | DUPLICATE_INVOICE_ID | dbg912ebf292f | PASS |  |
| R7 the seven event types of V7 are listed | 200 | - | dbg7712c15778 | PASS | 8 types listed |
| R8 list webhooks | 200 | - | dbgfd93c8a6f0 | PASS | 0 listeners registered |
| R9 INR is not a supported currency for Orders v2 (V12; checklist 3.7) | - | - | - | INFO | not re-tested by this script; recorded fact from the earlier run |

**Implication:** The PayPal Sandbox basics the adapter contract relies on (token, create, replay, early-authorize rejection, mock error) behave as recorded.

### S4 payload ladder (G8) -> PAYPAL_PAYLOAD_LEVEL

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| Level 1: custom_id and unique invoice_id accepted | 201 | CREATED | dbg7738820df9 | PASS |  |
| Level 1: replay (same request ID, same invoice_id) returns 200, same order, not DUPLICATE_INVOICE_ID | 200 | - | dbg6880f7b244 | PASS |  |
| Level 2: breakdown (item_total + shipping + tax_total) and items sum exactly: accepted | 201 | CREATED | dbga61a3541af | PASS |  |
| Level 2: a mismatching breakdown is rejected | 422 | AMOUNT_MISMATCH | dbgcf7cbd1bd9 | PASS |  |
| create S4-L3 (level 3) | 201 | PAYER_ACTION_REQUIRED | dbg5cb7447c15 | PASS |  |
| buyer approval of S4-L3 | 200 | APPROVED | dbg3bd92e8cc5 | PASS |  |
| Level 3: payment_source.paypal.experience_context + provided address accepted | 201 | PAYER_ACTION_REQUIRED | dbg5cb7447c15 | PASS | approval link rel: payer-action |
| Level 3: GET order returns the provided shipping address | - | - | - | PASS | address returned=True |
| Level 3: address changes disabled on the approval page (user-attested) | - | - | - | FAIL |  |
| highest accepted level (level 4 is unavailable per S3) | - | PAYPAL_PAYLOAD_LEVEL=2 | - | INFO |  |

**Implication:** Orders can carry payload level 2; the adapter must not send anything above it.

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
