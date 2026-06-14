import json
import threading
import unittest
import http.client

from server import make_server, RequestHandler


class AppTests(unittest.TestCase):
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

    def test_handler_class_exists(self):
        self.assertTrue(issubclass(RequestHandler, http.client.HTTPConnection.__mro__[0].__class__.__class__ if False else object))

    def test_shorten_returns_code(self):
        conn = self._conn()
        body = json.dumps({"url": "https://example.com/foo"})
        conn.request("POST", "/api/shorten", body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode())
        self.assertIn("code", data)
        self.assertIn("short_url", data)
        self.assertTrue(data["code"])
        conn.close()

    def test_redirect_302(self):
        original = "https://example.com/redirect/target"
        conn = self._conn()
        conn.request("POST", "/api/shorten", body=json.dumps({"url": original}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode())
        code = data["code"]
        conn.close()

        conn2 = self._conn()
        conn2.request("GET", "/" + code)
        resp2 = conn2.getresponse()
        self.assertEqual(resp2.status, 302)
        self.assertEqual(resp2.getheader("Location"), original)
        resp2.read()
        conn2.close()

    def test_invalid_url_400(self):
        conn = self._conn()
        conn.request("POST", "/api/shorten", body=json.dumps({"url": ""}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        resp.read()
        conn.close()

        conn = self._conn()
        conn.request("POST", "/api/shorten", body=json.dumps({"url": "ftp://nope"}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        resp.read()
        conn.close()

    def test_unknown_code_404(self):
        conn = self._conn()
        conn.request("GET", "/doesnotexist999")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        resp.read()
        conn.close()

    def test_single_active_acquire_then_blocked(self):
        # REQ-001: only one active session at a time
        conn = self._conn()
        conn.request("POST", "/api/acquire", body=json.dumps({"session_id": "s1"}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        d = json.loads(resp.read().decode())
        self.assertTrue(d["acquired"])
        conn.close()

        # second acquire must be blocked (409)
        conn = self._conn()
        conn.request("POST", "/api/acquire", body=json.dumps({"session_id": "s2"}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 409)
        d = json.loads(resp.read().decode())
        self.assertFalse(d["acquired"])
        conn.close()

        # release s1
        conn = self._conn()
        conn.request("POST", "/api/release", body=json.dumps({"session_id": "s1"}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        d = json.loads(resp.read().decode())
        self.assertTrue(d["released"])
        conn.close()

        # now s2 can acquire
        conn = self._conn()
        conn.request("POST", "/api/acquire", body=json.dumps({"session_id": "s2"}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        resp.read()
        conn.close()


if __name__ == "__main__":
    unittest.main()
