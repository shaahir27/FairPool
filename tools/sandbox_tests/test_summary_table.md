| Step | HTTP Status | PayPal Status or Issue | Debug ID | PASS or FAIL |
| :--- | :---: | :--- | :---: | :---: |
| Test 1: Create AUTHORIZE order 1 with Prefer: return=representation (checklist 2.1) | 201 | CREATED | `f44723503582b` | **PASS** |
| Test 1: GET Order 1 verification (checklist 2.2) | 200 | APPROVED (Country: US, Payee: Y6HZPU2WCQH5J, Amount: USD 1.00) | `ca4d5eb17c9da` | **PASS** |
| Test 1: Call authorize on Order 1 (checklist 2.3) | 201 | COMPLETED | `ca4d5eb1f7def` | **PASS** |
| Test 1: Replay authorize with same PayPal-Request-Id (checklist 2.3) | 200 | COMPLETED (Idempotent: True) | `ca4d5eb2bfe2d` | **PASS** |
| Test 1: Capture authorization (checklist 2.4) | 201 | COMPLETED | `ca4d5eb31eeac` | **PASS** |
| Test 1: GET capture confirms COMPLETED (checklist 2.4) | 200 | COMPLETED | `ca4d5eb3bb9e1` | **PASS** |
| Test 1: Replay capture with same ID (checklist 2.4) | 200 | COMPLETED (Single capture confirmed: True) | `ca4d5eb43bdc2` | **PASS** |
| Test 1: Fully refund capture (checklist 2.5) | 201 | COMPLETED | `ca4d5eb4c3a3c` | **PASS** |
| Test 1: GET refund confirms COMPLETED (checklist 2.5) | 200 | COMPLETED | `ca4d5eb566bc4` | **PASS** |
| Test 1: Replay refund with same PayPal-Request-Id (checklist 2.5) | 200 | COMPLETED | `ca4d5eb597e30` | **PASS** |
| Test 1: Authorize Order 2 (checklist 2.6) | 201 | COMPLETED | `ca4d5eb613edc` | **PASS** |
| Test 1: Void authorization (checklist 2.6) [200_WITH_BODY] | 200 | VOIDED | `ca4d5eb68d9d3` | **PASS** |
| Test 1: Replay void WITH PayPal-Request-Id (checklist 2.6) | 422 | UNPROCESSABLE_ENTITY | `ca4d5eb6e1f08` | **PASS** |
| Test 1: Replay void WITHOUT PayPal-Request-Id (checklist 2.6) | 422 | UNPROCESSABLE_ENTITY | `ca4d5eb725c22` | **PASS** |
| Test 1: Try capture after void (checklist 2.6) | 422 | AUTHORIZATION_VOIDED | `ca4d5eb76afe6` | **PASS** |
| Test 2: Partner Referrals onboarding & consent (checklist 3.1) | 403 | NOT_AUTHORIZED | `f103666bd7bdd` | **FAIL** |
| Test 2: Create AUTHORIZE order to second seller without assertion (control) | 201 | CREATED (Payee: Sh1@business.example.com, merchant_id: MISSING) | `f1132451fc70f` | **PASS** |
| Test 2: Create AUTHORIZE order with PayPal-Auth-Assertion (checklist 3.2) | 401 | invalid_subject | `f8946353e4380` | **FAIL** |
| Test 2: Platform fee on purchase unit control (checklist 3.8) | 422 | UNSUPPORTED_PAYMENT_INSTRUCTION | `f51806806ab7e` | **FAIL** |
| Test 2: Order to non-onboarded payee control (checklist 3.8) | 201 | CREATED | `f6128604ac6d5` | **PASS** |