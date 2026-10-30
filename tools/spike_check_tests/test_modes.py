import builtins, json, os, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import mock_paypal
import fairpool_spike_check as m
mock_paypal.start(9420); mock_paypal.S.approve_after = 1
os.environ.update({"FAIRPOOL_SPIKE_SELFTEST": "1", "PAYPAL_API_BASE": "http://127.0.0.1:9420", "PAYPAL_CHECKOUT_BASE": "http://127.0.0.1:9420",
                   "PAYPAL_CLIENT_ID": "CID123456", "PAYPAL_CLIENT_SECRET": "SECRETXYZ789ABC", "SINGLE_SELLER_EMAIL": "seller@example.com"})
def boom(prompt=""): raise AssertionError("prompted in non-interactive mode: " + prompt)
builtins.input = boom
m.webbrowser.open = lambda u: (_ for _ in ()).throw(AssertionError("opened a browser in non-interactive mode"))
out = HERE / "out_noninter"; shutil.rmtree(out, ignore_errors=True)
rc = m.main(["run", "--env-file", "/nonexistent", "--out-dir", str(out), "--non-interactive", "--only", "core,s1,s2,s4,s7,s12,s13"])
rep = json.loads((out / "spike_report.json").read_text())
res = {}
for r in rep["rows"]:
    res[r["result"]] = res.get(r["result"], 0) + 1
print("non-interactive results:", res, "exit", rc)
assert not any(r["result"] == "FAIL" for r in rep["rows"] if r["spike"] == "CORE"), "core must pass"
assert any(r["result"] == "MANUAL" for r in rep["rows"]), "human steps must be MANUAL"
assert not mock_paypal.S.caps and not any(a["status"] == "CREATED" for a in mock_paypal.S.auths.values())

# Ctrl-C after a capture exists: cleanup must refund the capture and void any open authorization
mock_paypal.S.__init__(); mock_paypal.S.approve_after = 1
m.REC.__init__()
def ok_input(prompt=""): return "y" if "[y/n]" in prompt else ""
builtins.input = ok_input
m.webbrowser.open = lambda u: True
orig = m.run_s12
def interrupt(ctx): raise KeyboardInterrupt()
m.run_s12 = interrupt
out2 = HERE / "out_interrupt"; shutil.rmtree(out2, ignore_errors=True)
rc = m.main(["run", "--env-file", "/nonexistent", "--out-dir", str(out2), "--no-confirm", "--only", "s2,s12"])
S = mock_paypal.S
print("exit", rc, "captures:", [c["status"] for c in S.caps.values()], "auths:", [a["status"] for a in S.auths.values()])
assert rc == 130
assert all(c["status"] == "REFUNDED" for c in S.caps.values()) and S.caps, "capture must be refunded on interrupt"
assert not any(a["status"] == "CREATED" for a in S.auths.values())
m.run_s12 = orig
print("MODE TESTS PASSED")
