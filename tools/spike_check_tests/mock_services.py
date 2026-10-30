"""Mock drand relay and mock Elasticsearch (control-flow tests only; Elastic's ranking is NOT emulated)."""
import json, hashlib, threading, time, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pyblst

DST = b"BLS_SIG_BLS12381G1_XMD:SHA-256_SSWU_RO_NUL_"
G2 = bytes.fromhex("93e02b6052719f607dacd3a088274f65596bd0d09920b61ab5da61bbdc7f5049334cf11213945d57e5ac7d055d042b7e024aa2b2f08f0a91260805272dc51051c6e47ad4fa403b02b4510b647ae3d1770bac0326a805bbefd48056c8c121bdb8")
SK = 987654321987654321
PK = pyblst.BlstP2Element.uncompress(G2).scalar_mul(SK).compress().hex()
GENESIS = int(time.time()) - 1000
PERIOD = 2
CHAIN = "ab" * 32


def beacon(rnd):
    msg = hashlib.sha256(rnd.to_bytes(8, "big")).digest()
    sig = pyblst.BlstP1Element.hash_to_group(msg, DST).scalar_mul(SK).compress().hex()
    return {"round": rnd, "randomness": hashlib.sha256(bytes.fromhex(sig)).hexdigest(), "signature": sig}


class Drand(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        def send(code, obj):
            raw = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        parts = self.path.strip("/").split("/")
        if parts[0] != CHAIN: return send(404, {})
        cur = int((time.time() - GENESIS) // PERIOD) + 1
        if parts[1:] == ["info"]:
            return send(200, {"hash": CHAIN, "public_key": PK, "period": PERIOD, "genesis_time": GENESIS, "schemeID": "bls-unchained-g1-rfc9380"})
        if parts[1:] == ["public", "latest"]: return send(200, beacon(cur))
        if parts[1] == "public" and parts[2].isdigit():
            r = int(parts[2])
            return send(200, beacon(r)) if r <= cur else send(404, {"error": "not yet"})
        send(404, {})


class Elastic(BaseHTTPRequestHandler):
    docs = {}
    def log_message(self, *a): pass
    def _send(self, code, obj):
        raw = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or 0); return self.rfile.read(n) if n else b""
    def do_GET(self):
        if self.path == "/": return self._send(200, {"version": {"number": "9.0.0", "build_flavor": "serverless"}})
        if self.path == "/_inference": return self._send(200, {"endpoints": [{"inference_id": ".elser-2-elastic", "task_type": "sparse_embedding"}, {"inference_id": ".jina-embeddings-v5-text-small", "task_type": "text_embedding"}]})
        self._send(404, {})
    def do_DELETE(self): self._send(200, {"acknowledged": True})
    def do_PUT(self):
        b = json.loads(self._body().decode()); ok = b["mappings"]["properties"]["content_embedding"]["type"] == "semantic_text"; Elastic.docs = {}
        self._send(200 if ok else 400, {"acknowledged": ok})
    def do_POST(self):
        raw = self._body().decode()
        if "/_bulk" in self.path:
            ls = [json.loads(x) for x in raw.strip().split("\n")]
            for a, d in zip(ls[0::2], ls[1::2]): Elastic.docs[a["index"]["_id"]] = d
            return self._send(200, {"errors": False, "items": []})
        if "/_search" in self.path:
            b = json.loads(raw)
            q = json.dumps(b)
            m = re.search(r'"match": \{"content": "([^"]+)"\}', q) or re.search(r'"query": "([^"]+)"', q)
            words = set(re.findall(r"[a-z0-9]+", m.group(1).lower())) if m else set()
            if "retriever" in b and '"semantic"' not in q:  # force the second shape to be tried when needed
                pass
            sc = []
            for i, d in Elastic.docs.items():
                if d["status"] != "OPEN": continue
                sc.append((len(words & set(re.findall(r"[a-z0-9]+", d["content"].lower()))), i, d))
            sc.sort(key=lambda x: (-x[0], x[1]))
            return self._send(200, {"hits": {"hits": [{"_id": i, "_source": d} for s, i, d in sc[:5]]}})
        self._send(404, {})


def serve(handler, port):
    s = ThreadingHTTPServer(("127.0.0.1", port), handler); threading.Thread(target=s.serve_forever, daemon=True).start(); return s
