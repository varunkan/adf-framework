# Calculator

A self-contained calculator web app. Python standard-library HTTP server +
single static HTML frontend (inline CSS + vanilla JS). No third-party
dependencies, no build step.

## Features

- Arithmetic: add, subtract, multiply, divide, power, modulo, integer-divide,
  gcd, lcm
- Bitwise / programmer ops: and, or, xor, left-shift, right-shift (integer
  operands), plus unary bitwise-not
- Combinatorics: nCr (combinations) and nPr (permutations)
- Percentage toolkit: percent-of, percent-change, increase-by, decrease-by
- Scientific unary ops: sqrt, cbrt, square, cube, reciprocal, abs, factorial,
  sin/cos/tan, asin/acos/atan, sinh/cosh/tanh, ln/log10/log2, exp, floor, ceil,
  round, sign, deg↔rad, percent, bitnot
- Free-form expression evaluation (safe recursive-descent parser, no `eval`)
  with constants `pi`, `e`, `tau`, `phi`
- Memory register (MC / MR / M+ / M− / MS), persisted to `memory.json`
- Server-side computation via JSON API
- Division-by-zero and invalid-input validation
- Number-base converter (bin / oct / dec / hex, signed)
- Descriptive statistics (count, sum, mean, median, mode, min, max, range,
  sample stdev/variance) over a list of numbers
- Number theory: is-prime, next-prime, prime factorization, divisors,
  divisor count/sum, is-perfect, Euler totient φ, Fibonacci
- Exact fraction arithmetic (add / subtract / multiply / divide of rationals,
  reduced to lowest terms — no floating-point error)
- Polynomial calculator (evaluate at a point, derivative, integral, add,
  multiply — real coefficient lists in ascending power order)
- Geometry calculator (area/perimeter of 2-D shapes and volume/surface of 3-D
  solids)
- Roman-numeral conversion (integer ↔ canonical Roman numeral, 1..3999)
- Calculation history (persisted to `history.json` next to `server.py`)
- Keyboard support (digits, `+ - * /`, Enter, Backspace, Escape)

## Run

```bash
python3 server.py
```

Then open http://localhost:8000

Override the port:

```bash
PORT=9000 python3 server.py
```

## Test

```bash
python3 test_app.py
```

All tests should pass with zero failures.

## API

### `POST /api/calculate`
Request body:
```json
{ "op": "add", "a": 2, "b": 3 }
```
`op` is one of `add`, `subtract`, `multiply`, `divide`, `power`, `modulo`,
`intdiv`, `gcd`, `lcm`. (`gcd`/`lcm` require integer operands.)

Success `200`:
```json
{ "op": "add", "a": 2, "b": 3, "result": 5, "expression": "2 + 3" }
```

Errors `400`:
- invalid JSON body
- `op` not in allowed set
- `a` or `b` not numeric
- division by zero

### `GET /api/history`
Returns the most recent calculations (newest first):
```json
{ "history": [ { "op": "add", "a": 2, "b": 3, "result": 5, "expression": "2 + 3" } ] }
```

### `DELETE /api/history`
Clears stored history. Returns `{ "history": [] }`.

### `POST /api/unary`
Single-operand scientific op. Body `{ "op": "sqrt", "a": 144 }`; `op` is one of
sqrt, cbrt, square, cube, negate, reciprocal, abs, factorial, sin, cos, tan,
asin, acos, atan, sinh, cosh, tanh, ln, log10, log2, exp, floor, ceil, round,
sign, deg, rad, percent. Returns `{ "op", "a", "result", "expression" }`.

### `POST /api/evaluate`
Evaluates a free-form expression. Body `{ "expression": "(2+3)*pi^2" }`.
Supports `+ - * / % ^`, parentheses, unary signs, decimals, and the constants
`pi`, `e`, `tau`, `phi`. Returns `{ "expression", "result" }`.

### `GET /api/memory` · `POST /api/memory` · `DELETE /api/memory`
The memory register. `GET` returns `{ "memory": <number> }`. `POST` takes
`{ "action": "store|recall|clear|add|subtract", "value": <number?> }` (value
required for store/add/subtract) and returns `{ "action", "memory" }`.
`DELETE` clears it to `0`.

### `POST /api/convert`
Convert an integer between number bases. Body
`{ "value": "ff", "from_base": "hex", "to_base": "bin" }`; each base is one of
`bin`, `oct`, `dec`, `hex`. Returns
`{ "value", "from_base", "to_base", "result", "expression" }`. Errors `400` for
an unknown base or a value that is not valid in `from_base`.

### `POST /api/stats`
Descriptive statistics over a list of numbers. Body
`{ "values": [2, 4, 4, 5, 5, 7, 9] }`. Returns
`{ "count", "stats": { count, sum, mean, median, mode, min, max, range, stdev,
variance }, "result" }`. `stdev`/`variance` are `0` for a single value; `mode`
is `null` when there is no unique most-common value. Errors `400` for an empty
or non-numeric list.

### `POST /api/numtheory`
Number-theory operation on a single integer. Body
`{ "op": "fibonacci", "n": 10 }`; `op` is one of `is_prime`, `next_prime`,
`prime_factors`, `divisors`, `divisor_count`, `divisor_sum`, `is_perfect`,
`totient`, `fibonacci`. Returns `{ "op", "n", "result", "expression" }` where
`result` is a boolean (`is_prime`/`is_perfect`), an integer, or a list
(`prime_factors`/`divisors`). Errors `400` for a non-integer `n`, an
out-of-domain value, or an unknown op.

### `POST /api/fraction`
Exact rational arithmetic over `n1/d1` and `n2/d2`. Body
`{ "op": "add", "n1": 1, "d1": 2, "n2": 1, "d2": 3 }`; `op` is one of `add`,
`subtract`, `multiply`, `divide`. Returns
`{ "op", "numerator", "denominator", "decimal", "result", "expression" }` with
`result` in lowest terms (e.g. `"5/6"`). Errors `400` for a zero denominator,
division by a zero fraction, non-integer parts, or an unknown op.

### `POST /api/polynomial`
Polynomial operations over ascending coefficient lists (`[c0, c1, c2]` means
`c0 + c1·x + c2·x²`). Body `{ "op": "evaluate", "coeffs": [1, 2, 3], "x": 2 }`;
`op` is one of `evaluate`, `derivative`, `integral`, `add`, `multiply`.
`evaluate` needs `coeffs` and `x` and returns a number; `derivative`/`integral`
need `coeffs` and return a coefficient list; `add`/`multiply` need `a` and `b`
coefficient lists and return a list. List results also include a `poly` string
(e.g. `"3x² + 1"`). Errors `400` for an unknown op, an empty/non-numeric
coefficient list, or a missing `x`.

### `POST /api/geometry`
Geometry metrics for a shape. Body `{ "shape": "cube", "side": 3 }`; `shape` is
one of `square`, `rectangle`, `circle`, `triangle`, `trapezoid`, `cube`,
`rectangular_prism`, `sphere`, `cylinder`, `cone`, each with its own positive
dimension fields. Returns `{ "shape", "inputs", "geometry": { … }, "result",
"expression" }` where `geometry` holds the area/perimeter (2-D) or
volume/surface (3-D). Errors `400` for an unknown shape or a non-positive
dimension.

### `POST /api/roman`
Roman-numeral conversion. Body `{ "op": "to_roman", "value": 2024 }` or
`{ "op": "from_roman", "value": "MMXXIV" }`. `to_roman` takes an integer in
`1..3999`; `from_roman` takes a canonical numeral string (case-insensitive).
Returns `{ "op", "result", "expression" }`. Errors `400` for an out-of-range
integer, a non-canonical numeral, or invalid characters.

### `GET /`
Serves the calculator UI (`index.html`).
