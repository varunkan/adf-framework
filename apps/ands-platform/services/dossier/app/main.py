"""Composition root — wire adapters from the environment, expose ``app``."""

from __future__ import annotations

from ands_shared import InMemoryEventBus, RedisEventBus, SqliteDb

from .api import build_app
from .config import Settings
from .repository_sqlite import SqliteDossierRepository
from .service import DossierService


def build():
    settings = Settings()
    if settings.db_backend == "postgres":
        from .repository_postgres import PostgresDossierRepository
        repo = PostgresDossierRepository(settings.pg_dsn)
    else:
        repo = SqliteDossierRepository(SqliteDb(settings.sqlite_path))
    bus = (RedisEventBus(settings.redis_url) if settings.bus == "redis"
           else InMemoryEventBus())
    # TIER3-SOD-ENFORCE: wire the workspace-policy read (require_sod) when the
    # identity service URL is configured; otherwise the sign path honors only
    # the manifest's own enforce flag.
    policy = None
    if settings.identity_url:
        from .policy_client import HttpWorkspacePolicyClient
        policy = HttpWorkspacePolicyClient(settings.identity_url)
    return build_app(DossierService(repo, bus, policy=policy).register())


app = build()
