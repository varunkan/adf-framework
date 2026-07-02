"""Environment-driven settings (stdlib only)."""

from __future__ import annotations

import os


class Settings:
    def __init__(self) -> None:
        self.db_backend = os.environ.get("ANDS_DB_BACKEND", "sqlite")
        self.sqlite_path = os.environ.get("ANDS_SQLITE_PATH", "journey.db")
        self.pg_dsn = os.environ.get(
            "ANDS_PG_DSN", "postgresql://ands:ands@localhost:5432/journey")
        self.bus = os.environ.get("ANDS_BUS", "memory")
        self.redis_url = os.environ.get("ANDS_REDIS_URL",
                                        "redis://localhost:6379/0")
        # The dossier service (eCTD engine) the journey composes; empty → the
        # journey falls back to its own flat content model.
        self.dossier_url = os.environ.get("DOSSIER_URL", "")
        # Governance (QA review + e-signature) and transmission (FDA-ESG/CESG)
        # services; empty -> those stages run as the guided simulation.
        self.governance_url = os.environ.get("GOVERNANCE_URL", "")
        self.transmission_url = os.environ.get("TRANSMISSION_URL", "")
