import json
import threading
import unittest
import http.client

from server import make_server


class NotesAppTest(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def _conn(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def test_index_served(self):
        conn = self._conn()
        conn.request("GET", "/")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertIn("<html", body.lower())
        conn.close()

    def test_add_note_returns_200_with_note(self):
        conn = self._conn()
        payload = json.dumps({"text": "Hello world"})
        conn.request("POST", "/api/notes", body=payload,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("note", data)
        self.assertEqual(data["note"]["text"], "Hello world")
        self.assertIn("id", data["note"])
        conn.close()

    def test_list_notes_contains_added(self):
        conn = self._conn()
        conn.request("POST", "/api/notes", body=json.dumps({"text": "Note A"}),
                     headers={"Content-Type": "application/json"})
        conn.getresponse().read()
        conn.close()

        conn = self._conn()
        conn.request("GET", "/api/notes")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        texts = [n["text"] for n in data["notes"]]
        self.assertIn("Note A", texts)
        conn.close()

    def test_empty_note_returns_400(self):
        conn = self._conn()
        conn.request("POST", "/api/notes", body=json.dumps({"text": "   "}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_invalid_json_returns_400(self):
        conn = self._conn()
        conn.request("POST", "/api/notes", body="not-json",
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_unknown_path_returns_404(self):
        conn = self._conn()
        conn.request("GET", "/nope")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        conn.close()


if __name__ == "__main__":
    unittest.main()
