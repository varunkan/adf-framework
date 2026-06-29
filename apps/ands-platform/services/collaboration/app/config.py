"""Environment-driven settings (stdlib only — no extra deps)."""

from __future__ import annotations

import os


class Settings:
    def __init__(self) -> None:
        # persistence: "sqlite" (dev/test) | "postgres" (prod)
        self.db_backend = os.environ.get("ANDS_DB_BACKEND", "sqlite")
        self.sqlite_path = os.environ.get("ANDS_SQLITE_PATH", "collaboration.db")
        self.pg_dsn = os.environ.get(
            "ANDS_PG_DSN",
            "postgresql://ands:ands@localhost:5432/collaboration")
        # event bus: "memory" (dev/test) | "redis" (prod)
        self.bus = os.environ.get("ANDS_BUS", "memory")
        self.redis_url = os.environ.get("ANDS_REDIS_URL",
                                        "redis://localhost:6379/0")
