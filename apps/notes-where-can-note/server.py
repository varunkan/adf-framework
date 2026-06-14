import json
import os
import threading
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

# In-memory note store
_notes = []
_next_id = 1
_lock = threading.Lock()

INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


def _read_index():
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<!doctype html><html><body><h1>index.html not found</h1></body></html>"


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, text):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._send_html(200, _read_index())
            return
        if self.path == "/api/notes":
            with _lock:
                self._send_json(200, {"notes": list(_notes)})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/notes":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length > 0 else b""

        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid JSON"})
            return

        if not isinstance(data, dict):
            self._send_json(400, {"error": "invalid payload"})
            return

        text = data.get("text", "")
        if not isinstance(text, str) or text.strip() == "":
            self._send_json(400, {"error": "note text must be non-empty"})
            return

        global _next_id
        with _lock:
            note = {"id": _next_id, "text": text.strip()}
            _next_id += 1
            _notes.append(note)

        self._send_json(200, {"note": note})


def make_server(port=0):
    ThreadingTCPServer.allow_reuse_address = True
    server = ThreadingTCPServer(("127.0.0.1", port), RequestHandler)
    return server


if __name__ == "__main__":
    srv = make_server(8000)
    print("Notes app server ready at http://127.0.0.1:8000")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
        srv.server_close()
