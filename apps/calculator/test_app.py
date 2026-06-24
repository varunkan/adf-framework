import json
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


if __name__ == '__main__':
    unittest.main()
