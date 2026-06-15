#!/usr/bin/env python3
"""Read-only browser for a generated app's live SQLite database — the dashboard
**Data tab**. ADF owns the data layer (SQLite), so it can show you exactly what
your app persisted; Lovable hides the DB behind a hosted Postgres.

Safety: opens the DB **read-only** (`mode=ro`) and only ever browses tables that
actually exist in `sqlite_master` — a table name is never interpolated into SQL
unless it matched a real table first, so a crafted name can't inject.

    python3 app_data.py --app apps/<id> [--table NAME] [--limit N] [--json]
"""
import argparse
import json
import os
import sqlite3
import sys

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
DB_NAME = "data.db"  # matches templates/react-vite-sqlite/server/db.mjs


def db_path_for(app_dir):
    return os.path.join(app_dir, DB_NAME)


def _connect_ro(db_path):
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _quote(ident):
    return '"' + ident.replace('"', '""') + '"'


def list_tables(db_path):
    """User tables (no sqlite_* internals) with row counts."""
    con = _connect_ro(db_path)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out = []
        for n in names:
            count = con.execute(f"SELECT COUNT(*) FROM {_quote(n)}").fetchone()[0]
            out.append({"name": n, "rows": count})
        return out
    finally:
        con.close()


def table_rows(db_path, table, limit):
    """Rows of `table` (capped at `limit`), or None if no such real table exists.
    The existence check is what makes interpolation safe."""
    con = _connect_ro(db_path)
    try:
        real = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if table not in real:
            return None
        cur = con.execute(f"SELECT * FROM {_quote(table)} LIMIT {int(limit) + 1}")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        truncated = len(rows) > limit
        return {
            "table": table,
            "columns": cols,
            "rows": [list(r) for r in rows[:limit]],
            "truncated": truncated,
        }
    finally:
        con.close()


def _main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only SQLite browser (Data tab)")
    ap.add_argument("--app", required=True, help="app dir (apps/<id>)")
    ap.add_argument("--db", help="explicit DB path (defaults to <app>/data.db)")
    ap.add_argument("--table", help="browse one table's rows")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    db_path = args.db or db_path_for(args.app)
    limit = max(1, min(args.limit, MAX_LIMIT))

    if not os.path.isfile(db_path):
        report = {"has_db": False, "db": db_path}
    elif args.table:
        res = table_rows(db_path, args.table, limit)
        report = {"has_db": True, "db": db_path, "error": f"no such table: {args.table}"} \
            if res is None else {"has_db": True, "db": db_path, **res}
    else:
        report = {"has_db": True, "db": db_path, "tables": list_tables(db_path)}

    if args.json:
        print(json.dumps(report, default=str))
    else:
        if not report["has_db"]:
            print(f"no database at {db_path}")
        elif args.table:
            print(report)
        else:
            for t in report["tables"]:
                print(f"  {t['name']}: {t['rows']} rows")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
