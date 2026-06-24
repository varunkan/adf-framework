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

import math
import statistics

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
}

VALID_OPS = tuple(BINARY_SYMBOL.keys())


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
        if a != int(a) or b != int(b):
            raise ValueError('gcd requires integers')
        return math.gcd(int(a), int(b))
    if op == 'lcm':
        if a != int(a) or b != int(b):
            raise ValueError('lcm requires integers')
        return math.lcm(int(a), int(b))
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
    raise ValueError('unknown operation')


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
        value = self._factor()
        while True:
            kind, val = self._peek()
            if kind == 'op' and val in '*/%':
                self._advance()
                rhs = self._factor()
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

    def _factor(self):
        # Power is right-associative and binds tighter than * /.
        base = self._unary()
        kind, val = self._peek()
        if kind == 'op' and val == '^':
            self._advance()
            exponent = self._factor()
            result = base ** exponent
            if isinstance(result, complex):
                raise ExpressionError('result is not a real number')
            return result
        return base

    def _unary(self):
        kind, val = self._peek()
        if kind == 'op' and val in '+-':
            self._advance()
            operand = self._unary()
            return operand if val == '+' else -operand
        return self._primary()

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
