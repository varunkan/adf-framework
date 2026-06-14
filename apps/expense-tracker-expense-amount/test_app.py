import os
import json
import threading
import unittest
import http.client

import server


class ExpenseAPITest(unittest.TestCase):
    def setUp(self):
        # isolate data file
        self.data_file = os.path.join(server.BASE_DIR, 'expenses_test.json')
        server.DATA_FILE = self.data_file
        if os.path.exists(self.data_file):
            os.remove(self.data_file)

        self.server = server.make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if os.path.exists(self.data_file):
            os.remove(self.data_file)

    def _conn(self):
        return http.client.HTTPConnection('127.0.0.1', self.port)

    def _request(self, method, path, body=None):
        conn = self._conn()
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body)
            headers['Content-Type'] = 'application/json'
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        parsed = None
        if raw:
            try:
                parsed = json.loads(raw.decode('utf-8'))
            except ValueError:
                parsed = None
        return resp.status, parsed

    def test_index_served(self):
        conn = self._conn()
        conn.request('GET', '/')
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn('Expense Tracker', body)

    def test_create_and_read_back(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 12.5,
            'category': 'Food',
            'date': '2024-01-15',
            'note': 'Lunch'
        })
        self.assertEqual(status, 201)
        self.assertEqual(data['category'], 'Food')
        self.assertEqual(data['amount'], 12.5)
        self.assertIn('id', data)
        eid = data['id']

        status, listing = self._request('GET', '/api/expenses')
        self.assertEqual(status, 200)
        self.assertEqual(len(listing['expenses']), 1)
        self.assertEqual(listing['total'], 12.5)
        self.assertEqual(listing['breakdown']['Food'], 12.5)
        self.assertEqual(listing['breakdown']['Bills'], 0.0)

        # delete it
        status, _ = self._request('DELETE', '/api/expenses/' + eid)
        self.assertEqual(status, 200)
        status, listing = self._request('GET', '/api/expenses')
        self.assertEqual(len(listing['expenses']), 0)
        self.assertEqual(listing['total'], 0)

    def test_total_and_breakdown_multiple(self):
        self._request('POST', '/api/expenses', {'amount': 10, 'category': 'Food', 'date': '2024-01-01'})
        self._request('POST', '/api/expenses', {'amount': 5, 'category': 'Food', 'date': '2024-01-02'})
        self._request('POST', '/api/expenses', {'amount': 20, 'category': 'Bills', 'date': '2024-01-03'})
        status, listing = self._request('GET', '/api/expenses')
        self.assertEqual(status, 200)
        self.assertEqual(listing['total'], 35.0)
        self.assertEqual(listing['breakdown']['Food'], 15.0)
        self.assertEqual(listing['breakdown']['Bills'], 20.0)

    def test_persistence_across_restart(self):
        self._request('POST', '/api/expenses', {'amount': 7, 'category': 'Fun', 'date': '2024-02-02'})
        # raw file should contain it
        with open(self.data_file) as f:
            saved = json.load(f)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['category'], 'Fun')

    def test_invalid_amount_returns_400(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': -5, 'category': 'Food', 'date': '2024-01-15'
        })
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_category_returns_400(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 5, 'category': 'Nope', 'date': '2024-01-15'
        })
        self.assertEqual(status, 400)

    def test_invalid_date_returns_400(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 5, 'category': 'Food', 'date': 'not-a-date'
        })
        self.assertEqual(status, 400)

    def test_delete_missing_returns_404(self):
        status, data = self._request('DELETE', '/api/expenses/doesnotexist')
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_unknown_route_returns_404(self):
        status, _ = self._request('GET', '/api/unknown')
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
