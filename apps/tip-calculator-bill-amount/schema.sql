CREATE TABLE IF NOT EXISTS tip_calculations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bill_amount REAL NOT NULL,
  tip_percent REAL NOT NULL,
  people INTEGER NOT NULL,
  tip_amount REAL NOT NULL,
  total_amount REAL NOT NULL,
  per_person REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
