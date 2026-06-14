import json
import threading
import unittest
import http.client

from server import make_server, RequestHandler


class TemperatureConverterTest(unittest.TestCase):
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
        conn.close()
        return status, data

    def test_handler_class_exists(self):
        self.assertTrue(issubclass(RequestHandler, object))

    def test_index_served(self):
        status, data = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Temperature Converter", data)

    def test_celsius_to_fahrenheit(self):
        status, data = self._post("/api/convert", {"value": 100, "direction": "c2f"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 212.0)
        self.assertEqual(payload["unit"], "F")

    def test_fahrenheit_to_celsius(self):
        status, data = self._post("/api/convert", {"value": 32, "direction": "f2c"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 0.0)
        self.assertEqual(payload["unit"], "C")

    def test_negative_celsius(self):
        status, data = self._post("/api/convert", {"value": -40, "direction": "c2f"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], -40.0)

    def test_string_numeric_value_accepted(self):
        status, data = self._post("/api/convert", {"value": "37", "direction": "c2f"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 98.6)

    def test_invalid_value_returns_400(self):
        status, data = self._post("/api/convert", {"value": "abc", "direction": "c2f"})
        self.assertEqual(status, 400)

    def test_missing_fields_returns_400(self):
        status, data = self._post("/api/convert", {"value": 10})
        self.assertEqual(status, 400)

    def test_invalid_direction_returns_400(self):
        status, data = self._post("/api/convert", {"value": 10, "direction": "x2y"})
        self.assertEqual(status, 400)

    def test_unknown_path_returns_404(self):
        status, data = self._get("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
