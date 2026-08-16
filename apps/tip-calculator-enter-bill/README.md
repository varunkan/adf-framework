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

### POST `/api/split`

Split a bill across payers. Body: `{ "bill", "tip_percent", "people", "round_total", "weights" }`.
Returns tip, total, per-person amounts and an exact `shares` list whose cents
sum to the total. Pass `weights` (a list of positive numbers, e.g. `[1, 1, 2]`)
to split **unevenly** — `people` is then taken from the weight count.

### POST `/api/tax`

Tax-aware totals. Body: `{ "bill", "tip_percent", "tax_percent", "tip_on" }`
where `bill` is the pre-tax subtotal and `tip_on` is `"pretax"` (default) or
`"posttax"`. Returns `subtotal`, `tax`, `tip` and `total`.

### POST `/api/suggest`

Suggest a tip from a 1–5 service rating. Body: `{ "bill", "rating" }`.
Ratings map to conventional percents (1→10%, 2→15%, 3→18%, 4→20%, 5→25%) and
the response carries the rating `label`, `tip_percent`, `tip` and `total`.

### POST `/api/presets`

Compare several tip percentages for one bill. Body: `{ "bill", "percents" }`
(defaults to `[10, 15, 18, 20, 25]`).

### POST `/api/reverse`

Derive the tip percent needed to hit a target total. Body: `{ "bill", "total" }`.

### GET `/`

Serves the frontend `index.html`.

## Test

```bash
python3 test_app.py
```

All tests must pass with zero failures. The test suite starts the server on an
ephemeral port (port 0) in a background thread, exercises the API and the
calculation logic, and shuts the server down afterward.
