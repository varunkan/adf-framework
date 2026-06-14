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

## Test

From the app root directory:

```
python3 test_app.py
```

All tests should pass with zero failures. The tests start the server on an
ephemeral port (port 0) in a background thread, exercise the conversion API,
and verify error handling.
