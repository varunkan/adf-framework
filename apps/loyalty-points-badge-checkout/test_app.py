import json
import threading
import unittest
import http.client

from server import make_server, RequestHandler


class LoyaltyAppTest(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _conn(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def test_handler_class_importable(self):
        self.assertTrue(issubclass(RequestHandler, http.client.HTTPConnection.__bases__[0].__class__.__mro__[-1] if False else object))
        self.assertTrue(hasattr(RequestHandler, "do_GET"))
        self.assertTrue(hasattr(RequestHandler, "do_POST"))

    def test_index_served(self):
        conn = self._conn()
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.getheader("Content-Type", ""))
        self.assertIn("Checkout", body)
        conn.close()

    def test_loyalty_badge_returned(self):
        conn = self._conn()
        conn.request("GET", "/api/loyalty/alice")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["customer_id"], "alice")
        self.assertIn("points", data)
        self.assertIn("tier", data)
        self.assertIn("badge_label", data)
        self.assertIn("color", data)
        conn.close()

    def test_unknown_customer_404(self):
        conn = self._conn()
        conn.request("GET", "/api/loyalty/nobody")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        conn.close()

    def test_checkout_earns_points(self):
        conn = self._conn()
        body = json.dumps({"customer_id": "bob", "amount_cents": 5000})
        conn.request("POST", "/api/checkout", body,
                     {"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["points_earned"], 50)
        self.assertEqual(data["customer_id"], "bob")
        self.assertIn("points_total", data)
        self.assertIn("badge_label", data)
        conn.close()

    def test_checkout_invalid_amount_400(self):
        conn = self._conn()
        body = json.dumps({"customer_id": "bob", "amount_cents": -5})
        conn.request("POST", "/api/checkout", body,
                     {"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_checkout_missing_customer_400(self):
        conn = self._conn()
        body = json.dumps({"amount_cents": 100})
        conn.request("POST", "/api/checkout", body,
                     {"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_checkout_invalid_json_400(self):
        conn = self._conn()
        conn.request("POST", "/api/checkout", "not json",
                     {"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_customers_list(self):
        conn = self._conn()
        conn.request("GET", "/api/customers")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("alice", data["customers"])
        conn.close()

    def test_unknown_route_404(self):
        conn = self._conn()
        conn.request("GET", "/nope")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        conn.close()


if __name__ == "__main__":
    unittest.main()
