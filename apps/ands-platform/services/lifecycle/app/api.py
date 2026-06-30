"""FastAPI surface for the lifecycle service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Query

from ands_shared import create_app

from .models import (CorrespondenceIn, DeadlineIn, NoticeIn, StartIn,
                     TransitionIn)
from .service import LifecycleService


def build_app(service: LifecycleService) -> FastAPI:
    app = create_app(title="lifecycle",
                     description="ANDS DSTS lifecycle + HC deadline calendar")
    router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])

    @router.post("/start", status_code=201)
    def start(body: StartIn):
        return service.start_lifecycle(body.model_dump())

    @router.post("/transition")
    def transition(body: TransitionIn):
        return service.transition(body.model_dump())

    @router.post("/notice")
    def ingest_notice(body: NoticeIn):
        return service.ingest_notice(body.model_dump())

    @router.get("/service-standard")
    def service_standard(submission_type: str = "ANDS"):
        return service.service_standard(submission_type)

    @router.post("/deadline")
    def deadline(body: DeadlineIn):
        return service.deadline(body.model_dump())

    @router.get("/holidays")
    def holidays(year: int = Query(...)):
        return service.holidays(year)

    @router.get("/state/{dossier_id}")
    def state(dossier_id: str):
        return service.get(dossier_id)

    # -- HC correspondence hub (REQ-112) -------------------------------
    @router.post("/correspondence", status_code=201)
    def log_correspondence(body: CorrespondenceIn):
        return service.log_correspondence(body.model_dump())

    @router.get("/correspondence")
    def list_correspondence(dossier_id: str = Query(...), kind: str = ""):
        return service.list_correspondence(dossier_id, kind)

    app.include_router(router)
    return app
