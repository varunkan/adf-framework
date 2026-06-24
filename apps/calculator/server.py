import json
import os
import http.server
import socketserver
from http import HTTPStatus

import domain

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, 'index.html')
HISTORY_PATH = os.path.join(BASE_DIR, 'history.json')
MEMORY_PATH = os.path.join(BASE_DIR, 'memory.json')

# Binary operations (extended via domain). Kept as module-level names so the
# original surface — VALID_OPS / OP_SYMBOL — continues to exist unchanged in
# meaning while now also covering power/modulo/intdiv.
VALID_OPS = domain.VALID_OPS
OP_SYMBOL = domain.BINARY_SYMBOL


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, 'r') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history):
    try:
        with open(HISTORY_PATH, 'w') as f:
            json.dump(history, f, indent=2)
    except OSError:
        pass


def load_memory():
    """Return the persisted memory-register value (0 if absent/corrupt)."""
    if not os.path.exists(MEMORY_PATH):
        return 0
    try:
        with open(MEMORY_PATH, 'r') as f:
            data = json.load(f)
            value = data.get('memory') if isinstance(data, dict) else None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return 0
            return value
    except (json.JSONDecodeError, OSError):
        return 0


def save_memory(value):
    try:
        with open(MEMORY_PATH, 'w') as f:
            json.dump({'memory': value}, f, indent=2)
    except OSError:
        pass


class RequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = 'CalculatorHTTP/1.0'

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, body):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode('utf-8'))

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            try:
                with open(INDEX_PATH, 'r', encoding='utf-8') as f:
                    self._send_html(HTTPStatus.OK, f.read())
            except OSError:
                self._send_html(HTTPStatus.NOT_FOUND, '<h1>index.html not found</h1>')
            return

        if self.path == '/api/history':
            self._send_json(HTTPStatus.OK, {'history': load_history()})
            return

        if self.path == '/api/memory':
            self._send_json(HTTPStatus.OK,
                            {'memory': domain.normalize_result(load_memory())})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {'error': 'not found'})

    def do_POST(self):
        if self.path == '/api/calculate':
            self._handle_calculate()
            return
        if self.path == '/api/unary':
            self._handle_unary()
            return
        if self.path == '/api/evaluate':
            self._handle_evaluate()
            return
        if self.path == '/api/memory':
            self._handle_memory()
            return
        if self.path == '/api/convert':
            self._handle_convert()
            return
        if self.path == '/api/stats':
            self._handle_stats()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {'error': 'not found'})

    def do_DELETE(self):
        if self.path == '/api/history':
            save_history([])
            self._send_json(HTTPStatus.OK, {'history': []})
            return
        if self.path == '/api/memory':
            save_memory(0)
            self._send_json(HTTPStatus.OK, {'memory': 0})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {'error': 'not found'})

    def _handle_calculate(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in VALID_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(VALID_OPS)})
            return

        a_raw = data.get('a')
        b_raw = data.get('b')
        try:
            a = float(a_raw)
            b = float(b_raw)
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "a and b must be numbers"})
            return

        try:
            result = domain.compute(op, a, b)
        except ZeroDivisionError:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'division by zero'})
            return
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        result_out = domain.normalize_result(result)

        expression = "{} {} {}".format(
            domain.fmt_number(a), OP_SYMBOL[op], domain.fmt_number(b))

        entry = {
            'op': op,
            'a': a,
            'b': b,
            'result': result_out,
            'expression': expression,
        }

        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _record(self, entry):
        """Prepend ``entry`` to the persisted history, capped at 50 items."""
        history = load_history()
        history.insert(0, entry)
        history = history[:50]
        save_history(history)

    def _handle_unary(self):
        """Apply a single-operand scientific operation (sqrt, sin, ln, …)."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.VALID_UNARY_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.VALID_UNARY_OPS)})
            return

        try:
            a = float(data.get('a'))
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': "a must be a number"})
            return

        try:
            result = domain.compute_unary(op, a)
        except ZeroDivisionError:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'division by zero'})
            return
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        result_out = domain.normalize_result(result)
        expression = domain.UNARY_TEMPLATE[op].format(a=domain.fmt_number(a))

        entry = {
            'op': op,
            'a': a,
            'result': result_out,
            'expression': expression,
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_evaluate(self):
        """Evaluate a free-form arithmetic expression via the safe parser."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        expression = data.get('expression')
        if not isinstance(expression, str) or expression.strip() == '':
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': 'expression must be a non-empty string'})
            return

        try:
            result = domain.evaluate(expression)
        except ZeroDivisionError:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'division by zero'})
            return
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        result_out = domain.normalize_result(result)
        entry = {
            'expression': expression,
            'result': result_out,
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_memory(self):
        """Mutate the persisted memory register (M+, M-, MS, MR, MC)."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        action = data.get('action')
        if action not in domain.MEMORY_ACTIONS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "action must be one of " + ", ".join(domain.MEMORY_ACTIONS)})
            return

        # store/add/subtract need a numeric operand; recall/clear do not.
        value = 0
        if action in ('store', 'add', 'subtract'):
            try:
                value = float(data.get('value'))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {'error': "value must be a number"})
                return

        try:
            new_memory = domain.apply_memory(action, load_memory(), value)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        save_memory(new_memory)
        self._send_json(HTTPStatus.OK, {
            'action': action,
            'memory': domain.normalize_result(new_memory),
        })

    def _handle_convert(self):
        """Convert an integer between number bases (bin/oct/dec/hex)."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        value = data.get('value')
        from_base = data.get('from_base')
        to_base = data.get('to_base')
        if value is None:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': 'value is required'})
            return

        try:
            converted = domain.convert_base(value, from_base, to_base)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        entry = {
            'value': str(value).strip(),
            'from_base': from_base,
            'to_base': to_base,
            'result': converted,
            'expression': '{} ({}) → {}'.format(
                str(value).strip(), from_base, to_base),
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_stats(self):
        """Compute descriptive statistics over a list of numbers."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        values = data.get('values')
        try:
            stats = domain.compute_stats(values)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        stats = {k: domain.normalize_result(v) for k, v in stats.items()}
        entry = {
            'count': stats['count'],
            'stats': stats,
            'result': stats['mean'],
            'expression': 'stats(n={})'.format(stats['count']),
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)


def _fmt(n):
    if n == int(n):
        return str(int(n))
    return str(n)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(port=0):
    return ThreadingHTTPServer(('', port), RequestHandler)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    server = make_server(port)
    print('Calculator server ready on http://localhost:{}'.format(server.server_address[1]))
    server.serve_forever()
