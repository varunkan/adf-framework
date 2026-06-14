import json
import threading
import unittest
import http.client

from server import make_server


class CountdownTimerTest(unittest.TestCase):
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
        return http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)

    def _post(self, path, payload=None):
        conn = self._conn()
        body = json.dumps(payload) if payload is not None else None
        headers = {'Content-Type': 'application/json'}
        conn.request('POST', path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        conn.close()
        return resp.status, json.loads(data) if data else {}

    def _get(self, path):
        conn = self._conn()
        conn.request('GET', path)
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
        ctype = resp.getheader('Content-Type', '')
        conn.close()
        return status, ctype, data

    def test_index_served(self):
        status, ctype, data = self._get('/')
        self.assertEqual(status, 200)
        self.assertIn('text/html', ctype)
        self.assertIn(b'Countdown Timer', data)

    def test_set_start_tick_reset_flow(self):
        # set 1 minute 5 seconds (REQ-001/002)
        status, body = self._post('/api/timer/set', {'minutes': 1, 'seconds': 5})
        self.assertEqual(status, 200)
        self.assertEqual(body['remaining'], 65)
        self.assertEqual(body['display'], '01:05')
        self.assertFalse(body['running'])

        # start (REQ-002)
        status, body = self._post('/api/timer/start')
        self.assertEqual(status, 200)
        self.assertTrue(body['running'])

        # tick decrements
        status, body = self._post('/api/timer/tick')
        self.assertEqual(status, 200)
        self.assertEqual(body['remaining'], 64)
        self.assertEqual(body['display'], '01:04')

        # pause (REQ-002)
        status, body = self._post('/api/timer/pause')
        self.assertEqual(status, 200)
        self.assertFalse(body['running'])

        # reset restores full duration (REQ-003)
        status, body = self._post('/api/timer/reset')
        self.assertEqual(status, 200)
        self.assertEqual(body['remaining'], 65)
        self.assertEqual(body['display'], '01:05')
        self.assertFalse(body['running'])

    def test_get_timer_state(self):
        self._post('/api/timer/set', {'minutes': 0, 'seconds': 30})
        status, _, data = self._get('/api/timer')
        self.assertEqual(status, 200)
        body = json.loads(data.decode('utf-8'))
        self.assertEqual(body['remaining'], 30)
        self.assertEqual(body['display'], '00:30')

    def test_invalid_seconds_returns_400(self):
        status, body = self._post('/api/timer/set', {'minutes': 0, 'seconds': 99})
        self.assertEqual(status, 400)
        self.assertIn('error', body)

    def test_start_with_zero_returns_400(self):
        self._post('/api/timer/set', {'minutes': 0, 'seconds': 0})
        status, body = self._post('/api/timer/start')
        self.assertEqual(status, 400)
        self.assertIn('error', body)

    def test_unknown_route_404(self):
        status, body = self._post('/api/nope')
        self.assertEqual(status, 404)
        self.assertIn('error', body)


if __name__ == '__main__':
    unittest.main()
