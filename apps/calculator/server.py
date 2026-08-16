import json
import math
import os
import threading
import http.server
import socketserver
from http import HTTPStatus

import domain

# Serializes the read-modify-write of the shared history.json and memory.json
# files so concurrent requests (ThreadingHTTPServer) cannot lose an entry.
_STATE_LOCK = threading.Lock()

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
        # Serialize first with allow_nan=False; a non-finite value raises here
        # and we skip the write rather than persisting invalid JSON.
        text = json.dumps(history, indent=2, allow_nan=False)
        with open(HISTORY_PATH, 'w') as f:
            f.write(text)
    except (OSError, ValueError):
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
        text = json.dumps({'memory': value}, indent=2, allow_nan=False)
        with open(MEMORY_PATH, 'w') as f:
            f.write(text)
    except (OSError, ValueError):
        pass


class RequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = 'CalculatorHTTP/1.0'

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status, payload):
        # allow_nan=False makes json.dumps raise on Infinity/-Infinity/NaN
        # instead of emitting the non-standard tokens that browsers' JSON.parse
        # rejects. A non-finite result (e.g. 1e308*10 overflow, or a 'nan'/'inf'
        # input) is reported as a 400 rather than an unparseable 200 body.
        try:
            body = json.dumps(payload, allow_nan=False).encode('utf-8')
        except ValueError:
            status = HTTPStatus.BAD_REQUEST
            body = json.dumps(
                {'error': 'result is not a finite number'}).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parse_float_fields(self, data, fields):
        """Parse named float fields from request data; send 400 and return None on error."""
        params = {}
        for name in fields:
            try:
                params[name] = float(data.get(name))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {'error': "{} must be numbers".format(', '.join(fields))})
                return None
        return params

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
        parsed = json.loads(raw.decode('utf-8'))
        # The handlers all treat the body as a JSON object (data.get(...)).
        # Reject any other JSON shape (list/number/string/null) here so it is
        # caught as a 400 rather than raising AttributeError outside the
        # handler's try/except.
        if not isinstance(parsed, dict):
            raise ValueError('request body must be a JSON object')
        return parsed

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            try:
                with open(INDEX_PATH, 'r', encoding='utf-8') as f:
                    self._send_html(HTTPStatus.OK, f.read())
            except OSError:
                self._send_html(HTTPStatus.NOT_FOUND, '<h1>index.html not found</h1>')
            return

        if self.path == '/favicon.ico':
            # Serve an empty favicon so the browser does not log a 404/network
            # error for its automatic /favicon.ico request.
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header('Content-Type', 'image/x-icon')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

        if self.path in ('/health', '/api/health'):
            self._send_json(HTTPStatus.OK, {'status': 'ok'})
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
        if self.path == '/api/percent':
            self._handle_percent()
            return
        if self.path == '/api/numtheory':
            self._handle_numtheory()
            return
        if self.path == '/api/fraction':
            self._handle_fraction()
            return
        if self.path == '/api/solve':
            self._handle_solve()
            return
        if self.path == '/api/finance':
            self._handle_finance()
            return
        if self.path == '/api/units':
            self._handle_units()
            return
        if self.path == '/api/date':
            self._handle_date()
            return
        if self.path == '/api/vector':
            self._handle_vector()
            return
        if self.path == '/api/matrix':
            self._handle_matrix()
            return
        if self.path == '/api/complex':
            self._handle_complex()
            return
        if self.path == '/api/polynomial':
            self._handle_polynomial()
            return
        if self.path == '/api/geometry':
            self._handle_geometry()
            return
        if self.path == '/api/roman':
            self._handle_roman()
            return
        if self.path == '/api/regression':
            self._handle_regression()
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
        """Prepend ``entry`` to the persisted history, capped at 50 items.

        The load→insert→save is held under ``_STATE_LOCK`` so concurrent
        requests cannot read the same baseline and overwrite each other.
        """
        with _STATE_LOCK:
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

        # Hold the lock across load→apply→save so a concurrent M+/M- cannot
        # lose an update against the shared memory.json register.
        with _STATE_LOCK:
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


    def _handle_percent(self):
        """Apply a percentage operation (of, change, increase, decrease)."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.VALID_PERCENT_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.VALID_PERCENT_OPS)})
            return

        try:
            a = float(data.get('a'))
            b = float(data.get('b'))
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "a and b must be numbers"})
            return

        try:
            result = domain.compute_percent(op, a, b)
        except ZeroDivisionError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        result_out = domain.normalize_result(result)
        expression = domain.PERCENT_SYMBOL[op].format(
            a=domain.fmt_number(a), b=domain.fmt_number(b))

        entry = {
            'op': op,
            'a': a,
            'b': b,
            'result': result_out,
            'expression': expression,
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_numtheory(self):
        """Apply a number-theory operation to a single integer operand."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.NUMBER_THEORY_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.NUMBER_THEORY_OPS)})
            return

        try:
            n = float(data.get('n'))
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': "n must be a number"})
            return

        try:
            result = domain.number_theory(op, n)
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        # result is a bool, int or list — pass ints through normalize; leave
        # bools and lists intact for clean JSON.
        if isinstance(result, list):
            result_out = result
        else:
            result_out = domain.normalize_result(result)

        expression = domain.NUMBER_THEORY_LABEL[op].format(n=domain.fmt_number(n))
        entry = {
            'op': op,
            'n': domain.normalize_result(n),
            'result': result_out,
            'expression': expression,
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_fraction(self):
        """Exact fraction arithmetic over n1/d1 and n2/d2 (no float error)."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.FRACTION_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.FRACTION_OPS)})
            return

        try:
            n1 = float(data.get('n1'))
            d1 = float(data.get('d1'))
            n2 = float(data.get('n2'))
            d2 = float(data.get('d2'))
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "n1, d1, n2 and d2 must be numbers"})
            return

        try:
            result = domain.compute_fraction(op, n1, d1, n2, d2)
        except ZeroDivisionError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        text = domain.format_fraction(result)
        expression = '{}/{} {} {}/{}'.format(
            int(n1), int(d1), domain.FRACTION_SYMBOL[op], int(n2), int(d2))
        entry = {
            'op': op,
            'numerator': result.numerator,
            'denominator': result.denominator,
            'decimal': domain.normalize_result(result.numerator / result.denominator),
            'result': text,
            'expression': expression,
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_solve(self):
        """Solve an equation: linear (ax+b=0), quadratic (ax²+bx+c=0) or a
        2×2 linear system."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        kind = data.get('kind')
        if kind not in domain.SOLVE_KINDS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "kind must be one of " + ", ".join(domain.SOLVE_KINDS)})
            return

        # Required numeric coefficients per equation kind.
        fields = {
            'linear': ('a', 'b'),
            'quadratic': ('a', 'b', 'c'),
            'system2': ('a1', 'b1', 'c1', 'a2', 'b2', 'c2'),
        }[kind]

        coeffs = {}
        for name in fields:
            try:
                coeffs[name] = float(data.get(name))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {'error': "{} must be a number".format(', '.join(fields))})
                return

        if kind == 'linear':
            solution = domain.solve_linear(coeffs['a'], coeffs['b'])
            expression = '{}x + {} = 0'.format(
                domain.fmt_number(coeffs['a']), domain.fmt_number(coeffs['b']))
        elif kind == 'quadratic':
            solution = domain.solve_quadratic(coeffs['a'], coeffs['b'], coeffs['c'])
            expression = '{}x² + {}x + {} = 0'.format(
                domain.fmt_number(coeffs['a']), domain.fmt_number(coeffs['b']),
                domain.fmt_number(coeffs['c']))
        else:
            solution = domain.solve_system2(
                coeffs['a1'], coeffs['b1'], coeffs['c1'],
                coeffs['a2'], coeffs['b2'], coeffs['c2'])
            expression = '{}x+{}y={}; {}x+{}y={}'.format(
                domain.fmt_number(coeffs['a1']), domain.fmt_number(coeffs['b1']),
                domain.fmt_number(coeffs['c1']), domain.fmt_number(coeffs['a2']),
                domain.fmt_number(coeffs['b2']), domain.fmt_number(coeffs['c2']))

        entry = dict(solution)
        entry['expression'] = expression
        entry['result'] = domain.solve_result_text(solution)
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_finance(self):
        """Financial calculations: interest, loan payments, time-value money."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.FINANCE_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.FINANCE_OPS)})
            return

        fields = domain.FINANCE_FIELDS[op]
        params = self._parse_float_fields(data, fields)
        if params is None:
            return

        try:
            result = domain.compute_finance(op, params)
        except ZeroDivisionError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        result = {k: domain.normalize_result(v) for k, v in result.items()}
        primary = result[domain.FINANCE_PRIMARY[op]]
        entry = {
            'op': op,
            'inputs': {k: domain.normalize_result(v) for k, v in params.items()},
            'finance': result,
            'result': primary,
            'expression': domain.finance_expression(op, params),
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_units(self):
        """Convert a quantity between units within a category (length, mass,
        temperature, volume, time, data, speed)."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        category = data.get('category')
        if category not in domain.VALID_UNIT_CATEGORIES:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "category must be one of " + ", ".join(domain.VALID_UNIT_CATEGORIES)})
            return

        from_unit = data.get('from_unit')
        to_unit = data.get('to_unit')
        try:
            value = float(data.get('value'))
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': "value must be a number"})
            return

        try:
            result = domain.convert_unit(category, value, from_unit, to_unit)
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        result_out = domain.normalize_result(result)
        expression = '{} {} → {}'.format(
            domain.fmt_number(value), from_unit, to_unit)
        entry = {
            'category': category,
            'value': domain.normalize_result(value),
            'from_unit': from_unit,
            'to_unit': to_unit,
            'result': result_out,
            'expression': expression,
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_date(self):
        """Date arithmetic: difference, shift by days, or weekday lookup."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.DATE_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.DATE_OPS)})
            return

        try:
            result = domain.date_calc(op, data)
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        # Build a history-friendly expression/result per op.
        if op == 'diff':
            primary = result['days']
            expression = '{} → {}'.format(data.get('date1'), data.get('date2'))
        elif op == 'add':
            primary = result['date']
            expression = '{} + {}d'.format(data.get('date'), data.get('days'))
        elif op == 'subtract':
            primary = result['date']
            expression = '{} − {}d'.format(data.get('date'), data.get('days'))
        else:  # weekday
            primary = result['name']
            expression = 'weekday({})'.format(data.get('date'))

        entry = dict(result)
        entry['op'] = op
        entry['result'] = primary
        entry['expression'] = expression
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)


    def _handle_vector(self):
        """Vector calculator: add/subtract/dot/cross/scale/magnitude/
        normalize/distance/angle over Euclidean vectors."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.VECTOR_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.VECTOR_OPS)})
            return

        k = None
        if op == 'scale':
            try:
                k = float(data.get('k'))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST, {'error': "k must be a number"})
                return

        try:
            result = domain.compute_vector(op, data.get('a'), data.get('b'), k)
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        result_out = _norm_deep(result)
        entry = {
            'op': op,
            'result': result_out,
            'expression': 'vec.{}'.format(op),
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_matrix(self):
        """Matrix calculator: add/subtract/multiply/scale/transpose/
        determinant/inverse/identity/trace over real-valued matrices."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.MATRIX_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.MATRIX_OPS)})
            return

        k = None
        n = None
        if op == 'scale':
            try:
                k = float(data.get('k'))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST, {'error': "k must be a number"})
                return
        if op == 'identity':
            try:
                n = float(data.get('n'))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST, {'error': "n must be a number"})
                return

        try:
            result = domain.compute_matrix(op, a=data.get('a'), b=data.get('b'),
                                           k=k, n=n)
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        result_out = _norm_deep(result)
        entry = {
            'op': op,
            'result': result_out,
            'expression': 'mat.{}'.format(op),
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)


    def _handle_complex(self):
        """Complex-number calculator: add/subtract/multiply/divide/conjugate/
        power/modulus/argument/polar over rectangular a+bi values."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.COMPLEX_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.COMPLEX_OPS)})
            return

        # z1 is always required; z2 only for the binary ops; n only for power.
        try:
            re1 = float(data.get('re1', 0))
            im1 = float(data.get('im1', 0))
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "re1 and im1 must be numbers"})
            return

        re2 = im2 = 0.0
        if op in domain.COMPLEX_BINARY:
            try:
                re2 = float(data.get('re2', 0))
                im2 = float(data.get('im2', 0))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {'error': "re2 and im2 must be numbers"})
                return

        n = 0
        if op == 'power':
            try:
                n = float(data.get('n'))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST, {'error': "n must be a number"})
                return

        try:
            result = domain.compute_complex(op, re1, im1, re2, im2, n)
        except ZeroDivisionError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        z1_text = domain.format_complex(complex(re1, im1))
        entry = {'op': op}
        if 'real' in result:
            z = complex(result['real'], result['imag'])
            entry['real'] = domain.normalize_result(result['real'])
            entry['imag'] = domain.normalize_result(result['imag'])
            entry['result'] = domain.format_complex(z)
        else:
            for k, v in result.items():
                entry[k] = domain.normalize_result(v)
            if op == 'polar':
                entry['result'] = '{} ∠ {} rad'.format(
                    domain.fmt_number(entry['modulus']),
                    domain.fmt_number(entry['argument']))
            elif op == 'modulus':
                entry['result'] = domain.fmt_number(entry['modulus'])
            else:  # argument
                entry['result'] = domain.fmt_number(entry['argument'])

        if op in domain.COMPLEX_BINARY:
            z2_text = domain.format_complex(complex(re2, im2))
            entry['expression'] = '({}) {} ({})'.format(
                z1_text, domain.COMPLEX_SYMBOL[op], z2_text)
        elif op == 'power':
            entry['expression'] = '({})^{}'.format(z1_text, domain.fmt_number(n))
        else:
            entry['expression'] = '{}({})'.format(op, z1_text)

        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_polynomial(self):
        """Polynomial calculator: evaluate/derivative/integral/add/multiply over
        ascending coefficient lists."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.POLYNOMIAL_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.POLYNOMIAL_OPS)})
            return

        x = None
        if op == 'evaluate':
            try:
                x = float(data.get('x'))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST, {'error': "x must be a number"})
                return

        try:
            result = domain.compute_polynomial(
                op, coeffs=data.get('coeffs'), a=data.get('a'),
                b=data.get('b'), x=x)
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        entry = {'op': op, 'expression': 'poly.{}'.format(op)}
        if isinstance(result, list):
            entry['coefficients'] = _norm_deep(result)
            entry['result'] = entry['coefficients']
            entry['poly'] = domain.format_polynomial(result)
        else:
            entry['result'] = domain.normalize_result(result)
            if op == 'evaluate':
                entry['x'] = domain.normalize_result(x)
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_geometry(self):
        """Geometry calculator: area/perimeter of 2-D shapes and volume/surface
        of 3-D solids."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        shape = data.get('shape')
        if shape not in domain.GEOMETRY_SHAPES:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "shape must be one of " + ", ".join(domain.GEOMETRY_SHAPES)})
            return

        fields = domain.GEOMETRY_FIELDS[shape]
        params = self._parse_float_fields(data, fields)
        if params is None:
            return

        try:
            metrics = domain.compute_geometry(shape, params)
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        metrics = {k: domain.normalize_result(v) for k, v in metrics.items()}
        entry = {
            'shape': shape,
            'inputs': {k: domain.normalize_result(v) for k, v in params.items()},
            'geometry': metrics,
            'result': metrics[domain.GEOMETRY_PRIMARY[shape]],
            'expression': 'geo.{}'.format(shape),
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_roman(self):
        """Roman-numeral conversion: to_roman (int→numeral) and from_roman
        (numeral→int), canonical 1..3999."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op')
        if op not in domain.ROMAN_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.ROMAN_OPS)})
            return

        if op == 'to_roman':
            try:
                value = float(data.get('value'))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST, {'error': "value must be a number"})
                return
            try:
                result = domain.to_roman(value)
            except (ValueError, OverflowError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            expression = '{} → roman'.format(
                domain.fmt_number(domain.normalize_result(value)))
        else:  # from_roman
            try:
                result = domain.from_roman(data.get('value'))
            except (ValueError, OverflowError) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
                return
            expression = '{} → decimal'.format(str(data.get('value')).strip())

        entry = {'op': op, 'result': result, 'expression': expression}
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)

    def _handle_regression(self):
        """Linear-regression calculator: ordinary least-squares fit over
        [x, y] points, with optional prediction at a given x."""
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        op = data.get('op', 'fit')
        if op not in domain.REGRESSION_OPS:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': "op must be one of " + ", ".join(domain.REGRESSION_OPS)})
            return

        predict_x = None
        if op == 'predict':
            predict_x = data.get('predict_x')
            if predict_x is None:
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {'error': 'predict_x is required for predict'})
                return

        try:
            fit = domain.compute_regression(data.get('points'), predict_x)
        except (ValueError, OverflowError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return

        fit = {k: domain.normalize_result(v) for k, v in fit.items()}
        entry = {
            'op': op,
            'regression': fit,
            'result': fit.get('predict_y', fit['slope']),
            'expression': 'y = {}x + {}'.format(
                domain.fmt_number(fit['slope']), domain.fmt_number(fit['intercept'])),
        }
        self._record(entry)
        self._send_json(HTTPStatus.OK, entry)


def _norm_deep(value):
    """Normalize a scalar, or recursively normalize a (possibly nested) list,
    so vectors/matrices serialize with clean integer-valued entries."""
    if isinstance(value, list):
        return [_norm_deep(x) for x in value]
    return domain.normalize_result(value)


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
    port = int(os.environ.get('ADF_SMOKE_PORT') or os.environ.get('PORT') or 8000)
    server = make_server(port)
    print('Calculator server ready on http://localhost:{}'.format(server.server_address[1]))
    server.serve_forever()
