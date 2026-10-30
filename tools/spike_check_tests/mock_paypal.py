"""A stand-in for the PayPal Sandbox REST API, built from the behaviour recorded in docs/registry.md.
It exists only to test the spike script's own logic offline. It is NOT PayPal."""
import json, threading, time, uuid, base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import urllib.request


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.orders = {}          # id -> dict
        self.by_key = {}          # request-id -> (kind, id, response_status)
        self.auths = {}           # id -> dict
        self.caps = {}
        self.refunds = {}
        self.invoices = set()
        self.webhooks = {}
        self.trackers = {}
        self.events_sent = []
        self.polls = {}
        self.buyer_counter = 0
        self.login_payer_matches = True
        self.token_calls = 0
        self.approve_after = 2   # GET polls before the simulated buyer approves
        self.cancelled = set()
        self.simulate_valid = False
        self.deny_email = 'second@example.com'   # a seller the app cannot void/refund for (recorded in S7)


S = State()


def deliver(event_type, resource, event_id=None):
    for wid, w in list(S.webhooks.items()):
        if event_type not in w["events"]:
            continue
        body = json.dumps({"id": event_id or ("WH-" + uuid.uuid4().hex[:12]), "event_type": event_type, "resource": resource}).encode()
        S.events_sent.append((wid, event_type))

        def post(url=w["url"], body=body):
            try:
                req = urllib.request.Request(url, data=body, method="POST", headers={
                    "Content-Type": "application/json", "PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert",
                    "PAYPAL-TRANSMISSION-ID": uuid.uuid4().hex, "PAYPAL-TRANSMISSION-SIG": "validsig", "PAYPAL-TRANSMISSION-TIME": "2026-10-28T00:00:00Z"})
                urllib.request.urlopen(req, timeout=5).read()
            except Exception:
                pass
        threading.Thread(target=post, daemon=True).start()


def err(h, code, name, issue=None):
    body = {"name": name, "message": name, "debug_id": "dbg" + uuid.uuid4().hex[:8], "details": [{"issue": issue or name}] if issue else []}
    h.reply(code, body)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body=None, headers=None):
        raw = b"" if body is None else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("PayPal-Debug-Id", "dbg" + uuid.uuid4().hex[:10])
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(n) if n else b""
        return raw

    def jbody(self):
        raw = self.body()
        try:
            return json.loads(raw.decode()) if raw else {}
        except ValueError:
            return {}

    def authed(self):
        a = self.headers.get("Authorization", "")
        return a.startswith("Bearer ")

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        u = urlparse(self.path)
        path = u.path
        with S.lock:
            self._route(method, path, u)

    def _route(self, method, path, u):
        if path == "/health":
            return self.reply(200, {})
        if path == "/v1/oauth2/token":
            raw = self.body().decode()
            form = parse_qs(raw)
            gt = form.get("grant_type", [""])[0]
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Basic "):
                return err(self, 401, "invalid_client")
            if gt == "authorization_code":
                if form.get("code", [""])[0] != "GOODCODE":
                    return self.reply(400, {"error": "invalid_grant", "error_description": "bad code"})
                return self.reply(200, {"access_token": "A21USERTOKENXXXXXXXXXXXXXXXXXXXXXXXX", "token_type": "Bearer", "scope": "openid https://uri.paypal.com/services/paypalattributes", "expires_in": 28800})
            if form.get("response_type", [""])[0] == "client_token":
                return self.reply(200, {"access_token": "eyJCLIENTTOKENXXXXXXXXXXXXXXXXXXXXXXXXXXXX", "expires_in": 900, "token_type": "Bearer"})
            S.token_calls += 1
            return self.reply(200, {"scope": "https://uri.paypal.com/services/payments/payment/authcapture openid", "access_token": "A21AAMOCKTOKENXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", "token_type": "Bearer", "app_id": "APP-MOCK", "expires_in": 32400, "nonce": "n"})
        if path.startswith("/v1/identity/oauth2/userinfo"):
            body = {"user_id": "https://www.paypal.com/webapps/auth/identity/user/PAYERBUYER1", "sub": "https://www.paypal.com/webapps/auth/identity/user/PAYERBUYER1", "name": "Secret Person Name", "verified_account": "true"}
            if S.login_payer_matches:
                body["payer_id"] = "PAYERBUYER1"
            return self.reply(200, body)
        if not self.authed():
            return err(self, 401, "AUTHENTICATION_FAILURE")
        # ---- orders
        if path == "/v2/checkout/orders" and method == "POST":
            body = self.jbody()
            key = self.headers.get("PayPal-Request-Id", "")
            if key in S.by_key:
                return self.reply(200, S.orders[S.by_key[key][1]])
            pu = body["purchase_units"][0]
            mock = self.headers.get("PayPal-Mock-Response", "")
            if "DUPLICATE_INVOICE_ID" in mock:
                return err(self, 422, "UNPROCESSABLE_ENTITY", "DUPLICATE_INVOICE_ID")
            if pu["amount"]["value"] != "1.00":
                return err(self, 400, "INVALID_REQUEST", "INVALID_AMOUNT")
            inv = pu.get("invoice_id")
            if inv and inv in S.invoices:
                return err(self, 422, "UNPROCESSABLE_ENTITY", "DUPLICATE_INVOICE_ID")
            br = pu["amount"].get("breakdown")
            if br:
                tot = float(br["item_total"]["value"]) + float(br["shipping"]["value"]) + float(br["tax_total"]["value"])
                if abs(tot - 1.0) > 1e-9:
                    return err(self, 422, "UNPROCESSABLE_ENTITY", "AMOUNT_MISMATCH")
            if inv:
                S.invoices.add(inv)
            oid = "ORD" + uuid.uuid4().hex[:12].upper()
            ps = "payment_source" in body
            order = {"id": oid, "status": "PAYER_ACTION_REQUIRED" if ps else "CREATED", "intent": body["intent"],
                     "purchase_units": [{"reference_id": pu.get("reference_id"), "amount": pu["amount"], "payee": pu.get("payee", {}), "shipping": pu.get("shipping")}],
                     "links": [{"rel": "payer-action" if ps else "approve", "href": f"http://127.0.0.1/approve/{oid}"}]}
            order["purchase_units"][0] = {k: v for k, v in order["purchase_units"][0].items() if v is not None}
            S.orders[oid] = order
            S.by_key[key] = ("order", oid, 201)
            return self.reply(201, order)
        parts = path.strip("/").split("/")
        if parts[:3] == ["v2", "checkout", "orders"] and len(parts) >= 4:
            oid = parts[3]
            o = S.orders.get(oid)
            if o is None:
                return err(self, 404, "RESOURCE_NOT_FOUND")
            if len(parts) == 4 and method == "GET":
                if o["status"] in ("CREATED", "PAYER_ACTION_REQUIRED"):
                    S.polls[oid] = S.polls.get(oid, 0) + 1
                    if S.polls[oid] > S.approve_after and oid not in S.cancelled:
                        S.buyer_counter += 1
                        pid = "PAYERBUYER1" if not getattr(S, "distinct_buyers", False) else f"PAYERBUYER{S.buyer_counter}"
                        o["status"] = "APPROVED"
                        o["payer"] = {"payer_id": pid, "address": {"country_code": "US"}}
                        deliver("CHECKOUT.ORDER.APPROVED", {"id": oid})
                return self.reply(200, o)
            if len(parts) == 5 and parts[4] == "authorize" and method == "POST":
                key = self.headers.get("PayPal-Request-Id", "")
                if key in S.by_key:
                    return self.reply(200, S.orders[oid])
                if o["status"] != "APPROVED":
                    return err(self, 422, "UNPROCESSABLE_ENTITY", "ORDER_NOT_APPROVED")
                aid = "AUTH" + uuid.uuid4().hex[:10].upper()
                S.auths[aid] = {"id": aid, "status": "CREATED", "order": oid}
                o["status"] = "COMPLETED"
                o["purchase_units"][0].setdefault("payments", {})["authorizations"] = [{"id": aid, "status": "CREATED"}]
                S.by_key[key] = ("auth", oid, 201)
                deliver("PAYMENT.AUTHORIZATION.CREATED", {"id": aid})
                return self.reply(201, o)
            if len(parts) == 5 and parts[4] == "capture" and method == "POST":
                return err(self, 422, "UNPROCESSABLE_ENTITY", "ORDER_NOT_APPROVED")
            if len(parts) == 5 and parts[4] == "track" and method == "POST":
                b = self.jbody()
                ship = o["purchase_units"][0].setdefault("shipping", {})
                tr = ship.setdefault("trackings", [])
                if any(x["tracking_number"] == b["tracking_number"] for x in tr):
                    return self.reply(200, o)
                tr.append({"tracking_number": b["tracking_number"], "status": "SHIPPED", "capture_id": b.get("capture_id")})
                return self.reply(201, o)
        if parts[:3] == ["v2", "payments", "authorizations"] and len(parts) >= 4:
            aid = parts[3]
            a = S.auths.get(aid)
            if a is None:
                return err(self, 404, "RESOURCE_NOT_FOUND")
            if len(parts) == 4:
                return self.reply(200, a)
            if parts[4] == "void":
                if S.orders[a["order"]]["purchase_units"][0].get("payee", {}).get("email_address") == S.deny_email:
                    return err(self, 403, "NOT_AUTHORIZED", "PERMISSION_DENIED")
                if a["status"] != "CREATED":
                    return err(self, 422, "UNPROCESSABLE_ENTITY", "AUTHORIZATION_ALREADY_VOIDED" if a["status"] == "VOIDED" else "PREVIOUS_CAPTURE")
                a["status"] = "VOIDED"
                S.orders[a["order"]]["purchase_units"][0]["payments"]["authorizations"][0]["status"] = "VOIDED"
                deliver("PAYMENT.AUTHORIZATION.VOIDED", {"id": aid})
                return self.reply(200, {"id": aid, "status": "VOIDED"})
            if parts[4] == "capture":
                key = self.headers.get("PayPal-Request-Id", "")
                if key in S.by_key:
                    return self.reply(200, S.caps[S.by_key[key][1]])
                if a["status"] == "VOIDED":
                    return err(self, 422, "UNPROCESSABLE_ENTITY", "AUTHORIZATION_VOIDED")
                cid = "CAP" + uuid.uuid4().hex[:10].upper()
                S.caps[cid] = {"id": cid, "status": "COMPLETED", "final_capture": True, "amount": {"value": "1.00", "currency_code": "USD"}, "order": a["order"]}
                a["status"] = "CAPTURED"
                o = S.orders[a["order"]]
                o["purchase_units"][0]["payments"]["captures"] = [{"id": cid, "status": "COMPLETED"}]
                S.by_key[key] = ("cap", cid, 201)
                deliver("PAYMENT.CAPTURE.COMPLETED", {"id": cid})
                return self.reply(201, S.caps[cid])
        if parts[:3] == ["v2", "payments", "captures"] and len(parts) >= 4:
            cid = parts[3]
            c = S.caps.get(cid)
            if c is None:
                return err(self, 404, "RESOURCE_NOT_FOUND")
            if len(parts) == 4:
                return self.reply(200, c)
            if parts[4] == "refund":
                if S.orders[c["order"]]["purchase_units"][0].get("payee", {}).get("email_address") == S.deny_email:
                    return err(self, 403, "NOT_AUTHORIZED", "PERMISSION_DENIED")
                key = self.headers.get("PayPal-Request-Id", "")
                if key in S.by_key:
                    return self.reply(200, S.refunds[S.by_key[key][1]])
                rid = "REF" + uuid.uuid4().hex[:10].upper()
                S.refunds[rid] = {"id": rid, "status": "COMPLETED"}
                c["status"] = "REFUNDED"
                S.by_key[key] = ("ref", rid, 201)
                deliver("PAYMENT.CAPTURE.REFUNDED", {"id": rid})
                return self.reply(201, S.refunds[rid])
        if parts[:3] == ["v2", "payments", "refunds"] and len(parts) == 4:
            return self.reply(200, S.refunds[parts[3]])
        # ---- webhooks
        if path == "/v1/notifications/webhooks-event-types":
            names = ["CHECKOUT.ORDER.APPROVED", "PAYMENT.AUTHORIZATION.CREATED", "PAYMENT.AUTHORIZATION.VOIDED", "PAYMENT.CAPTURE.PENDING", "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.REFUNDED", "OTHER.EVENT"]
            return self.reply(200, {"event_types": [{"name": n} for n in names]})
        if path == "/v1/notifications/webhooks" and method == "GET":
            return self.reply(200, {"webhooks": [{"id": k, "url": v["url"]} for k, v in S.webhooks.items()]})
        if path == "/v1/notifications/webhooks" and method == "POST":
            b = self.jbody()
            if any(w["url"] == b["url"] for w in S.webhooks.values()):
                return err(self, 400, "INVALID_REQUEST", "WEBHOOK_URL_ALREADY_EXISTS")
            wid = "WHK" + uuid.uuid4().hex[:8]
            S.webhooks[wid] = {"url": b["url"], "events": [e["name"] for e in b["event_types"]]}
            return self.reply(201, {"id": wid, "url": b["url"]})
        if parts[:3] == ["v1", "notifications", "webhooks"] and len(parts) == 4 and method == "DELETE":
            S.webhooks.pop(parts[3], None)
            return self.reply(204)
        if path == "/v1/notifications/simulate-event":
            b = self.jbody()
            deliver(b["event_type"], {"id": "SIM"})
            return self.reply(202, {"id": "SIM"})
        if parts[:3] == ["v1", "notifications", "webhooks-events"] and len(parts) == 5 and parts[4] == "resend":
            eid = parts[3]
            for wid, w in S.webhooks.items():
                body = json.dumps({"id": eid, "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {}}).encode()
                def post(url=w["url"], body=body):
                    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "PAYPAL-TRANSMISSION-SIG": "validsig", "PAYPAL-AUTH-ALGO": "x", "PAYPAL-CERT-URL": "x", "PAYPAL-TRANSMISSION-ID": uuid.uuid4().hex, "PAYPAL-TRANSMISSION-TIME": "t"})
                    urllib.request.urlopen(req, timeout=5).read()
                threading.Thread(target=post, daemon=True).start()
            return self.reply(202, {"id": eid})
        if path == "/v1/notifications/verify-webhook-signature":
            raw = self.body()
            try:
                j = json.loads(raw.decode())
            except ValueError:
                return self.reply(200, {"verification_status": "FAILURE"})
            ok = j.get("transmission_sig") == "validsig" and isinstance(j.get("webhook_event"), dict) and j["webhook_event"].get("id") and j.get("webhook_id") in S.webhooks
            return self.reply(200, {"verification_status": "SUCCESS" if ok else "FAILURE"})
        # ---- trackers
        if path == "/v1/shipping/trackers-batch":
            return err(self, 403, "NOT_AUTHORIZED", "PERMISSION_DENIED")
            b = self.jbody()
            ids = []
            for t in b["trackers"]:
                if t["transaction_id"] not in S.caps:
                    return self.reply(200, {"errors": [{"name": "INVALID_TRANSACTION_ID"}]})
                S.trackers[f"{t['transaction_id']}-{t['tracking_number']}"] = t
                ids.append({"transaction_id": t["transaction_id"], "tracking_number": t["tracking_number"]})
            return self.reply(200, {"tracker_identifiers": ids})
        if parts[:3] == ["v1", "shipping", "trackers"] and len(parts) == 4:
            t = S.trackers.get(parts[3])
            return self.reply(200, t) if t else err(self, 404, "RESOURCE_NOT_FOUND")
        if path == "/v2/customer/partner-referrals":
            return err(self, 403, "NOT_AUTHORIZED", "PERMISSION_DENIED")
        return err(self, 404, "RESOURCE_NOT_FOUND")


def start(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
