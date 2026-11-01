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
| `s5.json` | pending | Listener registered and verified by id on 2026-11-01: `1UT33484SD059942U` with all seven contracted event types. PayPal's list endpoint under-reports (zero links even for a listener that GET and DELETE by id handle), and the plain callback URL is held by two orphan listeners that only the dashboard can clear. `PAYPAL_WEBHOOK_ID` in `.env` is empty by the owner's action, and stays empty until they set the verified id; signature verification therefore has not been executed against a delivered event, and four of seven types cannot exist before Phase 4-5. |
| `s11.json` | pending | `IT-3` requires the APIMatic trial started in Phase 3; `OD-P3-2` forbids starting it without the owner. The OpenAPI document now exists and validates at ten operations, which was the original blocker. |
| `independent_review.json` | passed | A read-only review agent audited the diff and returned 1 blocker, 4 majors and 8 minors. All are fixed or corrected, each with a named test; the table is in `docs/progress.md`. |
| `ci.json` | passed | The merge commit `a57804a` was pushed and remote CI ran all nine jobs green (run 41271936679, 2m9s), including the Alembic migration and drift job. |

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

## What the review changed

The independent pass found one user-visible defect (`POST /api/v1/intake/manual`
returned 500 because a raw UUID reached Starlette's JSON encoder, and no test had ever
posted to that route), one latent concurrency problem (withdrawal doing provider I/O
under the pool lock), one log-hygiene gap (uvicorn's access line printing an OAuth
`code` and `state`), and a CR-3 contract sentence that named a type which does not
exist. All are fixed, with the table in `docs/progress.md`. `s5`, `s11` and `ci` remain
pending because they cannot be executed in this environment, not because they were
skipped.

## Elastic parity, executed 2026-11-01

`test_backends_agree_on_the_same_public_documents` ran against the real Elastic
cluster (version 9.5.5, official async client 9.5.1): the hybrid RRF query returned the
document the test wrote, and its `SearchHit` matched the Postgres backend's exactly.
That upgrades the Phase 3 search claim from "implemented, never executed" to executed -
with one honest caveat: the client and `aiohttp` are installed in this local venv only.
The committed requirements do not carry them, so CI still skips the test with its printed
reason, and adding them to the lockfile is an owner decision rather than something to
slip into a phase commit.

## Gate state after verification

`make gate-check GATE=ig-3` runs green through the whole automated chain and now fails on
`s11` alone: the APIMatic trial is an account signup the owner has chosen to leave for
later. `ig-3` is therefore not tagged - one parked owner decision still stands between
this phase and its gate.
