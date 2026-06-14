# Expense Tracker

A self-contained expense tracker. Add expenses with amount, category, optional
note, and date. View them in a filterable list, delete entries, and see the
running total plus a per-category horizontal bar chart. All data persists to a
backend JSON file (`expenses.json`).

## Requirements

- Python 3 (standard library only — no pip installs)

## Run

```bash
python3 server.py
```

Then open your browser at:

```
http://127.0.0.1:8000
```

The server serves the frontend and the JSON API on the same port. Data is
stored in `expenses.json` next to `server.py` and survives page refreshes and
server restarts.

## API

- `GET /` — serves `index.html`
- `GET /api/expenses` — returns `{"expenses": [...]}`
- `POST /api/expenses` — body `{"amount":12.5,"category":"Food","note":"lunch","date":"2024-01-01"}`
  - returns `200 {"expense": {...}}` on success
  - returns `400 {"error": ...}` for invalid amount or category
- `DELETE /api/expenses/<id>` — deletes an expense; `200` on success, `404` if not found

Valid categories: `Food`, `Transport`, `Bills`, `Fun`, `Other`.

## Test

```bash
python3 test_app.py
```

The test suite starts the server on an ephemeral port in a background thread and
verifies adding, listing, deleting, validation errors, persistence, and the
served frontend. It uses a temporary data file so it never touches your real
`expenses.json`. All tests must pass with zero failures.
