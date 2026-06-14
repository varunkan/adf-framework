import unittest
import http.client
import threading
from server import make_server, RequestHandler
import json

class TestApp(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()

    def test_shorten(self):
        conn = http.client.HTTPConnection(f'localhost:{self.port}')
        conn.request('POST', '/api/shorten', json.dumps({'url': 'https://www.example.com'}), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        data = json.loads(response.read())
        self.assertIn('short_url', data)
        self.assertIn('code', data)

    def test_redirect(self):
        conn = http.client.HTTPConnection(f'localhost:{self.port}')
        conn.request('POST', '/api/shorten', json.dumps({'url': 'https://www.example.com'}), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        data = json.loads(response.read())
        code = data['code']
        conn.request('GET', f'/{code}')
        response = conn.getresponse()
        self.assertEqual(response.status, 302)
        self.assertEqual(response.getheader('Location'), 'https://www.example.com')

    def test_invalid_url(self):
        conn = http.client.HTTPConnection(f'localhost:{self.port}')
        conn.request('POST', '/api/shorten', json.dumps({'url': 'invalid'}), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        self.assertEqual(response.status, 400)

if __name__ == '__main__':
    unittest.main()
