import json
import math
import threading
import unittest
import http.client

from server import make_server


class CalculatorTest(unittest.TestCase):
    def setUp(self):
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

    def _post(self, path, payload):
        conn = self._conn()
        body = json.dumps(payload)
        conn.request('POST', path, body=body,
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        conn.close()
        return resp.status, json.loads(data) if data else {}

    def _get(self, path):
        conn = self._conn()
        conn.request('GET', path)
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        conn.close()
        return resp.status, data

    def test_index_served(self):
        status, body = self._get('/')
        self.assertEqual(status, 200)
        self.assertIn('Calculator', body)

    def test_add(self):
        status, data = self._post('/api/calculate', {'op': 'add', 'a': 2, 'b': 3})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 5)

    def test_divide(self):
        status, data = self._post('/api/calculate', {'op': 'divide', 'a': 10, 'b': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 2.5)

    def test_multiply(self):
        status, data = self._post('/api/calculate', {'op': 'multiply', 'a': 6, 'b': 7})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 42)

    def test_history_roundtrip(self):
        self._post('/api/calculate', {'op': 'subtract', 'a': 9, 'b': 4})
        conn = self._conn()
        conn.request('GET', '/api/history')
        resp = conn.getresponse()
        data = json.loads(resp.read().decode('utf-8'))
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertTrue(any(e['result'] == 5 for e in data['history']))

    def test_divide_by_zero(self):
        status, data = self._post('/api/calculate', {'op': 'divide', 'a': 5, 'b': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_op(self):
        status, data = self._post('/api/calculate', {'op': 'pow', 'a': 2, 'b': 3})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_number(self):
        status, data = self._post('/api/calculate', {'op': 'add', 'a': 'x', 'b': 3})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_not_found(self):
        conn = self._conn()
        conn.request('GET', '/api/nope')
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)

    # ------------------------------------------------------------------
    # Extended binary operations (power / modulo / intdiv)
    # ------------------------------------------------------------------
    def test_power(self):
        status, data = self._post('/api/calculate', {'op': 'power', 'a': 2, 'b': 10})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 1024)

    def test_modulo(self):
        status, data = self._post('/api/calculate', {'op': 'modulo', 'a': 17, 'b': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 2)

    def test_intdiv(self):
        status, data = self._post('/api/calculate', {'op': 'intdiv', 'a': 17, 'b': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 3)

    def test_modulo_by_zero(self):
        status, data = self._post('/api/calculate', {'op': 'modulo', 'a': 5, 'b': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_power_complex_rejected(self):
        # (-1) ** 0.5 is complex and must be rejected, not crash.
        status, data = self._post('/api/calculate', {'op': 'power', 'a': -1, 'b': 0.5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    # ------------------------------------------------------------------
    # Unary / scientific operations — POST /api/unary
    # ------------------------------------------------------------------
    def test_unary_sqrt(self):
        status, data = self._post('/api/unary', {'op': 'sqrt', 'a': 144})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 12)

    def test_unary_square(self):
        status, data = self._post('/api/unary', {'op': 'square', 'a': 9})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 81)

    def test_unary_factorial(self):
        status, data = self._post('/api/unary', {'op': 'factorial', 'a': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 120)

    def test_unary_negate(self):
        status, data = self._post('/api/unary', {'op': 'negate', 'a': 7})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], -7)

    def test_unary_reciprocal(self):
        status, data = self._post('/api/unary', {'op': 'reciprocal', 'a': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 0.25)

    def test_unary_sin_zero(self):
        status, data = self._post('/api/unary', {'op': 'sin', 'a': 0})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 0)

    def test_unary_percent(self):
        status, data = self._post('/api/unary', {'op': 'percent', 'a': 50})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 0.5)

    def test_unary_expression_field(self):
        status, data = self._post('/api/unary', {'op': 'sqrt', 'a': 9})
        self.assertEqual(status, 200)
        self.assertIn('√', data['expression'])

    def test_unary_sqrt_negative(self):
        status, data = self._post('/api/unary', {'op': 'sqrt', 'a': -4})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_unary_reciprocal_zero(self):
        status, data = self._post('/api/unary', {'op': 'reciprocal', 'a': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_unary_ln_nonpositive(self):
        status, data = self._post('/api/unary', {'op': 'ln', 'a': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_unary_factorial_negative(self):
        status, data = self._post('/api/unary', {'op': 'factorial', 'a': -1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_unary_invalid_op(self):
        status, data = self._post('/api/unary', {'op': 'bogus', 'a': 1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_unary_invalid_number(self):
        status, data = self._post('/api/unary', {'op': 'sqrt', 'a': 'x'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_unary_recorded_in_history(self):
        self._post('/api/unary', {'op': 'square', 'a': 11})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e['result'] == 121 for e in history))

    # ------------------------------------------------------------------
    # Free-form expression evaluation — POST /api/evaluate
    # ------------------------------------------------------------------
    def test_evaluate_simple(self):
        status, data = self._post('/api/evaluate', {'expression': '2 + 3 * 4'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 14)

    def test_evaluate_parentheses(self):
        status, data = self._post('/api/evaluate', {'expression': '(2 + 3) * 4'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 20)

    def test_evaluate_power_right_assoc(self):
        status, data = self._post('/api/evaluate', {'expression': '2 ^ 3 ^ 2'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 512)

    def test_evaluate_unary_minus(self):
        status, data = self._post('/api/evaluate', {'expression': '-5 + 2'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], -3)

    def test_evaluate_constant_pi(self):
        status, data = self._post('/api/evaluate', {'expression': 'pi'})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['result'], 3.141592653590, places=6)

    def test_evaluate_division_by_zero(self):
        status, data = self._post('/api/evaluate', {'expression': '1 / 0'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_evaluate_malformed(self):
        status, data = self._post('/api/evaluate', {'expression': '2 +'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_evaluate_unknown_name(self):
        status, data = self._post('/api/evaluate', {'expression': 'foo + 1'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_evaluate_empty(self):
        status, data = self._post('/api/evaluate', {'expression': '   '})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_evaluate_missing_field(self):
        status, data = self._post('/api/evaluate', {})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_evaluate_recorded_in_history(self):
        self._post('/api/evaluate', {'expression': '6 * 7'})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e['result'] == 42 for e in history))

    # ------------------------------------------------------------------
    # Extended scientific unary operations
    # ------------------------------------------------------------------
    def test_unary_cbrt(self):
        status, data = self._post('/api/unary', {'op': 'cbrt', 'a': 27})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['result'], 3, places=9)

    def test_unary_cbrt_negative(self):
        # Real cube root of a negative is defined (unlike sqrt).
        status, data = self._post('/api/unary', {'op': 'cbrt', 'a': -8})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['result'], -2, places=9)

    def test_unary_sinh_zero(self):
        status, data = self._post('/api/unary', {'op': 'sinh', 'a': 0})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 0)

    def test_unary_cosh_zero(self):
        status, data = self._post('/api/unary', {'op': 'cosh', 'a': 0})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 1)

    def test_unary_tanh_zero(self):
        status, data = self._post('/api/unary', {'op': 'tanh', 'a': 0})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 0)

    def test_unary_floor(self):
        status, data = self._post('/api/unary', {'op': 'floor', 'a': 3.7})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 3)

    def test_unary_ceil(self):
        status, data = self._post('/api/unary', {'op': 'ceil', 'a': 3.2})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 4)

    def test_unary_round(self):
        status, data = self._post('/api/unary', {'op': 'round', 'a': 2.4})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 2)

    def test_unary_sign_negative(self):
        status, data = self._post('/api/unary', {'op': 'sign', 'a': -42})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], -1)

    def test_unary_sign_zero(self):
        status, data = self._post('/api/unary', {'op': 'sign', 'a': 0})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 0)

    def test_unary_deg(self):
        status, data = self._post('/api/unary', {'op': 'deg', 'a': 3.141592653589793})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['result'], 180, places=6)

    def test_unary_rad(self):
        status, data = self._post('/api/unary', {'op': 'rad', 'a': 180})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['result'], 3.141592653589793, places=9)

    # ------------------------------------------------------------------
    # Extended expression constants (tau, phi)
    # ------------------------------------------------------------------
    def test_evaluate_constant_tau(self):
        status, data = self._post('/api/evaluate', {'expression': 'tau'})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['result'], 6.283185307180, places=6)

    def test_evaluate_constant_phi(self):
        status, data = self._post('/api/evaluate', {'expression': 'phi * 2'})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['result'], 3.2360679775, places=6)

    # ------------------------------------------------------------------
    # Memory register — /api/memory
    # ------------------------------------------------------------------
    def _clear_memory(self):
        return self._post('/api/memory', {'action': 'clear'})

    def test_memory_store_and_recall(self):
        self._clear_memory()
        status, data = self._post('/api/memory', {'action': 'store', 'value': 42})
        self.assertEqual(status, 200)
        self.assertEqual(data['memory'], 42)
        status, data = self._post('/api/memory', {'action': 'recall'})
        self.assertEqual(status, 200)
        self.assertEqual(data['memory'], 42)

    def test_memory_add(self):
        self._clear_memory()
        self._post('/api/memory', {'action': 'store', 'value': 10})
        status, data = self._post('/api/memory', {'action': 'add', 'value': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['memory'], 15)

    def test_memory_subtract(self):
        self._clear_memory()
        self._post('/api/memory', {'action': 'store', 'value': 10})
        status, data = self._post('/api/memory', {'action': 'subtract', 'value': 3})
        self.assertEqual(status, 200)
        self.assertEqual(data['memory'], 7)

    def test_memory_clear(self):
        self._post('/api/memory', {'action': 'store', 'value': 99})
        status, data = self._post('/api/memory', {'action': 'clear'})
        self.assertEqual(status, 200)
        self.assertEqual(data['memory'], 0)

    def test_memory_get(self):
        self._clear_memory()
        self._post('/api/memory', {'action': 'store', 'value': 8})
        status, body = self._get('/api/memory')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['memory'], 8)

    def test_memory_delete_clears(self):
        self._post('/api/memory', {'action': 'store', 'value': 5})
        conn = self._conn()
        conn.request('DELETE', '/api/memory')
        resp = conn.getresponse()
        data = json.loads(resp.read().decode('utf-8'))
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertEqual(data['memory'], 0)

    def test_memory_invalid_action(self):
        status, data = self._post('/api/memory', {'action': 'bogus'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_memory_store_invalid_value(self):
        status, data = self._post('/api/memory', {'action': 'store', 'value': 'x'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_memory_add_to_empty(self):
        self._clear_memory()
        status, data = self._post('/api/memory', {'action': 'add', 'value': 7})
        self.assertEqual(status, 200)
        self.assertEqual(data['memory'], 7)

    # ------------------------------------------------------------------
    # GCD / LCM binary operations — POST /api/calculate
    # ------------------------------------------------------------------
    def test_gcd(self):
        status, data = self._post('/api/calculate', {'op': 'gcd', 'a': 24, 'b': 36})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 12)

    def test_gcd_coprime(self):
        status, data = self._post('/api/calculate', {'op': 'gcd', 'a': 17, 'b': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 1)

    def test_lcm(self):
        status, data = self._post('/api/calculate', {'op': 'lcm', 'a': 4, 'b': 6})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 12)

    def test_gcd_requires_integers(self):
        status, data = self._post('/api/calculate', {'op': 'gcd', 'a': 2.5, 'b': 5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_lcm_requires_integers(self):
        status, data = self._post('/api/calculate', {'op': 'lcm', 'a': 4, 'b': 6.1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_gcd_recorded_in_history(self):
        self._post('/api/calculate', {'op': 'gcd', 'a': 48, 'b': 18})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e['result'] == 6 for e in history))

    # ------------------------------------------------------------------
    # Number-base conversion — POST /api/convert
    # ------------------------------------------------------------------
    def test_convert_dec_to_hex(self):
        status, data = self._post('/api/convert',
                                  {'value': '255', 'from_base': 'dec', 'to_base': 'hex'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 'ff')

    def test_convert_hex_to_dec(self):
        status, data = self._post('/api/convert',
                                  {'value': 'ff', 'from_base': 'hex', 'to_base': 'dec'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '255')

    def test_convert_dec_to_bin(self):
        status, data = self._post('/api/convert',
                                  {'value': '10', 'from_base': 'dec', 'to_base': 'bin'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '1010')

    def test_convert_bin_to_oct(self):
        status, data = self._post('/api/convert',
                                  {'value': '1000', 'from_base': 'bin', 'to_base': 'oct'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '10')

    def test_convert_negative(self):
        status, data = self._post('/api/convert',
                                  {'value': '-255', 'from_base': 'dec', 'to_base': 'hex'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '-ff')

    def test_convert_invalid_value(self):
        status, data = self._post('/api/convert',
                                  {'value': 'xyz', 'from_base': 'dec', 'to_base': 'hex'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_convert_invalid_base(self):
        status, data = self._post('/api/convert',
                                  {'value': '10', 'from_base': 'dec', 'to_base': 'base64'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_convert_missing_value(self):
        status, data = self._post('/api/convert',
                                  {'from_base': 'dec', 'to_base': 'hex'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_convert_recorded_in_history(self):
        self._post('/api/convert',
                   {'value': '16', 'from_base': 'dec', 'to_base': 'hex'})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == '10' for e in history))

    # ------------------------------------------------------------------
    # Descriptive statistics — POST /api/stats
    # ------------------------------------------------------------------
    def test_stats_basic(self):
        status, data = self._post('/api/stats', {'values': [1, 2, 3, 4, 5]})
        self.assertEqual(status, 200)
        s = data['stats']
        self.assertEqual(s['count'], 5)
        self.assertEqual(s['sum'], 15)
        self.assertEqual(s['mean'], 3)
        self.assertEqual(s['median'], 3)
        self.assertEqual(s['min'], 1)
        self.assertEqual(s['max'], 5)
        self.assertEqual(s['range'], 4)

    def test_stats_mode(self):
        status, data = self._post('/api/stats', {'values': [1, 2, 2, 3]})
        self.assertEqual(status, 200)
        self.assertEqual(data['stats']['mode'], 2)

    def test_stats_stdev_variance(self):
        status, data = self._post('/api/stats', {'values': [2, 4, 4, 4, 5, 5, 7, 9]})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['stats']['variance'], 4.571428571, places=6)
        self.assertAlmostEqual(data['stats']['stdev'], 2.13808993, places=6)

    def test_stats_single_value(self):
        status, data = self._post('/api/stats', {'values': [42]})
        self.assertEqual(status, 200)
        s = data['stats']
        self.assertEqual(s['count'], 1)
        self.assertEqual(s['mean'], 42)
        self.assertEqual(s['stdev'], 0)
        self.assertEqual(s['variance'], 0)

    def test_stats_empty(self):
        status, data = self._post('/api/stats', {'values': []})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_stats_missing_field(self):
        status, data = self._post('/api/stats', {})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_stats_non_numeric(self):
        status, data = self._post('/api/stats', {'values': [1, 'x', 3]})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_stats_recorded_in_history(self):
        self._post('/api/stats', {'values': [10, 20, 30]})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == 20 for e in history))


    # ------------------------------------------------------------------
    # Bitwise binary operations — POST /api/calculate
    # ------------------------------------------------------------------
    def test_bitwise_and(self):
        status, data = self._post('/api/calculate', {'op': 'and', 'a': 12, 'b': 10})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 8)

    def test_bitwise_or(self):
        status, data = self._post('/api/calculate', {'op': 'or', 'a': 12, 'b': 10})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 14)

    def test_bitwise_xor(self):
        status, data = self._post('/api/calculate', {'op': 'xor', 'a': 12, 'b': 10})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 6)

    def test_bitwise_lshift(self):
        status, data = self._post('/api/calculate', {'op': 'lshift', 'a': 1, 'b': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 16)

    def test_bitwise_rshift(self):
        status, data = self._post('/api/calculate', {'op': 'rshift', 'a': 64, 'b': 3})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 8)

    def test_bitwise_requires_integers(self):
        status, data = self._post('/api/calculate', {'op': 'and', 'a': 2.5, 'b': 3})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_bitwise_negative_shift(self):
        status, data = self._post('/api/calculate', {'op': 'lshift', 'a': 1, 'b': -2})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_lshift_oversized_shift_rejected(self):
        # 1 << 1_000_000_000 would produce a ~120 MB integer — must be capped.
        status, data = self._post('/api/calculate', {'op': 'lshift', 'a': 1, 'b': 1_000_000_000})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_lshift_at_limit_accepted(self):
        # Exactly at MAX_LSHIFT_B (10000) must succeed.
        status, data = self._post('/api/calculate', {'op': 'lshift', 'a': 1, 'b': 10000})
        self.assertEqual(status, 200)
        self.assertIn('result', data)

    def test_bitwise_recorded_in_history(self):
        self._post('/api/calculate', {'op': 'xor', 'a': 5, 'b': 3})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == 6 for e in history))

    # ------------------------------------------------------------------
    # Combinatorics binary operations — POST /api/calculate
    # ------------------------------------------------------------------
    def test_ncr(self):
        status, data = self._post('/api/calculate', {'op': 'ncr', 'a': 5, 'b': 2})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 10)

    def test_npr(self):
        status, data = self._post('/api/calculate', {'op': 'npr', 'a': 5, 'b': 2})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 20)

    def test_ncr_k_greater_than_n(self):
        # math.comb defines C(n, k) = 0 when k > n.
        status, data = self._post('/api/calculate', {'op': 'ncr', 'a': 3, 'b': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 0)

    def test_ncr_requires_integers(self):
        status, data = self._post('/api/calculate', {'op': 'ncr', 'a': 5.5, 'b': 2})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_npr_negative(self):
        status, data = self._post('/api/calculate', {'op': 'npr', 'a': -1, 'b': 2})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    # ------------------------------------------------------------------
    # Unary bitwise NOT — POST /api/unary
    # ------------------------------------------------------------------
    def test_unary_bitnot(self):
        status, data = self._post('/api/unary', {'op': 'bitnot', 'a': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], -6)

    def test_unary_bitnot_requires_integer(self):
        status, data = self._post('/api/unary', {'op': 'bitnot', 'a': 2.5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    # ------------------------------------------------------------------
    # Percentage toolkit — POST /api/percent
    # ------------------------------------------------------------------
    def test_percent_of(self):
        status, data = self._post('/api/percent', {'op': 'of', 'a': 200, 'b': 50})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 100)

    def test_percent_change_increase(self):
        status, data = self._post('/api/percent', {'op': 'change', 'a': 200, 'b': 250})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 25)

    def test_percent_change_decrease(self):
        status, data = self._post('/api/percent', {'op': 'change', 'a': 200, 'b': 150})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], -25)

    def test_percent_increase(self):
        status, data = self._post('/api/percent', {'op': 'increase', 'a': 80, 'b': 25})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 100)

    def test_percent_decrease(self):
        status, data = self._post('/api/percent', {'op': 'decrease', 'a': 100, 'b': 20})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 80)

    def test_percent_change_from_zero(self):
        status, data = self._post('/api/percent', {'op': 'change', 'a': 0, 'b': 5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_percent_invalid_op(self):
        status, data = self._post('/api/percent', {'op': 'bogus', 'a': 1, 'b': 2})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_percent_invalid_number(self):
        status, data = self._post('/api/percent', {'op': 'of', 'a': 'x', 'b': 2})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_percent_expression_field(self):
        status, data = self._post('/api/percent', {'op': 'of', 'a': 200, 'b': 50})
        self.assertEqual(status, 200)
        self.assertIn('%', data['expression'])

    def test_percent_recorded_in_history(self):
        self._post('/api/percent', {'op': 'increase', 'a': 50, 'b': 10})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == 55 for e in history))

    # ------------------------------------------------------------------
    # Number theory — POST /api/numtheory
    # ------------------------------------------------------------------
    def test_numtheory_is_prime_true(self):
        status, data = self._post('/api/numtheory', {'op': 'is_prime', 'n': 17})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], True)

    def test_numtheory_is_prime_false(self):
        status, data = self._post('/api/numtheory', {'op': 'is_prime', 'n': 15})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], False)

    def test_numtheory_is_prime_one(self):
        status, data = self._post('/api/numtheory', {'op': 'is_prime', 'n': 1})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], False)

    def test_numtheory_next_prime(self):
        status, data = self._post('/api/numtheory', {'op': 'next_prime', 'n': 13})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 17)

    def test_numtheory_prime_factors(self):
        status, data = self._post('/api/numtheory', {'op': 'prime_factors', 'n': 60})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], [2, 2, 3, 5])

    def test_numtheory_prime_factors_prime(self):
        status, data = self._post('/api/numtheory', {'op': 'prime_factors', 'n': 13})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], [13])

    def test_numtheory_divisors(self):
        status, data = self._post('/api/numtheory', {'op': 'divisors', 'n': 28})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], [1, 2, 4, 7, 14, 28])

    def test_numtheory_divisor_count(self):
        status, data = self._post('/api/numtheory', {'op': 'divisor_count', 'n': 12})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 6)

    def test_numtheory_divisor_sum(self):
        status, data = self._post('/api/numtheory', {'op': 'divisor_sum', 'n': 12})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 28)

    def test_numtheory_is_perfect_true(self):
        status, data = self._post('/api/numtheory', {'op': 'is_perfect', 'n': 28})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], True)

    def test_numtheory_is_perfect_false(self):
        status, data = self._post('/api/numtheory', {'op': 'is_perfect', 'n': 12})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], False)

    def test_numtheory_totient(self):
        status, data = self._post('/api/numtheory', {'op': 'totient', 'n': 36})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 12)

    def test_numtheory_fibonacci(self):
        status, data = self._post('/api/numtheory', {'op': 'fibonacci', 'n': 10})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 55)

    def test_numtheory_fibonacci_zero(self):
        status, data = self._post('/api/numtheory', {'op': 'fibonacci', 'n': 0})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 0)

    def test_numtheory_requires_integer(self):
        status, data = self._post('/api/numtheory', {'op': 'is_prime', 'n': 2.5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_numtheory_invalid_op(self):
        status, data = self._post('/api/numtheory', {'op': 'bogus', 'n': 5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_numtheory_invalid_number(self):
        status, data = self._post('/api/numtheory', {'op': 'is_prime', 'n': 'x'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_numtheory_totient_nonpositive(self):
        status, data = self._post('/api/numtheory', {'op': 'totient', 'n': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_numtheory_fibonacci_negative(self):
        status, data = self._post('/api/numtheory', {'op': 'fibonacci', 'n': -3})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_numtheory_is_prime_oversized_rejected(self):
        # Trial division up to sqrt(10^18) ~10^9 iterations — must be capped.
        status, data = self._post('/api/numtheory', {'op': 'is_prime', 'n': 10**18})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_numtheory_divisors_oversized_rejected(self):
        status, data = self._post('/api/numtheory', {'op': 'divisors', 'n': 10**18})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_numtheory_totient_oversized_rejected(self):
        status, data = self._post('/api/numtheory', {'op': 'totient', 'n': 10**18})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_numtheory_prime_factors_oversized_rejected(self):
        status, data = self._post('/api/numtheory', {'op': 'prime_factors', 'n': 10**18})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_numtheory_recorded_in_history(self):
        self._post('/api/numtheory', {'op': 'fibonacci', 'n': 7})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == 13 for e in history))

    # ------------------------------------------------------------------
    # Exact fraction arithmetic — POST /api/fraction
    # ------------------------------------------------------------------
    def test_fraction_add(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'add', 'n1': 1, 'd1': 2, 'n2': 1, 'd2': 3})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '5/6')
        self.assertEqual(data['numerator'], 5)
        self.assertEqual(data['denominator'], 6)

    def test_fraction_subtract(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'subtract', 'n1': 3, 'd1': 4, 'n2': 1, 'd2': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '1/2')

    def test_fraction_multiply(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'multiply', 'n1': 2, 'd1': 3, 'n2': 3, 'd2': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '1/2')

    def test_fraction_divide(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'divide', 'n1': 1, 'd1': 2, 'n2': 1, 'd2': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '2')
        self.assertEqual(data['decimal'], 2)

    def test_fraction_reduces_to_whole(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'add', 'n1': 1, 'd1': 2, 'n2': 1, 'd2': 2})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '1')
        self.assertEqual(data['denominator'], 1)

    def test_fraction_negative(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'subtract', 'n1': 1, 'd1': 4, 'n2': 1, 'd2': 2})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '-1/4')

    def test_fraction_decimal_field(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'add', 'n1': 1, 'd1': 2, 'n2': 1, 'd2': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '3/4')
        self.assertEqual(data['decimal'], 0.75)

    def test_fraction_zero_denominator(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'add', 'n1': 1, 'd1': 0, 'n2': 1, 'd2': 2})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_fraction_divide_by_zero_fraction(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'divide', 'n1': 1, 'd1': 2, 'n2': 0, 'd2': 5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_fraction_requires_integers(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'add', 'n1': 1.5, 'd1': 2, 'n2': 1, 'd2': 3})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_fraction_invalid_op(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'bogus', 'n1': 1, 'd1': 2, 'n2': 1, 'd2': 3})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_fraction_invalid_number(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'add', 'n1': 'x', 'd1': 2, 'n2': 1, 'd2': 3})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_fraction_expression_field(self):
        status, data = self._post('/api/fraction',
                                  {'op': 'multiply', 'n1': 2, 'd1': 3, 'n2': 3, 'd2': 4})
        self.assertEqual(status, 200)
        self.assertIn('×', data['expression'])

    def test_fraction_recorded_in_history(self):
        self._post('/api/fraction',
                   {'op': 'add', 'n1': 1, 'd1': 6, 'n2': 1, 'd2': 6})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == '1/3' for e in history))


    # ------------------------------------------------------------------
    # Equation solver — POST /api/solve
    # ------------------------------------------------------------------
    def test_solve_linear_one_solution(self):
        status, data = self._post('/api/solve', {'kind': 'linear', 'a': 2, 'b': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'one solution')
        self.assertEqual(data['roots'], [-2])

    def test_solve_linear_no_solution(self):
        status, data = self._post('/api/solve', {'kind': 'linear', 'a': 0, 'b': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'no solution')
        self.assertEqual(data['roots'], [])

    def test_solve_linear_infinite(self):
        status, data = self._post('/api/solve', {'kind': 'linear', 'a': 0, 'b': 0})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'infinite solutions')

    def test_solve_quadratic_two_real_roots(self):
        status, data = self._post('/api/solve',
                                  {'kind': 'quadratic', 'a': 1, 'b': -5, 'c': 6})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'two real roots')
        self.assertEqual(sorted(data['roots']), [2, 3])
        self.assertEqual(data['discriminant'], 1)

    def test_solve_quadratic_repeated_root(self):
        status, data = self._post('/api/solve',
                                  {'kind': 'quadratic', 'a': 1, 'b': -2, 'c': 1})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'one real root (repeated)')
        self.assertEqual(data['roots'], [1])
        self.assertEqual(data['discriminant'], 0)

    def test_solve_quadratic_complex_roots(self):
        status, data = self._post('/api/solve',
                                  {'kind': 'quadratic', 'a': 1, 'b': 0, 'c': 1})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'two complex roots')
        self.assertEqual(data['roots'], ['i', '-i'])

    def test_solve_quadratic_complex_general(self):
        # x² - 2x + 5 = 0 → 1 ± 2i
        status, data = self._post('/api/solve',
                                  {'kind': 'quadratic', 'a': 1, 'b': -2, 'c': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['roots'], ['1+2i', '1-2i'])

    def test_solve_quadratic_degenerate_to_linear(self):
        # a = 0 falls back to the linear case 2x + 4 = 0 → x = -2
        status, data = self._post('/api/solve',
                                  {'kind': 'quadratic', 'a': 0, 'b': 2, 'c': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'one solution')
        self.assertEqual(data['roots'], [-2])

    def test_solve_system2_unique(self):
        # x + y = 3 ; x - y = 1 → x = 2, y = 1
        status, data = self._post('/api/solve',
                                  {'kind': 'system2', 'a1': 1, 'b1': 1, 'c1': 3,
                                   'a2': 1, 'b2': -1, 'c2': 1})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'one solution')
        self.assertEqual(data['x'], 2)
        self.assertEqual(data['y'], 1)
        self.assertEqual(data['roots'], [2, 1])

    def test_solve_system2_no_solution(self):
        # x + y = 1 ; x + y = 2 (parallel, inconsistent)
        status, data = self._post('/api/solve',
                                  {'kind': 'system2', 'a1': 1, 'b1': 1, 'c1': 1,
                                   'a2': 1, 'b2': 1, 'c2': 2})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'no solution')

    def test_solve_system2_infinite(self):
        # x + y = 1 ; 2x + 2y = 2 (same line)
        status, data = self._post('/api/solve',
                                  {'kind': 'system2', 'a1': 1, 'b1': 1, 'c1': 1,
                                   'a2': 2, 'b2': 2, 'c2': 2})
        self.assertEqual(status, 200)
        self.assertEqual(data['nature'], 'infinite solutions')

    def test_solve_invalid_kind(self):
        status, data = self._post('/api/solve', {'kind': 'cubic', 'a': 1, 'b': 2})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_solve_invalid_number(self):
        status, data = self._post('/api/solve',
                                  {'kind': 'quadratic', 'a': 'x', 'b': 1, 'c': 1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_solve_missing_coefficient(self):
        status, data = self._post('/api/solve', {'kind': 'quadratic', 'a': 1, 'b': 2})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_solve_expression_field(self):
        status, data = self._post('/api/solve',
                                  {'kind': 'quadratic', 'a': 1, 'b': -5, 'c': 6})
        self.assertEqual(status, 200)
        self.assertIn('x²', data['expression'])

    def test_solve_recorded_in_history(self):
        self._post('/api/solve',
                   {'kind': 'quadratic', 'a': 1, 'b': -5, 'c': 6})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == 'x = 3, 2' for e in history))


    # ------------------------------------------------------------------
    # Complex-number calculator (/api/complex)
    # ------------------------------------------------------------------

    def test_complex_add(self):
        status, data = self._post('/api/complex',
                                  {'op': 'add', 're1': 1, 'im1': 2,
                                   're2': 3, 'im2': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['real'], 4)
        self.assertEqual(data['imag'], 6)
        self.assertEqual(data['result'], '4+6i')

    def test_complex_subtract(self):
        status, data = self._post('/api/complex',
                                  {'op': 'subtract', 're1': 5, 'im1': 3,
                                   're2': 2, 'im2': 1})
        self.assertEqual(status, 200)
        self.assertEqual(data['real'], 3)
        self.assertEqual(data['imag'], 2)
        self.assertEqual(data['result'], '3+2i')

    def test_complex_multiply(self):
        status, data = self._post('/api/complex',
                                  {'op': 'multiply', 're1': 1, 'im1': 2,
                                   're2': 3, 'im2': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['real'], -5)
        self.assertEqual(data['imag'], 10)
        self.assertEqual(data['result'], '-5+10i')

    def test_complex_divide(self):
        # 1 / i == -i
        status, data = self._post('/api/complex',
                                  {'op': 'divide', 're1': 1, 'im1': 0,
                                   're2': 0, 'im2': 1})
        self.assertEqual(status, 200)
        self.assertEqual(data['real'], 0)
        self.assertEqual(data['imag'], -1)
        self.assertEqual(data['result'], '-i')

    def test_complex_divide_by_zero(self):
        status, data = self._post('/api/complex',
                                  {'op': 'divide', 're1': 1, 'im1': 1,
                                   're2': 0, 'im2': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_complex_conjugate(self):
        status, data = self._post('/api/complex',
                                  {'op': 'conjugate', 're1': 3, 'im1': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['real'], 3)
        self.assertEqual(data['imag'], -4)
        self.assertEqual(data['result'], '3-4i')

    def test_complex_power(self):
        # (1 + i)^2 == 2i
        status, data = self._post('/api/complex',
                                  {'op': 'power', 're1': 1, 'im1': 1, 'n': 2})
        self.assertEqual(status, 200)
        self.assertEqual(data['real'], 0)
        self.assertEqual(data['imag'], 2)
        self.assertEqual(data['result'], '2i')

    def test_complex_power_non_integer(self):
        status, data = self._post('/api/complex',
                                  {'op': 'power', 're1': 1, 'im1': 1, 'n': 1.5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_complex_power_negative_of_zero(self):
        status, data = self._post('/api/complex',
                                  {'op': 'power', 're1': 0, 'im1': 0, 'n': -1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_complex_modulus(self):
        status, data = self._post('/api/complex',
                                  {'op': 'modulus', 're1': 3, 'im1': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['modulus'], 5)
        self.assertEqual(data['result'], '5')

    def test_complex_argument(self):
        # arg(0 + i) == pi/2
        status, data = self._post('/api/complex',
                                  {'op': 'argument', 're1': 0, 'im1': 1})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['argument'], math.pi / 2, places=9)

    def test_complex_polar(self):
        status, data = self._post('/api/complex',
                                  {'op': 'polar', 're1': 3, 'im1': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['modulus'], 5)
        self.assertIn('∠', data['result'])

    def test_complex_invalid_op(self):
        status, data = self._post('/api/complex',
                                  {'op': 'bogus', 're1': 1, 'im1': 1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_complex_non_numeric_operand(self):
        status, data = self._post('/api/complex',
                                  {'op': 'add', 're1': 'x', 'im1': 1,
                                   're2': 2, 'im2': 2})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_complex_recorded_in_history(self):
        self._post('/api/complex',
                   {'op': 'add', 're1': 1, 'im1': 2, 're2': 3, 'im2': 4})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == '4+6i' for e in history))


    # ------------------------------------------------------------------
    # Polynomial calculator — POST /api/polynomial
    # ------------------------------------------------------------------
    def test_polynomial_evaluate(self):
        # 1 + 2x + 3x² at x = 2 → 1 + 4 + 12 = 17
        status, data = self._post('/api/polynomial',
                                  {'op': 'evaluate', 'coeffs': [1, 2, 3], 'x': 2})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 17)

    def test_polynomial_evaluate_negative_x(self):
        # 1 + 2x + 3x² at x = -1 → 1 - 2 + 3 = 2
        status, data = self._post('/api/polynomial',
                                  {'op': 'evaluate', 'coeffs': [1, 2, 3], 'x': -1})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 2)

    def test_polynomial_derivative(self):
        # d/dx (1 + 2x + 3x²) = 2 + 6x → [2, 6]
        status, data = self._post('/api/polynomial',
                                  {'op': 'derivative', 'coeffs': [1, 2, 3]})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], [2, 6])

    def test_polynomial_derivative_constant(self):
        status, data = self._post('/api/polynomial',
                                  {'op': 'derivative', 'coeffs': [5]})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], [0])

    def test_polynomial_integral(self):
        # ∫(2 + 6x) dx = 2x + 3x² (+C=0) → [0, 2, 3]
        status, data = self._post('/api/polynomial',
                                  {'op': 'integral', 'coeffs': [2, 6]})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], [0, 2, 3])

    def test_polynomial_add(self):
        # (1 + 2x) + (3 + 4x + 5x²) = 4 + 6x + 5x²
        status, data = self._post('/api/polynomial',
                                  {'op': 'add', 'a': [1, 2], 'b': [3, 4, 5]})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], [4, 6, 5])

    def test_polynomial_multiply(self):
        # (1 + x)(1 + x) = 1 + 2x + x²
        status, data = self._post('/api/polynomial',
                                  {'op': 'multiply', 'a': [1, 1], 'b': [1, 1]})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], [1, 2, 1])

    def test_polynomial_poly_text(self):
        status, data = self._post('/api/polynomial',
                                  {'op': 'add', 'a': [1, 0, 3], 'b': [0]})
        self.assertEqual(status, 200)
        self.assertEqual(data['poly'], '3x² + 1')

    def test_polynomial_invalid_op(self):
        status, data = self._post('/api/polynomial',
                                  {'op': 'bogus', 'coeffs': [1, 2]})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_polynomial_evaluate_missing_x(self):
        status, data = self._post('/api/polynomial',
                                  {'op': 'evaluate', 'coeffs': [1, 2]})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_polynomial_empty_coeffs(self):
        status, data = self._post('/api/polynomial',
                                  {'op': 'derivative', 'coeffs': []})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_polynomial_non_numeric(self):
        status, data = self._post('/api/polynomial',
                                  {'op': 'derivative', 'coeffs': [1, 'x']})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_polynomial_recorded_in_history(self):
        self._post('/api/polynomial',
                   {'op': 'evaluate', 'coeffs': [0, 0, 1], 'x': 9})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == 81 for e in history))

    # ------------------------------------------------------------------
    # Geometry calculator — POST /api/geometry
    # ------------------------------------------------------------------
    def test_geometry_square(self):
        status, data = self._post('/api/geometry', {'shape': 'square', 'side': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['geometry']['area'], 16)
        self.assertEqual(data['geometry']['perimeter'], 16)
        self.assertEqual(data['result'], 16)

    def test_geometry_rectangle(self):
        status, data = self._post('/api/geometry',
                                  {'shape': 'rectangle', 'width': 3, 'height': 5})
        self.assertEqual(status, 200)
        self.assertEqual(data['geometry']['area'], 15)
        self.assertEqual(data['geometry']['perimeter'], 16)

    def test_geometry_circle(self):
        status, data = self._post('/api/geometry', {'shape': 'circle', 'radius': 2})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['geometry']['area'], 12.566370614, places=6)
        self.assertAlmostEqual(data['geometry']['circumference'], 12.566370614, places=6)

    def test_geometry_triangle(self):
        status, data = self._post('/api/geometry',
                                  {'shape': 'triangle', 'base': 6, 'height': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['geometry']['area'], 12)

    def test_geometry_trapezoid(self):
        status, data = self._post('/api/geometry',
                                  {'shape': 'trapezoid', 'a': 3, 'b': 5, 'height': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['geometry']['area'], 16)

    def test_geometry_cube(self):
        status, data = self._post('/api/geometry', {'shape': 'cube', 'side': 3})
        self.assertEqual(status, 200)
        self.assertEqual(data['geometry']['volume'], 27)
        self.assertEqual(data['geometry']['surface'], 54)

    def test_geometry_rectangular_prism(self):
        status, data = self._post('/api/geometry',
                                  {'shape': 'rectangular_prism',
                                   'length': 2, 'width': 3, 'height': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['geometry']['volume'], 24)
        self.assertEqual(data['geometry']['surface'], 52)

    def test_geometry_sphere(self):
        status, data = self._post('/api/geometry', {'shape': 'sphere', 'radius': 3})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['geometry']['volume'], 113.097335529, places=5)
        self.assertAlmostEqual(data['geometry']['surface'], 113.097335529, places=5)

    def test_geometry_cylinder(self):
        status, data = self._post('/api/geometry',
                                  {'shape': 'cylinder', 'radius': 2, 'height': 5})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['geometry']['volume'], 62.831853072, places=5)

    def test_geometry_cone(self):
        # r=3, h=4 → slant 5; volume = π·9·4/3 = 12π; surface = π·3·(3+5)=24π
        status, data = self._post('/api/geometry',
                                  {'shape': 'cone', 'radius': 3, 'height': 4})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['geometry']['volume'], 37.699111843, places=5)
        self.assertAlmostEqual(data['geometry']['surface'], 75.398223686, places=5)

    def test_geometry_invalid_shape(self):
        status, data = self._post('/api/geometry', {'shape': 'dodecahedron', 'side': 1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_geometry_non_positive(self):
        status, data = self._post('/api/geometry', {'shape': 'square', 'side': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_geometry_non_numeric(self):
        status, data = self._post('/api/geometry', {'shape': 'square', 'side': 'x'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_geometry_recorded_in_history(self):
        self._post('/api/geometry', {'shape': 'square', 'side': 5})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == 25 for e in history))

    # ------------------------------------------------------------------
    # Roman numerals — POST /api/roman
    # ------------------------------------------------------------------
    def test_roman_to_roman(self):
        status, data = self._post('/api/roman', {'op': 'to_roman', 'value': 2024})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 'MMXXIV')

    def test_roman_to_roman_subtractive(self):
        status, data = self._post('/api/roman', {'op': 'to_roman', 'value': 49})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 'XLIX')

    def test_roman_from_roman(self):
        status, data = self._post('/api/roman', {'op': 'from_roman', 'value': 'MMXXIV'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 2024)

    def test_roman_from_roman_lowercase(self):
        status, data = self._post('/api/roman', {'op': 'from_roman', 'value': 'xiv'})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], 14)

    def test_roman_to_roman_out_of_range(self):
        status, data = self._post('/api/roman', {'op': 'to_roman', 'value': 4000})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_roman_to_roman_zero(self):
        status, data = self._post('/api/roman', {'op': 'to_roman', 'value': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_roman_to_roman_non_integer(self):
        status, data = self._post('/api/roman', {'op': 'to_roman', 'value': 3.5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_roman_from_roman_invalid_char(self):
        status, data = self._post('/api/roman', {'op': 'from_roman', 'value': 'ABC'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_roman_from_roman_non_canonical(self):
        # IIII is not canonical (should be IV)
        status, data = self._post('/api/roman', {'op': 'from_roman', 'value': 'IIII'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_roman_from_roman_empty(self):
        status, data = self._post('/api/roman', {'op': 'from_roman', 'value': '  '})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_roman_invalid_op(self):
        status, data = self._post('/api/roman', {'op': 'bogus', 'value': 5})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_roman_recorded_in_history(self):
        self._post('/api/roman', {'op': 'to_roman', 'value': 9})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        history = json.loads(body)['history']
        self.assertTrue(any(e.get('result') == 'IX' for e in history))


class RequirementTraceabilityTest(unittest.TestCase):
    """One traced test per REQ id in specs/calculator/spec.md.

    Each test names its requirement (REQ-0NN) so the functional-coverage gate
    can trace every functional requirement to an exercising test, and asserts
    real observable behaviour over the HTTP surface.
    """

    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path, payload):
        conn = http.client.HTTPConnection('localhost', self.port)
        conn.request('POST', path, body=json.dumps(payload),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        conn.close()
        return resp.status, json.loads(data) if data else {}

    def _post_raw(self, path, raw):
        """POST a raw (possibly non-object) body to exercise input handling."""
        conn = http.client.HTTPConnection('localhost', self.port)
        conn.request('POST', path, body=raw,
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        conn.close()
        return resp.status, data

    def _get(self, path):
        conn = http.client.HTTPConnection('localhost', self.port)
        conn.request('GET', path)
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        conn.close()
        return resp.status, data

    def test_req_001_basic_arithmetic(self):
        """REQ-001: add/subtract/multiply/divide; divide-by-zero fails safe."""
        self.assertEqual(self._post('/api/calculate', {'op': 'add', 'a': 2, 'b': 3})[1]['result'], 5)
        self.assertEqual(self._post('/api/calculate', {'op': 'subtract', 'a': 9, 'b': 4})[1]['result'], 5)
        self.assertEqual(self._post('/api/calculate', {'op': 'multiply', 'a': 6, 'b': 7})[1]['result'], 42)
        self.assertEqual(self._post('/api/calculate', {'op': 'divide', 'a': 10, 'b': 4})[1]['result'], 2.5)
        self.assertEqual(self._post('/api/calculate', {'op': 'divide', 'a': 1, 'b': 0})[0], 400)

    def test_req_002_extended_binary(self):
        """REQ-002: power, modulo, integer division."""
        self.assertEqual(self._post('/api/calculate', {'op': 'power', 'a': 2, 'b': 10})[1]['result'], 1024)
        self.assertEqual(self._post('/api/calculate', {'op': 'modulo', 'a': 17, 'b': 5})[1]['result'], 2)
        self.assertEqual(self._post('/api/calculate', {'op': 'intdiv', 'a': 17, 'b': 5})[1]['result'], 3)

    def test_req_003_gcd_lcm(self):
        """REQ-003: gcd and lcm of two integers."""
        self.assertEqual(self._post('/api/calculate', {'op': 'gcd', 'a': 12, 'b': 18})[1]['result'], 6)
        self.assertEqual(self._post('/api/calculate', {'op': 'lcm', 'a': 4, 'b': 6})[1]['result'], 12)

    def test_req_004_bitwise(self):
        """REQ-004: bitwise and/or/xor/shift."""
        self.assertEqual(self._post('/api/calculate', {'op': 'and', 'a': 12, 'b': 10})[1]['result'], 8)
        self.assertEqual(self._post('/api/calculate', {'op': 'or', 'a': 12, 'b': 10})[1]['result'], 14)
        self.assertEqual(self._post('/api/calculate', {'op': 'xor', 'a': 12, 'b': 10})[1]['result'], 6)
        self.assertEqual(self._post('/api/calculate', {'op': 'lshift', 'a': 1, 'b': 4})[1]['result'], 16)

    def test_req_005_combinatorics(self):
        """REQ-005: nCr and nPr."""
        self.assertEqual(self._post('/api/calculate', {'op': 'ncr', 'a': 5, 'b': 2})[1]['result'], 10)
        self.assertEqual(self._post('/api/calculate', {'op': 'npr', 'a': 5, 'b': 2})[1]['result'], 20)

    def test_req_006_scientific_unary(self):
        """REQ-006: scientific unary functions, domain errors fail safe."""
        self.assertEqual(self._post('/api/unary', {'op': 'sqrt', 'a': 9})[1]['result'], 3)
        self.assertEqual(self._post('/api/unary', {'op': 'factorial', 'a': 5})[1]['result'], 120)
        self.assertEqual(self._post('/api/unary', {'op': 'sqrt', 'a': -1})[0], 400)

    def test_req_007_expression_precedence(self):
        """REQ-007: safe evaluator; '^' binds tighter than unary minus."""
        self.assertEqual(self._post('/api/evaluate', {'expression': '(2+3)*4'})[1]['result'], 20)
        self.assertEqual(self._post('/api/evaluate', {'expression': '-2^2'})[1]['result'], -4)
        self.assertEqual(self._post('/api/evaluate', {'expression': '2^3^2'})[1]['result'], 512)

    def test_req_008_memory_register(self):
        """REQ-008: memory store/add/recall/clear."""
        self._post('/api/memory', {'action': 'store', 'value': 10})
        self._post('/api/memory', {'action': 'add', 'value': 5})
        self.assertEqual(self._post('/api/memory', {'action': 'recall'})[1]['memory'], 15)
        self.assertEqual(self._post('/api/memory', {'action': 'clear'})[1]['memory'], 0)

    def test_req_009_base_conversion(self):
        """REQ-009: convert integers across bin/oct/dec/hex."""
        self.assertEqual(self._post('/api/convert', {'value': '255', 'from_base': 'dec', 'to_base': 'hex'})[1]['result'], 'ff')
        self.assertEqual(self._post('/api/convert', {'value': 'ff', 'from_base': 'hex', 'to_base': 'dec'})[1]['result'], '255')

    def test_req_010_statistics(self):
        """REQ-010: descriptive statistics over a list."""
        status, data = self._post('/api/stats', {'values': [2, 4, 4, 5]})
        self.assertEqual(status, 200)
        self.assertEqual(data['stats']['count'], 4)
        self.assertEqual(data['stats']['mean'], 3.75)

    def test_req_011_percentage(self):
        """REQ-011: percent of / change / increase / decrease."""
        self.assertEqual(self._post('/api/percent', {'op': 'of', 'a': 200, 'b': 10})[1]['result'], 20)
        self.assertEqual(self._post('/api/percent', {'op': 'increase', 'a': 100, 'b': 25})[1]['result'], 125)

    def test_req_012_number_theory(self):
        """REQ-012: primality, factorisation, divisors, fibonacci."""
        self.assertTrue(self._post('/api/numtheory', {'op': 'is_prime', 'n': 13})[1]['result'])
        self.assertEqual(self._post('/api/numtheory', {'op': 'prime_factors', 'n': 360})[1]['result'], [2, 2, 2, 3, 3, 5])
        self.assertEqual(self._post('/api/numtheory', {'op': 'fibonacci', 'n': 10})[1]['result'], 55)

    def test_req_013_fractions(self):
        """REQ-013: exact fraction arithmetic reduced to lowest terms."""
        status, data = self._post('/api/fraction', {'op': 'add', 'n1': 1, 'd1': 2, 'n2': 1, 'd2': 3})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '5/6')

    def test_req_014_equation_solver(self):
        """REQ-014: linear / quadratic / system solving."""
        status, data = self._post('/api/solve', {'kind': 'quadratic', 'a': 1, 'b': -3, 'c': 2})
        self.assertEqual(status, 200)
        self.assertEqual(sorted(data['roots']), [1, 2])

    def test_req_015_finance(self):
        """REQ-015: interest / loan / time-value of money."""
        status, data = self._post('/api/finance', {'op': 'simple_interest', 'principal': 1000, 'rate': 5, 'years': 2})
        self.assertEqual(status, 200)
        self.assertEqual(data['finance']['interest'], 100)

    def test_req_016_unit_conversion(self):
        """REQ-016: unit conversion across categories."""
        self.assertEqual(self._post('/api/units', {'category': 'length', 'value': 1, 'from_unit': 'km', 'to_unit': 'm'})[1]['result'], 1000)
        self.assertEqual(self._post('/api/units', {'category': 'temperature', 'value': 100, 'from_unit': 'c', 'to_unit': 'f'})[1]['result'], 212)

    def test_req_017_date_calc(self):
        """REQ-017: date difference / shift / weekday."""
        self.assertEqual(self._post('/api/date', {'op': 'diff', 'date1': '2020-01-01', 'date2': '2020-01-31'})[1]['days'], 30)
        self.assertEqual(self._post('/api/date', {'op': 'weekday', 'date': '2020-01-01'})[1]['iso_weekday'], 3)

    def test_req_018_vectors(self):
        """REQ-018: vector operations."""
        self.assertEqual(self._post('/api/vector', {'op': 'dot', 'a': [1, 2, 3], 'b': [4, 5, 6]})[1]['result'], 32)
        self.assertEqual(self._post('/api/vector', {'op': 'add', 'a': [1, 2], 'b': [3, 4]})[1]['result'], [4, 6])

    def test_req_019_matrices(self):
        """REQ-019: matrix operations."""
        self.assertEqual(self._post('/api/matrix', {'op': 'determinant', 'a': [[1, 2], [3, 4]]})[1]['result'], -2)
        self.assertEqual(self._post('/api/matrix', {'op': 'transpose', 'a': [[1, 2], [3, 4]]})[1]['result'], [[1, 3], [2, 4]])

    def test_req_020_complex(self):
        """REQ-020: complex-number operations."""
        status, data = self._post('/api/complex', {'op': 'add', 're1': 1, 'im1': 2, 're2': 3, 'im2': 4})
        self.assertEqual(status, 200)
        self.assertEqual(data['result'], '4+6i')

    def test_req_021_history(self):
        """REQ-021: calculations persist to history."""
        self._post('/api/calculate', {'op': 'add', 'a': 1, 'b': 1})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        self.assertTrue(len(json.loads(body)['history']) >= 1)

    def test_req_022_non_object_body_rejected(self):
        """REQ-022: a non-object JSON body is a clean 400, never a 5xx/crash."""
        for raw in ('[1,2,3]', '42', '"x"', 'null'):
            status, body = self._post_raw('/api/calculate', raw)
            self.assertEqual(status, 400, raw)
            self.assertIn('error', body)
        self.assertEqual(self._post('/api/calculate', {'op': 'bogus', 'a': 1, 'b': 2})[0], 400)

    def test_req_023_non_finite_rejected(self):
        """REQ-023: non-finite results/inputs yield 400 + valid JSON, never NaN/Infinity tokens."""
        status, body = self._post_raw('/api/calculate', json.dumps({'op': 'multiply', 'a': 1e308, 'b': 10}))
        self.assertEqual(status, 400)
        self.assertNotIn('Infinity', body)
        json.loads(body)  # body is strictly-valid JSON
        self.assertEqual(self._post('/api/calculate', {'op': 'add', 'a': 'nan', 'b': 0})[0], 400)
        self.assertEqual(self._post('/api/calculate', {'op': 'add', 'a': 'inf', 'b': 1})[0], 400)
        status, body = self._post_raw('/api/evaluate', json.dumps({'expression': '1e308*10'}))
        self.assertEqual(status, 400)
        self.assertNotIn('Infinity', body)

    def test_req_024_dos_bounds(self):
        """REQ-024: compute-heavy operands are bounded to prevent CPU/memory DoS."""
        self.assertEqual(self._post('/api/unary', {'op': 'factorial', 'a': 100000000})[0], 400)
        self.assertEqual(self._post('/api/numtheory', {'op': 'fibonacci', 'n': 100000000})[0], 400)
        self.assertEqual(self._post('/api/numtheory', {'op': 'next_prime', 'n': 10**18})[0], 400)
        self.assertEqual(self._post('/api/unary', {'op': 'factorial', 'a': 6})[1]['result'], 720)

    def test_req_025_polynomial(self):
        """REQ-025: polynomial evaluate / derivative / integral / add / multiply."""
        self.assertEqual(self._post('/api/polynomial', {'op': 'evaluate', 'coeffs': [1, 2, 3], 'x': 2})[1]['result'], 17)
        self.assertEqual(self._post('/api/polynomial', {'op': 'derivative', 'coeffs': [1, 2, 3]})[1]['result'], [2, 6])
        self.assertEqual(self._post('/api/polynomial', {'op': 'multiply', 'a': [1, 1], 'b': [1, 1]})[1]['result'], [1, 2, 1])

    def test_req_026_geometry(self):
        """REQ-026: 2-D area/perimeter and 3-D volume/surface metrics."""
        self.assertEqual(self._post('/api/geometry', {'shape': 'rectangle', 'width': 3, 'height': 5})[1]['geometry']['area'], 15)
        self.assertEqual(self._post('/api/geometry', {'shape': 'cube', 'side': 3})[1]['geometry']['volume'], 27)
        self.assertEqual(self._post('/api/geometry', {'shape': 'square', 'side': -1})[0], 400)

    def test_req_027_roman_numerals(self):
        """REQ-027: integer↔Roman-numeral conversion, canonical 1..3999."""
        self.assertEqual(self._post('/api/roman', {'op': 'to_roman', 'value': 2024})[1]['result'], 'MMXXIV')
        self.assertEqual(self._post('/api/roman', {'op': 'from_roman', 'value': 'XLIX'})[1]['result'], 49)
        self.assertEqual(self._post('/api/roman', {'op': 'from_roman', 'value': 'IIII'})[0], 400)

    def test_regression_fit_perfect_line(self):
        status, data = self._post('/api/regression',
                                  {'op': 'fit', 'points': [[1, 3], [2, 5], [3, 7]]})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['regression']['slope'], 2)
        self.assertAlmostEqual(data['regression']['intercept'], 1)
        self.assertAlmostEqual(data['regression']['r2'], 1)
        self.assertEqual(data['result'], 2)

    def test_regression_predict(self):
        status, data = self._post('/api/regression',
                                  {'op': 'predict', 'points': [[1, 3], [2, 5], [3, 7]],
                                   'predict_x': 10})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['regression']['predict_y'], 21)
        self.assertEqual(data['result'], 21)

    def test_regression_negative_slope(self):
        status, data = self._post('/api/regression',
                                  {'op': 'fit', 'points': [[0, 10], [1, 8], [2, 6]]})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data['regression']['slope'], -2)
        self.assertAlmostEqual(data['regression']['r'], -1)

    def test_regression_requires_two_points(self):
        status, data = self._post('/api/regression',
                                  {'op': 'fit', 'points': [[1, 2]]})
        self.assertEqual(status, 400)
        self.assertIn('two', data['error'])

    def test_regression_vertical_rejected(self):
        status, data = self._post('/api/regression',
                                  {'op': 'fit', 'points': [[2, 1], [2, 5], [2, 9]]})
        self.assertEqual(status, 400)
        self.assertIn('identical', data['error'])

    def test_regression_bad_point_shape(self):
        status, _ = self._post('/api/regression',
                               {'op': 'fit', 'points': [[1, 2], [3]]})
        self.assertEqual(status, 400)

    def test_regression_predict_requires_x(self):
        status, _ = self._post('/api/regression',
                               {'op': 'predict', 'points': [[1, 2], [2, 4]]})
        self.assertEqual(status, 400)

    def test_regression_unknown_op(self):
        status, _ = self._post('/api/regression',
                               {'op': 'bogus', 'points': [[1, 2], [2, 4]]})
        self.assertEqual(status, 400)

    def test_regression_recorded_in_history(self):
        self._post('/api/regression', {'op': 'fit', 'points': [[1, 1], [2, 2]]})
        status, body = self._get('/api/history')
        self.assertEqual(status, 200)
        self.assertTrue(any('y =' in h.get('expression', '')
                            for h in json.loads(body)['history']))

    def test_req_028_linear_regression(self):
        """REQ-028: least-squares fit and prediction over [x, y] points."""
        fit = self._post('/api/regression',
                         {'op': 'fit', 'points': [[1, 2], [2, 4], [3, 6]]})[1]
        self.assertAlmostEqual(fit['regression']['slope'], 2)
        pred = self._post('/api/regression',
                          {'op': 'predict', 'points': [[1, 2], [2, 4], [3, 6]],
                           'predict_x': 5})[1]
        self.assertAlmostEqual(pred['regression']['predict_y'], 10)
        self.assertEqual(self._post('/api/regression',
                                    {'op': 'fit', 'points': [[1, 2]]})[0], 400)

    def test_favicon_no_404(self):
        """UI: /favicon.ico is served (204) so the page logs no 404."""
        status, _ = self._get('/favicon.ico')
        self.assertEqual(status, 204)

    def test_health_route(self):
        """ADF gate: /health returns 200 JSON {status: ok}."""
        status, body = self._get('/health')
        self.assertEqual(status, 200)
        self.assertIn('"ok"', body)

    def test_api_health_route(self):
        """ADF gate: /api/health returns 200 JSON {status: ok}."""
        status, body = self._get('/api/health')
        self.assertEqual(status, 200)
        self.assertIn('"ok"', body)


if __name__ == '__main__':
    unittest.main()
