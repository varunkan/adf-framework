"""Composition root — wire adapters from the environment and expose ``app``.

``uvicorn app.main:app`` runs the service. The backend/bus are chosen by env so
the same image runs over SQLite+in-memory-bus locally or Postgres+Redis in prod.
"""

from __future__ import annotations

from ands_shared import InMemoryEventBus, RedisEventBus, SqliteDb

from .api import build_app
from .config import Settings
from .repository_sqlite import SqliteCollaborationRepository
from .service import CollaborationService


def build():
    settings = Settings()

    if settings.db_backend == "postgres":
        from .repository_postgres import PostgresCollaborationRepository
        repo = PostgresCollaborationRepository(settings.pg_dsn)
    else:
        repo = SqliteCollaborationRepository(SqliteDb(settings.sqlite_path))

    bus = (RedisEventBus(settings.redis_url) if settings.bus == "redis"
           else InMemoryEventBus())

    service = CollaborationService(repo, bus).register()
    return build_app(service)


app = build()
