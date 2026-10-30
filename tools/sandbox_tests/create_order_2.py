import json
from paypal_tester import PayPalSandboxTester

tester = PayPalSandboxTester()
tester.get_token()

# Load state
state = {}
try:
    with open("scratch_state.json", "r") as f:
        state = json.load(f)
except:
    pass

# Check if Order 1 exists
order_1_id = state.get("order_1_id")
print(f"Order 1 ID: {order_1_id}")

# Create Order 2 for Void flow
res_2, req_id_2, debug_id_2 = tester.create_authorize_order(reference_id="order_2_void_flow")
if res_2.status_code in (200, 201):
    data_2 = res_2.json()
    order_2_id = data_2.get("id")
    print(f"Order 2 created: ID {order_2_id}, Debug-ID: {debug_id_2}")
    state["order_2_id"] = order_2_id
    state["order_2_req_id"] = req_id_2
    state["order_2_debug_id"] = debug_id_2
    with open("scratch_state.json", "w") as f:
        json.dump(state, f, indent=2)
else:
    print(f"Failed to create Order 2: {res_2.status_code}")
