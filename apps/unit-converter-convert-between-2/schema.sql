CREATE TABLE IF NOT EXISTS conversions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  direction TEXT NOT NULL,
  input_value REAL NOT NULL,
  output_value REAL NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
