# Vault and charge: the buyer payment path (PAYMENT_MODE=vault_charge)

Status: adopted by the owner on Oct 29, 2026 after the Sandbox vault spike (see `spike-results.md`, Oct 29 table). `authorize_capture` stays selectable as the fallback; every contract that describes it still applies when `PAYMENT_MODE=authorize_capture`.

## 1. What changes for the buyer

1. The buyer joins a pool and sets a maximum total (the cap, `max_total_cents` in the confirmed request). FairPool owns the cap: PayPal never sees it and does not enforce it.
2. Joining also saves the buyer's PayPal wallet for FairPool (a Vault setup token that the buyer approves on PayPal, then exchanged server side for a payment token). No funds are reserved and no authorization exists. PayPal's approval screen shows the merchant and future-payment wording but **no purchase amount** (observed).
3. The buyer may close the app. After the pool closes and a lot is awarded, FairPool charges each seated buyer once, server side, for the awarded delivered price if it is at or below the cap. A buyer who is not seated is never charged and the saved permission is deleted.
4. A buyer who withdraws before the charge deletes the saved permission and is never charged. After a charge, refunds follow the pool rules.

## 2. Flow and adapter calls (all deterministic code; never an AI call, FR-IG-09)

| Step | PayPal call | Key | Notes |
|---|---|---|---|
| Start saving | `POST /v3/vault/setup-tokens` with `payment_source.paypal.usage_type = MERCHANT`, return and cancel URLs | `PayPal-Request-Id` = `vs:{entry_id}` | Merchant-scoped on purpose: only the app's own seller may charge it. Copy any further required fields from the owner's `vault_spike.md` evidence and PayPal's current reference, never from memory. The response carries the approval link (relation `approve` or `payer-action`). |
| Buyer approves | browser redirect to that link | | Redirect is the verified path. The SDK v6 save-payment variant was not established. |
| Exchange | `POST /v3/vault/payment-tokens` with `payment_source.token = {id: <setup token id>, type: SETUP_TOKEN}` | `vp:{entry_id}` | Exchange immediately after approval; natural setup-token expiry was not tested. Store the returned payment token encrypted (section 5). |
| Charge | `POST /v2/checkout/orders` with `intent CAPTURE`, USD amount equal to the award total, payee = `SINGLE_SELLER_EMAIL`, `payment_source.paypal.vault_id = <payment token id>`, `custom_id` and `invoice_id` as in `paypal-adapter.md` section 5; then `POST /v2/checkout/orders/{id}/capture` only if the order did not complete itself | `vc:{buyer_order_id}` logical charge; separate UUIDv5 HTTP keys `vc:{buyer_order_id}:create` and `vc:{buyer_order_id}:capture` | Adapter method `charge_vault`. A replay with the same create key must return the same order; never charge again under a new key when the outcome is unknown: reconcile by GET. |
| Withdraw or end | `DELETE /v3/vault/payment-tokens/{id}` | `vd:{entry_id}` | Idempotent; 404 counts as deleted. |

Payment evidence is unchanged: a buyer is paid only when the capture resource reads `COMPLETED` (FR-FN-04, I3). `PENDING` waits for `capture.poll`.

## 3. State machine deltas

New transitions BO-23 to BO-27 in `state-machines.md` reuse the existing buyer-order states (`OFFERED`, `CAPTURING`, `CAPTURED`, CAPTURE_PENDING, CAPTURE_FAILED, `REJECTED`). In this mode `lot.open_checkout` creates every seat's `buyer_order` in `OFFERED` and enqueues `order.vault_charge` for each, at most `VAULT_CHARGE_CONCURRENCY` running at once. `buyer.continue`, approval, `order.authorize` and `order.capture` are not used, and there is no buyer payment window (`OFFER_WINDOW_S` is ignored). The lot's funding deadline and refill behaviour are unchanged: a failed or rejected charge opens one vacancy, `lot.refill` offers the next waitlisted buyer (who also has a saved permission and a cap), and the lot is `FUNDED` only when completed captures from distinct buyers reach the minimum.

## 4. Cap and eligibility rules (integer math only)

- **Join:** the entry requires an `ACTIVE` vault token with a recorded consent; otherwise it is rejected at pool close with reason `VAULT_MISSING` (error code `VAULT_REQUIRED` on the join API when checked earlier).
- **Award:** a seat is eligible only if `total_cents <= max_total_cents` (the existing rule, now applied against the flat delivered price, see `flat-delivered-bids.md`).
- **Charge precheck (BO-27):** token still `ACTIVE`, total still at or below the cap, lot still `CHECKOUT_OPEN`, award valid. Any failure rejects the seat and refills.
- A charge never exceeds the awarded total, and the awarded total never exceeds the cap. Tests assert both.

## 5. Token security

- The payment token ID is a credential. Store it only in `vault_tokens.token_ciphertext`, encrypted with AES-256-GCM using `VAULT_TOKEN_KEY` and a per-row nonce. Never log it, return it from any API, put it in an audit row, an AI prompt or a report. The redaction filter treats it as a secret.
- Show buyers only the last four characters of a token as a label, plus the cap they set.
- Delete the token when the entry is withdrawn, rejected at close, left unselected, or its lot ends (`CLOSED` or `FAILED_CLOSED`) with no pending capture, and record the deletion.
- Webhook events for vault tokens are hints that trigger a GET; the stored `status` follows the GET (`ACTIVE` or `DELETED`).

## 6. Consent text (exact wording lives in the web app; `VAULT_CONSENT_VERSION` names it)

The buyer must see and accept, before PayPal approval, text that says in plain words: FairPool will charge this PayPal account once for this pool, for the final delivered price of the winning offer, only if it is at or below the buyer's maximum; PayPal's approval screen will not show the amount; FairPool, not PayPal, enforces the maximum; the buyer can withdraw before the pool closes; nothing is charged if not selected; refunds follow the pool rules. Store the version, the SHA-256 of the exact rendered text, the cap, the pool ID and the time in `vault_tokens`. Changing the wording requires a new version.

## 7. Failure handling

| Charge outcome | Class | Action |
|---|---|---|
| Capture `COMPLETED` | paid | BO-24 |
| Capture `PENDING` | wait | BO-25, `capture.poll` |
| 422 `INSTRUMENT_DECLINED` (simulated in Sandbox with the mock header; a real low-balance decline was not reached) or status `DENIED` | definitive | BO-26, vacancy, refill |
| 403 `PERMISSION_DENIED` (deleted or revoked permission) | definitive; token marked `DELETED` | BO-26, vacancy, refill |
| 5xx, timeout, unknown | unknown | stay `CAPTURING`; GET by the stored order ID or the invoice; retry only with the same key |

If completed captures cannot reach the minimum before the funding deadline, every completed capture is refunded in full (existing failure path) and the lot closes. Unlike authorize-then-void, a refund of a completed capture may not return PayPal's fees; Sandbox cannot show this. Treat it as a cost of this mode and say so in the README.

## 8. Limits and owner decisions still open

- The flow works for the app-associated seller only (`PAYMENT_ROUTER=single_seller`); the token is not portable to another seller. Paying a winning merchant still happens outside PayPal (manual settlement): Payouts returned 403 `PAYOUT_NOT_AVAILABLE` and the second-seller route is blocked.
- Not established: natural setup-token expiry, a real low-balance decline, dispute exposure for buyers who forget they joined, legal permission to charge later and to hold funds for other parties, fee behaviour on refunds, how long tokens last in practice.
- Owner decisions: whether to send a notice before the charge (a default of none is assumed); whether failed pools may bear the fee cost; legal review before any live use. The Sandbox prototype is labelled accordingly.

## 9. Sandbox contract tests (marked `sandbox_interactive` where a buyer must approve)

| Test | Proves |
|---|---|
| VC-01 setup token, buyer approval, exchange, charge 1.00 with no browser, capture `COMPLETED`, refund | the whole path (spike V2, V7) |
| VC-02 replay the charge with the same key | one capture only (V3) |
| VC-03 delete the token, then charge | clean 403 `PERMISSION_DENIED`, order unpaid (V4) |
| VC-04 simulated decline with `PayPal-Mock-Response` `INSTRUMENT_DECLINED` | 422 and no payment (V5) |
| VC-05 unit: the token never appears in logs, API bodies, audit rows or prompts | section 5 |
| VC-06 unit: charge amount is at most the cap and equals the award total | section 4 |
