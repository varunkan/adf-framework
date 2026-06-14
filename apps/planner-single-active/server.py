import json
import os
import threading
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

# In-memory store: code -> original url
STORE = {}
# Single-active lock state: only one active session allowed at a time
_active_lock = threading.Lock()
_active_holder = {"id": None}

_counter_lock = threading.Lock()
_counter = {"n": 0}

HERE = os.path.dirname(os.path.abspath(__file__))


def _next_code():
    with _counter_lock:
        _counter["n"] += 1
        n = _counter["n"]
    # base36 encode
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    s = ""
    while n > 0:
        s = alphabet[n % 36] + s
        n //= 36
    return s


def _valid_url(url):
    if not isinstance(url, str):
        return False
    url = url.strip()
    if not url:
        return False
    return url.startswith("http://") or url.startswith("https://")


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/" or path == "/index.html":
            try:
                with open(os.path.join(HERE, "index.html"), "r", encoding="utf-8") as f:
                    html = f.read()
            except OSError:
                self._send_html(500, "<h1>index.html not found</h1>")
                return
            self._send_html(200, html)
            return

        if path == "/api/active":
            self._send_json(200, {"active_holder": _active_holder["id"]})
            return

        # treat as short code
        code = path.lstrip("/")
        if code and code in STORE:
            target = STORE[code]
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length > 0 else b""

        if path == "/api/shorten":
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid json"})
                return

            url = data.get("url", "")
            if not _valid_url(url):
                self._send_json(400, {"error": "invalid url"})
                return

            url = url.strip()
            code = _next_code()
            STORE[code] = url
            host = self.headers.get("Host", "localhost")
            short_url = "http://{}/{}".format(host, code)
            self._send_json(200, {"short_url": short_url, "code": code})
            return

        # Single-active session acquire/release endpoints (REQ-001)
        if path == "/api/acquire":
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                data = {}
            session_id = data.get("session_id") or _next_code()
            if _active_lock.acquire(blocking=False):
                _active_holder["id"] = session_id
                self._send_json(200, {"acquired": True, "session_id": session_id})
            else:
                self._send_json(409, {"acquired": False, "active_holder": _active_holder["id"]})
            return

        if path == "/api/release":
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                data = {}
            session_id = data.get("session_id")
            if _active_holder["id"] is not None and session_id == _active_holder["id"]:
                _active_holder["id"] = None
                try:
                    _active_lock.release()
                except RuntimeError:
                    pass
                self._send_json(200, {"released": True})
            else:
                self._send_json(400, {"released": False, "error": "not holder"})
            return

        self._send_json(404, {"error": "not found"})


class _Server(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_server(port=0):
    server = _Server(("127.0.0.1", port), RequestHandler)
    return server


if __name__ == "__main__":
    srv = make_server(8000)
    print("Server ready on http://127.0.0.1:8000")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
