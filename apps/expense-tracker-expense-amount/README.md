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

## Features

- Add / edit / delete expenses (amount, category, optional note, date)
- Running total, entry count, average per entry, top-spend category, and largest expense
- Per-category horizontal bar chart and a per-month breakdown
- Filter the list by category and/or an inclusive date range
- Search expenses by note text (case-insensitive substring)
- Sort the list server-side by date, amount, category, or note (ascending/descending)
- Optional monthly budget with a live "remaining / over budget" indicator
- One-click CSV export of all expenses, plus CSV import (round-trips the export)
- All data persists to backend JSON files (`expenses.json`, `budget.json`)

## API

- `GET /` — serves `index.html`
- `GET /api/expenses` — returns a summary `{"expenses":[...], "total", "count",
  "average", "breakdown", "top_category", "largest", "budget", "remaining",
  "over_budget"}`. `top_category` is the highest-spend category (ties broken
  alphabetically, `null` when nothing is spent) and `largest` is the
  single biggest expense object (`null` when the list is empty).
  - optional query params: `category=<Food|...|All>`, `start=YYYY-MM-DD`,
    `end=YYYY-MM-DD` (inclusive), `q=<text>` (case-insensitive note search),
    `sort=<date|amount|category|note>`, `order=<asc|desc>` (default `asc`).
    Invalid category/date/sort/order values return `400`.
- `POST /api/expenses` — body `{"amount":12.5,"category":"Food","note":"lunch","date":"2024-01-01"}`
  - returns `201 {...expense}` on success
  - returns `400 {"error": ...}` for invalid amount, category, or date
- `PUT /api/expenses/<id>` — partial update; provided fields override, others
  keep their value. `200` on success, `400` on invalid field, `404` if missing.
- `DELETE /api/expenses/<id>` — deletes an expense; `200` on success, `404` if not found
- `GET /api/budget` — returns `{"budget": <number|null>}`
- `PUT /api/budget` — body `{"budget": 500}` to set, `{"budget": null}` to clear.
  Negative or non-numeric values return `400`.
- `GET /api/summary/monthly` — returns `{"monthly": {"YYYY-MM": total, ...}}`
- `GET /api/expenses.csv` — downloads all expenses as a CSV attachment
- `POST /api/expenses/import` — body `{"csv": "<csv text>"}`. Parses a CSV with a
  header row (columns matched case-insensitively; `date`, `category`, `amount`,
  `note`, and an optional semicolon-separated `tags` are read, any `id` column is
  ignored). Each row is validated with the same rules as `POST /api/expenses`;
  invalid rows are skipped, not fatal. Returns `200 {"imported": N, "skipped": M,
  "errors": [{"row": <1-based>, "error": ...}], "expenses": [...]}`. A non-string
  or missing `csv` field returns `400`. Re-importing an exported file is safe —
  every imported row receives a fresh id.

Valid categories: `Food`, `Transport`, `Bills`, `Fun`, `Other`.

## Test

```bash
python3 test_app.py
```

The test suite starts the server on an ephemeral port in a background thread and
verifies adding, listing, deleting, validation errors, persistence, and the
served frontend. It uses a temporary data file so it never touches your real
`expenses.json`. All tests must pass with zero failures.
