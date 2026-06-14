import os
import json
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'expenses.json')
INDEX_FILE = os.path.join(BASE_DIR, 'index.html')

CATEGORIES = {'Food', 'Transport', 'Bills', 'Fun', 'Other'}

_lock = threading.Lock()


def _load():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (ValueError, OSError):
        return []


def _save(expenses):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(expenses, f, indent=2)


def _valid_date(s):
    if not isinstance(s, str) or len(s) != 10:
        return False
    parts = s.split('-')
    if len(parts) != 3:
        return False
    y, m, d = parts
    if not (y.isdigit() and m.isdigit() and d.isdigit()):
        return False
    if len(y) != 4 or len(m) != 2 or len(d) != 2:
        return False
    mi, di = int(m), int(d)
    return 1 <= mi <= 12 and 1 <= di <= 31


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
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
        except ValueError:
            return None

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self._serve_index()
            return
        if self.path == '/api/expenses':
            with _lock:
                expenses = _load()
            total = round(sum(float(e['amount']) for e in expenses), 2)
            breakdown = {c: 0.0 for c in CATEGORIES}
            for e in expenses:
                breakdown[e['category']] = round(breakdown.get(e['category'], 0.0) + float(e['amount']), 2)
            self._send_json({'expenses': expenses, 'total': total, 'breakdown': breakdown})
            return
        self._send_json({'error': 'not found'}, 404)

    def _serve_index(self):
        try:
            with open(INDEX_FILE, 'rb') as f:
                body = f.read()
        except OSError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != '/api/expenses':
            self._send_json({'error': 'not found'}, 404)
            return
        data = self._read_body()
        if data is None or not isinstance(data, dict):
            self._send_json({'error': 'invalid JSON'}, 400)
            return

        amount = data.get('amount')
        category = data.get('category')
        note = data.get('note', '')
        date = data.get('date')

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            self._send_json({'error': 'amount must be a number'}, 400)
            return
        if amount <= 0:
            self._send_json({'error': 'amount must be positive'}, 400)
            return
        if category not in CATEGORIES:
            self._send_json({'error': 'invalid category'}, 400)
            return
        if not _valid_date(date):
            self._send_json({'error': 'invalid date (expected YYYY-MM-DD)'}, 400)
            return
        if note is None:
            note = ''
        if not isinstance(note, str):
            self._send_json({'error': 'note must be a string'}, 400)
            return

        expense = {
            'id': uuid.uuid4().hex,
            'amount': round(amount, 2),
            'category': category,
            'note': note.strip(),
            'date': date,
        }
        with _lock:
            expenses = _load()
            expenses.append(expense)
            _save(expenses)
        self._send_json(expense, 201)

    def do_DELETE(self):
        prefix = '/api/expenses/'
        if not self.path.startswith(prefix):
            self._send_json({'error': 'not found'}, 404)
            return
        eid = self.path[len(prefix):]
        with _lock:
            expenses = _load()
            new = [e for e in expenses if e['id'] != eid]
            if len(new) == len(expenses):
                self._send_json({'error': 'expense not found'}, 404)
                return
            _save(new)
        self._send_json({'deleted': eid})


def make_server(port=0):
    return ThreadingHTTPServer(('', port), RequestHandler)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = make_server(port)
    print('Expense tracker server ready on port %d' % server.server_address[1])
    server.serve_forever()
