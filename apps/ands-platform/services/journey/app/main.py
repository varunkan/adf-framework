"""Composition root — wire adapters from the environment, expose ``app``."""

from __future__ import annotations

from ands_shared import InMemoryEventBus, RedisEventBus, SqliteDb

from .api import build_app
from .config import Settings
from .repository_sqlite import SqliteSessionRepository
from .service import JourneyService


def build():
    settings = Settings()
    if settings.db_backend == "postgres":
        from .repository_postgres import PostgresSessionRepository
        repo = PostgresSessionRepository(settings.pg_dsn)
    else:
        repo = SqliteSessionRepository(SqliteDb(settings.sqlite_path))
    bus = (RedisEventBus(settings.redis_url) if settings.bus == "redis"
           else InMemoryEventBus())
    dossier = None
    if settings.dossier_url:
        from .dossier_client import HttpDossierClient
        dossier = HttpDossierClient(settings.dossier_url)
    return build_app(JourneyService(repo, bus, dossier=dossier))


app = build()
