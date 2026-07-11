CREATE TABLE IF NOT EXISTS calculations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bill REAL NOT NULL,
  tip_percent REAL NOT NULL,
  people INTEGER NOT NULL,
  tip_amount REAL NOT NULL,
  total REAL NOT NULL,
  per_person REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
