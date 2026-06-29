"""Thread-safe SQLite base for dev/test repository adapters.

A single guarded connection with a row factory and parameterized helpers — the
production repositories use Postgres (pg8000) instead, but every service's
SQLite adapter shares this one correct, injection-safe implementation. Ported
from the monolith's ``_SqliteStore`` plumbing.
"""

from __future__ import annotations

import sqlite3
import threading


class SqliteDb:
    """One thread-guarded connection + parameterized query helpers."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()

    def executescript(self, script: str) -> None:
        with self._lock:
            self._conn.executescript(script)
            self._conn.commit()

    def execute(self, sql: str, params: tuple = ()):
        """Run a write/DDL statement under the lock, commit, return the cursor."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def fetchone(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
