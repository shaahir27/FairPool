# Sandbox contract suite (C-01 to C-18)

Real PayPal Sandbox calls for `docs/contracts/paypal-adapter.md` section 11. Nothing here
is mocked: `AGENTS.md` rule 18 forbids a mock inside this directory, and every money test
uses USD 1.00 at the app-owning seller. The suite proves PayPal behaves as the adapter
contract records; the adapter's own unit tests live under `backend/tests/unit/`.

## Files and IDs

| File | Marker | Cases |
|---|---|---|
| `test_gateway_contract.py` | `sandbox` | C-01 to C-07: token, create, create replay, pre-approval 422, distinct orders, verified mock, event types |
| `test_gateway_interactive.py` | `sandbox_interactive` | C-08, C-09, C-10: void, capture then refund, replay |
| `test_phase6_contracts.py` | `sandbox` | C-14 payload ladder; C-15 webhook signature over a captured delivery |
| `test_phase9_contracts.py` | `sandbox_interactive` | C-11 void replay and capture after void; C-12 payer and payee fields; C-13 India or INR rejected; C-17 SDK popup approval then server authorize; C-18 tracker submit and read-back |
| `test_router_contract.py` | none | C-16 the payee-email router raises `NotEnabled` (runs in the default suite) |
| `support.py` | - | Settings from exported variables, the USD 1.00 request, the approval poll, the capture poll |
| `conftest.py` | - | The approval gate and the shared `gateway` fixture |

## Markers

- `sandbox` — no human needed; CI never runs it because the credentials are absent.
- `sandbox_interactive` — a human must approve one order in the Sandbox buyer account.
  The whole module skips unless `FAIRPOOL_SANDBOX_APPROVAL=1` is exported, so a default
  run passes with skips instead of waiting five minutes and failing.
- No marker (C-16) — ordinary test, no provider, part of `make test` and CI.

## Environment variables (names only; never commit, print or log a value)

| Name | Needed by |
|---|---|
| `PAYPAL_CLIENT_ID` | every provider test |
| `PAYPAL_CLIENT_SECRET` | every provider test |
| `SINGLE_SELLER_EMAIL` | every provider test; must be the business account that owns the REST app |
| `FAIRPOOL_SANDBOX_APPROVAL` | set to `1` to unlock the `sandbox_interactive` runs |
| `PAYPAL_WEBHOOK_ID` | C-15 only |
| `FAIRPOOL_WEBHOOK_EVIDENCE_FILE` | C-15 only: raw body bytes of one delivered webhook |
| `FAIRPOOL_WEBHOOK_HEADER_EVIDENCE_FILE` | C-15 only: JSON of the `paypal-transmission-*` headers |
| `CI` | when set, every provider test skips |

Credentials come from the environment only (`AGENTS.md` rule 2, I14). The suite builds its
own `Settings` and never loads `.env`, so export the values first.

## Running

Non-interactive (real calls, no approval):

```bash
set -a; . ./.env; set +a
export APP_ENV=test
export TEST_DATABASE_URL="${TEST_DATABASE_URL%/*}/fairpool_sandbox_test"
export DATABASE_URL="$TEST_DATABASE_URL"
.venv/Scripts/python.exe -m pytest backend/tests/contract_sandbox -m sandbox -q
```

Interactive (the owner approves orders):

```bash
set -a; . ./.env; set +a
export APP_ENV=test
export TEST_DATABASE_URL="${TEST_DATABASE_URL%/*}/fairpool_sandbox_test"
export DATABASE_URL="$TEST_DATABASE_URL"
export FAIRPOOL_SANDBOX_APPROVAL=1
.venv/Scripts/python.exe -m pytest backend/tests/contract_sandbox -m sandbox_interactive -q
```

Everything at once, which skips the interactive cases unless the approval variable is set:

```bash
.venv/Scripts/python.exe -m pytest backend/tests/contract_sandbox -q
```

`make test-sandbox` and `make test-sandbox-interactive` run the two marker sets directly.

## The owner approval step

1. Sign in to the Sandbox buyer account in a second browser window, not the seller account.
2. Start the interactive run. Each test prints one line with an **order ID** and the time it
   will wait (five minutes). No approval URL, token or secret is printed (`AGENTS.md` §3).
3. Approve that order on the Sandbox checkout page (C-08 to C-13, C-18) or through the
   checkout page's JavaScript SDK v6 popup for C-17 (`PAYPAL_APPROVAL_UI=sdk_popup`).
4. Leave the run going: each test polls a GET until the order reads `APPROVED`, then makes
   its own assertions. A timeout fails that test; nothing is retried for you.

C-17's popup cannot be driven from pytest (the repository deliberately carries no browser
dependency for it), so the owner opens the popup; every server obligation of
`paypal-adapter.md` §12 is then asserted from a fresh GET. C-11's India seller half and
C-15's captured delivery are recorded facts (V12, S5) and stay manual.

Captures left by C-09, C-10 and C-18 are real Sandbox money and are the owner's to refund;
the suite does not refund on the operator's behalf.
