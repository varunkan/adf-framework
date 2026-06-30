"""Composition root — wire adapters from the environment, expose ``app``."""

from __future__ import annotations

from ands_shared import InMemoryEventBus, RedisEventBus, SqliteDb

from .api import build_app
from .config import Settings
from .repository_sqlite import SqliteProjectionRepository
from .service import ReadinessService


def build():
    settings = Settings()
    if settings.db_backend == "postgres":
        from .repository_postgres import PostgresProjectionRepository
        repo = PostgresProjectionRepository(settings.pg_dsn)
    else:
        repo = SqliteProjectionRepository(SqliteDb(settings.sqlite_path))
    bus = (RedisEventBus(settings.redis_url) if settings.bus == "redis"
           else InMemoryEventBus())
    return build_app(ReadinessService(repo, bus).register())


app = build()
