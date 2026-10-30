# Sandbox Tests & Spike Verification

This directory contains standalone PayPal Sandbox testing scripts and artifacts generated during earlier verification runs.

## Contents

- **`paypal_tester.py`**: Sandbox testing client (`PayPalSandboxTester`) providing helpers for OAuth, order creation, authorization, capture, void, and refund flows.
- **`execute_test_1.py`**: Executes the end-to-end Test 1 flow (creation, buyer approval verification, authorization, capture, and refund).
- **`create_order_2.py`**: Script to create a second order for the void flow.
- **`generate_report.py`**: Compiles `test_1_results.json` and `test_2_results.json` into a Markdown summary table.
- **`test_summary_table.md`**: Markdown report detailing HTTP status, PayPal status/issue, and PayPal Debug IDs for all test steps.
- **`scratch_state.json` / `test_1_results.json` / `test_2_results.json`**: Output states and recorded results from the test runs.
- **`legacy_fairpool_spike_check.py`**: Previous iteration of the spike check script (preserved for reference; the active, updated runner is located at `tools/fairpool_spike_check.py`).

