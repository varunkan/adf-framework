from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from .config import get_settings
from .storage.control_plane import ControlPlaneStore
from .storage.postgres import PostgresStore
from .storage.s3 import PackageStorage


_control_plane: ControlPlaneStore | None = None


def get_store() -> PostgresStore:
    settings = get_settings()
    return PostgresStore(settings.database_url)


def get_control_plane() -> ControlPlaneStore:
    global _control_plane
    if _control_plane is None:
        settings = get_settings()
        _control_plane = ControlPlaneStore(settings.database_url)
    return _control_plane


def get_package_storage() -> PackageStorage | None:
    settings = get_settings()
    if not settings.s3_enabled:
        return None
    return PackageStorage(
        endpoint=settings.s3_endpoint,
        bucket=settings.s3_bucket,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        region=settings.s3_region,
    )


def require_tenant_session(
    authorization: Annotated[str | None, Header()] = None,
    cp: ControlPlaneStore = Depends(get_control_plane),
) -> dict:
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    session = cp.resolve_session(token)
    if session is None or not session.get("tenant_id"):
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    return session


def reset_caches() -> None:
    global _control_plane
    _control_plane = None
    get_settings.cache_clear()
