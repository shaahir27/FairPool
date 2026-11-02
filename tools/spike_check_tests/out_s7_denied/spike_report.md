# FairPool spike check report

- Run ID: `6d6eccbd`; date (UTC): 2026-11-02 16:23; script v1.0.0; Python 3.12.16
- Spikes selected: core, s7
- PayPal hosts used: 127.0.0.1 and 127.0.0.1 (Sandbox only; every payment USD 1.00)
- Redaction: no secret, token, password, approval URL, buyer name or email, or account ID value is written here
- Totals: FAIL 3, INFO 4, PASS 23

## Derived settings (apply the rules in `docs/spikes.md`; the owner confirms before changing `.env.example`)

| Setting or measurement | Value | From |
|---|---|---|
| `S7_payee_email_eligible` | `False` | S7 |

## Results by spike

### PayPal Sandbox regression (V1-V7, checklist 1.x, 6.1, 6.2)

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| host guard: only the two Sandbox hosts are used (checklist 1.1) | - | - | - | PASS | 127.0.0.1, 127.0.0.1 |
| R1 OAuth token (V1, checklist 1.2) | 200 | - | - | PASS | fields=['access_token', 'app_id', 'expires_in', 'nonce', 'scope', 'token_type'] expires_in=32400 scopes=2 |
| R2 create AUTHORIZE order, payee set (V2) | 201 | CREATED | dbg1c33892408 | PASS | payee_email=present merchant_id=MISSING (not required) |
| R3 replay create with the same PayPal-Request-Id: 200 and same order (V3, checklist 6.2) | 200 | - | dbgcd7eb5af5c | PASS |  |
| R4a authorize before approval -> 422 ORDER_NOT_APPROVED (V4) | 422 | ORDER_NOT_APPROVED | dbgcf8c35be6d | PASS |  |
| R4b capture before approval is rejected (V4) | 422 | ORDER_NOT_APPROVED | dbg4c1acef8ab | PASS |  |
| R5 a second order gets a distinct ID (V5) | 201 | - | dbg368f39826d | PASS |  |
| R6 negative test DUPLICATE_INVOICE_ID: 422 and no order created (V6, checklist 6.1) | 422 | DUPLICATE_INVOICE_ID | dbg1018d2f100 | PASS |  |
| R7 the seven event types of V7 are listed | 200 | - | dbgf1954e3638 | PASS | 8 types listed |
| R8 list webhooks | 200 | - | dbgb4afe2dbd4 | PASS | 0 listeners registered |
| R9 INR is not a supported currency for Orders v2 (V12; checklist 3.7) | - | - | - | INFO | not re-tested by this script; recorded fact from the earlier run |

**Implication:** The PayPal Sandbox basics the adapter contract relies on (token, create, replay, early-authorize rejection, mock error) behave as recorded.

### S7 payee-email routing (G11): authorize, void, capture AND refund must all work

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| create S7-A second-seller payee (authorize then void) (level 0) | 201 | CREATED | dbgb48d9df593 | PASS |  |
| buyer approval of S7-A second-seller payee (authorize then void) | 200 | APPROVED | dbg7569cb069c | PASS |  |
| check after approval: status APPROVED and intent AUTHORIZE | - | - | - | PASS | status=APPROVED intent=AUTHORIZE |
| check after approval: currency USD and amount 1.00 | - | - | - | PASS | USD 1.00 |
| check after approval: payee present and matches (merchant ID reported as missing, never required) | - | - | - | PASS | email=present merchant_id=MISSING |
| check after approval: payer country US | - | - | - | PASS | country=US |
| GET order payee fields (what PayPal shows) | - | - | - | INFO | payee_email=present merchant_id=MISSING; matches second seller=True |
| authorize (S7-A): 201 and AUTHORIZATION status CREATED | 201 | authorization=CREATED; order=COMPLETED | dbg60d0b778d3 | PASS | O1: the COMPLETED seen earlier is the ORDER status; the authorization object must read CREATED |
| replay authorize with the same request ID (S7-A): 200 and same authorization | 200 | - | dbg6083c84eb4 | PASS |  |
| void the second seller's authorization | 403 | PERMISSION_DENIED | dbg97f68b0beb | FAIL | PERMISSION_DENIED here means the app cannot manage that seller's payments |
| create S7-B second-seller payee (capture then refund) (level 0) | 201 | CREATED | dbg63a1d87e55 | PASS |  |
| buyer approval of S7-B second-seller payee (capture then refund) | 200 | APPROVED | dbg6fe0cb13ee | PASS |  |
| authorize (S7-B): 201 and AUTHORIZATION status CREATED | 201 | authorization=CREATED; order=COMPLETED | dbgca0d739b98 | PASS | O1: the COMPLETED seen earlier is the ORDER status; the authorization object must read CREATED |
| replay authorize with the same request ID (S7-B): 200 and same authorization | 200 | - | dbg096e485d1f | PASS |  |
| capture the second seller's authorization | 201 | COMPLETED | dbgd78379915d | PASS |  |
| fully refund the second seller's capture | 403 | PERMISSION_DENIED | dbgd321ac6acd | FAIL | PERMISSION_DENIED here means the app cannot refund that seller's payments |
| control: payee that is not a sandbox account (record the failure mode) | 201 | CREATED | dbg0a19ccc3e8 | INFO | order creation outcome only |
| result | - | payee_email REJECTED: single_seller stays final | - | INFO |  |

**Implication:** payee_email is rejected; single_seller (the business account that owns the app) is final.

### Cleanup

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| void leftover authorization (S7-A) | 403 | PERMISSION_DENIED | dbge8fe9b750c | FAIL |  |

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

- S7: a USD 1.00 capture ending ...E402 could not be refunded through the API; refund it from that seller's Sandbox dashboard
- cleanup: a USD 1.00 authorization ending ...785E could not be voided through the API (it holds no captured money and expires on its own); void it in the Sandbox dashboard if you can

## After this run

- Rotate the Sandbox app secret now (checklist 0.1), and change any buyer password that was ever shown on screen or pasted anywhere.
- Delete the `.env.spike` file or keep it out of git; never commit it.
- Copy the derived settings and each spike's table into `docs/spike-results.md` and mark the spikes RECORDED in `docs/progress.md`.
