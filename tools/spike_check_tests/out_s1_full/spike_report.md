# FairPool spike check report

- Run ID: `e274dbdf`; date (UTC): 2026-11-02 16:22; script v1.0.0; Python 3.12.16
- Spikes selected: core, s1
- PayPal hosts used: 127.0.0.1 and 127.0.0.1 (Sandbox only; every payment USD 1.00)
- Redaction: no secret, token, password, approval URL, buyer name or email, or account ID value is written here
- Totals: INFO 2, PASS 16

## Derived settings (apply the rules in `docs/spikes.md`; the owner confirms before changing `.env.example`)

| Setting or measurement | Value | From |
|---|---|---|
| `DEDUPE_MODE` | `full` | S1 |
| `login_scope` | `openid` | S1 |

## Results by spike

### PayPal Sandbox regression (V1-V7, checklist 1.x, 6.1, 6.2)

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| host guard: only the two Sandbox hosts are used (checklist 1.1) | - | - | - | PASS | 127.0.0.1, 127.0.0.1 |
| R1 OAuth token (V1, checklist 1.2) | 200 | - | - | PASS | fields=['access_token', 'app_id', 'expires_in', 'nonce', 'scope', 'token_type'] expires_in=32400 scopes=2 |
| R2 create AUTHORIZE order, payee set (V2) | 201 | CREATED | dbg3c20f47381 | PASS | payee_email=present merchant_id=MISSING (not required) |
| R3 replay create with the same PayPal-Request-Id: 200 and same order (V3, checklist 6.2) | 200 | - | dbg09fab3d8ff | PASS |  |
| R4a authorize before approval -> 422 ORDER_NOT_APPROVED (V4) | 422 | ORDER_NOT_APPROVED | dbge62b32373d | PASS |  |
| R4b capture before approval is rejected (V4) | 422 | ORDER_NOT_APPROVED | dbge82c9b1efe | PASS |  |
| R5 a second order gets a distinct ID (V5) | 201 | - | dbg36d6384ee2 | PASS |  |
| R6 negative test DUPLICATE_INVOICE_ID: 422 and no order created (V6, checklist 6.1) | 422 | DUPLICATE_INVOICE_ID | dbg32048d0adf | PASS |  |
| R7 the seven event types of V7 are listed | 200 | - | dbgce29c280b2 | PASS | 8 types listed |
| R8 list webhooks | 200 | - | dbge6826b880c | PASS | 0 listeners registered |
| R9 INR is not a supported currency for Orders v2 (V12; checklist 3.7) | - | - | - | INFO | not re-tested by this script; recorded fact from the earlier run |

**Implication:** The PayPal Sandbox basics the adapter contract relies on (token, create, replay, early-authorize rejection, mock error) behave as recorded.

### S1 Log in with PayPal, scope openid (G1, G2) -> DEDUPE_MODE

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| variant A: authorization request accepted, code returned | - | code | - | PASS |  |
| variant A: exchange code for a user token (server side) | 200 | - | dbgacb160bd9c | PASS | fields=['access_token', 'expires_in', 'scope', 'token_type'] |
| variant A: userinfo; identifier fields present (values never recorded) | 200 | - | dbgea8bdae0f2 | PASS | fields=['name', 'payer_id', 'sub', 'user_id', 'verified_account']; identifier fields=['payer_id', 'sub', 'user_id'] |
| create S1 checkout payer_id comparison (use the SAME buyer as the consent) (level 0) | 201 | CREATED | dbgf335684d54 | PASS |  |
| buyer approval of S1 checkout payer_id comparison (use the SAME buyer as the consent) | 200 | APPROVED | dbgfe3c7ba47b | PASS |  |
| compare HMAC(each raw userinfo identifier) with HMAC(order payer_id) (values never recorded; raw strings, never normalised) | - | EQUAL via ['payer_id'] | - | PASS |  |
| rule applied | - | DEDUPE_MODE=full | - | INFO | neither identifier proves one human; do not strip prefixes to force equality |

**Implication:** A login identifier equals the checkout payer_id: one key per PayPal account.

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
