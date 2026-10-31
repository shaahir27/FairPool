# Phase 3 verification record (2026-11-01)

Phase 3 (T03A01, T03A02, T03B01, T03B02, T03B03, T03B04 and the spikes S5, S10,
S11, S12) is implemented on the `phase-3` branch in three commits: the CR-3
contract change request, the migration and engine work, and the join, close,
linking and search work with their tests.

**IG-3 is not passed and this directory says exactly why.** `tools/gate_check.py` now
supports `ig-3` and refuses any gate name it does not know; it reads this
directory and stays red while any required file has a status other than
`passed`. Nothing here was marked passed to make the gate look green.

| File | Status | Why |
|---|---|---|
| `local_checks.json` | passed | 659 offline tests and 8 fault tests, one documented skip, every static and generated-artifact check, run under `make gate-check GATE=ig-3`. |
| `migrations.json` | passed | `tools/check_migrations.py` under `APP_ENV=test`: fresh database, 0001 to head, drift check, downgrade to base, head again, drift check again. |
| `s10.json` | passed | Pinned Oct 28-29 read-only MCP evidence reused, with its limits stated. Nothing re-executed. |
| `s12.json` | passed | Pinned Oct 28 tracker evidence reused, with its limits stated. Nothing re-executed. |
| `s5.json` | pending | Four of the seven contracted webhook event types cannot be produced before the Phase 4-5 money handlers, and a listener needs a public URL plus dashboard registration. `spikes.md` S5 requires judging each event type separately, so unrun types are pending. |
| `s11.json` | pending | `IT-3` requires the APIMatic trial started in Phase 3; `OD-P3-2` forbids starting it without the owner. The OpenAPI document now exists and validates at ten operations, which was the original blocker. |
| `independent_review.json` | pending | Written once the independent review of contracts, lock order, unknown outcomes, account and permission binding, privacy and evidence claims has been dispositioned. |
| `ci.json` | pending | CI is green for `main` at `88105a0`; the `phase-3` branch has not been pushed, so there is no remote CI evidence for this work yet. |

## What Phase 3 does not claim

- No live PayPal call was made in this session, and nothing here presents a
  simulated result as a real one (`AGENTS.md` rule 18, `I12`).
- Saving a PayPal permission is fake-only (`VAULT_REAL_SAVE_ENABLED=false`,
  `DEP-5`). A live-sandbox buyer cannot become eligible at close until `T05A01`
  ships the real save path, and that is a stated product limit, not a pass.
- The Elastic half of search is implemented from the recorded S8 request shape
  but never executed here: no credentials, and the official client is not
  installed in this environment. The one skipped test prints that reason.
- `pool.seed`, `lot.refill`, allocation, award, authorization, capture, refund,
  webhook processing, agent APIs, merchant keys and any new screen remain in
  their scheduled phases. Their jobs stay unregistered and `PENDING` on purpose.

## One test that proves the deadline fix

`backend/tests/integration/test_f26_clock_skew.py::test_a_join_that_starts_before_close_and_inserts_after_is_refused`
was run twice: once with the pre-CR-3 trigger restored in the test database, where it
**failed**, and once with the `clock_timestamp()` trigger migration 0003 installs, where it
**passed**. The assertion is only worth anything because it can tell those two states apart.
