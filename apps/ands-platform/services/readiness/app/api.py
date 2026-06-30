"""FastAPI surface for the readiness BFF."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from ands_shared import create_app

from .service import ReadinessService


def build_app(service: ReadinessService) -> FastAPI:
    app = create_app(title="readiness",
                     description="ANDS event-driven readiness dashboard (REQ-071)")
    router = APIRouter(prefix="/api/readiness", tags=["readiness"])

    @router.get("/dashboard")
    def dashboard():
        return service.dashboard()

    @router.get("/dossier/{dossier_id}")
    def dossier(dossier_id: str):
        return service.get(dossier_id)

    app.include_router(router)
    return app
