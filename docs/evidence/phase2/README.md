# Phase 2 verification record (2026-10-31)

Implementation is on `phase-2`; IG-2 remains open. JSON evidence distinguishes
local verification from pending external acceptance. Do not tag `ig-2` from
local unit tests or fake responses.

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

The initial live Gemini attempt and its failure are retained in gemini.json.
The exported-key lookup returned HTTP 400 / INVALID_ARGUMENT. This does not
establish model acceptance or diagnose the precise configuration error.
Prompt/dataset changes invalidate that fingerprint. Configure a working key
locally and export the settings, then run:

```
python tools/evaluate_gemini.py --requests-per-minute <verified-account-quota>
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
the external evidence below is complete. The local run used a separate
postgres:16 container on port 55432, not the development or hosted database.
`python tools/check_migrations.py` creates and drops its own additional
database in that disposable cluster.

`python tools/benchmark_search.py` measured actual pg_trgm over 20 fictional
public documents and ten labelled queries. Recall@5 was 10/10; see s8.json for
request shape, per-query latency and timestamps. Elastic comparison and trial
dates remain pending; SEARCH_BACKEND stays postgres. Similarity is advisory.

C-01 to C-07 passed against Sandbox with the app-owning seller on 2026-10-31
(7/7); C-06 uses the documented PayPal-Mock-Response test header; no captures or
refunds. S4 still needs human approval and resource cleanup; no new live
resources were created for S4. Existing S13 evidence is retained; hosted repeat
remains later.

`python tools/gate_check.py ig-2` runs local checks and rejects pending or stale
evidence. Authentication throttling is intentionally per process; shared rate
limits are required before deploying multiple processes. Public registration
creates buyers only; privileged accounts require operator provisioning.
