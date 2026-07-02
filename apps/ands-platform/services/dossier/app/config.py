"""Environment-driven settings (stdlib only, plus optional .env for local dev)."""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # picks up services/dossier/.env when cwd is the service dir
except ImportError:
    pass


class Settings:
    def __init__(self) -> None:
        self.db_backend = os.environ.get("ANDS_DB_BACKEND", "sqlite")
        self.sqlite_path = os.environ.get("ANDS_SQLITE_PATH", "dossier.db")
        self.pg_dsn = os.environ.get(
            "ANDS_PG_DSN", "postgresql://ands:ands@localhost:5432/dossier")
        self.bus = os.environ.get("ANDS_BUS", "memory")
        self.redis_url = os.environ.get("ANDS_REDIS_URL",
                                        "redis://localhost:6379/0")
        # open-weight LLM (Groq-hosted) for interactive document drafting
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "")
        self.groq_model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
