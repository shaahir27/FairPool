# Phase 5 evidence

Each file answers one question IG-5 asks. A file whose `status` is not `passed`
keeps the gate red on purpose; nothing here is upgraded by hand.

| File | Question |
|---|---|
| `migrations.json` | Is the schema at a known revision, and did this phase add one? |
| `local_checks.json` | Did the full local chain run, in the recorded configuration? |
| `failure_net_zero.json` | Does the failure path end at net zero (PT-11, F9, F24)? |
| `auction_vectors.json` | Does the rules engine reproduce the vectors and PT-06? |
| `merchant_bids.json` | Do the profile, sealed bids and receipts pass their tests? |
| `it5_sandbox.json` | Has one real buyer completed the redirect path? |
| `sandbox_contracts.json` | Do the non-interactive and interactive Sandbox contract tests pass? |
| `independent_review.json` | Has a read-only review of the diff happened? |
| `ci.json` | Is there a green CI run for this branch? |

`independent_review.json` is the record of five read-only passes. The first four
returned FAIL with findings, all of which are fixed and named by a test; the fifth
re-read the fixed state and returned PASS with no blocker and no major, so the gate
is closed on it. Its three follow-ups are listed there and carried forward, not
buried. Nothing in this directory is upgraded by hand: a `status` changes only when
the check it describes actually ran.
