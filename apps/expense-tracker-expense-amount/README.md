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
- Filter the list by category, an inclusive date range, and/or an inclusive amount range (min/max)
- Search expenses by note text (case-insensitive substring)
- Per-category monthly pivot (how each category trends month over month)
- Sort the list server-side by date, amount, category, or note (ascending/descending)
- Optional monthly budget with a live "remaining / over budget" indicator
- Budget pacing: project month-end spend from the rate so far and check whether you're on track, with a safe-to-spend-per-remaining-day allowance
- One-click CSV export of all expenses, plus CSV import (round-trips the export)
- Spending insights: weekly (ISO-week) spend, per-category share of total, and a top-N largest-spends list
- Bulk-delete many expenses in a single request
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
    `min_amount=<number>`, `max_amount=<number>` (inclusive amount bounds),
    `sort=<date|amount|category|note>`, `order=<asc|desc>` (default `asc`).
    Invalid category/date/sort/order/amount values return `400`, as does a
    `min_amount` greater than `max_amount`.
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
- `GET /api/summary/category-monthly` — returns
  `{"category_monthly": {"Food": {"YYYY-MM": total, ...}, ...}}`, pivoting spend
  by category then month (categories and months sorted ascending)
- `GET /api/summary/weekly` — returns `{"weekly": {"YYYY-Www": total, ...}}`,
  spend grouped by ISO week (sorted ascending; an ISO week may straddle two
  calendar months)
- `GET /api/summary/percentages` — returns `{"percentages": {"total": <number>,
  "categories": {"Food": {"spent": <number>, "percent": <0..100>}, ...}}}`, each
  category's share of total spend (every category present; `0.0` when nothing is
  spent — no divide-by-zero)
- `GET /api/summary/top?n=5` — returns `{"top": [...]}`, the `n` highest-amount
  expenses (largest first; ties broken by date then id). `n` defaults to `5`,
  is clamped to the available count, and must be an integer `>= 1` (else `400`)
- `POST /api/expenses/bulk-delete` — body `{"ids": ["id1", "id2", ...]}`. Deletes
  all matching expenses in one pass and returns `{"deleted": [...], "not_found":
  [...], "count": N}`. Ids are de-duplicated in request order; an empty/missing
  list is a no-op (not an error); a non-list `ids` returns `400`.
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
