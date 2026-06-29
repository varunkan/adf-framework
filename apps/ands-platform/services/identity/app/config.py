"""Environment-driven settings (stdlib only)."""

from __future__ import annotations

import os


class Settings:
    def __init__(self) -> None:
        self.db_backend = os.environ.get("ANDS_DB_BACKEND", "sqlite")
        self.sqlite_path = os.environ.get("ANDS_SQLITE_PATH", "identity.db")
        self.pg_dsn = os.environ.get(
            "ANDS_PG_DSN", "postgresql://ands:ands@localhost:5432/identity")
        self.bus = os.environ.get("ANDS_BUS", "memory")
        self.redis_url = os.environ.get("ANDS_REDIS_URL",
                                        "redis://localhost:6379/0")
        self.owner_email = os.environ.get("ANDS_OWNER_EMAIL",
                                          "owner@ands.platform")
        self.owner_password = os.environ.get("ANDS_OWNER_PASSWORD", "change-me")
