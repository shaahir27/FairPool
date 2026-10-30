import os
import uuid
import json
import base64
import requests

def b64url(s):
    return base64.urlsafe_b64encode(s.encode('utf-8')).decode('utf-8').rstrip('=')

class PayPalSandboxTester:
    def __init__(self, env_path=".env"):
        self.env = self.load_env(env_path)
        self.client_id = self.env.get("PAYPAL_CLIENT_ID")
        self.client_secret = self.env.get("PAYPAL_CLIENT_SECRET")
        self.base_url = self.env.get("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")
        self.token = None
        self.results = []

    def load_env(self, path):
        env = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
        return env

    def get_token(self):
        res = requests.post(
            f"{self.base_url}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            headers={"Accept": "application/json", "Accept-Language": "en_US"}
        )
        debug_id = res.headers.get("Paypal-Debug-Id", "N/A")
        if res.status_code == 200:
            self.token = res.json().get("access_token")
            return res.status_code, "TOKEN_OBTAINED", debug_id
        return res.status_code, "OAUTH_FAILED", debug_id

    def record_step(self, step_name, http_status, paypal_status_or_issue, debug_id, passed):
        row = {
            "step": step_name,
            "http_status": http_status,
            "status_or_issue": paypal_status_or_issue,
            "debug_id": debug_id,
            "pass_fail": "PASS" if passed else "FAIL"
        }
        self.results.append(row)
        print(f"[{row['pass_fail']}] {step_name} -> HTTP {http_status} | {paypal_status_or_issue} | Debug-ID: {debug_id}")
        return row

    def create_authorize_order(self, reference_id="test_unit", payee=None):
        req_id = str(uuid.uuid4())
        payload = {
            "intent": "AUTHORIZE",
            "purchase_units": [
                {
                    "reference_id": reference_id,
                    "amount": {
                        "currency_code": "USD",
                        "value": "1.00"
                    }
                }
            ]
        }
        if payee:
            payload["purchase_units"][0]["payee"] = payee

        res = requests.post(
            f"{self.base_url}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": req_id
            },
            json=payload
        )
        debug_id = res.headers.get("Paypal-Debug-Id", "N/A")
        return res, req_id, debug_id

    def get_order(self, order_id):
        res = requests.get(
            f"{self.base_url}/v2/checkout/orders/{order_id}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )
        debug_id = res.headers.get("Paypal-Debug-Id", "N/A")
        return res, debug_id

    def authorize_order(self, order_id, request_id):
        res = requests.post(
            f"{self.base_url}/v2/checkout/orders/{order_id}/authorize",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": request_id
            }
        )
        debug_id = res.headers.get("Paypal-Debug-Id", "N/A")
        return res, debug_id

    def capture_authorization(self, auth_id, request_id, final_capture=True):
        res = requests.post(
            f"{self.base_url}/v2/payments/authorizations/{auth_id}/capture",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": request_id
            },
            json={
                "amount": {
                    "currency_code": "USD",
                    "value": "1.00"
                },
                "final_capture": final_capture
            }
        )
        debug_id = res.headers.get("Paypal-Debug-Id", "N/A")
        return res, debug_id

    def get_capture(self, capture_id):
        res = requests.get(
            f"{self.base_url}/v2/payments/captures/{capture_id}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )
        debug_id = res.headers.get("Paypal-Debug-Id", "N/A")
        return res, debug_id

    def refund_capture(self, capture_id, request_id):
        res = requests.post(
            f"{self.base_url}/v2/payments/captures/{capture_id}/refund",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": request_id
            },
            json={
                "amount": {
                    "currency_code": "USD",
                    "value": "1.00"
                }
            }
        )
        debug_id = res.headers.get("Paypal-Debug-Id", "N/A")
        return res, debug_id

    def get_refund(self, refund_id):
        res = requests.get(
            f"{self.base_url}/v2/payments/refunds/{refund_id}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
        )
        debug_id = res.headers.get("Paypal-Debug-Id", "N/A")
        return res, debug_id

    def void_authorization(self, auth_id, request_id=None):
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        res = requests.post(
            f"{self.base_url}/v2/payments/authorizations/{auth_id}/void",
            headers=headers
        )
        debug_id = res.headers.get("Paypal-Debug-Id", "N/A")
        return res, debug_id

    def run_test_2_suite(self):
        print("\n--- Running Test 2 (Second Seller & Platform Controls) ---")
        
        # 3.1 Partner Referrals onboarding & consent
        ref_payload = {
            "tracking_id": f"fairpool_ref_{uuid.uuid4().hex[:8]}",
            "operations": [{"operation": "API_INTEGRATION"}],
            "products": ["EXPRESS_CHECKOUT"]
        }
        res_ref = requests.post(
            f"{self.base_url}/v2/customer/partner-referrals",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json=ref_payload
        )
        debug_ref = res_ref.headers.get("Paypal-Debug-Id", "N/A")
        issue_ref = res_ref.json().get("name", "ERROR") if res_ref.status_code >= 400 else "COMPLETED"
        # Since app does not have Partner permissions, 403 NOT_AUTHORIZED is expected
        self.record_step(
            "Test 2: Partner Referrals onboarding & consent (checklist 3.1)",
            res_ref.status_code,
            issue_ref,
            debug_ref,
            passed=(res_ref.status_code in (200, 201)) # Record true status
        )

        # 3.2 Order with second seller payee (Sh1@business.example.com) without assertion
        res_payee, _, debug_payee = self.create_authorize_order(
            reference_id="test2_second_seller_direct",
            payee={"email_address": "Sh1@business.example.com"}
        )
        if res_payee.status_code in (200, 201):
            data = res_payee.json()
            pu = data.get("purchase_units", [{}])[0]
            returned_payee = pu.get("payee", {})
            returned_email = returned_payee.get("email_address")
            has_merchant_id = "merchant_id" in returned_payee
            m_id_status = returned_payee.get("merchant_id") if has_merchant_id else "MISSING"
            
            # Verify payee is second seller and merchant ID is reported missing rather than inferred
            status_desc = f"CREATED (Payee: {returned_email}, merchant_id: {m_id_status})"
            passed = (returned_email == "Sh1@business.example.com" and not has_merchant_id)
            self.record_step(
                "Test 2: Create AUTHORIZE order to second seller without assertion (control)",
                res_payee.status_code,
                status_desc,
                debug_payee,
                passed=passed
            )
        else:
            self.record_step(
                "Test 2: Create AUTHORIZE order to second seller without assertion (control)",
                res_payee.status_code,
                res_payee.json().get("name", "FAILED"),
                debug_payee,
                passed=False
            )

        # 3.3 Order with PayPal-Auth-Assertion header and merchant ID
        header_b64 = b64url(json.dumps({"alg": "none"}))
        payload_payer = b64url(json.dumps({"iss": self.client_id, "payer_id": "TEST_SELLER_MERCHANT_ID"}))
        assertion = f"{header_b64}.{payload_payer}."
        
        res_assert = requests.post(
            f"{self.base_url}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": str(uuid.uuid4()),
                "PayPal-Auth-Assertion": assertion
            },
            json={
                "intent": "AUTHORIZE",
                "purchase_units": [
                    {
                        "reference_id": "test2_auth_assertion",
                        "amount": {"currency_code": "USD", "value": "1.00"},
                        "payee": {"merchant_id": "TEST_SELLER_MERCHANT_ID"}
                    }
                ]
            }
        )
        debug_assert = res_assert.headers.get("Paypal-Debug-Id", "N/A")
        issue_assert = res_assert.json().get("error", "UNKNOWN_ERROR")
        self.record_step(
            "Test 2: Create AUTHORIZE order with PayPal-Auth-Assertion (checklist 3.2)",
            res_assert.status_code,
            issue_assert,
            debug_assert,
            passed=(res_assert.status_code in (200, 201)) # Captures PayPal rejection accurately
        )

        # 3.4 Platform fee control on purchase unit
        res_fee = requests.post(
            f"{self.base_url}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": str(uuid.uuid4())
            },
            json={
                "intent": "AUTHORIZE",
                "purchase_units": [
                    {
                        "reference_id": "test2_platform_fee",
                        "amount": {"currency_code": "USD", "value": "1.00"},
                        "payment_instruction": {
                            "disbursement_mode": "INSTANT",
                            "platform_fees": [{"amount": {"currency_code": "USD", "value": "0.10"}}]
                        }
                    }
                ]
            }
        )
        debug_fee = res_fee.headers.get("Paypal-Debug-Id", "N/A")
        fee_issue = "SUPPORTED"
        if res_fee.status_code >= 400:
            details = res_fee.json().get("details", [{}])[0]
            fee_issue = details.get("issue", res_fee.json().get("name", "FAILED"))
        self.record_step(
            "Test 2: Platform fee on purchase unit control (checklist 3.8)",
            res_fee.status_code,
            fee_issue,
            debug_fee,
            passed=(res_fee.status_code in (200, 201))
        )

        # 3.5 Order to non-onboarded payee
        res_non = requests.post(
            f"{self.base_url}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
                "PayPal-Request-Id": str(uuid.uuid4())
            },
            json={
                "intent": "AUTHORIZE",
                "purchase_units": [
                    {
                        "reference_id": "test2_non_onboarded",
                        "amount": {"currency_code": "USD", "value": "1.00"},
                        "payee": {"email_address": "nonexistent_seller_9876@example.com"}
                    }
                ]
            }
        )
        debug_non = res_non.headers.get("Paypal-Debug-Id", "N/A")
        non_status = res_non.json().get("status", res_non.json().get("name", "N/A"))
        self.record_step(
            "Test 2: Order to non-onboarded payee control (checklist 3.8)",
            res_non.status_code,
            non_status,
            debug_non,
            passed=(res_non.status_code in (200, 201))
        )

        # Save test 2 results
        with open("test_2_results.json", "w") as f:
            json.dump(self.results, f, indent=2)

if __name__ == "__main__":
    tester = PayPalSandboxTester()
    tester.get_token()
    tester.run_test_2_suite()
