#!/usr/bin/env python3
"""Unit tests for app_data.py — the read-only browser for a generated app's live
SQLite DB (the dashboard Data tab). Visibility Lovable hides: see exactly what your
app persisted. Read-only + injection-safe (only real tables, never raw SQL).

    python3 scripts/orch/test_app_data.py
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_data  # noqa: E402


def _seed(app):
    db = os.path.join(app, "data.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
    con.executemany("INSERT INTO notes (body) VALUES (?)",
                    [("hello",), ("world",)])
    con.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    return db


class ListTables(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        self.db = _seed(self.app)

    def test_lists_user_tables_with_row_counts(self):
        tables = {t["name"]: t["rows"] for t in app_data.list_tables(self.db)}
        self.assertEqual(tables["notes"], 2)
        self.assertIn("tags", tables)
        # internal sqlite_* tables are hidden
        self.assertNotIn("sqlite_sequence", tables)


class TableRows(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        self.db = _seed(self.app)

    def test_returns_columns_and_rows(self):
        r = app_data.table_rows(self.db, "notes", 100)
        self.assertEqual(r["columns"], ["id", "body"])
        self.assertEqual(len(r["rows"]), 2)
        self.assertIn("hello", [row[1] for row in r["rows"]])
        self.assertFalse(r["truncated"])

    def test_limit_truncates_and_flags(self):
        con = sqlite3.connect(self.db)
        con.executemany("INSERT INTO notes (body) VALUES (?)",
                        [(f"n{i}",) for i in range(10)])
        con.commit()
        con.close()
        r = app_data.table_rows(self.db, "notes", 3)
        self.assertEqual(len(r["rows"]), 3)
        self.assertTrue(r["truncated"])

    def test_unknown_or_injected_table_is_none(self):
        # only REAL tables are browsable — an injection attempt resolves to None,
        # never executed as SQL.
        self.assertIsNone(app_data.table_rows(self.db, "nope", 100))
        self.assertIsNone(
            app_data.table_rows(self.db, "notes; DROP TABLE notes;--", 100))
        # the table is intact after the injection attempt
        self.assertEqual(app_data.table_rows(self.db, "notes", 100)["rows"]
                         .__len__(), 2)


class ReadOnly(unittest.TestCase):
    def test_connection_cannot_write(self):
        app = tempfile.mkdtemp()
        db = _seed(app)
        con = app_data._connect_ro(db)
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("INSERT INTO notes (body) VALUES ('x')")
        con.close()


class Cli(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        self.db = _seed(self.app)

    def _run(self, *args):
        here = os.path.dirname(os.path.abspath(__file__))
        return subprocess.run(
            [sys.executable, os.path.join(here, "app_data.py"), *args],
            capture_output=True, text=True)

    def test_json_lists_tables(self):
        import json
        r = self._run("--app", self.app, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["has_db"])
        self.assertIn("notes", [t["name"] for t in out["tables"]])

    def test_json_table_rows(self):
        import json
        r = self._run("--app", self.app, "--table", "notes", "--json")
        out = json.loads(r.stdout)
        self.assertEqual(out["columns"], ["id", "body"])

    def test_json_no_db(self):
        import json
        r = self._run("--app", tempfile.mkdtemp(), "--json")
        out = json.loads(r.stdout)
        self.assertFalse(out["has_db"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
