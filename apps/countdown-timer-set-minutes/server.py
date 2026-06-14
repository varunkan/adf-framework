import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, 'index.html')

# In-memory timer state guarded by a lock
_lock = threading.Lock()
_state = {
    'minutes': 0,
    'seconds': 0,
    'remaining': 0,   # total seconds remaining
    'running': False,
}


def _clamp_state():
    total = _state['minutes'] * 60 + _state['seconds']
    _state['remaining'] = total


def validate_set(minutes, seconds):
    if not isinstance(minutes, int) or not isinstance(seconds, int):
        return 'minutes and seconds must be integers'
    if minutes < 0 or minutes > 1439:
        return 'minutes out of range (0-1439)'
    if seconds < 0 or seconds > 59:
        return 'seconds out of range (0-59)'
    return None


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, code, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode('utf-8'))
        except Exception:
            return None

    def _snapshot(self):
        with _lock:
            return {
                'minutes': _state['minutes'],
                'seconds': _state['seconds'],
                'remaining': _state['remaining'],
                'running': _state['running'],
                'display': _format(_state['remaining']),
            }

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            try:
                with open(INDEX_PATH, 'rb') as f:
                    body = f.read()
            except OSError:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'index.html not found')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == '/api/timer':
            self._send_json(200, self._snapshot())
            return

        self._send_json(404, {'error': 'not found'})

    def do_POST(self):
        # REQ-001/002: set minutes and seconds
        if self.path == '/api/timer/set':
            data = self._read_json()
            if data is None:
                self._send_json(400, {'error': 'invalid JSON'})
                return
            minutes = data.get('minutes', 0)
            seconds = data.get('seconds', 0)
            err = validate_set(minutes, seconds)
            if err:
                self._send_json(400, {'error': err})
                return
            with _lock:
                _state['minutes'] = minutes
                _state['seconds'] = seconds
                _clamp_state()
                _state['running'] = False
            self._send_json(200, self._snapshot())
            return

        # REQ-002: start
        if self.path == '/api/timer/start':
            with _lock:
                if _state['remaining'] <= 0:
                    self._send_json(400, {'error': 'nothing to count down'})
                    return
                _state['running'] = True
            self._send_json(200, self._snapshot())
            return

        # REQ-002: pause
        if self.path == '/api/timer/pause':
            with _lock:
                _state['running'] = False
            self._send_json(200, self._snapshot())
            return

        # REQ-002: tick (decrement one second)
        if self.path == '/api/timer/tick':
            with _lock:
                if _state['running'] and _state['remaining'] > 0:
                    _state['remaining'] -= 1
                    if _state['remaining'] <= 0:
                        _state['remaining'] = 0
                        _state['running'] = False
            self._send_json(200, self._snapshot())
            return

        # REQ-003: reset
        if self.path == '/api/timer/reset':
            with _lock:
                _state['running'] = False
                _clamp_state()
            self._send_json(200, self._snapshot())
            return

        self._send_json(404, {'error': 'not found'})


def _format(total_seconds):
    if total_seconds < 0:
        total_seconds = 0
    m = total_seconds // 60
    s = total_seconds % 60
    return '%02d:%02d' % (m, s)


def make_server(port=0):
    return ThreadingHTTPServer(('0.0.0.0', port), RequestHandler)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = make_server(port)
    print('Countdown timer server ready on port %d' % server.server_address[1])
    server.serve_forever()
