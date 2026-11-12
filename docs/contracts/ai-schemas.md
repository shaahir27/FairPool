# Contract: AI tasks, schemas and evaluation

Owner: Member B. Code lives in `backend/src/fairpool/adapters/ai/` and the `intake` and `auction` modules. The AI never decides eligibility, never sees PayPal, and never moves money (I2, FR-AI-02). Every output is a **proposal**: deterministic code validates it and a human (buyer or merchant) confirms it.

## 1. Rules for every task

1. Closed JSON schema with enums. Validate every output; on invalid JSON or schema failure retry once; then fall back to the manual form (FR-IN-08) or, for reconciliation, to ops review.
2. Untrusted input (buyer messages, merchant quotes, notes) is JSON-encoded inside an explicitly labelled untrusted data envelope (so embedded closing tags cannot escape) in the prompt and the system prompt states that nothing inside it is an instruction (F19, F20). No tools are given to the model.
3. Input limits: buyer message 2,000 characters; quote and notes 4,000 characters; control characters stripped before the call.
4. Provider: Google Gemini through `google-genai`; omit temperature for Gemini 3.x; 20 second timeout; `max_output_tokens` 1,000 (2,000 for SIM_TEXT). Model names from `AI_MODEL_PARSE` and `AI_MODEL_SIM` (BD-04).
5. Every call writes an `ai_runs` row: task, model, prompt version, SHA-256 of the canonical input, output, ok flag, error, latency, tokens.
6. The AI package imports nothing from payments, ledger, checkout or the database layer. `AIClient` methods receive a session and pass it unchanged to the injected `AiRunLogger` (`domain-ports.md`), which writes the `ai_runs` row.
7. Amounts are strings (for example `"600.00"`), never numbers, so no floating point enters the system. The server converts to cents with the regex `^\d+(\.\d{1,2})?$` and rejects anything else (BD-14).
8. The model never chooses zones, pool IDs outside the supplied candidates, product keys or prices on a merchant's behalf. The server resolves zones from the region and verifies IDs.

## 2. Task INTAKE (buyer text to proposal)

Input: `message`, `candidates` (at most 5 open pools: `pool_id`, `title`, `variant`, `condition`, `regions`), `history` (previous turns).

```json
{
  "pool_id": "uuid from candidates, or null",
  "match_confidence": "high | medium | low | none",
  "condition": "NEW | REFURBISHED | OPEN_BOX | null",
  "quantity": 1,
  "delivery": {"region": "string or null"},
  "required_by": "YYYY-MM-DD or null",
  "max_total": {"amount": "600.00 or null", "currency": "USD or other code or null"},
  "firm_requirements": ["string"],
  "preferences": ["string"],
  "ambiguities": [{"field": "string", "question": "string"}],
  "clarifying_question": "string or null"
}
```

Server validation after the model (deterministic; DEP-1, FR-IN-01 to FR-IN-07):

1. `pool_id` is one of the supplied candidates and the pool is OPEN; otherwise status NO_MATCH.
2. `condition` equals the pool template condition (a mismatch becomes a clarifying question, never a silent change).
3. `quantity` is 1. A request for more is explained ("limit one per entry") and the proposal continues with 1 only if the buyer agrees.
4. `max_total.currency` is USD; any other currency becomes an ambiguity. Convert the amount to `max_total_cents` (positive, within the template's bounds). A symbol states its code as plainly as the code does, so `$650`, `650 dollars` and `USD 650` all ground USD (CR-12); a currency the message contradicts is an ambiguity, never a conversion.
5. `delivery.region` maps to exactly one zone of the template; otherwise ask.
6. `required_by` is not earlier than the pool's latest delivery date (`fund_by` plus `delivery_sla_days`); otherwise tell the buyer the pool cannot meet the date. A written date in any form (ISO, `Nov 30, 2026`, `30 November 2026`) is canonicalised to the day the message states (CR-12). A weekday or a relative phrase is not a value: the field becomes null and this item asks for the date. A numeric slash date (`11/30/2026`) grounds nothing, because two readers disagree about which number is the day. Grounding reads the buyer's earlier messages in `history` when the current one only answers the question, and never the server's own question text, which quotes the pool's bound.
7. `firm_requirements` are a subset of what the template provides; anything else is shown as unsupported.
8. Ask at most one clarifying question per turn, at most three turns, then the manual form.

The confirmation card (`api.md`) is built by the server from catalog data. Confirming writes the canonical request; the AI output is never stored as the buyer's requirement.

## 3. Task QUOTE (merchant quote to proposed fields, DEP-2)

Input: `quote_text`, `lot_requirement` (product key, condition, bundle, seats, zone regions).

```json
{
  "product_text": "string or null",
  "condition": "NEW | REFURBISHED | OPEN_BOX | null",
  "bundle_contents": ["string"],
  "capacity": "integer or null",
  "target_quantity": "integer or null",
  "moq": "integer or null",
  "tiers": [{"min_qty": 1, "item_price": "500.00"}],
  "shipping_by_zone": {"US-EAST": "15.00"},
  "tax": {"mode": "INCLUDED | RATE_TABLE | null", "rate_bps_by_region": {"NY": 875}},
  "delivery_sla_days": "integer or null",
  "returns_days": "integer or null",
  "valid_until": "ISO 8601 or null",
  "total_capacity": "integer or null",
  "evidence_note": "string or null",
  "ambiguities": [{"field": "string", "question": "string"}]
}
```

The server converts amounts to cents and builds a `structured` object (shape in `db-schema.md`) with unresolved fields left empty for the merchant to fill. Status becomes PROPOSED (BS-01). Nothing reaches the auction until the merchant confirms (BS-03). `product_key` is prefilled by the server from the lot and is editable by the merchant; a different product then fails R3.

## 4. Task RECONCILE (flags only)

Input: the lot requirement, the merchant-confirmed `structured` fields and the free text (quote and notes).

```json
{
  "consistent": true,
  "flags": [
    {"code": "BUNDLE_MISMATCH | CONDITION_MISMATCH | DELIVERY_CONFLICT | HIDDEN_FEE | QUANTITY_CONFLICT | RETURN_CONFLICT | OTHER",
     "severity": "BLOCKING | WARNING",
     "field": "string",
     "snippet": "quoted text, at most 200 characters"}
  ]
}
```

Asymmetry rule (design 10.5): a BLOCKING flag moves the bid to FLAGGED (BS-04) and excludes it (R7) until the merchant saves a corrected revision. The AI can never qualify an offer that R1 to R6 reject, never edit a field, never accept a variation for a buyer. `consistent` must be false when any flag is BLOCKING. If the AI is unavailable, bids with non-empty free text wait for ops review; bids with only structured fields proceed.

## 5. Task SIM_TEXT (simulation variety)

Input: `kind` (`buyer_message` or `merchant_quote`) and `facts` (numbers and terms drawn from the seeded generator). Output: one natural-language string that states exactly those facts. Numbers, caps, prices and behaviour come from the seeded generator, never from the model, so every run is reproducible (FR-AI-03). Output is labelled SIMULATED wherever shown.

## 6. Evaluation (FR-AI-05)

Files (Phase 2 baseline; T09B02 extends the same production-path evaluation):

- `backend/tests/ai_eval/data/intake_cases.jsonl`: about 50 messy buyer messages. Each line `{"id", "pool_candidates", "message", "history", "expected": {fields as in section 2 after server validation}}`.
- `backend/tests/ai_eval/data/quote_cases.jsonl`: about 30 merchant quotes. Each line `{"id", "lot_requirement", "quote_text", "expected_fields"}`.
- `backend/tests/ai_eval/data/reconcile_cases.jsonl`: 60 cases (30 consistent, 20 explicit contradictions and 10 ambiguous) built from synthetic quotes with deliberate mismatches (extra bundle item, wrong condition, hidden fee, injected instruction). Each line `{"id", "lot_requirement", "structured", "text", "expected_flags": [codes], "must_not_qualify": true}`.

Metrics: per-field exact match for enums, integers and dates; ambiguity recall (did it ask when it should); false-confirmation rate (confirmed something wrong); for reconcile, flag-code recall and precision and the count of injected instructions that changed the outcome (must be zero). The README publishes the measured numbers. Phase 2 requires three complete live runs, at least 95% exact extraction accuracy, zero accepted malformed outputs, invented monetary values, unauthorized IDs, unsupported blocking flags or successful injections. Non-demo extraction errors are permitted only for condition, quantity, region, date and non-monetary quote quantities; every error remains reported. Review is acceptable for a non-demo reconciliation case, including a consistent offer, but a provider outage is not an accepted review. Every contradiction must be flagged or routed to review; ambiguous cases remain unresolved. All supplied simulation facts must be preserved and all demo cases must meet their expectations. Retain every failure and retry; no acceptance claim while a required check is pending. This revision is the owner-requested proposed CR in `contracts/README.md`, pending independent review and merge.

## 7. Retrieval and similarity (INT-1, FR-IG-01)

Search is **retrieval**, not AI judgement, and never a gate for requirements (R3 and the deterministic rules stay the only gates).

- **What is indexed:** only public documents: one per pool and one per lot, with `doc_kind`, `pool_id`, `lot_id`, `status`, `product_key`, `condition`, `title`, and a `content` text built from title, variant, condition, bundle contents, zone regions and delivery terms. Never buyer entries, caps, users, requests or quotes.
- **Backend:** `SEARCH_BACKEND=elastic` uses an index per `ELASTIC_INDEX_PREFIX` (default `fairpool`), for example `fairpool-search-v1`, with a `text` field `content` copied (`copy_to`) into a `semantic_text` field `content_embedding` that names an explicit `ELASTIC_INFERENCE_ID` (the docs recommend an explicit inference endpoint for production). Query is hybrid: the `rrf` retriever over a `match` query on `content` and a `semantic` query on `content_embedding`, filtered by `status`. Confirm the exact request shape against Elastic's "Hybrid search with semantic_text" page in spike S8. `SEARCH_BACKEND=postgres` uses `pg_trgm` over `pools.search_text`. Both return the same `SearchHit` shape.
- **Where it is used:** (1) intake candidate retrieval, replacing keyword retrieval (at most 5 candidate pools are passed to INTAKE; the server still validates everything); (2) the merchant Demand Board and `GET /merchant-api/v1/lots?q=`; (3) agent and MCP `q` search; (4) the advisory check below.
- **Advisory wrong-product check:** after a bid revision is confirmed, `similarity_check` runs a semantic-only query over open lots with the quote and notes text. If the lot's own document is not ranked first **and** the top hit has a different `product_key`, create a `bid_flags` row with code `LOW_SIMILARITY`, severity WARNING and a short evidence string. A WARNING never changes a bid's status, never excludes it and never qualifies it; it is shown to the merchant and ops. The check is skipped (no flag) if search is unavailable or the text is empty.
- **Sync:** Postgres is the source of truth. `search.index` jobs upsert documents on publish and status changes; the index can be rebuilt with `POST /api/v1/admin/search/reindex`. Search failure falls back to Postgres and is logged; it never fails a user action.
- **Sync details (CR-3):** delivery is at-least-once, so writes are repeatable rather than exactly-once. A document id is the row id it describes — `doc_id = pool_id` for a pool document, `doc_id = lot_id` for a lot document — and upsert and delete are both idempotent for the same id; the projection is re-read from the current committed row at upsert time, never from the job payload, which carries ids only. One pool document and one lot document per row is the whole index, and a lot document is deleted when its lot leaves the visible set. A hit is only returned after it is hydrated against current Postgres visibility, so a stale or private document is dropped rather than shown; dropping a hit never changes a result's meaning because search is advisory. Index availability must never block pool publication: publish enqueues and moves on. Reindex pages over rows, is admin-only, and re-enqueues per document instead of rebuilding in one request.
- **Evaluation:** retrieval quality is measured on the intake cases (does the expected pool appear in the top 5) and reported next to the AI metrics.

## 8. Fake AI (for tests)

`FakeAI` returns scripted outputs keyed by the SHA-256 of the canonical input, can return invalid JSON or time out on demand, and never makes a network call. Unit and integration tests use it; the evaluation and a few smoke tests use the real model.

## 9. Task MANDATE (buyer intent to a proposed delegation mandate)

Added by CR-14 (owner authorized 2026-11-07, FR-AI-06). Numbered last so sections 2 to 8 keep their existing numbers and every cross-reference to them stays valid.

CR-17 exposes `POST /api/v1/me/mandate-proposal` to the signed-in buyer (api.md §4.4). It returns an editable proposal or the manual form and mints nothing. An empty pool selection triggers ordinary public OPEN-pool retrieval from the buyer’s intent, with at most five candidates; the buyer need not search and select pools by hand. Its candidate category is the product key; category proposals resolve to explicit supplied pool IDs with a null delegation category, so the ordinary pool-scoped token can use them without gaining access to any future pool.

Input: `message`, the accepted INTAKE proposal from section 2, `candidates` (the same at most 5 open pools, each with its template bounds and `timeline`), and `history`.

```json
{
  "pool_scope": {"pool_ids": ["uuid from candidates"], "category": "string or null"},
  "max_total": {"amount": "600.00 or null", "currency": "USD or null"},
  "expires": "YYYY-MM-DD or null",
  "conditions": [
    {"predicate": "PRICE_ABOVE | FUNDING_BELOW | BLOCKING_FLAG_ON_AWARD | DELIVERY_AFTER | NO_AWARD_BY",
     "params": {},
     "action": "PROCEED | REASK | HALT"}
  ],
  "ambiguities": [{"field": "string", "question": "string"}],
  "clarifying_question": "string or null"
}
```

`params` is typed per predicate and closed: `PRICE_ABOVE` takes `{"amount": "520.00"}`; `FUNDING_BELOW` takes `{"percent": 60, "hours_before_close": 24}`; `BLOCKING_FLAG_ON_AWARD` takes `{}`; `DELIVERY_AFTER` and `NO_AWARD_BY` take `{"date": "YYYY-MM-DD"}`. Any other predicate name or parameter set is invalid output.

The `reserved` acts are **not** model output. The server stamps `["payment_approval"]` on every mandate, because no AI-callable surface has a payment verb to reserve against (section 4.5 of `api.md`, rule 22). The model cannot widen, narrow or omit it.

Server validation after the model (deterministic; the same retry-once-then-fall-back rule as section 1, falling back to the plain delegation form rather than the intake form):

1. `pool_scope.pool_ids` is a subset of the supplied candidates and every named pool is OPEN; `category` matches a candidate's template category. A scope with neither is refused, never widened, exactly as `delegations` already refuses it (`db-schema.md`).
2. `max_total.amount` converts to cents under the section 1 regex and is at or below both the INTAKE proposal's cap and the delegation's own ceiling; `currency` is USD or the field is an ambiguity. The model never raises a cap the buyer stated. The ceiling is enforced **per entry**, exactly as `agentapi/service.py` does today: a delegation that can see several pools may hold one entry in each, each at or below the cap, and nothing sums them. The card must not present the cap as a total across pools.
3. `expires` is not later than the latest candidate's close plus its `delivery_sla_days`, and not earlier than the database clock's date.
4. Every condition names a predicate in the closed vocabulary with matching typed params and an action in the closed set. An unknown predicate is dropped and reported as an ambiguity, never guessed at.
5. Conditions are evaluated by deterministic code against stored state only. A condition the server cannot evaluate from its own rows is rejected, so no condition can require a provider call or a model call to resolve.
6. At most one clarifying question per turn, at most three turns, then the plain delegation form.

Ratification (never skipped, and the reason this task is not a join path): the buyer sees the mandate as rendered text, may edit every field, and confirms. The server stores `mandate_version`, the SHA-256 of the canonical mandate fields and the conditions inside `delegations.scope` (`db-schema.md`), alongside the `ai_runs` row that produced the proposal. The canonical fields are `category`, `conditions` in order, `expires_at` in UTC with milliseconds and a `Z` suffix, `max_cap_cents`, and `pool_ids` sorted and lowercased, serialised as compact JSON with sorted keys in UTF-8; the rendered card is a readability view derived from those same fields. The minting path recomputes that hash and refuses unless the stored hash matches, so a token cannot carry a cap, scope, expiry or condition set the buyer did not ratify. Those keys needed code in `DelegationScope` and `DelegationService.create` (which rebuilt `scope` as exactly `{pool_ids, category}` and silently dropped any other key), and `ai_task` needed `MANDATE` through migration `0007` because it is a PostgreSQL enum fixed in `0001`. Editing the wording requires a new `mandate_version`. A delegation token is minted only from a ratified mandate, and minting still runs every existing delegation rule — the mandate narrows what the token may do and can never widen it.

The mandate is authority, not payment. It authorizes no charge, holds no funds and creates no reservation at PayPal, and an entry created under it still needs a human approval exactly as FR-AG-02 requires.

Evaluation: `backend/tests/ai_eval/data/mandate_cases.jsonl`, at least 25 cases covering a plain cap, a cap with a price ceiling below it, a funding condition, a delivery-date condition, an out-of-scope pool request, a non-USD amount, a relative date phrase that must become an ambiguity, and at least three injected instructions that must not alter the output. Metrics: per-field exact match, predicate-vocabulary adherence, cap-never-raised violations (must be zero), and injected instructions that changed the outcome (must be zero). Reported with the section 6 numbers and subject to the same three-live-run discipline.

## Phase 2 acceptance amendment

Strict JSON rejects duplicate keys, non-finite numbers, trailing prose, unknown
properties and coercions. Monetary extraction is validated against the source;
unknown data stays null. Flags require valid code/field, grounded non-empty
snippet and consistent severity. Ambiguous or ungrounded reconciliation is an
unavailable proposal requiring ops review, never silently consistent.

The synthetic evaluation corpus has 50 intake, 30 quote, 60 reconciliation
(30 consistent, 20 contradictions, 10 ambiguous), and 20 simulation cases.
Run the full live corpus three times and retain every result and retry with
model/prompt/schema/dataset fingerprint. Changing the model invalidates acceptance.
The owner-approved exception for the v5 capacity-validation change uses the
recorded v4 three-run baseline plus v5 live spot checks covering all 50 intake
and 30 quote cases and `reconcile-009`. Both use the same model, schema and
dataset. Report the baseline and v5 results separately; do not call the v4
results a full live run of v5. Independent review identified a single-label
capacity ambiguity; v6 adds a fail-closed guard. A second review found a case
where a field was marked ambiguous but retained a definite value; v7 rejects it.
A third found punctuation and unit variants even without the model marking an
ambiguity; v8 rejects those specific source patterns. Verify each version with
separately labelled live conflict spots and revalidate accepted v4/v5 outputs
offline using the v8 production validator. Do not describe v4/v5 results as a
full v8 run or claim all possible ambiguous wording is recognized.
Further model, prompt, schema or dataset changes
require fresh evaluation unless approved in another contract change.
Zero observed false positives is a measured result, not a future guarantee.
Unpaid Gemini evaluation uses fictional inputs only; confidential data requires
an appropriate paid service under Google's terms.
