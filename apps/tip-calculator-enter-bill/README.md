# Tip Calculator — `tip-calculator-enter-bill`

A self-contained tip calculator web app. Enter a bill amount and a tip percent,
get the tip and total. Backend uses only the Python 3 standard library; the
frontend is a single static HTML file with vanilla JS.

## Requirements

- Python 3 (standard library only — no pip installs).

## Run

```bash
python3 server.py
```

The server starts on port 8000. Open:

```
http://127.0.0.1:8000
```

Enter a bill amount and tip percent, then click **Calculate**.

## API

### POST `/api/tip`

Request body (JSON):

```json
{ "bill": 100, "tip_percent": 15 }
```

Success response — `200`:

```json
{ "tip": 15.0, "total": 115.0 }
```

Validation errors return `400` with `{ "error": "..." }`:

- `bill` must be a non-negative number
- `tip_percent` must be a number between 0 and 100
- both fields are required

Results are rounded to two decimal places.

### GET `/`

Serves the frontend `index.html`.

## Test

```bash
python3 test_app.py
```

All tests must pass with zero failures. The test suite starts the server on an
ephemeral port (port 0) in a background thread, exercises the API and the
calculation logic, and shuts the server down afterward.
