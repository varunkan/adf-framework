"""Calculator domain logic — pure functions, Python standard library only.

This module is the single source of truth for arithmetic. The HTTP layer in
``server.py`` delegates here. Everything is implemented for real:

- Binary operations: add, subtract, multiply, divide, power, modulo, intdiv
- Unary / scientific operations: sqrt, square, cube, negate, reciprocal, abs,
  factorial, sin, cos, tan, asin, acos, atan, ln, log10, log2, exp, percent
- A safe recursive-descent expression evaluator (no ``eval``) supporting
  ``+ - * / % ^``, parentheses, unary minus/plus, decimals and the
  constants ``pi`` and ``e``.
"""

import datetime
import math
import statistics
from fractions import Fraction

# ---------------------------------------------------------------------------
# Binary operations
# ---------------------------------------------------------------------------

# Display symbol for each binary op (used to build a human-readable expression).
BINARY_SYMBOL = {
    'add': '+',
    'subtract': '-',
    'multiply': '×',
    'divide': '÷',
    'power': '^',
    'modulo': 'mod',
    'intdiv': '//',
    'gcd': 'gcd',
    'lcm': 'lcm',
    'and': '&',
    'or': '|',
    'xor': 'xor',
    'lshift': '<<',
    'rshift': '>>',
    'ncr': 'nCr',
    'npr': 'nPr',
}

VALID_OPS = tuple(BINARY_SYMBOL.keys())

# Binary ops that operate purely on integers (bitwise + combinatorics). They
# reject non-integer operands rather than silently truncating.
INTEGER_BINARY_OPS = ('gcd', 'lcm', 'and', 'or', 'xor', 'lshift', 'rshift',
                      'ncr', 'npr')


# Upper bounds on compute-heavy operands so a single small request cannot
# exhaust CPU/memory (DoS). The limits are far above any realistic calculator
# use yet keep each operation well under a second.
MAX_FACTORIAL = 10000        # math.factorial(10000) is fast (~35k digits)
MAX_FIBONACCI = 200000       # 200k-iteration big-int loop, sub-second
MAX_NEXT_PRIME = 10 ** 12    # trial division stays bounded (sqrt ≈ 10^6)
MAX_N_NUMTHEORY = 10 ** 12   # is_prime/divisors/totient trial-div ≤ sqrt ≈ 10^6
MAX_LSHIFT_B = 10000         # 1 << 10000 ≈ 10^3010 digits — safe to serialize


def _as_int(value, name):
    """Return ``value`` as an ``int`` or raise if it is not integer-valued."""
    if value != int(value):
        raise ValueError('{} requires integers'.format(name))
    return int(value)


def compute(op, a, b):
    """Apply binary ``op`` to ``a`` and ``b``.

    Raises ``ValueError`` for an unknown op and ``ZeroDivisionError`` when the
    divisor is zero for divide/modulo/intdiv.
    """
    if op == 'add':
        return a + b
    if op == 'subtract':
        return a - b
    if op == 'multiply':
        return a * b
    if op == 'divide':
        if b == 0:
            raise ZeroDivisionError('division by zero')
        return a / b
    if op == 'power':
        result = a ** b
        # a ** b can produce a complex number (e.g. (-1) ** 0.5); reject it.
        if isinstance(result, complex):
            raise ValueError('result is not a real number')
        return result
    if op == 'modulo':
        if b == 0:
            raise ZeroDivisionError('modulo by zero')
        return a % b
    if op == 'intdiv':
        if b == 0:
            raise ZeroDivisionError('division by zero')
        return a // b
    if op == 'gcd':
        return math.gcd(_as_int(a, 'gcd'), _as_int(b, 'gcd'))
    if op == 'lcm':
        return math.lcm(_as_int(a, 'lcm'), _as_int(b, 'lcm'))
    if op == 'and':
        return _as_int(a, 'and') & _as_int(b, 'and')
    if op == 'or':
        return _as_int(a, 'or') | _as_int(b, 'or')
    if op == 'xor':
        return _as_int(a, 'xor') ^ _as_int(b, 'xor')
    if op == 'lshift':
        shift = _as_int(b, 'lshift')
        if shift < 0:
            raise ValueError('shift amount must be non-negative')
        if shift > MAX_LSHIFT_B:
            raise ValueError(
                'lshift amount too large (max {})'.format(MAX_LSHIFT_B))
        return _as_int(a, 'lshift') << shift
    if op == 'rshift':
        shift = _as_int(b, 'rshift')
        if shift < 0:
            raise ValueError('shift amount must be non-negative')
        return _as_int(a, 'rshift') >> shift
    if op == 'ncr':
        n, k = _as_int(a, 'ncr'), _as_int(b, 'ncr')
        if n < 0 or k < 0:
            raise ValueError('nCr requires non-negative integers')
        return math.comb(n, k)
    if op == 'npr':
        n, k = _as_int(a, 'npr'), _as_int(b, 'npr')
        if n < 0 or k < 0:
            raise ValueError('nPr requires non-negative integers')
        return math.perm(n, k)
    raise ValueError('unknown operation')


# ---------------------------------------------------------------------------
# Unary / scientific operations
# ---------------------------------------------------------------------------

# How each unary op renders into an expression string given the operand text.
UNARY_TEMPLATE = {
    'sqrt': '√({a})',
    'square': '({a})²',
    'cube': '({a})³',
    'negate': '-({a})',
    'reciprocal': '1/({a})',
    'abs': '|{a}|',
    'factorial': '({a})!',
    'sin': 'sin({a})',
    'cos': 'cos({a})',
    'tan': 'tan({a})',
    'asin': 'asin({a})',
    'acos': 'acos({a})',
    'atan': 'atan({a})',
    'ln': 'ln({a})',
    'log10': 'log({a})',
    'log2': 'log₂({a})',
    'exp': 'exp({a})',
    'percent': '({a})%',
    'cbrt': '∛({a})',
    'sinh': 'sinh({a})',
    'cosh': 'cosh({a})',
    'tanh': 'tanh({a})',
    'floor': '⌊{a}⌋',
    'ceil': '⌈{a}⌉',
    'round': 'round({a})',
    'sign': 'sign({a})',
    'deg': 'deg({a})',
    'rad': 'rad({a})',
    'bitnot': '~({a})',
}

VALID_UNARY_OPS = tuple(UNARY_TEMPLATE.keys())


def compute_unary(op, a):
    """Apply unary ``op`` to ``a``.

    Raises ``ValueError`` for an unknown op or out-of-domain input and
    ``ZeroDivisionError`` for reciprocal of zero.
    """
    if op == 'sqrt':
        if a < 0:
            raise ValueError('cannot take square root of a negative number')
        return math.sqrt(a)
    if op == 'square':
        return a * a
    if op == 'cube':
        return a ** 3
    if op == 'negate':
        return -a
    if op == 'reciprocal':
        if a == 0:
            raise ZeroDivisionError('division by zero')
        return 1 / a
    if op == 'abs':
        return abs(a)
    if op == 'factorial':
        if a < 0 or a != int(a):
            raise ValueError('factorial requires a non-negative integer')
        if a > MAX_FACTORIAL:
            raise ValueError(
                'factorial input too large (max {})'.format(MAX_FACTORIAL))
        return math.factorial(int(a))
    if op == 'sin':
        return math.sin(a)
    if op == 'cos':
        return math.cos(a)
    if op == 'tan':
        return math.tan(a)
    if op == 'asin':
        if a < -1 or a > 1:
            raise ValueError('asin domain is [-1, 1]')
        return math.asin(a)
    if op == 'acos':
        if a < -1 or a > 1:
            raise ValueError('acos domain is [-1, 1]')
        return math.acos(a)
    if op == 'atan':
        return math.atan(a)
    if op == 'ln':
        if a <= 0:
            raise ValueError('logarithm requires a positive number')
        return math.log(a)
    if op == 'log10':
        if a <= 0:
            raise ValueError('logarithm requires a positive number')
        return math.log10(a)
    if op == 'log2':
        if a <= 0:
            raise ValueError('logarithm requires a positive number')
        return math.log2(a)
    if op == 'exp':
        return math.exp(a)
    if op == 'percent':
        return a / 100
    if op == 'cbrt':
        # Real cube root, well-defined for negatives (math.pow would fail).
        return math.copysign(abs(a) ** (1.0 / 3.0), a)
    if op == 'sinh':
        return math.sinh(a)
    if op == 'cosh':
        return math.cosh(a)
    if op == 'tanh':
        return math.tanh(a)
    if op == 'floor':
        return math.floor(a)
    if op == 'ceil':
        return math.ceil(a)
    if op == 'round':
        # Round half-to-even to the nearest integer (calculator convention).
        return round(a)
    if op == 'sign':
        return (a > 0) - (a < 0)
    if op == 'deg':
        return math.degrees(a)
    if op == 'rad':
        return math.radians(a)
    if op == 'bitnot':
        return ~_as_int(a, 'bitnot')
    raise ValueError('unknown operation')


# ---------------------------------------------------------------------------
# Percentage toolkit
# ---------------------------------------------------------------------------

# Each percentage op maps a (value, percent) pair to a result and renders a
# human-readable expression. ``of`` and ``change`` read both operands as plain
# numbers; the others treat ``b`` as a percentage applied to ``a``.
PERCENT_SYMBOL = {
    'of': '{b}% of {a}',
    'change': '% change {a} → {b}',
    'increase': '{a} + {b}%',
    'decrease': '{a} − {b}%',
}

VALID_PERCENT_OPS = tuple(PERCENT_SYMBOL.keys())


def compute_percent(op, a, b):
    """Apply a percentage operation to ``a`` and ``b``.

    - ``of``: ``b`` percent of ``a`` (``a * b / 100``)
    - ``change``: percentage change from ``a`` to ``b`` (requires ``a != 0``)
    - ``increase``: ``a`` increased by ``b`` percent
    - ``decrease``: ``a`` decreased by ``b`` percent

    Raises ``ValueError`` for an unknown op and ``ZeroDivisionError`` for a
    percentage change from zero.
    """
    if op == 'of':
        return a * b / 100
    if op == 'change':
        if a == 0:
            raise ZeroDivisionError('cannot compute percentage change from zero')
        return (b - a) / a * 100
    if op == 'increase':
        return a * (1 + b / 100)
    if op == 'decrease':
        return a * (1 - b / 100)
    raise ValueError('unknown percentage operation')


# ---------------------------------------------------------------------------
# Memory register (classic M+ / M- / MR / MC / MS)
# ---------------------------------------------------------------------------

# Memory mutations and what each does given the current memory value and an
# operand. ``recall`` and ``clear`` ignore the operand.
MEMORY_ACTIONS = ('store', 'recall', 'clear', 'add', 'subtract')


def apply_memory(action, current, value=0):
    """Apply a memory ``action`` to the ``current`` register value.

    Returns the new register value. Raises ``ValueError`` for an unknown
    action. ``recall`` and ``clear`` ignore ``value``.
    """
    if action == 'store':
        return value
    if action == 'recall':
        return current
    if action == 'clear':
        return 0
    if action == 'add':
        return current + value
    if action == 'subtract':
        return current - value
    raise ValueError('unknown memory action')


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_number(n):
    """Render a number the way a calculator would: drop a trailing ``.0`` and
    trim binary-float noise, but keep genuine decimals."""
    if isinstance(n, bool):  # guard: bool is a subclass of int
        n = int(n)
    if isinstance(n, int):
        return str(n)
    if n != n or n in (float('inf'), float('-inf')):  # NaN / inf
        return str(n)
    if n == int(n) and abs(n) < 1e15:
        return str(int(n))
    # Round away floating-point noise (e.g. 0.30000000000000004) while keeping
    # precision for legitimate values.
    rounded = round(n, 12)
    text = repr(rounded)
    return text


def normalize_result(n):
    """Collapse an integer-valued float to an int for clean JSON output."""
    if isinstance(n, float):
        if n != n or n in (float('inf'), float('-inf')):
            return n
        if n == int(n) and abs(n) < 1e15:
            return int(n)
        return round(n, 12)
    return n


# ---------------------------------------------------------------------------
# Safe expression evaluator (recursive-descent; no eval)
# ---------------------------------------------------------------------------

CONSTANTS = {
    'pi': math.pi,
    'e': math.e,
    'tau': math.tau,
    'phi': (1 + math.sqrt(5)) / 2,  # golden ratio
}


class ExpressionError(ValueError):
    """Raised when an expression string is malformed."""


def _tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in '+-*/%^()':
            tokens.append(('op', ch))
            i += 1
            continue
        if ch.isdigit() or ch == '.':
            j = i
            seen_dot = False
            seen_exp = False
            while j < n:
                c = text[j]
                if c.isdigit():
                    j += 1
                elif c == '.' and not seen_dot and not seen_exp:
                    seen_dot = True
                    j += 1
                elif c in 'eE' and not seen_exp and j > i:
                    seen_exp = True
                    j += 1
                    if j < n and text[j] in '+-':
                        j += 1
                else:
                    break
            chunk = text[i:j]
            try:
                tokens.append(('num', float(chunk)))
            except ValueError:
                raise ExpressionError('invalid number: {}'.format(chunk))
            i = j
            continue
        if ch.isalpha():
            j = i
            while j < n and text[j].isalpha():
                j += 1
            name = text[i:j].lower()
            if name not in CONSTANTS:
                raise ExpressionError('unknown name: {}'.format(name))
            tokens.append(('num', CONSTANTS[name]))
            i = j
            continue
        raise ExpressionError('unexpected character: {!r}'.format(ch))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def _advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self):
        if not self.tokens:
            raise ExpressionError('empty expression')
        value = self._expr()
        if self.pos != len(self.tokens):
            raise ExpressionError('unexpected trailing input')
        return value

    def _expr(self):
        value = self._term()
        while True:
            kind, val = self._peek()
            if kind == 'op' and val in '+-':
                self._advance()
                rhs = self._term()
                value = value + rhs if val == '+' else value - rhs
            else:
                return value

    def _term(self):
        value = self._unary()
        while True:
            kind, val = self._peek()
            if kind == 'op' and val in '*/%':
                self._advance()
                rhs = self._unary()
                if val == '*':
                    value = value * rhs
                elif val == '/':
                    if rhs == 0:
                        raise ZeroDivisionError('division by zero')
                    value = value / rhs
                else:
                    if rhs == 0:
                        raise ZeroDivisionError('modulo by zero')
                    value = value % rhs
            else:
                return value

    def _unary(self):
        # Unary +/- binds LOOSER than '^', matching standard math convention
        # and Python (-2**2 == -4): a leading minus negates the whole power.
        kind, val = self._peek()
        if kind == 'op' and val in '+-':
            self._advance()
            operand = self._unary()
            return operand if val == '+' else -operand
        return self._power()

    def _power(self):
        # Power binds tighter than unary +/- and is right-associative, so
        # -2^2 == -(2^2) == -4 and 2^3^2 == 2^(3^2) == 512. The exponent is a
        # _unary so '2^-3' (negative exponent) still parses.
        base = self._primary()
        kind, val = self._peek()
        if kind == 'op' and val == '^':
            self._advance()
            exponent = self._unary()
            result = base ** exponent
            if isinstance(result, complex):
                raise ExpressionError('result is not a real number')
            return result
        return base

    def _primary(self):
        kind, val = self._peek()
        if kind == 'num':
            self._advance()
            return val
        if kind == 'op' and val == '(':
            self._advance()
            value = self._expr()
            kind2, val2 = self._peek()
            if not (kind2 == 'op' and val2 == ')'):
                raise ExpressionError('missing closing parenthesis')
            self._advance()
            return value
        raise ExpressionError('unexpected token')


def evaluate(expression):
    """Safely evaluate an arithmetic ``expression`` string and return a number.

    Raises ``ExpressionError`` (a ``ValueError``) on malformed input and
    ``ZeroDivisionError`` on division/modulo by zero.
    """
    if not isinstance(expression, str):
        raise ExpressionError('expression must be a string')
    return _Parser(_tokenize(expression)).parse()


# ---------------------------------------------------------------------------
# Number-base conversion (programmer mode)
# ---------------------------------------------------------------------------

# Supported radixes by name.
BASE_RADIX = {
    'bin': 2,
    'oct': 8,
    'dec': 10,
    'hex': 16,
}

VALID_BASES = tuple(BASE_RADIX.keys())

# Python format specifier that renders an integer in each base (lower-case,
# no prefix). ``dec`` is handled separately via ``str``.
_BASE_FORMAT = {'bin': 'b', 'oct': 'o', 'hex': 'x'}


def format_in_base(n, to_base):
    """Render integer ``n`` as a string in ``to_base`` (no 0x/0b prefix).

    Negatives are rendered with a leading ``-`` sign. Raises ``ValueError``
    for an unknown base.
    """
    if to_base not in BASE_RADIX:
        raise ValueError('base must be one of ' + ', '.join(VALID_BASES))
    if to_base == 'dec':
        return str(n)
    return format(n, _BASE_FORMAT[to_base])


def convert_base(value, from_base, to_base):
    """Parse ``value`` (a string/int) as a number in ``from_base`` and return
    its representation in ``to_base``.

    Raises ``ValueError`` for an unknown base or a value that is not a valid
    integer in ``from_base``.
    """
    if from_base not in BASE_RADIX:
        raise ValueError('from_base must be one of ' + ', '.join(VALID_BASES))
    if to_base not in BASE_RADIX:
        raise ValueError('to_base must be one of ' + ', '.join(VALID_BASES))
    text = str(value).strip()
    if text == '':
        raise ValueError('value must not be empty')
    try:
        n = int(text, BASE_RADIX[from_base])
    except (ValueError, TypeError):
        raise ValueError('{!r} is not a valid {} number'.format(text, from_base))
    return format_in_base(n, to_base)


# ---------------------------------------------------------------------------
# Descriptive statistics over a list of numbers
# ---------------------------------------------------------------------------

def compute_stats(values):
    """Compute descriptive statistics over a non-empty list of numbers.

    Returns a dict with count, sum, mean, median, mode, min, max, range,
    population/sample stdev and variance. ``stdev``/``variance`` are ``0`` for a
    single-element list (undefined sample dispersion). ``mode`` is ``None`` when
    there is no unique most-common value.

    Raises ``ValueError`` if ``values`` is not a non-empty list of numbers.
    """
    if not isinstance(values, list) or len(values) == 0:
        raise ValueError('values must be a non-empty list of numbers')
    nums = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError('all values must be numbers')
        nums.append(v)

    result = {
        'count': len(nums),
        'sum': sum(nums),
        'mean': statistics.mean(nums),
        'median': statistics.median(nums),
        'min': min(nums),
        'max': max(nums),
        'range': max(nums) - min(nums),
    }
    if len(nums) >= 2:
        result['stdev'] = statistics.stdev(nums)
        result['variance'] = statistics.variance(nums)
    else:
        result['stdev'] = 0
        result['variance'] = 0
    try:
        result['mode'] = statistics.mode(nums)
    except statistics.StatisticsError:
        result['mode'] = None
    return result


# ---------------------------------------------------------------------------
# Number theory (single non-negative integer operand)
# ---------------------------------------------------------------------------

# Each op maps a single integer ``n`` to a result. Booleans (is_prime,
# is_perfect), integers (next_prime, divisor_count, divisor_sum, totient,
# fibonacci) and lists (prime_factors, divisors) are all real return shapes.
NUMBER_THEORY_OPS = (
    'is_prime', 'next_prime', 'prime_factors', 'divisors', 'divisor_count',
    'divisor_sum', 'is_perfect', 'totient', 'fibonacci',
)

# Human-readable expression label for each op given the operand text.
NUMBER_THEORY_LABEL = {
    'is_prime': 'isPrime({n})',
    'next_prime': 'nextPrime({n})',
    'prime_factors': 'factor({n})',
    'divisors': 'divisors({n})',
    'divisor_count': 'd({n})',
    'divisor_sum': 'σ({n})',
    'is_perfect': 'isPerfect({n})',
    'totient': 'φ({n})',
    'fibonacci': 'fib({n})',
}


def _is_prime(n):
    """Deterministic trial-division primality test for an ``int``."""
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def _prime_factors(n):
    """Return the prime factorization of ``n`` (>= 2) as a sorted list with
    multiplicity, e.g. ``60 -> [2, 2, 3, 5]``."""
    factors = []
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors.append(d)
            n //= d
        d += 1 if d == 2 else 2
    if n > 1:
        factors.append(n)
    return factors


def _divisors(n):
    """Return all positive divisors of ``n`` (>= 1) in ascending order."""
    small = []
    large = []
    i = 1
    while i * i <= n:
        if n % i == 0:
            small.append(i)
            if i != n // i:
                large.append(n // i)
        i += 1
    return small + large[::-1]


def _totient(n):
    """Euler's totient φ(n): count of integers in [1, n] coprime to ``n``."""
    result = n
    m = n
    p = 2
    while p * p <= m:
        if m % p == 0:
            while m % p == 0:
                m //= p
            result -= result // p
        p += 1
    if m > 1:
        result -= result // m
    return result


def _fibonacci(n):
    """Return the ``n``-th Fibonacci number (0-indexed: fib(0)=0, fib(1)=1)."""
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def number_theory(op, n):
    """Apply a number-theory ``op`` to integer ``n``.

    Raises ``ValueError`` for a non-integer operand, an out-of-domain value, or
    an unknown op.
    """
    n = _as_int(n, op)
    _BOUNDED_OPS = ('is_prime', 'prime_factors', 'divisors', 'divisor_count',
                    'divisor_sum', 'is_perfect', 'totient')
    if op in _BOUNDED_OPS and abs(n) > MAX_N_NUMTHEORY:
        raise ValueError(
            '{} input too large (max {})'.format(op, MAX_N_NUMTHEORY))
    if op == 'is_prime':
        return _is_prime(n)
    if op == 'next_prime':
        if n < 0:
            raise ValueError('next_prime requires a non-negative integer')
        if n > MAX_NEXT_PRIME:
            raise ValueError(
                'next_prime input too large (max {})'.format(MAX_NEXT_PRIME))
        candidate = n + 1
        while not _is_prime(candidate):
            candidate += 1
        return candidate
    if op == 'prime_factors':
        if n < 1:
            raise ValueError('prime_factors requires a positive integer')
        return _prime_factors(n)
    if op == 'divisors':
        if n < 1:
            raise ValueError('divisors requires a positive integer')
        return _divisors(n)
    if op == 'divisor_count':
        if n < 1:
            raise ValueError('divisor_count requires a positive integer')
        return len(_divisors(n))
    if op == 'divisor_sum':
        if n < 1:
            raise ValueError('divisor_sum requires a positive integer')
        return sum(_divisors(n))
    if op == 'is_perfect':
        # A perfect number equals the sum of its proper divisors (6, 28, ...).
        if n < 1:
            return False
        return sum(_divisors(n)) - n == n
    if op == 'totient':
        if n < 1:
            raise ValueError('totient requires a positive integer')
        return _totient(n)
    if op == 'fibonacci':
        if n < 0:
            raise ValueError('fibonacci requires a non-negative index')
        if n > MAX_FIBONACCI:
            raise ValueError(
                'fibonacci index too large (max {})'.format(MAX_FIBONACCI))
        return _fibonacci(n)
    raise ValueError('unknown number-theory operation')


# ---------------------------------------------------------------------------
# Exact fraction arithmetic (rational numbers, no floating-point error)
# ---------------------------------------------------------------------------

FRACTION_OPS = ('add', 'subtract', 'multiply', 'divide')

FRACTION_SYMBOL = {
    'add': '+',
    'subtract': '−',
    'multiply': '×',
    'divide': '÷',
}


def compute_fraction(op, n1, d1, n2, d2):
    """Apply ``op`` to the exact fractions ``n1/d1`` and ``n2/d2``.

    Returns a ``fractions.Fraction`` in lowest terms. Raises
    ``ZeroDivisionError`` for a zero denominator or division by a zero
    fraction, and ``ValueError`` for non-integer parts or an unknown op.
    """
    n1 = _as_int(n1, 'fraction')
    d1 = _as_int(d1, 'fraction')
    n2 = _as_int(n2, 'fraction')
    d2 = _as_int(d2, 'fraction')
    if d1 == 0 or d2 == 0:
        raise ZeroDivisionError('fraction denominator must be non-zero')
    f1 = Fraction(n1, d1)
    f2 = Fraction(n2, d2)
    if op == 'add':
        return f1 + f2
    if op == 'subtract':
        return f1 - f2
    if op == 'multiply':
        return f1 * f2
    if op == 'divide':
        if f2 == 0:
            raise ZeroDivisionError('division by zero')
        return f1 / f2
    raise ValueError('unknown fraction operation')


def format_fraction(frac):
    """Render a ``Fraction`` the way a calculator would: ``5`` for whole
    values, otherwise ``num/den`` in lowest terms."""
    if frac.denominator == 1:
        return str(frac.numerator)
    return '{}/{}'.format(frac.numerator, frac.denominator)


# ---------------------------------------------------------------------------
# Equation solver (linear, quadratic, 2×2 linear system)
# ---------------------------------------------------------------------------

# Supported equation kinds. ``linear`` solves ax + b = 0, ``quadratic`` solves
# ax² + bx + c = 0 (real or complex roots), and ``system2`` solves a 2×2 linear
# system by Cramer's rule.
SOLVE_KINDS = ('linear', 'quadratic', 'system2')


def _fmt_coef(x):
    """Render a coefficient for an equation string (drops a trailing .0)."""
    return fmt_number(normalize_result(x))


def format_complex(z):
    """Render a complex number as a calculator-style ``a+bi`` string.

    Whole real/imaginary parts drop their ``.0``; a unit imaginary part shows
    as ``i`` (not ``1i``); a zero real part is omitted (pure imaginary)."""
    re = z.real
    im = z.imag
    re_i = int(re) if re == int(re) else round(re, 12)
    im_i = int(im) if im == int(im) else round(im, 12)
    if im_i == 0:
        return str(re_i)
    mag = abs(im_i)
    mag_str = '' if mag == 1 else str(mag)
    if re_i == 0:
        return ('' if im_i > 0 else '-') + mag_str + 'i'
    sign = '+' if im_i > 0 else '-'
    return '{}{}{}i'.format(re_i, sign, mag_str)


def solve_linear(a, b):
    """Solve ``a*x + b = 0``.

    Returns a dict with ``kind``, ``nature`` and ``roots``. A zero leading
    coefficient yields no solution (``b != 0``) or infinitely many (``b == 0``)
    rather than dividing by zero."""
    if a == 0:
        if b == 0:
            return {'kind': 'linear', 'nature': 'infinite solutions', 'roots': []}
        return {'kind': 'linear', 'nature': 'no solution', 'roots': []}
    return {
        'kind': 'linear',
        'nature': 'one solution',
        'roots': [normalize_result(-b / a)],
    }


def solve_quadratic(a, b, c):
    """Solve ``a*x² + b*x + c = 0``.

    Returns a dict with ``kind``, ``discriminant``, ``nature`` and ``roots``.
    Real roots are numbers; complex roots are formatted ``a+bi`` strings. A zero
    leading coefficient degrades gracefully to the linear case."""
    if a == 0:
        result = solve_linear(b, c)
        result['kind'] = 'quadratic'
        result['note'] = 'a = 0, solved as linear'
        return result
    disc = b * b - 4 * a * c
    if disc > 0:
        root = math.sqrt(disc)
        r1 = (-b + root) / (2 * a)
        r2 = (-b - root) / (2 * a)
        return {
            'kind': 'quadratic',
            'discriminant': normalize_result(disc),
            'nature': 'two real roots',
            'roots': [normalize_result(r1), normalize_result(r2)],
        }
    if disc == 0:
        return {
            'kind': 'quadratic',
            'discriminant': 0,
            'nature': 'one real root (repeated)',
            'roots': [normalize_result(-b / (2 * a))],
        }
    real = -b / (2 * a)
    imag = math.sqrt(-disc) / (2 * a)
    return {
        'kind': 'quadratic',
        'discriminant': normalize_result(disc),
        'nature': 'two complex roots',
        'roots': [format_complex(complex(real, imag)),
                  format_complex(complex(real, -imag))],
    }


def solve_system2(a1, b1, c1, a2, b2, c2):
    """Solve the 2×2 linear system ``a1 x + b1 y = c1`` / ``a2 x + b2 y = c2``.

    Returns a dict with ``kind``, ``nature`` and (for a unique solution) ``x``,
    ``y`` and ``roots``. A zero determinant yields no solution or infinitely
    many depending on consistency."""
    det = a1 * b2 - a2 * b1
    if det == 0:
        det_x = c1 * b2 - c2 * b1
        det_y = a1 * c2 - a2 * c1
        if det_x == 0 and det_y == 0:
            return {'kind': 'system2', 'nature': 'infinite solutions', 'roots': []}
        return {'kind': 'system2', 'nature': 'no solution', 'roots': []}
    x = (c1 * b2 - c2 * b1) / det
    y = (a1 * c2 - a2 * c1) / det
    return {
        'kind': 'system2',
        'nature': 'one solution',
        'x': normalize_result(x),
        'y': normalize_result(y),
        'roots': [normalize_result(x), normalize_result(y)],
    }


def solve_result_text(solution):
    """Build a compact human-readable summary of a solver ``solution`` dict
    (used for the history entry's ``result`` field)."""
    nature = solution['nature']
    if nature in ('no solution', 'infinite solutions'):
        return nature
    if solution['kind'] == 'system2':
        return 'x = {}, y = {}'.format(
            fmt_number(solution['x']), fmt_number(solution['y']))
    roots = solution['roots']
    rendered = [r if isinstance(r, str) else fmt_number(r) for r in roots]
    if len(rendered) == 1:
        return 'x = {}'.format(rendered[0])
    return 'x = {}'.format(', '.join(rendered))


# ---------------------------------------------------------------------------
# Financial calculator (interest, loans, time-value of money)
# ---------------------------------------------------------------------------

# Each finance op maps a set of named numeric inputs to a result dict. All
# rates are entered as annual (or per-period) percentages, e.g. ``5`` means 5%.
FINANCE_OPS = (
    'simple_interest', 'compound_interest', 'loan_payment',
    'future_value', 'present_value',
)

# The numeric input fields each op requires (drives parsing/validation in the
# HTTP layer). ``rate`` is always a percentage.
FINANCE_FIELDS = {
    'simple_interest': ('principal', 'rate', 'years'),
    'compound_interest': ('principal', 'rate', 'n', 'years'),
    'loan_payment': ('principal', 'rate', 'months'),
    'future_value': ('principal', 'rate', 'periods'),
    'present_value': ('amount', 'rate', 'periods'),
}

# Which result key is the headline number used for the history entry.
FINANCE_PRIMARY = {
    'simple_interest': 'amount',
    'compound_interest': 'amount',
    'loan_payment': 'payment',
    'future_value': 'amount',
    'present_value': 'amount',
}


def compute_finance(op, params):
    """Apply a financial ``op`` to the ``params`` dict and return a result dict.

    - ``simple_interest``: I = P·r·t; returns ``interest`` and ``amount``.
    - ``compound_interest``: A = P·(1 + r/n)^(n·t); returns ``amount`` and
      ``interest``. ``n`` (compounding periods per year) must be a positive
      integer.
    - ``loan_payment``: fixed monthly payment that amortizes ``principal`` over
      ``months`` at an annual ``rate``; returns ``payment``, ``total_paid`` and
      ``total_interest``. A zero rate yields an even ``principal / months``
      split.
    - ``future_value``: FV = PV·(1 + r)^n over ``periods`` (``rate`` is the
      per-period rate); returns ``amount``.
    - ``present_value``: PV = FV/(1 + r)^n; returns ``amount``.

    Raises ``ValueError`` for an unknown op or an out-of-domain input and
    ``ZeroDivisionError`` when a discount factor collapses to zero.
    """
    if op == 'simple_interest':
        p = params['principal']
        rate = params['rate']
        years = params['years']
        if p < 0:
            raise ValueError('principal must be non-negative')
        if years < 0:
            raise ValueError('years must be non-negative')
        interest = p * (rate / 100.0) * years
        return {'interest': interest, 'amount': p + interest}

    if op == 'compound_interest':
        p = params['principal']
        rate = params['rate']
        n = params['n']
        years = params['years']
        if p < 0:
            raise ValueError('principal must be non-negative')
        if years < 0:
            raise ValueError('years must be non-negative')
        if n != int(n) or n < 1:
            raise ValueError('n (compounding periods per year) must be a '
                             'positive integer')
        n = int(n)
        amount = p * (1 + (rate / 100.0) / n) ** (n * years)
        return {'amount': amount, 'interest': amount - p}

    if op == 'loan_payment':
        p = params['principal']
        rate = params['rate']
        months = params['months']
        if p < 0:
            raise ValueError('principal must be non-negative')
        if months != int(months) or months < 1:
            raise ValueError('months must be a positive integer')
        months = int(months)
        r = (rate / 100.0) / 12
        if r == 0:
            payment = p / months
        else:
            factor = (1 + r) ** months
            payment = p * r * factor / (factor - 1)
        total_paid = payment * months
        return {
            'payment': payment,
            'total_paid': total_paid,
            'total_interest': total_paid - p,
        }

    if op == 'future_value':
        pv = params['principal']
        rate = params['rate']
        periods = params['periods']
        if periods < 0:
            raise ValueError('periods must be non-negative')
        return {'amount': pv * (1 + rate / 100.0) ** periods}

    if op == 'present_value':
        fv = params['amount']
        rate = params['rate']
        periods = params['periods']
        if periods < 0:
            raise ValueError('periods must be non-negative')
        denom = (1 + rate / 100.0) ** periods
        if denom == 0:
            raise ZeroDivisionError('discount factor is zero')
        return {'amount': fv / denom}

    raise ValueError('unknown finance operation')


def finance_expression(op, params):
    """Build a human-readable expression string for a finance ``op``."""
    f = fmt_number
    if op == 'simple_interest':
        return 'SI(P={}, r={}%, t={}y)'.format(
            f(params['principal']), f(params['rate']), f(params['years']))
    if op == 'compound_interest':
        return 'CI(P={}, r={}%, n={}, t={}y)'.format(
            f(params['principal']), f(params['rate']),
            f(params['n']), f(params['years']))
    if op == 'loan_payment':
        return 'PMT(P={}, r={}%, {}mo)'.format(
            f(params['principal']), f(params['rate']), f(params['months']))
    if op == 'future_value':
        return 'FV(PV={}, r={}%, {}n)'.format(
            f(params['principal']), f(params['rate']), f(params['periods']))
    if op == 'present_value':
        return 'PV(FV={}, r={}%, {}n)'.format(
            f(params['amount']), f(params['rate']), f(params['periods']))
    return op


# ---------------------------------------------------------------------------
# Unit conversion (length, mass, temperature, volume, time, data, speed)
# ---------------------------------------------------------------------------

# Each linear category maps every unit to its size in the category's base unit
# (length→metre, mass→gram, volume→litre, time→second, data→byte, speed→m/s).
# A conversion is value · factor[from] / factor[to]. Temperature is affine and
# handled separately below.
UNIT_CATEGORIES = {
    'length': {
        'mm': 0.001, 'cm': 0.01, 'm': 1.0, 'km': 1000.0,
        'in': 0.0254, 'ft': 0.3048, 'yd': 0.9144, 'mi': 1609.344,
    },
    'mass': {
        'mg': 0.001, 'g': 1.0, 'kg': 1000.0, 't': 1000000.0,
        'oz': 28.349523125, 'lb': 453.59237,
    },
    'volume': {
        'ml': 0.001, 'l': 1.0, 'gal': 3.785411784, 'qt': 0.946352946,
        'pt': 0.473176473, 'cup': 0.2365882365, 'floz': 0.0295735295625,
    },
    'time': {
        'ms': 0.001, 's': 1.0, 'min': 60.0, 'hr': 3600.0,
        'day': 86400.0, 'week': 604800.0,
    },
    'data': {
        'bit': 0.125, 'byte': 1.0, 'kb': 1000.0, 'mb': 1000000.0,
        'gb': 1000000000.0, 'tb': 1000000000000.0,
    },
    'speed': {
        'mps': 1.0, 'kph': 1000.0 / 3600.0, 'mph': 0.44704,
        'fps': 0.3048, 'knot': 1852.0 / 3600.0,
    },
}

# Temperature units (affine, not a simple multiplicative factor).
TEMPERATURE_UNITS = ('c', 'f', 'k')

# Every category the converter understands, including temperature.
VALID_UNIT_CATEGORIES = tuple(UNIT_CATEGORIES.keys()) + ('temperature',)


def _to_celsius(value, unit):
    """Convert a temperature ``value`` in ``unit`` (c/f/k) to Celsius."""
    if unit == 'c':
        return value
    if unit == 'f':
        return (value - 32) * 5.0 / 9.0
    if unit == 'k':
        return value - 273.15
    raise ValueError('temperature unit must be one of ' +
                     ', '.join(TEMPERATURE_UNITS))


def _from_celsius(celsius, unit):
    """Convert a Celsius ``value`` to ``unit`` (c/f/k)."""
    if unit == 'c':
        return celsius
    if unit == 'f':
        return celsius * 9.0 / 5.0 + 32
    if unit == 'k':
        return celsius + 273.15
    raise ValueError('temperature unit must be one of ' +
                     ', '.join(TEMPERATURE_UNITS))


def convert_unit(category, value, from_unit, to_unit):
    """Convert ``value`` from ``from_unit`` to ``to_unit`` within ``category``.

    Temperature is converted via Celsius; every other category is a linear
    base-unit conversion. Raises ``ValueError`` for an unknown category or a
    unit that does not belong to it.
    """
    if category == 'temperature':
        from_u = str(from_unit).lower()
        to_u = str(to_unit).lower()
        return _from_celsius(_to_celsius(value, from_u), to_u)

    factors = UNIT_CATEGORIES.get(category)
    if factors is None:
        raise ValueError('category must be one of ' +
                         ', '.join(VALID_UNIT_CATEGORIES))
    if from_unit not in factors:
        raise ValueError('{!r} is not a {} unit'.format(from_unit, category))
    if to_unit not in factors:
        raise ValueError('{!r} is not a {} unit'.format(to_unit, category))
    return value * factors[from_unit] / factors[to_unit]


# ---------------------------------------------------------------------------
# Date calculator (difference, shift by days, weekday) — ISO YYYY-MM-DD
# ---------------------------------------------------------------------------

DATE_OPS = ('diff', 'add', 'subtract', 'weekday')


def _parse_date(text):
    """Parse an ISO ``YYYY-MM-DD`` string into a ``datetime.date``."""
    try:
        return datetime.date.fromisoformat(str(text))
    except (ValueError, TypeError):
        raise ValueError('date must be in YYYY-MM-DD format')


def _date_days(params):
    """Read and validate the integer ``days`` field for add/subtract."""
    raw = params.get('days')
    if raw is None or isinstance(raw, bool):
        raise ValueError('days must be an integer')
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError('days must be an integer')
    return _as_int(value, 'days')


def date_calc(op, params):
    """Apply a date ``op`` to the ``params`` dict and return a result dict.

    - ``diff``: signed day count from ``date1`` to ``date2`` (``days``).
    - ``add`` / ``subtract``: shift ``date`` by an integer ``days`` (``date``).
    - ``weekday``: the weekday ``name`` and ``iso_weekday`` (1=Mon..7=Sun).

    Raises ``ValueError`` for an unknown op, a malformed date, or a
    non-integer ``days`` value.
    """
    if op == 'diff':
        d1 = _parse_date(params.get('date1'))
        d2 = _parse_date(params.get('date2'))
        return {'days': (d2 - d1).days}
    if op == 'add':
        d = _parse_date(params.get('date'))
        days = _date_days(params)
        return {'date': (d + datetime.timedelta(days=days)).isoformat()}
    if op == 'subtract':
        d = _parse_date(params.get('date'))
        days = _date_days(params)
        return {'date': (d - datetime.timedelta(days=days)).isoformat()}
    if op == 'weekday':
        d = _parse_date(params.get('date'))
        return {'name': d.strftime('%A'), 'iso_weekday': d.isoweekday()}
    raise ValueError('unknown date operation')


# ---------------------------------------------------------------------------
# Vector calculator (Euclidean vectors of arbitrary dimension)
# ---------------------------------------------------------------------------

# Each op maps one or two vectors (and optionally a scalar ``k``) to a result.
# ``add``/``subtract``/``cross``/``scale``/``normalize`` return vectors (lists);
# ``dot``/``magnitude``/``distance``/``angle`` return scalars (numbers).
VECTOR_OPS = (
    'add', 'subtract', 'dot', 'cross', 'scale',
    'magnitude', 'normalize', 'distance', 'angle',
)

# Ops that need a second vector ``b``.
_VECTOR_BINARY = ('add', 'subtract', 'dot', 'cross', 'distance', 'angle')


def _check_vector(v, name='vector'):
    """Validate ``v`` is a non-empty list of real numbers; return it as a list."""
    if not isinstance(v, list) or len(v) == 0:
        raise ValueError('{} must be a non-empty list of numbers'.format(name))
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ValueError('{} components must be numbers'.format(name))
        out.append(x)
    return out


def compute_vector(op, a, b=None, k=None):
    """Apply a vector ``op`` to vector ``a`` (and ``b``/``k`` as needed).

    Returns a list (for vector-valued ops) or a number (for scalar-valued ops).
    Raises ``ValueError`` for an unknown op, a shape mismatch, a missing scalar,
    or an undefined operation (e.g. normalizing the zero vector).
    """
    a = _check_vector(a, 'a')
    if op in _VECTOR_BINARY:
        b = _check_vector(b, 'b')
    if op in ('add', 'subtract', 'dot', 'distance', 'angle'):
        if len(a) != len(b):
            raise ValueError('vectors must have the same length')

    if op == 'add':
        return [x + y for x, y in zip(a, b)]
    if op == 'subtract':
        return [x - y for x, y in zip(a, b)]
    if op == 'dot':
        return sum(x * y for x, y in zip(a, b))
    if op == 'cross':
        if len(a) != 3 or len(b) != 3:
            raise ValueError('cross product requires two 3-D vectors')
        return [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ]
    if op == 'scale':
        if k is None:
            raise ValueError('scale requires a scalar k')
        return [x * k for x in a]
    if op == 'magnitude':
        return math.sqrt(sum(x * x for x in a))
    if op == 'normalize':
        mag = math.sqrt(sum(x * x for x in a))
        if mag == 0:
            raise ValueError('cannot normalize the zero vector')
        return [x / mag for x in a]
    if op == 'distance':
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
    if op == 'angle':
        ma = math.sqrt(sum(x * x for x in a))
        mb = math.sqrt(sum(x * x for x in b))
        if ma == 0 or mb == 0:
            raise ValueError('angle is undefined for the zero vector')
        cos = sum(x * y for x, y in zip(a, b)) / (ma * mb)
        # Clamp to guard against tiny floating-point overshoot past ±1.
        cos = max(-1.0, min(1.0, cos))
        return math.degrees(math.acos(cos))
    raise ValueError('unknown vector operation')


# ---------------------------------------------------------------------------
# Matrix calculator (real-valued matrices)
# ---------------------------------------------------------------------------

# Each op maps one or two matrices (and optionally a scalar ``k`` / size ``n``)
# to a result. ``add``/``subtract``/``multiply``/``scale``/``transpose``/
# ``inverse``/``identity`` return matrices; ``determinant``/``trace`` return
# scalars.
MATRIX_OPS = (
    'add', 'subtract', 'multiply', 'scale', 'transpose',
    'determinant', 'inverse', 'identity', 'trace',
)


def _check_matrix(m, name='matrix'):
    """Validate ``m`` is a non-empty rectangular list-of-lists of numbers."""
    if not isinstance(m, list) or len(m) == 0:
        raise ValueError('{} must be a non-empty list of rows'.format(name))
    width = None
    out = []
    for row in m:
        if not isinstance(row, list) or len(row) == 0:
            raise ValueError('{} rows must be non-empty lists'.format(name))
        if width is None:
            width = len(row)
        elif len(row) != width:
            raise ValueError('{} rows must all have the same length'.format(name))
        clean = []
        for x in row:
            if isinstance(x, bool) or not isinstance(x, (int, float)):
                raise ValueError('{} entries must be numbers'.format(name))
            clean.append(x)
        out.append(clean)
    return out


def _dims(m):
    """Return the (rows, columns) shape of a validated matrix."""
    return len(m), len(m[0])


def _require_square(m):
    """Return the size of a square matrix or raise if it is not square."""
    rows, cols = _dims(m)
    if rows != cols:
        raise ValueError('matrix must be square')
    return rows


def _determinant(m):
    """Determinant via cofactor expansion (exact for integer matrices)."""
    n = len(m)
    if n == 1:
        return m[0][0]
    if n == 2:
        return m[0][0] * m[1][1] - m[0][1] * m[1][0]
    total = 0
    for j in range(n):
        minor = [row[:j] + row[j + 1:] for row in m[1:]]
        total += ((-1) ** j) * m[0][j] * _determinant(minor)
    return total


def _inverse(m):
    """Matrix inverse via Gauss-Jordan elimination with partial pivoting."""
    n = _require_square(m)
    # Build the augmented matrix [m | I] in floating point.
    aug = [[float(x) for x in row] +
           [1.0 if i == j else 0.0 for j in range(n)]
           for i, row in enumerate(m)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError('matrix is singular (no inverse)')
        aug[col], aug[pivot] = aug[pivot], aug[col]
        piv = aug[col][col]
        aug[col] = [x / piv for x in aug[col]]
        for r in range(n):
            if r != col:
                factor = aug[r][col]
                aug[r] = [a - factor * b for a, b in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]


def compute_matrix(op, a=None, b=None, k=None, n=None):
    """Apply a matrix ``op`` to matrix ``a`` (and ``b``/``k``/``n`` as needed).

    Returns a list-of-lists (matrix-valued ops) or a number (``determinant``,
    ``trace``). Raises ``ValueError`` for an unknown op, a shape mismatch, a
    singular matrix, or a missing scalar/size argument.
    """
    if op == 'identity':
        if n is None or n != int(n) or n < 1:
            raise ValueError('identity requires a positive integer size n')
        n = int(n)
        return [[1 if i == j else 0 for j in range(n)] for i in range(n)]

    a = _check_matrix(a, 'a')
    if op in ('add', 'subtract', 'multiply'):
        b = _check_matrix(b, 'b')

    if op in ('add', 'subtract'):
        if _dims(a) != _dims(b):
            raise ValueError('matrices must have the same dimensions')
        if op == 'add':
            return [[x + y for x, y in zip(ra, rb)] for ra, rb in zip(a, b)]
        return [[x - y for x, y in zip(ra, rb)] for ra, rb in zip(a, b)]
    if op == 'multiply':
        ar, ac = _dims(a)
        br, bc = _dims(b)
        if ac != br:
            raise ValueError('inner dimensions must agree for multiplication')
        return [[sum(a[i][t] * b[t][j] for t in range(ac)) for j in range(bc)]
                for i in range(ar)]
    if op == 'scale':
        if k is None:
            raise ValueError('scale requires a scalar k')
        return [[x * k for x in row] for row in a]
    if op == 'transpose':
        rows, cols = _dims(a)
        return [[a[i][j] for i in range(rows)] for j in range(cols)]
    if op == 'determinant':
        _require_square(a)
        return _determinant(a)
    if op == 'inverse':
        return _inverse(a)
    if op == 'trace':
        _require_square(a)
        return sum(a[i][i] for i in range(len(a)))
    raise ValueError('unknown matrix operation')


# ---------------------------------------------------------------------------
# Complex-number calculator (rectangular a+bi arithmetic)
# ---------------------------------------------------------------------------

# Each op acts on one complex number ``z1 = re1 + im1·i`` and, for the binary
# ops, a second ``z2 = re2 + im2·i``. ``add``/``subtract``/``multiply``/
# ``divide``/``conjugate``/``power`` yield another complex number; ``modulus``
# and ``argument`` yield a real scalar; ``polar`` yields both (r and θ).
COMPLEX_OPS = (
    'add', 'subtract', 'multiply', 'divide',
    'conjugate', 'modulus', 'argument', 'polar', 'power',
)

# Ops needing a second operand z2 (re2, im2).
COMPLEX_BINARY = ('add', 'subtract', 'multiply', 'divide')

# Display symbol for the binary complex ops (used to build an expression).
COMPLEX_SYMBOL = {
    'add': '+',
    'subtract': '−',
    'multiply': '×',
    'divide': '÷',
}


def compute_complex(op, re1, im1, re2=0.0, im2=0.0, n=0):
    """Apply complex ``op`` to ``z1 = re1 + im1·i`` (and ``z2``/``n`` as needed).

    Returns a dict. Complex-valued ops return ``{'real', 'imag'}``; ``modulus``
    returns ``{'modulus'}``; ``argument`` returns ``{'argument'}`` (radians,
    via atan2); ``polar`` returns ``{'modulus', 'argument'}``. Raises
    ``ZeroDivisionError`` for division by (or a negative power of) zero and
    ``ValueError`` for a non-integer power or an unknown op.
    """
    z1 = complex(re1, im1)
    if op in COMPLEX_BINARY:
        z2 = complex(re2, im2)
        if op == 'add':
            z = z1 + z2
        elif op == 'subtract':
            z = z1 - z2
        elif op == 'multiply':
            z = z1 * z2
        else:  # divide
            if z2 == 0:
                raise ZeroDivisionError('division by a zero complex number')
            z = z1 / z2
        return {'real': z.real, 'imag': z.imag}
    if op == 'conjugate':
        z = z1.conjugate()
        return {'real': z.real, 'imag': z.imag}
    if op == 'power':
        if n != int(n):
            raise ValueError('power exponent n must be an integer')
        n = int(n)
        if z1 == 0 and n < 0:
            raise ZeroDivisionError('negative power of zero')
        z = z1 ** n
        return {'real': z.real, 'imag': z.imag}
    if op == 'modulus':
        return {'modulus': abs(z1)}
    if op == 'argument':
        return {'argument': math.atan2(im1, re1)}
    if op == 'polar':
        return {'modulus': abs(z1), 'argument': math.atan2(im1, re1)}
    raise ValueError('unknown complex operation')


# ---------------------------------------------------------------------------
# Polynomial calculator (real coefficients, ascending order)
# ---------------------------------------------------------------------------

# A polynomial is a list of coefficients in ascending power order, so
# ``[1, 2, 3]`` means ``1 + 2x + 3x²``. ``evaluate`` returns a number (the value
# at ``x``); ``derivative``/``integral``/``add``/``multiply`` return coefficient
# lists in the same ascending convention.
POLYNOMIAL_OPS = ('evaluate', 'derivative', 'integral', 'add', 'multiply')

# Ops that combine two polynomials ``a`` and ``b``.
_POLY_BINARY = ('add', 'multiply')

# Superscript digits for rendering exponents in a human-readable polynomial.
_SUPERSCRIPT = {'0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
                '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'}


def _superscript(n):
    """Render a non-negative integer ``n`` as Unicode superscript digits."""
    return ''.join(_SUPERSCRIPT[d] for d in str(n))


def _check_poly(c, name='coefficients'):
    """Validate ``c`` is a non-empty list of real numbers; return it as a list."""
    if not isinstance(c, list) or len(c) == 0:
        raise ValueError('{} must be a non-empty list of numbers'.format(name))
    out = []
    for x in c:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise ValueError('{} must be numbers'.format(name))
        out.append(x)
    return out


def _poly_trim(c):
    """Drop trailing (highest-degree) zero coefficients, keeping at least one."""
    i = len(c) - 1
    while i > 0 and c[i] == 0:
        i -= 1
    return c[:i + 1]


def compute_polynomial(op, coeffs=None, a=None, b=None, x=None):
    """Apply a polynomial ``op``.

    - ``evaluate``: value of ``coeffs`` at ``x`` (Horner's method) → number.
    - ``derivative``: term-by-term derivative → coefficient list.
    - ``integral``: antiderivative with zero constant → coefficient list.
    - ``add`` / ``multiply``: combine polynomials ``a`` and ``b`` → list.

    Raises ``ValueError`` for an unknown op, a missing/invalid coefficient list,
    or a missing ``x``.
    """
    if op == 'evaluate':
        c = _check_poly(coeffs, 'coefficients')
        if x is None:
            raise ValueError('evaluate requires x')
        result = 0.0
        for coef in reversed(c):
            result = result * x + coef
        return result
    if op == 'derivative':
        c = _check_poly(coeffs, 'coefficients')
        if len(c) == 1:
            return [0]
        return _poly_trim([i * c[i] for i in range(1, len(c))])
    if op == 'integral':
        c = _check_poly(coeffs, 'coefficients')
        return [0] + [c[i] / (i + 1) for i in range(len(c))]
    if op in _POLY_BINARY:
        ca = _check_poly(a, 'a')
        cb = _check_poly(b, 'b')
        if op == 'add':
            n = max(len(ca), len(cb))
            res = [(ca[i] if i < len(ca) else 0) + (cb[i] if i < len(cb) else 0)
                   for i in range(n)]
            return _poly_trim(res)
        res = [0] * (len(ca) + len(cb) - 1)
        for i, va in enumerate(ca):
            for j, vb in enumerate(cb):
                res[i + j] += va * vb
        return _poly_trim(res)
    raise ValueError('unknown polynomial operation')


def format_polynomial(coeffs):
    """Render an ascending-coefficient list as a descending-power string
    (e.g. ``[1, 0, 3]`` → ``3x² + 1``). The zero polynomial renders as ``0``."""
    terms = []
    for power in range(len(coeffs) - 1, -1, -1):
        coef = normalize_result(coeffs[power])
        if coef == 0:
            continue
        mag = abs(coef)
        if power == 0:
            body = fmt_number(mag)
        elif power == 1:
            body = ('' if mag == 1 else fmt_number(mag)) + 'x'
        else:
            body = ('' if mag == 1 else fmt_number(mag)) + 'x' + _superscript(power)
        terms.append(('-' if coef < 0 else '+', body))
    if not terms:
        return '0'
    sign0, body0 = terms[0]
    out = ('-' if sign0 == '-' else '') + body0
    for sign, body in terms[1:]:
        out += ' {} {}'.format(sign, body)
    return out


# ---------------------------------------------------------------------------
# Geometry calculator (2-D shapes and 3-D solids)
# ---------------------------------------------------------------------------

# Each shape maps a set of positive named dimensions to a metrics dict. 2-D
# shapes report ``area`` (and ``perimeter`` where the inputs determine it); 3-D
# solids report ``volume`` and ``surface``.
GEOMETRY_SHAPES = (
    'square', 'rectangle', 'circle', 'triangle', 'trapezoid',
    'cube', 'rectangular_prism', 'sphere', 'cylinder', 'cone',
)

# The positive numeric dimensions each shape requires (drives HTTP parsing).
GEOMETRY_FIELDS = {
    'square': ('side',),
    'rectangle': ('width', 'height'),
    'circle': ('radius',),
    'triangle': ('base', 'height'),
    'trapezoid': ('a', 'b', 'height'),
    'cube': ('side',),
    'rectangular_prism': ('length', 'width', 'height'),
    'sphere': ('radius',),
    'cylinder': ('radius', 'height'),
    'cone': ('radius', 'height'),
}

# The headline metric used for the history entry (area for 2-D, volume for 3-D).
GEOMETRY_PRIMARY = {
    'square': 'area',
    'rectangle': 'area',
    'circle': 'area',
    'triangle': 'area',
    'trapezoid': 'area',
    'cube': 'volume',
    'rectangular_prism': 'volume',
    'sphere': 'volume',
    'cylinder': 'volume',
    'cone': 'volume',
}


def compute_geometry(shape, params):
    """Compute the metrics for ``shape`` from its positive ``params``.

    Raises ``ValueError`` for an unknown shape or a non-positive dimension.
    """
    if shape not in GEOMETRY_FIELDS:
        raise ValueError('shape must be one of ' + ', '.join(GEOMETRY_SHAPES))
    for name, value in params.items():
        if value <= 0:
            raise ValueError('{} must be positive'.format(name))

    if shape == 'square':
        s = params['side']
        return {'area': s * s, 'perimeter': 4 * s}
    if shape == 'rectangle':
        w, h = params['width'], params['height']
        return {'area': w * h, 'perimeter': 2 * (w + h)}
    if shape == 'circle':
        r = params['radius']
        return {'area': math.pi * r * r, 'circumference': 2 * math.pi * r}
    if shape == 'triangle':
        return {'area': 0.5 * params['base'] * params['height']}
    if shape == 'trapezoid':
        a, b, h = params['a'], params['b'], params['height']
        return {'area': 0.5 * (a + b) * h}
    if shape == 'cube':
        s = params['side']
        return {'volume': s ** 3, 'surface': 6 * s * s}
    if shape == 'rectangular_prism':
        l, w, h = params['length'], params['width'], params['height']
        return {'volume': l * w * h,
                'surface': 2 * (l * w + l * h + w * h)}
    if shape == 'sphere':
        r = params['radius']
        return {'volume': 4.0 / 3.0 * math.pi * r ** 3,
                'surface': 4 * math.pi * r * r}
    if shape == 'cylinder':
        r, h = params['radius'], params['height']
        return {'volume': math.pi * r * r * h,
                'surface': 2 * math.pi * r * (r + h)}
    if shape == 'cone':
        r, h = params['radius'], params['height']
        slant = math.sqrt(r * r + h * h)
        return {'volume': 1.0 / 3.0 * math.pi * r * r * h,
                'surface': math.pi * r * (r + slant)}
    raise ValueError('unknown shape')


# ---------------------------------------------------------------------------
# Roman numerals (1..3999, canonical form)
# ---------------------------------------------------------------------------

ROMAN_OPS = ('to_roman', 'from_roman')

# Subtractive-notation table, largest value first, used to encode an integer.
_ROMAN_TABLE = (
    (1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
    (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
    (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I'),
)

_ROMAN_VALUE = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}


def to_roman(n):
    """Encode integer ``n`` (1..3999) as a canonical Roman numeral string.

    Raises ``ValueError`` for a non-integer or an out-of-range value."""
    n = _as_int(n, 'to_roman')
    if n < 1 or n > 3999:
        raise ValueError('Roman numerals support integers 1..3999')
    out = []
    for value, sym in _ROMAN_TABLE:
        while n >= value:
            out.append(sym)
            n -= value
    return ''.join(out)


def from_roman(s):
    """Decode a canonical Roman numeral string to an integer.

    Rejects unknown characters and non-canonical strings (e.g. ``IIII``, ``IC``)
    via a round-trip check. Raises ``ValueError`` on any of these."""
    if not isinstance(s, str) or s.strip() == '':
        raise ValueError('value must be a non-empty Roman numeral string')
    text = s.strip().upper()
    for ch in text:
        if ch not in _ROMAN_VALUE:
            raise ValueError('invalid Roman numeral character: {!r}'.format(ch))
    total = 0
    prev = 0
    for ch in reversed(text):
        value = _ROMAN_VALUE[ch]
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    if total < 1 or total > 3999 or to_roman(total) != text:
        raise ValueError('{!r} is not a canonical Roman numeral'.format(s))
    return total


# ---------------------------------------------------------------------------
# Linear regression (ordinary least-squares fit over (x, y) points)
# ---------------------------------------------------------------------------

REGRESSION_OPS = ('fit', 'predict')


def compute_regression(points, predict_x=None):
    """Ordinary least-squares linear fit ``y = slope*x + intercept`` over a list
    of ``[x, y]`` points (at least two, with non-zero variance in x).

    Returns a dict with ``n``, ``slope``, ``intercept``, ``r`` (Pearson
    correlation) and ``r2``; when ``predict_x`` is given it also returns
    ``predict_x`` and the predicted ``predict_y`` at that x.

    Raises ``ValueError`` for malformed input, fewer than two points, or a
    degenerate (vertical) fit where every x is identical.
    """
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError('points must be a list of at least two [x, y] pairs')
    xs, ys = [], []
    for p in points:
        if (not isinstance(p, (list, tuple)) or len(p) != 2
                or any(isinstance(c, bool) or not isinstance(c, (int, float))
                       for c in p)):
            raise ValueError('each point must be an [x, y] pair of numbers')
        xs.append(p[0])
        ys.append(p[1])

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError('cannot fit a line: all x values are identical')
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    syy = sum((y - mean_y) ** 2 for y in ys)

    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    # Pearson r is undefined when y is constant (syy == 0); report 0 there.
    r = 0.0 if syy == 0 else sxy / math.sqrt(sxx * syy)
    result = {
        'n': n,
        'slope': slope,
        'intercept': intercept,
        'r': r,
        'r2': r * r,
    }
    if predict_x is not None:
        if isinstance(predict_x, bool) or not isinstance(predict_x, (int, float)):
            raise ValueError('predict_x must be a number')
        result['predict_x'] = predict_x
        result['predict_y'] = slope * predict_x + intercept
    return result
