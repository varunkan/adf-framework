# Temperature Converter (Celsius ⇄ Fahrenheit)

A self-contained web app that converts between Celsius and Fahrenheit.
Backend uses only the Python 3 standard library. Frontend is a single
static HTML file with inline CSS and vanilla JavaScript.

## Requirements

- Python 3.7+ (standard library only — no pip installs)

## Run

From the app root directory:

```
python3 server.py
```

The server starts on port 8000. Open your browser at:

```
http://127.0.0.1:8000/
```

Enter a value, choose a direction (Celsius → Fahrenheit or
Fahrenheit → Celsius), and click **Convert**.

## API

### POST /api/convert

Request body (JSON):

```json
{ "value": 100, "direction": "c2f" }
```

- `value`: a number (or numeric string).
- `direction`: `"c2f"` (Celsius to Fahrenheit) or `"f2c"` (Fahrenheit to Celsius).

Success response (200):

```json
{ "input": 100.0, "direction": "c2f", "result": 212.0, "unit": "F" }
```

Error responses (400) for invalid/missing `value` or `direction`.

Formulas used:
- Celsius → Fahrenheit: `F = C × 9/5 + 32`
- Fahrenheit → Celsius: `C = (F − 32) × 5/9`

Temperature also supports Kelvin (`c2k`, `k2c`, `f2k`, `k2f`).

### POST /api/temperature/all

Convert one temperature into **every** scale (C/F/K) at once.

```json
{ "value": 100, "from": "C" }
```

Response: `{ "input": 100.0, "from": "C", "category": "temperature", "results": { "C": 100.0, "F": 212.0, "K": 373.15 } }`

### POST /api/units

General linear-factor conversion. Categories: **length**, **mass**, **volume**,
**area**, **speed**, **time**, **data**, **pressure**, **energy**, **angle**,
**power**, **force**, **frequency**, **illuminance**. Both units must share a
category.

```json
{ "value": 1, "from": "acre", "to": "m2" }
```

Response: `{ "input": 1.0, "from": "acre", "to": "m2", "category": "area", "result": 4046.856422 }`

### POST /api/units/all

Convert one value into **every** unit of its category at once.

```json
{ "value": 1, "from": "h" }
```

Response: `{ "input": 1.0, "from": "h", "category": "time", "results": { "ms": 3600000.0, "s": 3600.0, ... } }`

### POST /api/units/batch

Convert a list of independent conversions in one request. A bad item never
fails the others — each result is flagged `ok: true|false`.

```json
{ "conversions": [ { "value": 1, "from": "kw", "to": "w" }, { "value": 1, "from": "kgf", "to": "n" } ] }
```

Response: `{ "count": 2, "ok_count": 2, "results": [ { "ok": true, ... }, ... ] }`

### POST /api/fuel

Fuel-economy conversion between `mpg` (US), `mpgimp` (imperial), `kmpl`, and
`l100km`. Unlike linear-factor units, consumption (`l100km`) is the **reciprocal**
of efficiency, so this routes through a km/L base. A value of `0 l100km` is an
undefined (infinite) economy and returns 400.

```json
{ "value": 30, "from": "mpg", "to": "l100km" }
```

Response: `{ "input": 30.0, "from": "mpg", "to": "l100km", "category": "fuel", "result": 7.840486 }`

### POST /api/base

Convert an integer between number bases (`bin`/`oct`/`dec`/`hex`). The value is a
string of digits in the source radix; an optional `0x`/`0o`/`0b` prefix is
tolerated. The result is the same integer rendered in the target radix.

```json
{ "value": "ff", "from": "hex", "to": "dec" }
```

Response: `{ "input": "ff", "from": "hex", "to": "dec", "category": "base", "result": "255" }`

### POST /api/roman

Convert between an Arabic integer and a Roman numeral. Classical numerals cover
**1–3999** only (no zero or negative), and only the canonical form is accepted —
`"IIII"` is rejected in favour of `"IV"`. Out-of-range integers, malformed
numerals, and unknown notations return 400.

```json
{ "value": 2024, "from": "arabic", "to": "roman" }
```

Response: `{ "input": "2024", "from": "arabic", "to": "roman", "category": "roman", "result": "MMXXIV" }`

### POST /api/words

Convert between an Arabic integer and its English number words — the lexical
sibling of `/api/base` and `/api/roman`. Both directions route through a Python
integer, so `2024` ⇄ `"two thousand twenty-four"`. The U.S. short scale covers
roughly ±10¹⁵ (up to "trillion"); zero and negatives are supported. Only
canonical phrasings are accepted on the way in — `"ten hundred"`, `"two two"`,
and `"negative zero"` are rejected — though a hyphen-free `"forty two"` and a
British `"one hundred and one"` are tolerated. An out-of-range integer, a
malformed phrase, or an unknown notation returns 400.

```json
{ "value": 2024, "from": "arabic", "to": "words" }
```

Response: `{ "input": "2024", "from": "arabic", "to": "words", "category": "words", "result": "two thousand twenty-four" }`

The linear-factor categories also include **acceleration**, **density**, and
**flowrate** via `/api/units`, plus the electrical trio **voltage** (`v`/`mv`/`kv`/`uv`),
**current** (`a`/`ma`/`ka`/`ua`), and **resistance** (`ohm`/`mohm`/`kohm`/`megohm`); the
electromagnetic family **capacitance** (`farad`…`pfarad`), **inductance** (`henry`…`nhenry`),
**magflux** (`weber`/`maxwell`), and **magfluxdensity** (`tesla`/`gauss`); and a **typography**
family (`point`/`pica`/`px`/`twip`, where 1 pica = 12 pt, 1 px = 0.75 pt, 1 twip = 0.05 pt).

### POST /api/color

Convert a colour between `hex`, `rgb`, and `hsl` notations. Like number bases
and Roman numerals, a colour is one underlying value (a point in RGB space) in
different clothes, so every input routes through a canonical `(r, g, b)` byte
triple and is re-rendered in the target notation. Hex accepts the `#rrggbb` and
`#rgb` shorthand forms (the `#` is optional); rgb accepts `rgb(r, g, b)`, `r,g,b`,
or `r g b` with channels in 0–255; hsl accepts `hsl(h, s%, l%)` with hue 0–360
and saturation/lightness 0–100. A malformed or out-of-range colour, or an
unknown notation, returns 400.

```json
{ "value": "#ff0000", "from": "hex", "to": "hsl" }
```

Response: `{ "input": "#ff0000", "from": "hex", "to": "hsl", "category": "color", "result": "hsl(0, 100%, 50%)" }`

### GET /api/units

Returns the full catalogue of supported categories and their units.

## Test

From the app root directory:

```
python3 test_app.py
```

All tests should pass with zero failures. The tests start the server on an
ephemeral port (port 0) in a background thread, exercise the conversion API,
and verify error handling.
