# Calculator

A self-contained calculator web app. Python standard-library HTTP server +
single static HTML frontend (inline CSS + vanilla JS). No third-party
dependencies, no build step.

## Features

- Arithmetic: add, subtract, multiply, divide, power, modulo, integer-divide,
  gcd, lcm
- Scientific unary ops: sqrt, cbrt, square, cube, reciprocal, abs, factorial,
  sin/cos/tan, asin/acos/atan, sinh/cosh/tanh, ln/log10/log2, exp, floor, ceil,
  round, sign, deg↔rad, percent
- Free-form expression evaluation (safe recursive-descent parser, no `eval`)
  with constants `pi`, `e`, `tau`, `phi`
- Memory register (MC / MR / M+ / M− / MS), persisted to `memory.json`
- Server-side computation via JSON API
- Division-by-zero and invalid-input validation
- Number-base converter (bin / oct / dec / hex, signed)
- Descriptive statistics (count, sum, mean, median, mode, min, max, range,
  sample stdev/variance) over a list of numbers
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

### `GET /`
Serves the calculator UI (`index.html`).
