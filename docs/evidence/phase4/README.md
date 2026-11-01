# Phase 4 verification record (2026-11-01)

Phase 4 (T04A01 to T04X01: `lot.open_checkout`, approval and authorization flow,
the funding trigger and capture sweep, intake, beacon and `pool.seed`, allocation
with the real `AllocationReadService`, the public audit content and the first
integration) is implemented on the `phase-4` branch in three commits: CR-4 contracts
and migration 0004 (`e11a801`), the seed/allocation/checkout/money engines
(`9b6f452`), and intake, the HTTP surface, the real wiring and IT-4 (`ad656fb`).

**IG-4 is not passed and this directory says exactly why.** `tools/gate_check.py` now
supports `ig-4`, reads this directory, and stays red while any required file has a
status other than `passed`. Nothing here was marked passed to make the gate look
green, and no number in this directory came from a plan or an earlier phase.

| File | Status | Why |
|---|---|---|
| `migrations.json` | passed | `tools/check_migrations.py` under `APP_ENV=test`: fresh disposable database, 0001 to head, drift check, downgrade to base, head again, drift check again. `fairpool_test` is at revision 0004 with 35 application tables plus `alembic_version`. |
| `local_checks.json` | passed | 836 backend tests (828 offline plus the 8 fault tests, which the gate also runs on their own), no skips, ruff and format clean, `mypy --strict` clean over 58 files, import boundaries, docs validator, merchant OpenAPI, generated frontend types, gitleaks, frontend lint with 14 tests and a production build. Every command was run in this session. |
| `pipeline.json` | passed | `tests/integration/test_pipeline_fakes.py` re-run on its own and pasted: 1 passed in 4.67s, with `FakeAI` and the fake gateway as the only fakes. |
| `independent_review.json` | pending | No independent review has run on this diff. The implementing agent cannot review its own work, so the file records that fact instead of a pass. |
| `ci.json` | pending | The branch is unpushed. No remote CI run exists for `phase-4`, and the Phase 3 run is not represented as Phase 4's. |

## What Phase 4 does not claim

- **No real PayPal call was made in this session.** No order was created, approved,
  authorized, captured, voided or refunded against the Sandbox in Phase 4. The money
  path runs entirely through the fake router and `test_pipeline_fakes.py`; `I12` and
  `AGENTS.md` rule 18 apply.
- `WEBHOOKS_ENABLED` is still `false` and no money-state handler is registered. The
  webhook simulator evidence from S5 is mock evidence and is not repeated here.
- There is no refund path and no void-driven failure path yet: a lot that misses its
  minimum cannot be rolled back in Phase 4, which is `T05A03` and `T06A01`.
- No buyer checkout UI, no fulfillment, no agent or merchant surface, and no auction
  or bid engine exist. Their handlers are unregistered and `PENDING` on purpose; the
  current wiring registry test compares the registered kinds with the implemented set.
- In `PAYMENT_MODE=vault_charge` a live-sandbox buyer still cannot become eligible at
  close, because saving a permission for real is `T05A01` (`DEP-5`). Phase 4 exercises
  the vault charge against the fake only.
- The hosted skeleton still runs the Phase 3 image and its Supabase database is at
  0003. Phase 4 was not deployed, because the branch is local.

## Beacon spike S6, checked read-only

`DRAND_BASE_URL` and `DRAND_CHAIN_HASH` are absent from `.env` (present only as
commented placeholders) and from the process environment, so the Phase 4 check records
`not configured` and nothing else: no chain hash, period, round or randomness value is
invented. `BEACON_MODE=drand` in `docs/decisions.md` section 4 therefore remains a
switch that this environment cannot honour, and even a configured chain could only be
announced today, because `BeaconAnnouncement.fetch` still raises `NotImplementedError`.
The detail is under S6 in `docs/spike-results.md`.

## Gate state after verification

`gate_check.py ig-4 --evidence-only` exits 2 with exactly two lines:
`independent_review: required evidence pending` and `ci: required evidence pending`.
That is the correct result for a local, unreviewed, unpushed branch. Closing IG-4
needs a pushed branch with nine green CI jobs, a read-only independent review with its
findings dispositioned, and then the `ig-4` tag.
