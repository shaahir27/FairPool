# Graph Report - FairPool  (2026-10-30)

## Corpus Check
- 111 files · ~132,874 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 22 file(s) not represented in the graph (top: (none) 12, .toml 2, .in 2)

## Summary
- 1487 nodes · 2447 edges · 124 communities (81 shown, 43 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 114 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `707f6d63`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Ctx
- now_s
- run_s10
- create_app
- test_end_to_end.py
- tools_fairpool_spike_check_http / tools_fairpool_spike_check_http_init / tools_fairpool_spike_check_http_request
- logging.py
- pytest
- export_merchant_openapi.py
- tools_spike_check_tests_mock_paypal_deliver / tools_spike_check_tests_mock_paypal_deliver_post / tools_spike_check_tests_mock_paypal_err
- tools_spike_check_tests_mock_services_beacon / tools_spike_check_tests_mock_services_drand / tools_spike_check_tests_mock_services_drand_do_get
- tools_fairpool_spike_check_webhooklistener / tools_fairpool_spike_check_webhooklistener_init / tools_fairpool_spike_check_webhooklistener_init_do_get
- test_fairness_vectors.py
- FairPool: Group Buying Where Merchants Compete for the Group
- check_imports.py
- fairpool_spike_check.py
- IllegalTransition
- 4. Phase-by-phase lanes
- test_pt03_commitments.py
- Progress
- test_check_imports.py
- auction_rules.py
- config.py
- 1. Functional requirements
- test_state_machines_contract.py
- McpStdio
- Settings
- domain/errors.py
- HashingError
- 3. Payload shapes (key endpoints)
- hashing.py
- money.py
- test_branches.py
- sha256_hex
- Spike results
- FairPool: System Design and Solution Architecture (v1)
- Spikes
- canonical_json
- agents.md: rules for AI coding agents
- Tables
- Scaffold
- test_pt05_tiers.py
- McpStdio
- PH8: Fulfillment, verification, merchant console and simulation (gate IG-8)
- 11. Layer 8: Checkout and PayPal orchestration (idea sections 6 and 7)
- test_pt07_transitions.py
- FairPool docs index
- Contract: ports, jobs and handoffs
- Contract: fairness, hashing and money rounding
- Vault and charge: the buyer payment path (PAYMENT_MODE=vault_charge)
- Implementation plan
- PH3: Core engines II: buyer-order engine, seat control, join, search, PayPal Login, pool close (gate IG-3)
- PH7: Live end to end and the agent and merchant lanes (gate IG-7)
- PH9: Hardening, evaluation and feature freeze (gate IG-9)
- Registry of IDs
- Contract: AI tasks, schemas and evaluation
- Demo and submission
- PH2: Core engines I: PayPal gateway, ledger, identity, catalog, AI adapter (gate IG-2)
- PH6: Money completion and auction to checkout (gate IG-6)
- 10. Layer 7: Merchant and auction engine (idea section 5)
- test_validate_docs.py
- PH0: Bootstrap and contract freeze (gate IG-0)
- PH10: Rehearsals and release candidate (gate IG-10)
- PH1: Data, platform and shell foundations (gate IG-1)
- PH4: Core engines III and the first integration (gate IG-4)
- 9. Layer 6: Pool engine (idea sections 3 and 4)
- Testing strategy
- PH5: Real PayPal path, auction core and merchant foundation (gate IG-5)
- Spike check runbook
- 12. Layer 9: Webhooks, reconciliation and idempotency
- contract-change.md
- PULL_REQUEST_TEMPLATE.md
- mock_mcp_server.py
- Contracts
- 4. Layer 1: System context and architecture style
- 7. Layer 4: Identity and duplicate-entry control (idea section 1)
- 8. Layer 5: Request intake and AI (idea section 2)
- 13. Layer 10: Agent (A2A) lane
- 17. Layer 14: Platform, observability and testing
- 3. Evidence base from your two MD files
- 5. Layer 2: Data model
- 6. Layer 3: State machines
- Contract: configuration, errors and reason codes
- 20. Build plan
- test_get_settings_is_cached
- AGENTS.md
- fairpool

## God Nodes (most connected - your core abstractions)
1. `Ctx` - 35 edges
2. `Resp` - 30 edges
3. `cmd_run()` - 30 edges
4. `PayPal` - 26 edges
5. `FairPool: System Design and Solution Architecture (v1)` - 26 edges
6. `make_settings()` - 24 edges
7. `create_app()` - 23 edges
8. `run_s10()` - 20 edges
9. `Implementation plan` - 20 edges
10. `Settings` - 19 edges

## Surprising Connections (you probably didn't know these)
- `Contract: configuration, errors and reason codes` --references--> `Settings`  [INFERRED]
  docs/contracts/config-and-errors.md → backend/src/fairpool/config.py
- `Test obligations` --references--> `IllegalTransition`  [INFERRED]
  docs/contracts/state-machines.md → backend/src/fairpool/domain/errors.py
- `5. Ranking and lots` --references--> `rank_hash()`  [INFERRED]
  docs/contracts/fairness-and-hashing.md → backend/src/fairpool/domain/hashing.py
- `Public audit` --references--> `rules_hash()`  [INFERRED]
  docs/contracts/api.md → backend/src/fairpool/domain/hashing.py
- `Public audit` --references--> `award_hash()`  [INFERRED]
  docs/contracts/api.md → backend/src/fairpool/domain/hashing.py

## Import Cycles
- None detected.

## Communities (124 total, 43 thin omitted)

### Community 0 - "Ctx"
Cohesion: 0.12
Nodes (23): approval_checks(), ask(), ask_yes(), authorize_flow(), cleanup(), cmd_run(), confirm_stage(), create_and_approve() (+15 more)

### Community 1 - "now_s"
Cohesion: 0.16
Nodes (12): bls_verify_quicknet(), link_of(), load_env_file(), log(), now_s(), poll_capture(), round_at_or_after(), run_s13() (+4 more)

### Community 2 - "run_s10"
Cohesion: 0.13
Nodes (9): classify_tools(), discover_paypal_mcp_permissions(), mcp_reply_ok(), McpError, McpHttp, McpSse, run_s10(), run_s9() (+1 more)

### Community 3 - "create_app"
Cohesion: 0.05
Nodes (27): add_request_id(), create_app(), current_request_id(), error_response(), http_exception_handler(), register_exception_handlers(), unhandled_exception_handler(), validation_exception_handler() (+19 more)

### Community 4 - "test_end_to_end.py"
Cohesion: 0.16
Nodes (6): start(), State, serve(), fake_open(), http_post(), sim_page()

### Community 5 - "tools_fairpool_spike_check_http / tools_fairpool_spike_check_http_init / tools_fairpool_spike_check_http_request"
Cohesion: 0.09
Nodes (17): 10. Demo mock toggles, 11. Sandbox contract tests, 12. JavaScript SDK v6 server obligations (INT-7), 14. Never, 1. Host guard, 2. Types and ports, 3. Idempotency keys, 4. Call catalogue (+9 more)

### Community 6 - "logging.py"
Cohesion: 0.05
Nodes (22): get_settings(), configure_logging(), JsonFormatter, _mask_key_value(), redact_text(), RedactionFilter, install_signal_handlers(), main() (+14 more)

### Community 7 - "pytest"
Cohesion: 0.16
Nodes (22): env_example_names(), make_settings(), test_ai_enabled_requires_anthropic_key(), test_cors_origins_parse_as_a_tuple(), test_country_list_is_uppercase_iso2_tuple(), test_drand_requires_url_and_chain_hash(), test_each_literal_rejects_an_invalid_value(), test_effective_defaults_and_redirect_derivation() (+14 more)

### Community 8 - "export_merchant_openapi.py"
Cohesion: 0.10
Nodes (10): _check(), _contract_operation_ids(), ExportError, _find_merchant_spec(), _generated_operations(), _load_app(), main(), dfs() (+2 more)

### Community 9 - "tools_spike_check_tests_mock_paypal_deliver / tools_spike_check_tests_mock_paypal_deliver_post / tools_spike_check_tests_mock_paypal_err"
Cohesion: 0.21
Nodes (4): deliver(), post(), err(), H

### Community 11 - "tools_fairpool_spike_check_webhooklistener / tools_fairpool_spike_check_webhooklistener_init / tools_fairpool_spike_check_webhooklistener_init_do_get"
Cohesion: 0.22
Nodes (3): webhook_setup(), WebhookListener, do_POST()

### Community 12 - "test_fairness_vectors.py"
Cohesion: 0.07
Nodes (32): AllocationError, Allocation, AllocationResult, assign_lots(), EntryCommitment, LotSpec, PlannedLot, rank_order() (+24 more)

### Community 14 - "FairPool: Group Buying Where Merchants Compete for the Group"
Cohesion: 0.06
Nodes (34): 10. Integrations, 11. Claims, 12. Scope, 13. Demonstration, 14. Open decisions and open questions, 15. Revision notes, 1. At a glance, 2.1 Buyers cannot reach volume prices alone (+26 more)

### Community 15 - "check_imports.py"
Cohesion: 0.18
Nodes (19): _check_import(), _decorator_strings(), _frontend_area(), _group(), _import_targets(), _is_ai_run_target(), _is_area_index(), _is_under() (+11 more)

### Community 16 - "fairpool_spike_check.py"
Cohesion: 0.12
Nodes (17): camel(), cmd_check_env(), cmd_list(), env_missing(), ForbiddenHost, guard_paypal_hosts(), load_openapi(), main() (+9 more)

### Community 17 - "IllegalTransition"
Cohesion: 0.10
Nodes (16): DomainError, IllegalTransition, UnknownMachine, assert_transition(), is_legal(), Machine, _machine(), Transition (+8 more)

### Community 18 - "4. Phase-by-phase lanes"
Cohesion: 0.07
Nodes (27): 10. Conflict avoidance, 11. Blocked, behind or idle, 12. Ordered task lists, 1. Flow at a glance, 2. Ownership map, 3. First 48 hours (PH0), in order, 4. Phase-by-phase lanes, 5. Merge points (+19 more)

### Community 19 - "test_pt03_commitments.py"
Cohesion: 0.13
Nodes (20): CanonicalJSONError, _award_document(), _b64url_chars(), _canonical_values(), _rules_document(), _scalars(), test_award_hash_is_the_canonical_snapshot_hash(), test_bid_receipt_hash_binds_the_revision() (+12 more)

### Community 20 - "Progress"
Cohesion: 0.08
Nodes (25): Blockers, Daily log, Decisions log, Defects from rehearsals, Gates, Open questions, PH0: Bootstrap and contract freeze, PH10: Rehearsals and release candidate (+17 more)

### Community 21 - "test_check_imports.py"
Cohesion: 0.26
Nodes (20): _load_checker(), _rules(), _scan(), test_ai_adapter_allows_its_declared_imports(), test_ai_adapter_rejects_checkout_and_other_sdks(), test_cli_exits_zero_on_clean_tree(), test_cli_prints_file_line_rule_and_exits_one(), test_current_tree_is_clean() (+12 more)

### Community 22 - "auction_rules.py"
Cohesion: 0.17
Nodes (14): AwardedLot, bid_ranking_key(), capacity_ok(), evaluate_tiers(), remaining_capacity(), _require_int(), resolve_tiers(), SeatedBuyer (+6 more)

### Community 23 - "config.py"
Cohesion: 0.13
Nodes (9): assert_sandbox_host(), ForbiddenHost, test_checkout_host_is_not_accepted_in_place_of_api_host(), test_create_app_accepts_validated_sandbox_settings(), test_create_app_rechecks_hosts_on_a_hand_built_object(), test_non_sandbox_origins_raise_forbidden_host(), test_sandbox_origins_are_accepted(), test_settings_reject_live_api_host() (+1 more)

### Community 24 - "1. Functional requirements"
Cohesion: 0.09
Nodes (21): 1. Functional requirements, 2. Non-goals, 3. Claims we may and may not make, 4. Demo scope, 5.1 Gaps in the idea that the design filled, 5. Idea alignment audit, 6. Challenge register, Agent lane, audit, operations, simulation (+13 more)

### Community 25 - "test_state_machines_contract.py"
Cohesion: 0.12
Nodes (12): _enum_values(), _job_kinds(), _table_rows(), test_every_unlisted_pair_raises(), test_job_and_ledger_effects_name_known_kinds(), test_states_equal_db_schema_enum(), test_states_initial_and_terminal_match_yaml(), test_transitions_match_yaml() (+4 more)

### Community 26 - "McpStdio"
Cohesion: 0.20
Nodes (3): Recorder, Redactor, Row

### Community 27 - "Settings"
Cohesion: 0.13
Nodes (7): Settings, contract_defaults(), expected_default(), plain(), test_contract_has_sixty_variables(), test_defaults_match_contract(), test_field_names_match_contract_exactly()

### Community 28 - "domain/errors.py"
Cohesion: 0.19
Nodes (9): _half_up(), test_mean_matches_round_half_up_and_stays_within_bounds(), test_money_rejects_booleans_and_negatives(), test_money_rejects_floats(), test_parse_rejects_malformed_strings(), test_parse_rejects_non_strings(), test_paypal_string_round_trips(), test_tax_matches_round_half_up() (+1 more)

### Community 29 - "HashingError"
Cohesion: 0.16
Nodes (10): HashingError, inclusion_proof(), leaf_hash(), merkle_root(), MerkleStep, _next_level(), parent_hash(), _require_hex64() (+2 more)

### Community 30 - "3. Payload shapes (key endpoints)"
Cohesion: 0.10
Nodes (19): 1. Conventions, 2. Endpoint table, 3. Payload shapes (key endpoints), 4.1 Checkout with the PayPal JavaScript SDK v6 (INT-7, FR-IG-06), 4.2 Merchant console endpoints (session), 4.3 Merchant Agent API (INT-9, FR-IG-04), 4.4 Agent API additions (FR-AG-01, INT-2, INT-3), 4.5 FairPool MCP server (INT-3, FR-IG-02) (+11 more)

### Community 31 - "hashing.py"
Cohesion: 0.13
Nodes (8): _b64url(), _b64url_decode(), bid_receipt_payload(), ed25519_public_key(), _private_key(), receipt_payload(), sign_ed25519(), verify_ed25519()

### Community 32 - "money.py"
Cohesion: 0.13
Nodes (10): MoneyError, _as_cents(), mean_total_cents(), parse_paypal_string(), tax_cents(), to_paypal_string(), total_cents(), Flat delivered bids (BID_PRICING_MODE=flat_delivered) (+2 more)

### Community 34 - "sha256_hex"
Cohesion: 0.15
Nodes (9): commitment(), demo_seed(), lot_seed(), rank_hash(), request_hash(), sha256_hex(), tiebreak_hash(), 5. Ranking and lots (+1 more)

### Community 35 - "Spike results"
Cohesion: 0.12
Nodes (16): Final available Sandbox verification, recorded Oct 29, 2026 (from the owner's report of the same date), Owner Sandbox runs, recorded Oct 28, 2026 (from `FAIRPOOL_BUILD_HANDOFF.md`), S10: PayPal MCP read-only verification (G14). RECORDED Oct 28, 2026, S11: APIMatic SDK and portal generation (G15). DEFERRED, S12: PayPal shipment tracking (G16). RECORDED Oct 28, 2026, S13: JavaScript SDK v6 approval (G17). RECORDED Oct 28, 2026, S1: Log in with PayPal (G1, G2). RECORDED Oct 28, 2026, S2: authorization capture and idempotency (G3). RECORDED Oct 20, 2026 (+8 more)

### Community 36 - "FairPool: System Design and Solution Architecture (v1)"
Cohesion: 0.12
Nodes (15): 0. How to read this document, 14.1 Isolation by pool mode, 14.2 What it produces, 14. Layer 11: Synthetic rehearsal engine, 15. Layer 12: Experience layer, 16. Layer 13: Security, privacy and compliance, 18. Cross-component impact matrix, 19. Failure-mode catalogue (+7 more)

### Community 37 - "Spikes"
Cohesion: 0.05
Nodes (33): 1. Checked and correct, 2. Corrected, 3. Your integration notes versus the design, 4. Not settled by documents (only live runs can settle), 5. Schedule risk (decision for the owner), 6. Spike check script (added Oct 28, 2026), 7. Owner Sandbox runs incorporated (Oct 28, 2026), 8. Vault-and-charge and flat delivered bids (Oct 29, 2026) (+25 more)

### Community 38 - "canonical_json"
Cohesion: 0.20
Nodes (7): audit_hash(), award_hash(), bid_receipt_hash(), canonical_json(), _require_exact_keys(), rules_hash(), _validate_canonical()

### Community 39 - "agents.md: rules for AI coding agents"
Cohesion: 0.14
Nodes (13): 10. Standard prompt a member gives an agent, 11. Things that will fail review, 1. Read order for any task, 2. Source-of-truth order, 3. Hard rules (invariants I1 to I15 made concrete), 4. Engineering standards, 4a. Development-time agent tooling, 5. PayPal handling rules (from the checklist and sandbox report) (+5 more)

### Community 40 - "Tables"
Cohesion: 0.14
Nodes (13): Allocation and lots, Catalog and pools, Checkout and PayPal mirrors, Contract: database schema, Conventions, Enums, Identity, JSON shapes (+5 more)

### Community 41 - "Scaffold"
Cohesion: 0.14
Nodes (13): 10. Bootstrap (task T00A01, in this order), 11. Render deployment, 12. Frontend routes, 1. Repository layout, 2. Tooling, 3. Make targets, 4. Containers, 5. Import boundaries (enforced by `tools/check_imports.py`) (+5 more)

### Community 42 - "test_pt05_tiers.py"
Cohesion: 0.18
Nodes (6): BidCandidate, rank_bids(), test_capacity_never_exceeds_merchant_total(), test_rank_bids_sorts_by_key_and_is_a_permutation(), test_tiebreak_is_deterministic_and_merchant_specific(), test_tier_resolution_rejects_invalid_inputs()

### Community 44 - "PH8: Fulfillment, verification, merchant console and simulation (gate IG-8)"
Cohesion: 0.17
Nodes (12): PH8: Fulfillment, verification, merchant console and simulation (gate IG-8), T08A01: Fulfillment backend: progress, fulfillment, shipments, manifest, verification, T08A02: Fulfillment tab UI, T08A03: Merchant Agent API: fulfillment, shipments, manifest and verification routes, T08A04: PayPal MCP verification copilot, T08A05: Observability, T08A06: Security pass, T08B01: Merchant console UI I: Demand Board and bid submission (+4 more)

### Community 45 - "11. Layer 8: Checkout and PayPal orchestration (idea sections 6 and 7)"
Cohesion: 0.17
Nodes (12): 11.10 Happy-path sequence, 11.11 Fulfillment and verification (INT-6, INT-8), 11.1 Two switches: router and mode, 11.2 Time constraints, 11.3 Order creation: the payload ladder, 11.4 Approval handling (redirect first, D10; superseded by INT-7), 11.5 Authorization with a seat lock, 11.6 Funding decision (+4 more)

### Community 46 - "test_pt07_transitions.py"
Cohesion: 0.18
Nodes (4): test_a_trigger_selects_only_listed_transitions(), test_every_pair_of_states(), test_random_state_pairs_follow_the_whitelist(), test_unknown_machines_are_rejected()

### Community 47 - "FairPool docs index"
Cohesion: 0.18
Nodes (8): 1. Read order, 2. File map, 3. Which source wins, 4. Placing the files, 5. Current state of decisions, 6. Ground rules in one paragraph, FairPool docs index, FairPool

### Community 48 - "Contract: ports, jobs and handoffs"
Cohesion: 0.18
Nodes (10): 1. Rules for every port and service, 2. Platform ports (implemented by Member A, task T01A02; used by both), 3. Edge ports (implemented by Member B unless noted), 4.1 `AllocationReadService` (Member B implements; Member A calls), 4.2 `MerchantDirectory` (Member B implements; Member A calls), 4.3 Checkout surface for the API layer (Member A implements; Member B's UI calls via HTTP only), 4. Cross-member services, 5. Job kinds (+2 more)

### Community 49 - "Contract: fairness, hashing and money rounding"
Cohesion: 0.12
Nodes (13): Public audit, 10. Tier resolution, feasibility and bid ranking (ranking_v1), 11. Capacity across lots (R9), 12. What the vectors file contains, 1. Canonical JSON, 2. Hash prefixes and formats, 3. Entry commitments and Merkle root (pool close), 4. Seed (+5 more)

### Community 50 - "Vault and charge: the buyer payment path (PAYMENT_MODE=vault_charge)"
Cohesion: 0.18
Nodes (10): 1. What changes for the buyer, 2. Flow and adapter calls (all deterministic code; never an AI call, FR-IG-09), 3. State machine deltas, 4. Cap and eligibility rules (integer math only), 5. Token security, 6. Consent text (exact wording lives in the web app; `VAULT_CONSENT_VERSION` names it), 7. Failure handling, 8. Limits and owner decisions still open (+2 more)

### Community 51 - "Implementation plan"
Cohesion: 0.18
Nodes (11): 1. Principles, 2. Phases at a glance, 3. Gates, 4. Capacity check (computed from the task sizes), 5. Integration traceability, 6. Requirement coverage, 7. Sizing and conventions, Implementation plan (+3 more)

### Community 52 - "PH3: Core engines II: buyer-order engine, seat control, join, search, PayPal Login, pool close (gate IG-3)"
Cohesion: 0.18
Nodes (11): PH3: Core engines II: buyer-order engine, seat control, join, search, PayPal Login, pool close (gate IG-3), T03A01: Buyer-order transition engine, T03A02: Offer expiry and seat control, T03A03: Spike S5 webhooks, T03A04: Spike S10 PayPal MCP read-only verification, T03A05: Spike S12 shipment tracking, T03B01: Pool join, receipts and events, T03B02: Search service and indexer (+3 more)

### Community 53 - "PH7: Live end to end and the agent and merchant lanes (gate IG-7)"
Cohesion: 0.18
Nodes (11): PH7: Live end to end and the agent and merchant lanes (gate IG-7), T07A01: JavaScript SDK v6 approval, T07A02: Refill orchestration, T07A03: Routers per S3 and S7, T07A04: Ops console v1, T07B01: Buyer UI v2: My Pools and Orders, T07B02: Agent API and delegations, T07B03: FairPool MCP server (+3 more)

### Community 54 - "PH9: Hardening, evaluation and feature freeze (gate IG-9)"
Cohesion: 0.18
Nodes (11): PH9: Hardening, evaluation and feature freeze (gate IG-9), T09A01: Fault-injection suite, T09A02: Sandbox contract suite complete, T09A03: Deployment hardening and demo tooling, T09A04: STRETCH: top-up after FUNDED, T09B01: Public audit page and verify-my-place, T09B02: AI evaluation sets and runner, T09B03: Concurrency and property suites for pools, allocation and auction (+3 more)

### Community 55 - "Registry of IDs"
Cohesion: 0.18
Nodes (10): Auction rules (design section 10.4), Design decisions (design section 21; status in `docs/decisions.md`), Failure modes (design section 19), Invariants (never break; design section 2), Open gates (design section 3.3 plus G11 to G17; spikes in `docs/spikes.md`; results in `docs/spike-results.md`), PayPal-documented, untested (design section 3.2), Registry of IDs, Spikes (design section 20.1 plus S7 to S13; plans in `docs/spikes.md`) (+2 more)

### Community 56 - "Contract: AI tasks, schemas and evaluation"
Cohesion: 0.20
Nodes (9): 1. Rules for every task, 2. Task INTAKE (buyer text to proposal), 3. Task QUOTE (merchant quote to proposed fields, DEP-2), 4. Task RECONCILE (flags only), 5. Task SIM_TEXT (simulation variety), 6. Evaluation (FR-AI-05), 7. Retrieval and similarity (INT-1, FR-IG-01), 8. Fake AI (for tests) (+1 more)

### Community 57 - "Demo and submission"
Cohesion: 0.20
Nodes (9): 1. What must be submitted, 2. Demo data rules, 3. Three-minute storyboard (hard limit 3:00; target 2:50), 4. Rehearsal procedure, 5. README outline (task T09X01; Member A writes the PayPal, operations and run sections, Member B the product, fairness, AI, search and agent sections), 6. Devpost fields, 7. Final QA checklist (task T11X01), 8. After submission (task T11X02) (+1 more)

### Community 58 - "PH2: Core engines I: PayPal gateway, ledger, identity, catalog, AI adapter (gate IG-2)"
Cohesion: 0.20
Nodes (10): PH2: Core engines I: PayPal gateway, ledger, identity, catalog, AI adapter (gate IG-2), T02A01: PayPal gateway (raw REST), T02A02: Payment routers and fake gateway, T02A03: Ledger service, T02A04: Spike S4 payload ladder, T02B01: Identity and notifier, T02B02: Catalog, pool templates, admin publish and rules, T02B03: AI adapter and run logging (+2 more)

### Community 59 - "PH6: Money completion and auction to checkout (gate IG-6)"
Cohesion: 0.20
Nodes (10): PH6: Money completion and auction to checkout (gate IG-6), T06A01: Funding sweep and failure path on the real Sandbox, T06A02: Webhooks, T06A03: Reconciler and unknown-outcome resolution, T06A04: Payload ladder levels and shipping address, T06B01: Quote parsing and confirmation, T06B02: AI offer reconciliation and flags, T06B03: Lot handlers: bid_open, bid_close, award (+2 more)

### Community 60 - "10. Layer 7: Merchant and auction engine (idea section 5)"
Cohesion: 0.20
Nodes (10): 10.1 Merchants, 10.2 Bid schema (merchant-confirmed structured fields are authoritative), 10.3 Sealing, 10.4 Rule pipeline (deterministic, in this order), 10.5 AI quote parsing and offer reconciliation, 10.6 Tiers, feasibility and ranking, 10.7 Award snapshot and price-out, 10.8 Edge cases (+2 more)

### Community 61 - "test_validate_docs.py"
Cohesion: 0.48
Nodes (3): _run(), test_broken_fixture_fails_with_nonzero_exit(), test_real_docs_have_zero_errors()

### Community 62 - "PH0: Bootstrap and contract freeze (gate IG-0)"
Cohesion: 0.22
Nodes (9): PH0: Bootstrap and contract freeze (gate IG-0), T00A01: Repository bootstrap, T00A02: Secrets hygiene, T00A03: API and worker skeleton, settings, host guard, T00A04: Containers, CI and repo tools, T00B01: Pure domain library with shared vectors, T00B02: Spike S1 Log in with PayPal, T00B03: Spike S7 payee-email routing (+1 more)

### Community 63 - "PH10: Rehearsals and release candidate (gate IG-10)"
Cohesion: 0.22
Nodes (9): PH10: Rehearsals and release candidate (gate IG-10), T10A01: Fixes from rehearsal 1 (payments, ops, fulfillment), T10A02: Repository cleanup and compliance, T10A03: Devpost text, T10A04: Merchant SDKs and developer portal, T10B01: Fixes from rehearsal 1 (product, UI, agent lane), T10B02: Demo video, T10X01: Rehearsal 1 (+1 more)

### Community 64 - "PH1: Data, platform and shell foundations (gate IG-1)"
Cohesion: 0.22
Nodes (9): PH1: Data, platform and shell foundations (gate IG-1), T01A01: Database foundation and migration 0001, T01A02: Platform services, T01A03: Deploy the skeleton to Render, T01A04: Spike S2 follow-up, T01B01: API schemas, route-table test and Merchant API OpenAPI, T01B02: Port fakes and award fixture, T01B03: Frontend scaffold (+1 more)

### Community 65 - "PH4: Core engines III and the first integration (gate IG-4)"
Cohesion: 0.22
Nodes (9): PH4: Core engines III and the first integration (gate IG-4), T04A01: lot.open_checkout handler, T04A02: Approval checks and authorization flow (fake router), T04A03: Funding trigger and capture sweep (fake router), T04B01: Intake pipeline, T04B02: Beacon adapter and pool.seed, T04B03: Allocation and AllocationReadService, T04B04: Public audit endpoint and keys (+1 more)

### Community 66 - "9. Layer 6: Pool engine (idea sections 3 and 4)"
Cohesion: 0.22
Nodes (9): 9.1 What is fixed before the pool opens, 9.2 Timeline and defaults, 9.3 Join (concurrency-safe), 9.4 Close, 9.5 Seed and ordering, 9.6 Lots and waitlist, 9.7 Vacancy and refill (bounded waves), 9.8 What this layer can and cannot claim (+1 more)

### Community 67 - "Testing strategy"
Cohesion: 0.22
Nodes (8): 1. Layers, 2. Property tests, 3. Integration acceptance tests (one per gate), 4. Fault matrix (F1 to F30), 5. Checklist mapping, 6. Rules for writing tests, Testing strategy, Vault-mode additions (`PAYMENT_MODE=vault_charge`, Oct 29)

### Community 68 - "PH5: Real PayPal path, auction core and merchant foundation (gate IG-5)"
Cohesion: 0.29
Nodes (7): PH5: Real PayPal path, auction core and merchant foundation (gate IG-5), T05A01: Real PayPal path for one buyer (redirect), T05A02: Checkout UI, T05A03: Failure path and compensating refund (fake router), T05B01: Merchant profile and onboarding states, T05B02: Bid API with receipts and sealing, T05B03: Auction rules engine

### Community 69 - "Spike check runbook"
Cohesion: 0.29
Nodes (6): How far the script itself is verified (read this), How to run, Spike check runbook, What it cannot do yet (it reports BLOCKED, not PASS), What it does not cover, What you must provide

### Community 70 - "12. Layer 9: Webhooks, reconciliation and idempotency"
Cohesion: 0.29
Nodes (7): 12.1 Who is the authority, 12.2 Ingest, 12.3 Processing, 12.4 Reconciler, 12.5 Retry policy, 12.6 Crash safety, 12. Layer 9: Webhooks, reconciliation and idempotency

### Community 71 - "contract-change.md"
Cohesion: 0.29
Nodes (6): Affected tasks and owners, Approval, Change, Contract file and section, Migration or code impact, Reason

### Community 72 - "PULL_REQUEST_TEMPLATE.md"
Cohesion: 0.29
Nodes (6): Acceptance, Contracts, Invariants, Notes, Task, Verification

### Community 73 - "mock_mcp_server.py"
Cohesion: 0.32
Nodes (3): create_order(), get_order(), list_transaction()

### Community 74 - "Contracts"
Cohesion: 0.33
Nodes (5): Change log, Contract notes (ambiguities in the design resolved here), Contracts, Files, Rules

### Community 75 - "4. Layer 1: System context and architecture style"
Cohesion: 0.33
Nodes (6): 4.1 Context, 4.2 Decision: modular monolith, 4.3 Component necessity check, 4.4 Module map and dependency rule, 4.5 Sponsor and partner tools: layer, usage and fallback, 4. Layer 1: System context and architecture style

### Community 76 - "7. Layer 4: Identity and duplicate-entry control (idea section 1)"
Cohesion: 0.33
Nodes (6): 7.1 Purpose and limits, 7.2 Flow, 7.3 Where each key is enforced, 7.4 Outcome matrix, 7.5 Failure modes, 7. Layer 4: Identity and duplicate-entry control (idea section 1)

### Community 77 - "8. Layer 5: Request intake and AI (idea section 2)"
Cohesion: 0.33
Nodes (6): 8.1 Where AI sits, 8.2 Pipeline, 8.3 AI contract, 8.4 Evaluation, 8.5 Failure modes, 8. Layer 5: Request intake and AI (idea section 2)

### Community 78 - "13. Layer 10: Agent (A2A) lane"
Cohesion: 0.40
Nodes (5): 13.1 What the lane is, 13.2 Endpoints and delegation, 13.3 Behaviour that keeps the invariants, 13.4 Tools in this layer (INT-2, INT-3, INT-6, INT-9), 13. Layer 10: Agent (A2A) lane

### Community 79 - "17. Layer 14: Platform, observability and testing"
Cohesion: 0.40
Nodes (5): 17.1 Deployment, 17.2 Observability, 17.3 Test layers, 17.4 How your checklist maps onto the design, 17. Layer 14: Platform, observability and testing

### Community 80 - "3. Evidence base from your two MD files"
Cohesion: 0.40
Nodes (5): 3.1 Verified facts and what each one forces, 3.2 Documented by PayPal, not yet tested, 3.3 Open gates (each needs a spike), 3.4 Hackathon constraints that shape the design, 3. Evidence base from your two MD files

### Community 81 - "5. Layer 2: Data model"
Cohesion: 0.40
Nodes (5): 5.1 Ground rules, 5.2 Entities, 5.3 Money rules, 5.4 Privacy, 5. Layer 2: Data model

### Community 82 - "6. Layer 3: State machines"
Cohesion: 0.40
Nodes (5): 6.1 Pool and lot lifecycles, 6.2 Lot transitions, 6.3 Buyer-order (seat) transitions, 6.4 Rules, 6. Layer 3: State machines

### Community 83 - "Contract: configuration, errors and reason codes"
Cohesion: 0.29
Nodes (6): 1. Environment variables, 2. Timing profiles, 3. Rate limits, 4. Error codes, 5. Reason codes, Contract: configuration, errors and reason codes

### Community 84 - "20. Build plan"
Cohesion: 0.50
Nodes (4): 20.1 Step 0 and spikes, 20.2 Schedule, 20.3 Three-minute demo storyboard (no brand names on screen), 20. Build plan

## Knowledge Gaps
- **1 isolated node(s):** `fairpool`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 834 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **43 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Resp` connect `tools_fairpool_spike_check_http / tools_fairpool_spike_check_http_init / tools_fairpool_spike_check_http_request` to `fairpool_spike_check.py`, `Ctx`, `Spikes`, `now_s`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `cmd_run()` (e.g. with `run_core()` and `run_s1()`) actually correct?**
  _`cmd_run()` has 12 INFERRED edges - model-reasoned connections that need verification._
- **What connects `fairpool` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Ctx` be split into smaller, more focused modules?**
  _Cohesion score 0.12280701754385964 - nodes in this community are weakly interconnected._
- **Why does `Settings` connect `Settings` to `create_app`, `logging.py`, `pytest`, `Contract: configuration, errors and reason codes`, `test_get_settings_is_cached`, `config.py`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Should `run_s10` be split into smaller, more focused modules?**
  _Cohesion score 0.1330049261083744 - nodes in this community are weakly interconnected._
- **Why does `H` connect `tools_spike_check_tests_mock_paypal_deliver / tools_spike_check_tests_mock_paypal_deliver_post / tools_spike_check_tests_mock_paypal_err` to `test_end_to_end.py`?**
  _High betweenness centrality (0.020) - this node is a cross-community bridge._