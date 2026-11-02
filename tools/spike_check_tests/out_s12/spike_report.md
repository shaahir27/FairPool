# FairPool spike check report

- Run ID: `3d893320`; date (UTC): 2026-11-02 16:23; script v1.0.0; Python 3.12.16
- Spikes selected: core, s12
- PayPal hosts used: 127.0.0.1 and 127.0.0.1 (Sandbox only; every payment USD 1.00)
- Redaction: no secret, token, password, approval URL, buyer name or email, or account ID value is written here
- Totals: INFO 1, PASS 21

## Derived settings (apply the rules in `docs/spikes.md`; the owner confirms before changing `.env.example`)

| Setting or measurement | Value | From |
|---|---|---|
| `SHIPMENT_TRACKING_ENABLED` | `True` | S12 |

## Results by spike

### PayPal Sandbox regression (V1-V7, checklist 1.x, 6.1, 6.2)

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| host guard: only the two Sandbox hosts are used (checklist 1.1) | - | - | - | PASS | 127.0.0.1, 127.0.0.1 |
| R1 OAuth token (V1, checklist 1.2) | 200 | - | - | PASS | fields=['access_token', 'app_id', 'expires_in', 'nonce', 'scope', 'token_type'] expires_in=32400 scopes=2 |
| R2 create AUTHORIZE order, payee set (V2) | 201 | CREATED | dbg4c5b5e06e6 | PASS | payee_email=present merchant_id=MISSING (not required) |
| R3 replay create with the same PayPal-Request-Id: 200 and same order (V3, checklist 6.2) | 200 | - | dbg51960bc1fe | PASS |  |
| R4a authorize before approval -> 422 ORDER_NOT_APPROVED (V4) | 422 | ORDER_NOT_APPROVED | dbg9fdf034de1 | PASS |  |
| R4b capture before approval is rejected (V4) | 422 | ORDER_NOT_APPROVED | dbgb364499ceb | PASS |  |
| R5 a second order gets a distinct ID (V5) | 201 | - | dbg4f20668ba6 | PASS |  |
| R6 negative test DUPLICATE_INVOICE_ID: 422 and no order created (V6, checklist 6.1) | 422 | DUPLICATE_INVOICE_ID | dbg732579cf15 | PASS |  |
| R7 the seven event types of V7 are listed | 200 | - | dbge0b73b5a8d | PASS | 8 types listed |
| R8 list webhooks | 200 | - | dbgacca283027 | PASS | 0 listeners registered |
| R9 INR is not a supported currency for Orders v2 (V12; checklist 3.7) | - | - | - | INFO | not re-tested by this script; recorded fact from the earlier run |

**Implication:** The PayPal Sandbox basics the adapter contract relies on (token, create, replay, early-authorize rejection, mock error) behave as recorded.

### S2 follow-up: authorize/capture/void/refund replays, O1, O2

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| full refund of the capture: 201 | 201 | COMPLETED | dbg69dfcc17a8 | PASS |  |
| replay refund with the same request ID: 200 and the original refund | 200 | - | dbg2ba7acd98c | PASS |  |
| GET refund: COMPLETED | 200 | COMPLETED | dbgb10b4a0680 | PASS |  |

### S12 shipment tracking via Orders v2 track (G16) -> SHIPMENT_TRACKING_ENABLED

| Step | HTTP | PayPal status or issue | Debug ID | Result | Note |
|---|---|---|---|---|---|
| create s12-capture source (level 0) | 201 | CREATED | dbgec1fa30263 | PASS |  |
| buyer approval of s12-capture source | 200 | APPROVED | dbgc3dbcddd8d | PASS |  |
| authorize (s12-src): 201 and AUTHORIZATION status CREATED | 201 | authorization=CREATED; order=COMPLETED | dbgf28f8db757 | PASS | O1: the COMPLETED seen earlier is the ORDER status; the authorization object must read CREATED |
| replay authorize with the same request ID (s12-src): 200 and same authorization | 200 | - | dbgf603a3de0f | PASS |  |
| Orders v2 track (fictional carrier, notify_payer=false) | 201 | created | dbgcf70c2bf38 | PASS |  |
| GET the order: exactly one matching tracker | 200 | - | dbgdfdeddbf3a | PASS | trackers on the order=1 matching=1 |
| repeat the same request: still exactly one tracker (idempotent in effect) | 200 | - | dbgfa31de2f98 | PASS | matching trackers after repeat=1 |
| dashboard visibility (user-attested) | - | - | - | PASS | API acceptance is not proof of shipment or delivery |

**Implication:** Tracking can be written to PayPal with Orders v2 and read back.

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
