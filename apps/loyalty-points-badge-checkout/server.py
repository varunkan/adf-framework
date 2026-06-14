import json
import os
import threading
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, "index.html")

# In-memory loyalty data store
_LOCK = threading.Lock()
# customer_id -> points balance
_LOYALTY = {
    "guest": 0,
    "alice": 1250,
    "bob": 340,
    "carol": 8765,
}

# Tier thresholds for badge metadata
def tier_for(points):
    if points >= 5000:
        return {"name": "Platinum", "color": "#6c5ce7"}
    if points >= 1000:
        return {"name": "Gold", "color": "#f5b301"}
    if points >= 250:
        return {"name": "Silver", "color": "#95a5a6"}
    return {"name": "Bronze", "color": "#cd7f32"}


def loyalty_for(customer_id):
    with _LOCK:
        points = _LOYALTY.get(customer_id)
    if points is None:
        return None
    tier = tier_for(points)
    # Points earned per dollar; redemption value
    return {
        "customer_id": customer_id,
        "points": points,
        "tier": tier["name"],
        "color": tier["color"],
        "redeem_value_cents": points,  # 100 points = $1.00
        "badge_label": "{} \u2022 {} pts".format(tier["name"], points),
    }


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "LoyaltyBadge/1.0"

    def log_message(self, fmt, *args):
        pass  # silence

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code, html):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            try:
                with open(INDEX_PATH, "r", encoding="utf-8") as f:
                    html = f.read()
            except OSError:
                self._send_json(500, {"error": "index.html not found"})
                return
            self._send_html(200, html)
            return

        if path.startswith("/api/loyalty/"):
            customer_id = path[len("/api/loyalty/"):].strip("/")
            if not customer_id:
                self._send_json(400, {"error": "customer_id required"})
                return
            data = loyalty_for(customer_id)
            if data is None:
                self._send_json(404, {"error": "unknown customer"})
                return
            self._send_json(200, data)
            return

        if path == "/api/customers":
            with _LOCK:
                ids = sorted(_LOYALTY.keys())
            self._send_json(200, {"customers": ids})
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""

        if path == "/api/checkout":
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid json"})
                return

            customer_id = payload.get("customer_id")
            amount_cents = payload.get("amount_cents")

            if not customer_id or not isinstance(customer_id, str):
                self._send_json(400, {"error": "customer_id required"})
                return
            if not isinstance(amount_cents, int) or amount_cents < 0:
                self._send_json(400, {"error": "amount_cents must be a non-negative integer"})
                return

            data = loyalty_for(customer_id)
            if data is None:
                self._send_json(404, {"error": "unknown customer"})
                return

            # Earn 1 point per dollar spent (100 cents)
            earned = amount_cents // 100
            with _LOCK:
                _LOYALTY[customer_id] = _LOYALTY.get(customer_id, 0) + earned
                new_points = _LOYALTY[customer_id]

            tier = tier_for(new_points)
            self._send_json(200, {
                "customer_id": customer_id,
                "amount_cents": amount_cents,
                "points_earned": earned,
                "points_total": new_points,
                "tier": tier["name"],
                "color": tier["color"],
                "badge_label": "{} \u2022 {} pts".format(tier["name"], new_points),
            })
            return

        self._send_json(404, {"error": "not found"})


class ThreadingHTTPServer(ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_server(port=0):
    return ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)


if __name__ == "__main__":
    server = make_server(8000)
    print("Loyalty badge server ready on http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
