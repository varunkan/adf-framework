import json
import os
import threading
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "index.html")


def c_to_f(celsius):
    return celsius * 9.0 / 5.0 + 32.0


def f_to_c(fahrenheit):
    return (fahrenheit - 32.0) * 5.0 / 9.0


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Silence default logging to keep test output clean.
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html_bytes):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.end_headers()
        self.wfile.write(html_bytes)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            try:
                with open(INDEX_PATH, "rb") as f:
                    html = f.read()
            except OSError:
                self._send_json(500, {"error": "index.html not found"})
                return
            self._send_html(200, html)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/convert":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length > 0 else b""

        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid JSON body"})
            return

        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return

        value = data.get("value")
        direction = data.get("direction")

        if value is None or direction is None:
            self._send_json(400, {"error": "missing 'value' or 'direction'"})
            return

        # Accept numbers or numeric strings.
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            self._send_json(400, {"error": "'value' must be a number"})
            return

        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            self._send_json(400, {"error": "'value' must be finite"})
            return

        direction = str(direction).strip().lower()

        if direction in ("c2f", "ctof", "celsius-to-fahrenheit"):
            result = c_to_f(numeric)
            unit = "F"
        elif direction in ("f2c", "ftoc", "fahrenheit-to-celsius"):
            result = f_to_c(numeric)
            unit = "C"
        else:
            self._send_json(400, {"error": "'direction' must be 'c2f' or 'f2c'"})
            return

        rounded = round(result, 4)
        self._send_json(200, {
            "input": numeric,
            "direction": direction,
            "result": rounded,
            "unit": unit,
        })


def make_server(port=0):
    ThreadingTCPServer.allow_reuse_address = True
    server = ThreadingTCPServer(("127.0.0.1", port), RequestHandler)
    return server


if __name__ == "__main__":
    srv = make_server(8000)
    host, port = srv.server_address
    print("Temperature converter ready on http://127.0.0.1:%d/" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
        srv.server_close()
