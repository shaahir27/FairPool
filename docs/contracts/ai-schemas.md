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
4. `max_total.currency` is USD; any other currency becomes an ambiguity. Convert the amount to `max_total_cents` (positive, within the template's bounds).
5. `delivery.region` maps to exactly one zone of the template; otherwise ask.
6. `required_by` is not earlier than the pool's latest delivery date (`fund_by` plus `delivery_sla_days`); otherwise tell the buyer the pool cannot meet the date.
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

Metrics: per-field exact match for enums, integers and dates; ambiguity recall (did it ask when it should); false-confirmation rate (confirmed something wrong); for reconcile, flag-code recall and precision and the count of injected instructions that changed the outcome (must be zero). The README publishes the measured numbers. Phase 2 requires three complete live runs, at least 95% exact extraction accuracy, zero accepted malformed outputs, invented monetary values, unauthorized IDs, unsupported blocking flags or successful injections. Every contradiction must be flagged or routed to review; ambiguous cases remain unresolved. All supplied simulation facts must be preserved. Retain every failure and retry; no acceptance claim while a required check is pending.

## 7. Retrieval and similarity (INT-1, FR-IG-01)

Search is **retrieval**, not AI judgement, and never a gate for requirements (R3 and the deterministic rules stay the only gates).

- **What is indexed:** only public documents: one per pool and one per lot, with `doc_kind`, `pool_id`, `lot_id`, `status`, `product_key`, `condition`, `title`, and a `content` text built from title, variant, condition, bundle contents, zone regions and delivery terms. Never buyer entries, caps, users, requests or quotes.
- **Backend:** `SEARCH_BACKEND=elastic` uses an index per `ELASTIC_INDEX_PREFIX` (default `fairpool`), for example `fairpool-search-v1`, with a `text` field `content` copied (`copy_to`) into a `semantic_text` field `content_embedding` that names an explicit `ELASTIC_INFERENCE_ID` (the docs recommend an explicit inference endpoint for production). Query is hybrid: the `rrf` retriever over a `match` query on `content` and a `semantic` query on `content_embedding`, filtered by `status`. Confirm the exact request shape against Elastic's "Hybrid search with semantic_text" page in spike S8. `SEARCH_BACKEND=postgres` uses `pg_trgm` over `pools.search_text`. Both return the same `SearchHit` shape.
- **Where it is used:** (1) intake candidate retrieval, replacing keyword retrieval (at most 5 candidate pools are passed to INTAKE; the server still validates everything); (2) the merchant Demand Board and `GET /merchant-api/v1/lots?q=`; (3) agent and MCP `q` search; (4) the advisory check below.
- **Advisory wrong-product check:** after a bid revision is confirmed, `similarity_check` runs a semantic-only query over open lots with the quote and notes text. If the lot's own document is not ranked first **and** the top hit has a different `product_key`, create a `bid_flags` row with code `LOW_SIMILARITY`, severity WARNING and a short evidence string. A WARNING never changes a bid's status, never excludes it and never qualifies it; it is shown to the merchant and ops. The check is skipped (no flag) if search is unavailable or the text is empty.
- **Sync:** Postgres is the source of truth. `search.index` jobs upsert documents on publish and status changes; the index can be rebuilt with `POST /api/v1/admin/search/reindex`. Search failure falls back to Postgres and is logged; it never fails a user action.
- **Evaluation:** retrieval quality is measured on the intake cases (does the expected pool appear in the top 5) and reported next to the AI metrics.

## 8. Fake AI (for tests)

`FakeAI` returns scripted outputs keyed by the SHA-256 of the canonical input, can return invalid JSON or time out on demand, and never makes a network call. Unit and integration tests use it; the evaluation and a few smoke tests use the real model.

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
Zero observed false positives is a measured result, not a future guarantee.
Unpaid Gemini evaluation uses fictional inputs only; confidential data requires
an appropriate paid service under Google's terms.
