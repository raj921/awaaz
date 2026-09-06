"""Memory sidecar: serves one MemoryStore over local HTTP (stdlib only).

Single-user demo store ("local"); restart-safe via pickle snapshot.
Endpoints (JSON):
  POST /add     {"text": "..."} -> {"id": N, "text": "..."}
  POST /forget  {"text": "..."} -> {"forgot": true|false}
  GET  /facts                   -> {"facts": [{"id": N, "text": "..."}]}
  POST /context {"query": "..."} -> {"block": "MEMORY:\n- ..."} ("" when empty)
"""
import json
import pickle
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from memory_v2 import MemoryStore

SNAP = Path(__file__).with_name(".memory_snap.pkl")
store = MemoryStore()


def save():
    try:
        SNAP.write_bytes(pickle.dumps(store))
    except Exception:
        pass


try:
    if SNAP.exists():
        store = pickle.loads(SNAP.read_bytes())
except Exception:
    store = MemoryStore()


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        try:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        if self.path != "/facts":
            return self._send({"error": "not found"}, 404)
        self._send({"facts": [
            {"id": m.id, "text": m.text}
            for m in sorted(store.memories.values(), key=lambda m: m.id)
            if m.status == "active" and m.text
        ]})

    def do_POST(self):
        if self.path == "/add":
            m = store.add((self._body().get("text") or "").strip())
            save()
            return self._send({"id": m.id, "text": m.text} if m else {"id": None, "text": ""})
        if self.path == "/forget":
            ok = store.forget((self._body().get("text") or "").strip())
            save()
            return self._send({"forgot": ok})
        if self.path == "/context":
            q = (self._body().get("query") or "").strip()
            return self._send({"block": store.context_block(q) if q else ""})
        return self._send({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 18081), H).serve_forever()
