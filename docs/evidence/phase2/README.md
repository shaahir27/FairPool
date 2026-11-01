# Phase 2 verification record (2026-10-31)

Phase 2 was merged into `main`. On 2026-10-31 the owner explicitly closed IG-2
by exception; the `ig-2` tag has not been created, and automated acceptance
checks still report pending evidence. Closure does not mean those checks passed.

On 2026-11-01 the owner requested a 95% extraction threshold with safe review
and accepted the v4 live baseline plus separate v5 spot checks for the capacity
validation fix. The proposed contract revision and evaluator changes are not
yet independently reviewed or merged. The reconstructed report records 480 v4
cases and 89 v5 spots; each measured 100% on its labelled extraction fields.
The v4 case sent to review and the quota-interrupted attempts remain recorded;
the v5 spots are not represented as a full v5 evaluation. Under the proposed
rules the Gemini evidence check passes; current-revision CI evidence is pending.
Independent review found additional ambiguous-capacity variants. The v6, v7 and
v8 guards each have two separately labelled live spot checks; the v8 validator
also rechecks every accepted v4/v5 output offline. These do not constitute full
live evaluations of those versions or prove coverage of all ambiguous wording.

On the isolated PostgreSQL rerun, the local gate completed its backend, frontend,
migration, generated-artifact and secret checks, then stopped on pending CI.
The first full run had two concurrency test failures; those two tests passed
individually and in the full rerun. Their initial failure cause remains unknown.

The later prompt-v4 Gemini evaluation was resumed across reports after quota
interruptions. Of the 480 recorded v4 rows, 439 met every expected field and 41 went
to human review; 479 are distinct live calls, because one row is duplicated across
runs 1 and 3 (identical output, latency and token counts) and is disclosed rather
than counted as an independent call. Run 1's
`reconcile-015` routed a consistent offer to review after validation retries;
runs 2 and 3 recorded 160/160 rows each, 13 of them in review. An earlier 100-case sample exposed capacity
mismatches in `quote-005`, `quote-008` and `quote-025`, including conflicting
capacity values returned as a definite value. The v4 baseline resolves those three
cases (005 and 025 are null, 008 is 6); the earlier reports carry the problem, and
the fail-closed guard plus its deterministic tests cover every variant the review
found afterwards. 19 of the 41 review rows are demo cases and four of those expected
a definite rejection under the old rule; the owner's 2026-11-01 decision allows
review for contradictory demo cases, so that is disclosed rather than scored as a
pass.
See `gemini-full-quota-20261031.json`,
`gemini-resume-run2-retry-20261031.json`, and
`gemini-resume-run3-20261031.json`; retain quota failures and earlier reports.
CI passed for the commit carrying this evidence, and the gate's CI file records
pending for the current uncommitted prompt/test changes.

Foundation repairs cover handler rollback, claim ownership and supported kinds,
shipment association (migration 0002), application error codes/Retry-After,
disposable test database protection and explicit fail-fast gate tooling.
Original idea text, migration 0001 and historical spike results were preserved.

Gemini uses `GEMINI_API_KEY`, `AI_MODEL_PARSE` and `AI_MODEL_SIM`; safe defaults
are `gemini-3.5-flash-lite`. The local .env block was appended without reading
existing contents. Never commit .env or paste keys into reports. Missing keys
with AI enabled fail configuration. A different provider needs its own adapter.
Unpaid evaluation uses fictional text only; confidential inputs require an
appropriate paid service under Google's terms.

The 160 independently reviewed synthetic labels cover 50 intake, 30 quote,
60 reconciliation and 20 simulation cases. Simulation accepts neutral framing
around an exact labelled fact string, protecting field relationships as well
as numbers. Uncertain reconciliation requires review; UI integration must use
neutral wording, such as "Possible mismatch - please review."

The full live evaluation was subsequently run: 480/480 results, 154 errors,
48.3% exact extraction accuracy, status failed. The free-tier daily limit
(500 requests for gemini-3.5-flash-lite) was then exhausted, so a 40-case
diagnostic subset returned 429 on every call and did not test prompt v3. Prompt
v3, raw invalid-output logging and subset support are implemented; a live
rerun awaits a quota-enabled key. No failed run has been rewritten.

When a quota-enabled key is available, run a diagnostic subset first and then
the full corpus:

```
python tools/evaluate_gemini.py --requests-per-minute <quota> --runs 1 --case-ids <ids> --report <temp>
python tools/evaluate_gemini.py --requests-per-minute <quota>
```

This invokes the production parser for three complete runs, retains attempts,
failures and prior reports, paces individual requests (including validation
retries), and uses no fake fallback. Reported zero false positives would be an
observed result on this corpus, not a universal guarantee.

Run tests only with APP_ENV=test and an explicitly exported DATABASE_URL naming
a loopback PostgreSQL database ending in _test. Tests never load .env. Export
the other required settings explicitly as well: `SECRET_KEY`, `HMAC_KEY`,
`RECEIPT_SIGNING_KEY`, `ADDRESS_ENCRYPTION_KEY`, `PAYPAL_CLIENT_ID`,
`PAYPAL_CLIENT_SECRET`, `VAULT_TOKEN_KEY` and `SINGLE_SELLER_EMAIL`; set
`AI_ENABLED=false` for the offline suite (or export a valid `GEMINI_API_KEY`).
The canonical local gate is `python tools/gate_check.py ig-2`; it exits 2 until
the external evidence below is complete. The latest offline run passed 352
backend tests. Tests used a separate postgres:16 container on port 55432, not
the development or hosted database.
`python tools/check_migrations.py` creates and drops its own additional
database in that disposable cluster.

`python tools/benchmark_search.py` measured actual pg_trgm over 20 fictional
public documents and ten labelled queries. Recall@5 was 10/10. The live
Elastic cluster was then tested: the managed `.jina-embeddings-v5-text-small`
inference endpoint accepted a temporary 20-document semantic index, and a
hybrid RRF query (BM25 + semantic_text) also reached recall@5 10/10 at
205-387 ms per query. The temporary index was deleted. The local
`.multilingual-e5-small-elasticsearch` endpoint had no ML-node capacity, so it
was not used. The Elastic acceptance rule therefore passes; Elastic is selected,
and `SEARCH_BACKEND=elastic` and `ELASTIC_INFERENCE_ID=.jina-embeddings-v5-text-small`
are set in `.env`, `deploy/render.yaml` and live Render (`/ready` 200). Similarity
remains advisory.

C-01 to C-07 passed against Sandbox with the app-owning seller on 2026-10-31
(7/7); C-06 uses the documented PayPal-Mock-Response test header; no captures or
refunds. S4 levels 1-2 passed (highest verified 2); level 3 needs a human
address-lock attestation and was not verified in the non-interactive run.
Existing S13 evidence is retained; hosted repeat remains later. The ledger's
completed/distinct-buyer counting is tested; PT-09's funding half requires the
T04A03 engine and is recorded as Q-2026-10-31-07.

`python tools/gate_check.py ig-2` runs local checks and rejects pending or stale
evidence. Authentication throttling is intentionally per process; shared rate
limits are required before deploying multiple processes. Public registration
creates buyers only; privileged accounts require operator provisioning.
