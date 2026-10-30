"""End-to-end test of fairpool_spike_check.py against local mocks (no real PayPal, no network)."""
import builtins, json, os, shutil, subprocess, sys, threading, time, urllib.request
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import mock_paypal, mock_services
import fairpool_spike_check as m

out = HERE / "out_e2e"
shutil.rmtree(out, ignore_errors=True)
pp = mock_paypal.start(9400)
mock_paypal.S.approve_after = 1
mock_paypal.S.distinct_buyers = True
mock_services.serve(mock_services.Drand, 9401)
mock_services.serve(mock_services.Elastic, 9402)
py1 = os.environ.get("MCP_REF_PYTHON", sys.executable)
procs = [subprocess.Popen([py1, str(HERE / "mock_mcp_server.py"), "streamable-http", "9403", "paypal"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
         subprocess.Popen([py1, str(HERE / "mock_mcp_server.py"), "streamable-http", "9404", "zapier4"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
time.sleep(3)

ops = {"list_lots": ("get", "/merchant-api/v1/lots"), "get_lot": ("get", "/merchant-api/v1/lots/{lot_id}"), "submit_bid": ("put", "/merchant-api/v1/lots/{lot_id}/bid"),
       "list_bids": ("get", "/merchant-api/v1/bids"), "get_bid": ("get", "/merchant-api/v1/bids/{bid_id}"), "get_lot_progress": ("get", "/merchant-api/v1/lots/{lot_id}/progress"),
       "get_lot_fulfillment": ("get", "/merchant-api/v1/lots/{lot_id}/fulfillment"), "submit_shipments": ("post", "/merchant-api/v1/lots/{lot_id}/shipments"),
       "get_verification_manifest": ("get", "/merchant-api/v1/lots/{lot_id}/verification-manifest"), "get_lot_verification": ("get", "/merchant-api/v1/lots/{lot_id}/verification")}
paths = {}
for oid, (meth, p) in ops.items():
    paths.setdefault(p, {})[meth] = {"operationId": oid}
(HERE / "openapi_test.json").write_text(json.dumps({"openapi": "3.1.0", "paths": paths}))

env = {
    "FAIRPOOL_SPIKE_SELFTEST": "1", "PAYPAL_API_BASE": "http://127.0.0.1:9400", "PAYPAL_CHECKOUT_BASE": "http://127.0.0.1:9400",
    "PAYPAL_CLIENT_ID": "CID123456", "PAYPAL_CLIENT_SECRET": "SECRETXYZ789ABC", "SINGLE_SELLER_EMAIL": "seller@example.com", "SECOND_SELLER_EMAIL": "second@example.com",
    "PAYPAL_LOGIN_REDIRECT_URI": "https://example.com/cb", "WEBHOOK_PUBLIC_URL": "http://127.0.0.1:8787", "WEBHOOK_LISTEN_PORT": "8787",
    "DRAND_BASE_URL": "http://127.0.0.1:9401", "DRAND_CHAIN_HASH": mock_services.CHAIN, "DRAND_OTHER_RELAYS": "http://127.0.0.1:9401", "S6_BEACON_DELAY_S": "3",
    "ELASTICSEARCH_URL": "http://127.0.0.1:9402", "ELASTICSEARCH_API_KEY": "ESKEY123456789", "ZAPIER_MCP_TOKEN": "ZAPTOKEN123456", "ZAPIER_MCP_URL": "http://127.0.0.1:9404/mcp",
    "PAYPAL_MCP_BASE": "http://127.0.0.1:9403", "S10_LOCAL_CALL": "0", "OPENAPI_JSON_PATH": str(HERE / "openapi_test.json"), "S13_LISTEN_PORT": "8788",
}
os.environ.update(env)
state = {"s1_state": None}


def http_post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", **(headers or {})})
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode() or "{}")


def sim_page():
    base = "http://localhost:8788"
    time.sleep(0.5)
    http_post(base + "/api/event", {"kind": "init_ok", "mode": "client_id"})
    http_post(base + "/api/event", {"kind": "eligible", "eligible": True})
    oid = http_post(base + "/api/orders", {})["id"]
    for _ in range(4):       # the simulated buyer approves the order (the mock approves on polls)
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:9400/v2/checkout/orders/{oid}", headers={"Authorization": "Bearer x"}), timeout=10).read()
    http_post(base + "/api/approved", {"fields": ["orderId"], "orderId": oid})
    time.sleep(4)
    oid2 = http_post(base + "/api/orders", {})["id"]
    http_post(base + "/api/event", {"kind": "cancel", "fields": ["orderId"], "orderId": oid2})


def fake_open(url):
    if "/connect?" in url:
        state["s1_state"] = parse_qs(urlparse(url).query)["state"][0]
    elif url.startswith("http://localhost:8788"):
        threading.Thread(target=sim_page, daemon=True).start()
    return True


def fake_input(prompt=""):
    if "Paste the full redirected URL" in prompt:
        return f"https://example.com/cb?code=GOODCODE&state={state['s1_state']}"
    if "[y/n]" in prompt:
        return "y"
    return ""


m.webbrowser.open = fake_open
builtins.input = fake_input
rc = m.main(["run", "--env-file", "/nonexistent", "--out-dir", str(out), "--no-confirm"])
for p in procs:
    p.terminate()
rep = json.loads((out / "spike_report.json").read_text())
md = (out / "spike_report.md").read_text()
print("\n==== exit code", rc)
print("FACTS:", json.dumps(rep["facts"], indent=1))
bad = [r for r in rep["rows"] if r["result"] == "FAIL"]
print("FAIL rows:", len(bad))
for r in bad:
    print("  ", r["spike"], "|", r["step"], "|", r["http"], r["status"], "|", r["note"][:140])
blk = [r for r in rep["rows"] if r["result"] in ("BLOCKED", "MANUAL")]
print("BLOCKED/MANUAL rows:", len(blk))
for r in blk:
    print("  ", r["spike"], "|", r["result"], "|", r["step"][:90], "|", r["note"][:100])
leaks = [s for s in ("SECRETXYZ789ABC", "A21AAMOCKTOKEN", "A21USERTOKEN", "eyJCLIENTTOKEN", "ESKEY123456789", "ZAPTOKEN123456", "Secret Person Name", "/approve/ORD", "PAYERBUYER", "seller@example.com", "second@example.com") if s in md or s in json.dumps(rep)]
print("LEAKS:", leaks)

# assertions: the only FAIL rows allowed are the second seller's denied void/refund (recorded behaviour of the real service)
unexpected = [r for r in bad if not ((r["spike"] == "S7" and ("PERMISSION_DENIED" in r["status"] or "second seller" in r["step"])) or (r["spike"] == "CLEANUP" and "S7" in r["step"] and "PERMISSION_DENIED" in r["status"]))]
assert not unexpected, unexpected
f = rep["facts"]
assert f["S7_payee_email_eligible"] is False and f["DEDUPE_MODE"] in ("two_keys", "full") and f["SHIPMENT_TRACKING_ENABLED"] is True
assert f["PAYPAL_APPROVAL_UI"] == "sdk_popup" and f["BEACON_MODE"] == "drand" and f["ZAPIER_BRIDGE"] == "managed"
assert "PAYMENT.CAPTURE.COMPLETED" in f["WEBHOOK_TYPES_VERIFIED"] and f["WEBHOOKS_ENABLED"] is True
assert not leaks
print("E2E ASSERTIONS PASSED")
