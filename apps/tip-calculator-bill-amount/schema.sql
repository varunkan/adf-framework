-- Storage for the Python app under test (server.py). Columns mirror the
-- Python domain's calculate_tip() output keys so a result round-trips into the
-- table without renaming. server.py applies this schema on first connect.
CREATE TABLE IF NOT EXISTS tip_calculations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bill REAL NOT NULL,
  tip_percent REAL NOT NULL,
  people INTEGER NOT NULL,
  tip REAL NOT NULL,
  total REAL NOT NULL,
  total_per_person REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
