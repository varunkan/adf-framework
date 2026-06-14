import json
import os
import http.server
import socketserver


def calculate_tip(bill, tip_percent):
    """Calculate tip and total. Returns (tip, total) rounded to 2 decimals.
    Raises ValueError on invalid input."""
    if bill is None or tip_percent is None:
        raise ValueError("bill and tip_percent are required")
    try:
        bill = float(bill)
        tip_percent = float(tip_percent)
    except (TypeError, ValueError):
        raise ValueError("bill and tip_percent must be numbers")
    if bill < 0:
        raise ValueError("bill must be non-negative")
    if tip_percent < 0 or tip_percent > 100:
        raise ValueError("tip_percent must be between 0 and 100")
    tip = round(bill * tip_percent / 100.0, 2)
    total = round(bill + tip, 2)
    return tip, total


class RequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            here = os.path.dirname(os.path.abspath(__file__))
            index_path = os.path.join(here, "index.html")
            try:
                with open(index_path, "rb") as f:
                    body = f.read()
            except OSError:
                self._send_json(500, {"error": "index.html not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/tip":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid JSON"})
                return
            try:
                tip, total = calculate_tip(data.get("bill"), data.get("tip_percent"))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"tip": tip, "total": total})
            return
        self._send_json(404, {"error": "not found"})


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(port=0):
    return _Server(("127.0.0.1", port), RequestHandler)


if __name__ == "__main__":
    server = make_server(8000)
    print("Tip calculator server ready on http://127.0.0.1:8000")
    server.serve_forever()
