import json
import threading
import unittest
import http.client

from server import make_server, RequestHandler, calculate_tip


class TipCalculatorTest(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        body = json.dumps(payload)
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
        conn.close()
        return status, data

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
        ctype = resp.getheader("Content-Type")
        conn.close()
        return status, data, ctype

    def test_index_served(self):
        status, data, ctype = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"Tip Calculator", data)

    def test_tip_calculation(self):
        status, data = self._post("/api/tip", {"bill": 100, "tip_percent": 15})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 15.0)
        self.assertEqual(payload["total"], 115.0)

    def test_tip_rounding(self):
        status, data = self._post("/api/tip", {"bill": 53.27, "tip_percent": 18})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 9.59)
        self.assertEqual(payload["total"], 62.86)

    def test_zero_bill(self):
        status, data = self._post("/api/tip", {"bill": 0, "tip_percent": 20})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 0.0)
        self.assertEqual(payload["total"], 0.0)

    def test_negative_bill_invalid(self):
        status, data = self._post("/api/tip", {"bill": -5, "tip_percent": 10})
        self.assertEqual(status, 400)

    def test_tip_percent_out_of_range(self):
        status, data = self._post("/api/tip", {"bill": 50, "tip_percent": 150})
        self.assertEqual(status, 400)

    def test_missing_fields(self):
        status, data = self._post("/api/tip", {})
        self.assertEqual(status, 400)

    def test_non_numeric(self):
        status, data = self._post("/api/tip", {"bill": "abc", "tip_percent": 10})
        self.assertEqual(status, 400)

    def test_unknown_route_404(self):
        status, data, _ = self._get("/nope")
        self.assertEqual(status, 404)

    def test_calculate_tip_unit(self):
        self.assertEqual(calculate_tip(200, 10), (20.0, 220.0))
        with self.assertRaises(ValueError):
            calculate_tip(-1, 10)
        with self.assertRaises(ValueError):
            calculate_tip(10, 200)


if __name__ == "__main__":
    unittest.main()
