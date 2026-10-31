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
