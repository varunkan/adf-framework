"""Environment-driven settings (stdlib only)."""

from __future__ import annotations

import os


class Settings:
    def __init__(self) -> None:
        self.db_backend = os.environ.get("ANDS_DB_BACKEND", "sqlite")
        self.sqlite_path = os.environ.get("ANDS_SQLITE_PATH", "dossier.db")
        self.pg_dsn = os.environ.get(
            "ANDS_PG_DSN", "postgresql://ands:ands@localhost:5432/dossier")
        self.bus = os.environ.get("ANDS_BUS", "memory")
        self.redis_url = os.environ.get("ANDS_REDIS_URL",
                                        "redis://localhost:6379/0")
