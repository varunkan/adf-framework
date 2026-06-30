"""Composition root — wire adapters from the environment, expose ``app``."""

from __future__ import annotations

from ands_shared import InMemoryEventBus, RedisEventBus, SqliteDb

from .api import build_app
from .config import Settings
from .repository_sqlite import SqliteAuditRepository
from .service import GovernanceService


def build():
    settings = Settings()
    if settings.db_backend == "postgres":
        from .repository_postgres import PostgresAuditRepository
        repo = PostgresAuditRepository(settings.pg_dsn)
    else:
        repo = SqliteAuditRepository(SqliteDb(settings.sqlite_path))
    bus = (RedisEventBus(settings.redis_url) if settings.bus == "redis"
           else InMemoryEventBus())
    return build_app(GovernanceService(repo, bus).register())


app = build()
