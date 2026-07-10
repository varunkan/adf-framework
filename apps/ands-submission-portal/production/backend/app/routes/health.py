from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "ands-portal-api"}
