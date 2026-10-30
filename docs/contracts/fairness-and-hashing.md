# Contract: fairness, hashing and money rounding

Two implementations must agree byte for byte: the Python backend (`domain/hashing.py`, `domain/fairness.py`, `domain/money.py`) and the browser verify-my-place widget (`frontend/src/audit/verify.ts`). Both must reproduce every value in `vectors/fairness_v1.json`. Member B owns this contract and writes the vectors test first (task T00B01).

Wording limit (FR-SL-06, I13): this machinery makes selection **auditable under published rules**. Do not call it provably fair or cryptographically verified.

## 1. Canonical JSON

Used wherever a hash or signature covers structured data.

- UTF-8 text, keys sorted by code point, no whitespace, separators `,` and `:`, non-ASCII characters left as is (no `\u` escaping), no trailing newline.
- Only integers, strings, booleans, null, arrays and objects. **Floats are forbidden**; reject them. Keys are ASCII only.
- Python reference: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
- Browser reference: sort keys recursively, then `JSON.stringify` (output matches the Python form for ASCII keys).
- Timestamps inside hashed data are strings in the form `YYYY-MM-DDTHH:MM:SS.ffffffZ` (UTC, six fractional digits).

## 2. Hash prefixes and formats

All hashes are SHA-256 shown as 64 lowercase hex characters. Domain-separation prefixes are fixed strings:

| Name | Formula |
|---|---|
| request_hash | `sha256(canonical_json(canonical_request))` |
| commitment | `sha256("fairpool/commit/v1\|" + pool_id + "\|" + entry_id + "\|" + request_hash + "\|" + salt_hex)` |
| rank_hash | `sha256("fairpool/rank/v1\|" + seed_hex + "\|" + commitment)` |
| demo seed | `sha256("fairpool/demo-seed/v1\|" + pool_id)` |
| lot seed | `sha256("fairpool/lot-seed/v1\|" + seed_hex + "\|" + lot_id)` |
| tie-break | `sha256("fairpool/tiebreak/v1\|" + lot_seed + "\|" + merchant_id)` |
| empty Merkle root | `sha256("fairpool/empty/v1")` |

IDs are lowercase hyphenated UUIDs. `salt_hex` is 32 random bytes as 64 hex characters, generated server-side per entry and revealed only to that buyer in the receipt. All strings are UTF-8 encoded before hashing.

## 3. Entry commitments and Merkle root (pool close)

1. Collect the commitments of all ELIGIBLE entries, sorted ascending as hex strings.
2. Leaf hash: `sha256(0x00 || bytes(commitment))`. Parent hash: `sha256(0x01 || left || right)`.
3. Build level by level. When a level has an odd number of nodes, the last node is promoted to the next level unchanged.
4. The root is stored as `pools.entries_root` with `entries_count`. With no entries the root is the empty root above.
5. Inclusion proof: from leaf to root, a list of `{"side": "L" | "R", "hash": hex}` where `side` says on which side the sibling sits. A promoted node adds no step.
6. Publish the sorted commitment list, root and count at close, **before** the seed exists (I11).

## 4. Seed

- Live: `seed_hex` is the beacon round `randomness` value, lowercase hex (64 characters), from the round announced at publication (the first round whose time is at or after `close_at + beacon_delay_s`). Store the full beacon response in `pools.beacon`. If the round is unavailable, selection waits (F27); there is no fallback chosen by FairPool.
- Demo: `BEACON_MODE=demo` uses the demo seed and sets `seed_is_demo = true`. The UI shows DEMO SEED wherever the seed appears.

## 5. Ranking and lots

- Per delivery zone, compute `rank_hash` for each eligible entry's commitment. Sort ascending by `rank_hash`; ties break on `entry_id` ascending. Position 1 is `rank = 1`.
- Walk the ordered entries once per zone following the lot plan: the first lot takes ranks 1 to its seats, the next lot the following ranks, and so on. Remaining entries are WAITLISTED in rank order. A lot that would receive fewer entries than `min_seats` is created CANCELLED (LS-12) and its entries stay WAITLISTED for refill of other lots in the same zone.
- Assign `lot_order` by zone order in the lot plan, then `lot_index` (N7).
- Waitlist candidate for a vacancy (N12): the first WAITLISTED entry in the same zone, ascending rank, whose cap is at least that lot's total for the entry and whose entry is still ELIGIBLE. Entries that fail the cap test are skipped, not removed.

## 6. Receipts

Entry receipt payload (canonical JSON):

`{"commitment": ..., "entry_id": ..., "pool_id": ..., "received_at": "<timestamp>", "v": 1}`

`signature` is the Ed25519 signature over the canonical JSON bytes, encoded base64url without padding. The public key (raw 32 bytes, base64url) is served at `GET /api/v1/public/keys`. The receipt the buyer keeps is the payload plus `salt_hex`, `request_hash` and `signature`.

**Verify my place** (browser): recompute `commitment` from the receipt, find it in the published list, check the Merkle proof against `entries_root`, compute `rank_hash` with the published seed, sort the published list the same way, and show the resulting rank and lot boundary. It never needs personal data.

Bid receipt: `receipt_hash = sha256(canonical_json({"bid_id", "revision", "structured", "submitted_at", "v": 1}))`; the signature covers `canonical_json({"bid_id", "revision", "receipt_hash", "v": 1})`.

## 7. Rules hash and award hash

- `rules_hash = sha256(canonical_json(rules_document))` where `rules_document` has exactly these keys: `v` (1), `pool_id`, `rule_version`, `template`, `lot_plan`, `timeline`, `require_paypal_link`, `allocation` (`"seeded_lottery_v1"`), `bid_ranking` (`"ranking_v1"`), `refill` (`{"max_refill_waves": n}`), `beacon` (announced source, chain hash and round), `disclosures` (`{"lots_may_differ": true}`). It is computed at publish and shown on the public page (FR-LT-03).
- `award_hash = sha256(canonical_json({"v": 1, "lot_id", "bid_revision_id", "merchant_id", "tier_index", "item_cents", "moq", "totals", "valid_until", "rule_version"}))`.

## 8. Audit chain

`hash = sha256(prev_hash + "|" + canonical_json({"actor", "action", "subject_type", "subject_id", "payload", "created_at"}))`. The first row's `prev_hash` is 64 zeros. `AuditLog.append` takes a global transaction-level advisory lock so rows are chained in order, reads `now()` from the database for `created_at`, then inserts. Checkpoints (the latest hash) are written into the public audit payload at pool close and at award. The chain is tamper-evident only to someone holding a published checkpoint.

## 9. Money, tax and ranking arithmetic

All integer arithmetic, no floats (BD-14).

- `tax_cents = (item_cents * rate_bps + 5000) // 10000`; tax applies to the item price only, shipping is untaxed; tax mode `INCLUDED` gives `tax_cents = 0` and the item price is the delivered item price. Tax is simulated and labelled (non-goal: a tax engine).
- `total_cents = item_cents + shipping_cents + tax_cents` per buyer, using that buyer's zone shipping and region rate.
- `mean_total_cents = (sum(totals) + n // 2) // n` (round half up).
- PayPal strings: `cents -> "D.CC"` with exactly two decimals; parse back with a regex `^\d+\.\d{2}$` and reject anything else.

## 10. Tier resolution, feasibility and bid ranking (ranking_v1)

Given a lot's seated entries and one bid's tiers:

1. For each tier compute each seated entry's total at that tier's item price, shipping for its zone and tax for its region.
2. `n_tier` = number of seated entries whose total is at most their cap.
3. A tier **applies** when `n_tier >= tier.min_qty`. The chosen tier is the applicable tier with the lowest item price. If none applies the bid fails R8 (`R8_NO_FEASIBLE_TIER`).
4. The bid is **feasible** only if the chosen tier's `n_tier >= moq`; otherwise it fails R8 (`R8_INFEASIBLE`).
5. Ranking key, ascending: `(mean_total_cents over the entries who can accept at the chosen tier, max_total_cents over those entries, tie-break hash)`. Lowest key wins (FR-AU-04).

Worked example (also in the vectors): caps `[60000, 55000, 52000, 61000, 49900]`, shipping 1500, tax 875 bps, tiers `[(1, 50000), (3, 47000)]`. Tier 1 total is 55875 and 2 entries can accept; tier 2 total is 52613 and 3 can accept, so both apply and tier index 1 is chosen.

## 11. Capacity across lots (R9)

Process lots in ascending `lot_order`. A merchant's `remaining = total_capacity - sum(seats of lots already awarded to that merchant)`. A bid whose `capacity` for this lot exceeds `remaining` fails R9 (`R9_CAPACITY_EXHAUSTED`) and the next-best bid wins.

## 12. What the vectors file contains

`vectors/fairness_v1.json`: canonical JSON cases, five entries with salts, canonical requests, request hashes and commitments, the sorted commitment list, the Merkle root, an inclusion proof, a seed, the resulting order, the demo seed, an Ed25519 receipt (with the test private key, public key and signature), a two-row audit chain, tax and mean cases, tie-break hashes, and the tier case above. The test private key in the file is for vectors only and must never be used in any environment.
