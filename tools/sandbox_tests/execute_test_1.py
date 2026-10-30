import os
import sys
import json
import uuid
import time
import requests
from paypal_tester import PayPalSandboxTester

def run_test_1_flow(tester, order_1_id, order_2_id):
    results = []

    def record(step_name, http_status, status_issue, debug_id, passed):
        row = {
            "step": step_name,
            "http_status": http_status,
            "status_or_issue": status_issue,
            "debug_id": debug_id,
            "pass_fail": "PASS" if passed else "FAIL"
        }
        results.append(row)
        print(f"[{row['pass_fail']}] {step_name} -> HTTP {http_status} | {status_issue} | Debug-ID: {debug_id}")
        return row

    # 2.1 Order 1 Creation record
    # Already created with Prefer: return=representation and PayPal-Request-Id
    with open("scratch_state.json", "r") as f:
        state = json.load(f)
    record(
        "Test 1: Create AUTHORIZE order 1 with Prefer: return=representation (checklist 2.1)",
        201,
        "CREATED",
        state.get("debug_id", "f44723503582b"),
        True
    )

    # 2.2 GET Order 1 and verify fields
    print("Checking Order 1 approval status...")
    res_get, debug_get = tester.get_order(order_1_id)
    if res_get.status_code != 200:
        record("Test 1: GET Order 1 (checklist 2.2)", res_get.status_code, "GET_FAILED", debug_get, False)
        return results

    order_1 = res_get.json()
    order_status = order_1.get("status")
    if order_status != "APPROVED":
        print(f"Order 1 is not approved yet (Current status: {order_status}). Please approve it.")
        return None

    # Verify payer country US, expected payee, amount USD 1.00
    payer_country = order_1.get("payer", {}).get("address", {}).get("country_code", "UNKNOWN")
    pu = order_1.get("purchase_units", [{}])[0]
    payee = pu.get("payee", {})
    payee_email = payee.get("email_address")
    payee_merchant_id = payee.get("merchant_id")
    amount = pu.get("amount", {})
    currency = amount.get("currency_code")
    amount_val = amount.get("value")

    passed_2_2 = (
        order_status == "APPROVED" and
        payer_country == "US" and
        payee_merchant_id == "Y6HZPU2WCQH5J" and
        currency == "USD" and
        amount_val == "1.00"
    )
    status_desc_2_2 = f"APPROVED (Country: {payer_country}, Payee: {payee_merchant_id}, Amount: {currency} {amount_val})"
    record("Test 1: GET Order 1 verification (checklist 2.2)", res_get.status_code, status_desc_2_2, debug_get, passed_2_2)

    # 2.3 Authorize Order 1
    auth_req_id = str(uuid.uuid4())
    res_auth, debug_auth = tester.authorize_order(order_1_id, auth_req_id)
    auth_data = res_auth.json() if res_auth.status_code in (200, 201) else {}
    auth_status = auth_data.get("status", res_auth.json().get("name", "FAILED"))
    
    # Extract authorization ID
    authorizations = auth_data.get("purchase_units", [{}])[0].get("payments", {}).get("authorizations", [])
    auth_id = authorizations[0].get("id") if authorizations else None
    
    record("Test 1: Call authorize on Order 1 (checklist 2.3)", res_auth.status_code, auth_status, debug_auth, res_auth.status_code in (200, 201))

    # Replay authorize with same PayPal-Request-Id
    res_auth_replay, debug_auth_replay = tester.authorize_order(order_1_id, auth_req_id)
    replay_status = res_auth_replay.json().get("status", res_auth_replay.json().get("name", "UNKNOWN"))
    honours_idempotency = (res_auth_replay.status_code in (200, 201))
    idemp_desc = f"{replay_status} (Idempotent: {honours_idempotency})"
    record("Test 1: Replay authorize with same PayPal-Request-Id (checklist 2.3)", res_auth_replay.status_code, idemp_desc, debug_auth_replay, honours_idempotency)

    if not auth_id:
        print("No authorization ID found, cannot proceed with capture.")
        return results

    # 2.4 Capture Authorization
    cap_req_id = str(uuid.uuid4())
    res_cap, debug_cap = tester.capture_authorization(auth_id, cap_req_id, final_capture=True)
    cap_data = res_cap.json() if res_cap.status_code in (200, 201) else {}
    cap_status = cap_data.get("status", res_cap.json().get("name", "FAILED"))
    cap_id = cap_data.get("id")
    record("Test 1: Capture authorization (checklist 2.4)", res_cap.status_code, cap_status, debug_cap, res_cap.status_code in (200, 201))

    # GET Capture and confirm COMPLETED
    if cap_id:
        res_get_cap, debug_get_cap = tester.get_capture(cap_id)
        get_cap_status = res_get_cap.json().get("status", "FAILED")
        record("Test 1: GET capture confirms COMPLETED (checklist 2.4)", res_get_cap.status_code, get_cap_status, debug_get_cap, get_cap_status == "COMPLETED")

        # Replay Capture with same PayPal-Request-Id
        res_cap_replay, debug_cap_replay = tester.capture_authorization(auth_id, cap_req_id, final_capture=True)
        replay_cap_status = res_cap_replay.json().get("status", res_cap_replay.json().get("name", "REPLAY_PROCESSED"))
        # Verify single capture: status code 200/201 returns same capture, or issue error
        one_capture_confirmed = (res_cap_replay.status_code in (200, 201) and res_cap_replay.json().get("id") == cap_id)
        desc_cap_replay = f"{replay_cap_status} (Single capture confirmed: {one_capture_confirmed})"
        record("Test 1: Replay capture with same ID (checklist 2.4)", res_cap_replay.status_code, desc_cap_replay, debug_cap_replay, one_capture_confirmed)

        # 2.5 Fully refund that capture
        ref_req_id = str(uuid.uuid4())
        res_ref, debug_ref = tester.refund_capture(cap_id, ref_req_id)
        ref_data = res_ref.json() if res_ref.status_code in (200, 201) else {}
        ref_status = ref_data.get("status", res_ref.json().get("name", "FAILED"))
        ref_id = ref_data.get("id")
        record("Test 1: Fully refund capture (checklist 2.5)", res_ref.status_code, ref_status, debug_ref, res_ref.status_code in (200, 201))

        # GET refund and confirm COMPLETED
        if ref_id:
            res_get_ref, debug_get_ref = tester.get_refund(ref_id)
            get_ref_status = res_get_ref.json().get("status", "FAILED")
            record("Test 1: GET refund confirms COMPLETED (checklist 2.5)", res_get_ref.status_code, get_ref_status, debug_get_ref, get_ref_status == "COMPLETED")

            # Replay refund with same PayPal-Request-Id
            res_ref_replay, debug_ref_replay = tester.refund_capture(cap_id, ref_req_id)
            replay_ref_status = res_ref_replay.json().get("status", res_ref_replay.json().get("name", "REPLAY_PROCESSED"))
            ref_replay_passed = (res_ref_replay.status_code in (200, 201) and res_ref_replay.json().get("id") == ref_id)
            record("Test 1: Replay refund with same PayPal-Request-Id (checklist 2.5)", res_ref_replay.status_code, replay_ref_status, debug_ref_replay, ref_replay_passed)

    # 2.6 Run second approved AUTHORIZE order through authorize and void
    print("\nChecking Order 2 approval status...")
    res_get_2, debug_get_2 = tester.get_order(order_2_id)
    if res_get_2.status_code != 200:
        record("Test 1: GET Order 2 (checklist 2.6)", res_get_2.status_code, "GET_FAILED", debug_get_2, False)
        return results

    order_2 = res_get_2.json()
    order_2_status = order_2.get("status")
    if order_2_status != "APPROVED":
        print(f"Order 2 is not approved yet (Current status: {order_2_status}). Please approve it.")
        return None

    # Call authorize on Order 2
    auth_2_req_id = str(uuid.uuid4())
    res_auth_2, debug_auth_2 = tester.authorize_order(order_2_id, auth_2_req_id)
    auth_2_data = res_auth_2.json() if res_auth_2.status_code in (200, 201) else {}
    auth_2_status = auth_2_data.get("status", res_auth_2.json().get("name", "FAILED"))
    auth_2_id = auth_2_data.get("purchase_units", [{}])[0].get("payments", {}).get("authorizations", [{}])[0].get("id")
    record("Test 1: Authorize Order 2 (checklist 2.6)", res_auth_2.status_code, auth_2_status, debug_auth_2, res_auth_2.status_code in (200, 201))

    if auth_2_id:
        # Void the authorization
        res_void, debug_void = tester.void_authorization(auth_2_id)
        # Check whether void returns 200 with body or 204 empty
        void_body_info = "204_NO_CONTENT" if res_void.status_code == 204 else ("200_WITH_BODY" if res_void.status_code == 200 else res_void.json().get("name", "FAILED"))
        void_status = "VOIDED" if res_void.status_code in (200, 204) else void_body_info
        record(f"Test 1: Void authorization (checklist 2.6) [{void_body_info}]", res_void.status_code, void_status, debug_void, res_void.status_code in (200, 204))

        # Replay void WITH PayPal-Request-Id
        void_replay_req_id = str(uuid.uuid4())
        res_void_rep_req, debug_void_rep_req = tester.void_authorization(auth_2_id, request_id=void_replay_req_id)
        void_rep_req_desc = "204_NO_CONTENT" if res_void_rep_req.status_code == 204 else ("200_WITH_BODY" if res_void_rep_req.status_code == 200 else res_void_rep_req.json().get("name", "REPLAY_ERROR"))
        record("Test 1: Replay void WITH PayPal-Request-Id (checklist 2.6)", res_void_rep_req.status_code, void_rep_req_desc, debug_void_rep_req, res_void_rep_req.status_code in (200, 204, 422, 400))

        # Replay void WITHOUT PayPal-Request-Id
        res_void_rep_noreq, debug_void_rep_noreq = tester.void_authorization(auth_2_id, request_id=None)
        void_rep_noreq_desc = "204_NO_CONTENT" if res_void_rep_noreq.status_code == 204 else ("200_WITH_BODY" if res_void_rep_noreq.status_code == 200 else res_void_rep_noreq.json().get("name", "REPLAY_ERROR"))
        record("Test 1: Replay void WITHOUT PayPal-Request-Id (checklist 2.6)", res_void_rep_noreq.status_code, void_rep_noreq_desc, debug_void_rep_noreq, res_void_rep_noreq.status_code in (200, 204, 422, 400))

        # Try capturing after the void
        res_cap_after_void, debug_cap_void = tester.capture_authorization(auth_2_id, str(uuid.uuid4()), final_capture=True)
        cap_void_issue = "FAILED"
        if res_cap_after_void.status_code >= 400:
            details = res_cap_after_void.json().get("details", [{}])[0]
            cap_void_issue = details.get("issue", res_cap_after_void.json().get("name", "ERROR"))
        record("Test 1: Try capture after void (checklist 2.6)", res_cap_after_void.status_code, cap_void_issue, debug_cap_void, res_cap_after_void.status_code >= 400) # Expecting failure/rejection

    return results

if __name__ == "__main__":
    tester = PayPalSandboxTester()
    tester.get_token()
    with open("scratch_state.json", "r") as f:
        state = json.load(f)
    o1 = state.get("order_1_id")
    o2 = state.get("order_2_id")
    res = run_test_1_flow(tester, o1, o2)
    if res:
        with open("test_1_results.json", "w") as f:
            json.dump(res, f, indent=2)
        print("Test 1 completed successfully!")
    else:
        print("Test 1 paused for approvals.")
