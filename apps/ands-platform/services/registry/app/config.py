"""Environment-driven settings (stdlib only)."""

from __future__ import annotations

import os


class Settings:
    def __init__(self) -> None:
        self.db_backend = os.environ.get("ANDS_DB_BACKEND", "sqlite")
        self.sqlite_path = os.environ.get("ANDS_SQLITE_PATH", "registry.db")
        self.pg_dsn = os.environ.get(
            "ANDS_PG_DSN", "postgresql://ands:ands@localhost:5432/registry")
        self.bus = os.environ.get("ANDS_BUS", "memory")
        self.redis_url = os.environ.get("ANDS_REDIS_URL",
                                        "redis://localhost:6379/0")
        # round-9: identity service for e-signature credential re-auth
        self.identity_url = os.environ.get("IDENTITY_URL",
                                           "http://127.0.0.1:8014")
