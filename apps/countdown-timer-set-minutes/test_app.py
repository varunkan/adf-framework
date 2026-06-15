import json
import threading
import unittest
import http.client

from server import make_server, RequestHandler, _state


class CountdownTimerTests(unittest.TestCase):
    def setUp(self):
        # reset module state to defaults
        _state.update({'minutes': 5, 'seconds': 0, 'remaining': 300, 'running': False})
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _conn(self):
        return http.client.HTTPConnection('localhost', self.port)

    def _request(self, method, path, body=None):
        conn = self._conn()
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers['Content-Type'] = 'application/json'
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        status = resp.status
        conn.close()
        try:
            parsed = json.loads(data)
        except ValueError:
            parsed = None
        return status, parsed

    def test_index_served(self):
        status, _ = self._request('GET', '/')
        self.assertEqual(status, 200)

    def test_main_success_path(self):
        # REQ-001/002: set minutes and seconds
        status, data = self._request('POST', '/api/timer', {'minutes': 2, 'seconds': 30})
        self.assertEqual(status, 201)
        self.assertEqual(data['minutes'], 2)
        self.assertEqual(data['seconds'], 30)
        self.assertEqual(data['remaining'], 150)
        self.assertFalse(data['running'])

        # read it back
        status, data = self._request('GET', '/api/timer')
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 150)

        # REQ-002: start
        status, data = self._request('POST', '/api/timer/start')
        self.assertEqual(status, 200)
        self.assertTrue(data['running'])

        # tick once -> decrement
        status, data = self._request('POST', '/api/timer/tick')
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 149)

        # REQ-002: pause
        status, data = self._request('POST', '/api/timer/pause')
        self.assertEqual(status, 200)
        self.assertFalse(data['running'])

        # tick while paused -> no change
        status, data = self._request('POST', '/api/timer/tick')
        self.assertEqual(data['remaining'], 149)

        # REQ-003: reset
        status, data = self._request('POST', '/api/timer/reset')
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 150)
        self.assertFalse(data['running'])

    def test_invalid_seconds_returns_400(self):
        status, data = self._request('POST', '/api/timer', {'minutes': 1, 'seconds': 99})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_minutes_returns_400(self):
        status, data = self._request('POST', '/api/timer', {'minutes': 99, 'seconds': 10})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_missing_fields_returns_400(self):
        status, data = self._request('POST', '/api/timer', {'minutes': 1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_unknown_route_returns_404(self):
        status, data = self._request('GET', '/api/nope')
        self.assertEqual(status, 404)
        self.assertIn('error', data)


if __name__ == '__main__':
    unittest.main()
