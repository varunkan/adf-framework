"""Composition root — wire adapters from the environment, expose ``app``."""

from __future__ import annotations

from ands_shared import InMemoryEventBus, RedisEventBus, SqliteDb

from .api import build_app
from .config import Settings
from .repository_sqlite import SqliteIdentityRepository
from .service import IdentityService


def build():
    settings = Settings()
    if settings.db_backend == "postgres":
        from .repository_postgres import PostgresIdentityRepository
        repo = PostgresIdentityRepository(settings.pg_dsn)
    else:
        repo = SqliteIdentityRepository(SqliteDb(settings.sqlite_path))
    bus = (RedisEventBus(settings.redis_url) if settings.bus == "redis"
           else InMemoryEventBus())
    service = IdentityService(repo, bus).register()
    service.ensure_owner(settings.owner_email, settings.owner_password)
    return build_app(service)


app = build()
