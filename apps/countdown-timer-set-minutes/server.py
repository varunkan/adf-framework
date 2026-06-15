import os
import json
import threading
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, 'index.html')

# In-memory timer state with a lock for thread safety.
_lock = threading.Lock()
_state = {
    'minutes': 5,
    'seconds': 0,
    'remaining': 5 * 60,   # remaining seconds
    'running': False,
}


def _clamp_int(value, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < lo or n > hi:
        return None
    return n


def get_state():
    with _lock:
        return dict(_state)


def set_timer(minutes, seconds):
    """Set timer minutes (0-60) and seconds (0-59). Returns (state, error)."""
    m = _clamp_int(minutes, 0, 60)
    s = _clamp_int(seconds, 0, 59)
    if m is None or s is None:
        return None, 'minutes must be 0-60 and seconds must be 0-59'
    with _lock:
        _state['minutes'] = m
        _state['seconds'] = s
        _state['remaining'] = m * 60 + s
        _state['running'] = False
        return dict(_state), None


def start_timer():
    with _lock:
        if _state['remaining'] > 0:
            _state['running'] = True
        return dict(_state)


def pause_timer():
    with _lock:
        _state['running'] = False
        return dict(_state)


def reset_timer():
    with _lock:
        _state['running'] = False
        _state['remaining'] = _state['minutes'] * 60 + _state['seconds']
        return dict(_state)


def tick():
    """Decrement remaining by one second if running. Returns state."""
    with _lock:
        if _state['running'] and _state['remaining'] > 0:
            _state['remaining'] -= 1
            if _state['remaining'] <= 0:
                _state['remaining'] = 0
                _state['running'] = False
        return dict(_state)


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html):
        body = html.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return None

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            try:
                with open(INDEX_PATH, 'r', encoding='utf-8') as f:
                    html = f.read()
            except OSError:
                self._send_html(500, '<h1>index.html not found</h1>')
                return
            self._send_html(200, html)
            return

        if self.path == '/api/timer':
            self._send_json(200, get_state())
            return

        self._send_json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path == '/api/timer':
            body = self._read_body()
            if body is None or not isinstance(body, dict):
                self._send_json(400, {'error': 'invalid JSON body'})
                return
            if 'minutes' not in body or 'seconds' not in body:
                self._send_json(400, {'error': 'minutes and seconds are required'})
                return
            state, err = set_timer(body.get('minutes'), body.get('seconds'))
            if err:
                self._send_json(400, {'error': err})
                return
            self._send_json(201, state)
            return

        if self.path == '/api/timer/start':
            self._send_json(200, start_timer())
            return

        if self.path == '/api/timer/pause':
            self._send_json(200, pause_timer())
            return

        if self.path == '/api/timer/reset':
            self._send_json(200, reset_timer())
            return

        if self.path == '/api/timer/tick':
            self._send_json(200, tick())
            return

        self._send_json(404, {'error': 'not found'})


class _Server(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_server(port=0):
    return _Server(('', port), RequestHandler)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = make_server(port)
    print('Server ready on port %d (http://localhost:%d)' % (server.server_address[1], server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
