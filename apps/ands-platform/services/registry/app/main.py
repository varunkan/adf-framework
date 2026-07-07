"""Composition root — wire adapters from the environment, expose ``app``."""

from __future__ import annotations

from ands_shared import InMemoryEventBus, RedisEventBus, SqliteDb

from .api import build_app
from .config import Settings
from .repository_sqlite import SqliteRegistrationRepository
from .service import RegistryService


def build():
    settings = Settings()
    if settings.db_backend == "postgres":
        from .repository_postgres import PostgresRegistrationRepository
        repo = PostgresRegistrationRepository(settings.pg_dsn)
    else:
        repo = SqliteRegistrationRepository(SqliteDb(settings.sqlite_path))
    bus = (RedisEventBus(settings.redis_url) if settings.bus == "redis"
           else InMemoryEventBus())

    # round-9: the credential re-auth port behind controlled e-signatures —
    # a real HTTP check against the identity service (fail CLOSED: any error
    # or non-200 refuses the signature; never sign on a guess).
    def reauth(email: str, password: str, mfa_code: str = "") -> bool:
        import os
        import httpx
        tok = os.environ.get("ANDS_INTERNAL_TOKEN", "").strip()
        try:
            r = httpx.post(
                settings.identity_url.rstrip("/") + "/api/identity/auth/reauth",
                json={"email": email, "password": password,
                      "mfa_code": mfa_code},
                headers={"X-Internal-Auth": tok} if tok else {},
                timeout=5.0)
            return r.status_code == 200 and bool(r.json().get("ok"))
        except Exception:
            return False

    return build_app(RegistryService(repo, bus, reauth=reauth).register())


app = build()
