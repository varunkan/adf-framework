"""Thread-safe SQLite base for dev/test repository adapters.

A single guarded connection with a row factory and parameterized helpers — the
production repositories use Postgres (pg8000) instead, but every service's
SQLite adapter shares this one correct, injection-safe implementation. Ported
from the monolith's ``_SqliteStore`` plumbing.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager


class SqliteDb:
    """One thread-guarded connection + parameterized query helpers.

    The default helpers (``execute``/``fetchone``/``fetchall``) each acquire the
    lock and — for writes — commit per statement, which is correct for the
    single-statement mutations most callers do. When several statements must
    commit ATOMICALLY (all-or-nothing — e.g. WS3's ledger write + state
    mutation), open a :meth:`transaction` scope: it holds the lock for the whole
    block, suppresses the per-statement commit, and commits ONCE at the end
    (rolling back on any exception). The scope is opt-in; existing per-statement
    usage in other services is unchanged.
    """

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # RLock so a transaction scope can hold the lock while the statements it
        # runs re-enter execute()/fetchone() without deadlocking.
        self._lock = threading.RLock()
        # Set while inside a transaction() scope: statements executed then must
        # NOT re-acquire-and-commit on their own — the scope owns the commit.
        self._in_txn = False

    def executescript(self, script: str) -> None:
        with self._lock:
            self._conn.executescript(script)
            self._conn.commit()

    def execute(self, sql: str, params: tuple = ()):
        """Run a write/DDL statement under the lock, commit, return the cursor.

        Inside a :meth:`transaction` scope the commit is deferred to the scope
        (one atomic commit for the whole block)."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            if not self._in_txn:
                self._conn.commit()
            return cur

    def fetchone(self, sql: str, params: tuple = ()):
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    @contextmanager
    def transaction(self):
        """Run multiple statements atomically: hold the lock for the whole
        block, defer commits, and commit ONCE on clean exit — rolling back the
        entire block if the body raises. Not nestable (a single flat scope).

        Statements run through the normal ``execute``/``fetchone``/``fetchall``
        helpers inside the block: the re-entrant lock lets them run without
        re-acquiring, and ``_in_txn`` makes their writes defer to this scope's
        single commit. Either every statement in the block persists or none do —
        this is what lets a caller pair a durable audit write with a state
        mutation so there is no 'mutation without a record' / 'phantom record'
        window."""
        with self._lock:
            if self._in_txn:
                # Already inside an atomic scope — just run the body; the outer
                # scope owns the commit/rollback. (Defensive; callers use flat
                # scopes.)
                yield self
                return
            self._in_txn = True
            try:
                yield self
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()
            finally:
                self._in_txn = False

    def close(self) -> None:
        with self._lock:
            self._conn.close()
