"""FastAPI surface for the validation service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Query

from ands_shared import create_app

from .models import BatchIn, FixIn, InlineIn, ValidateIn
from .service import ValidationService


def build_app(service: ValidationService) -> FastAPI:
    app = create_app(title="validation",
                     description="ANDS eCTD technical validation (REQ-104)")
    router = APIRouter(prefix="/api/validation", tags=["validation"])

    @router.get("/rulesets")
    def rulesets():
        return service.list_rulesets()

    @router.get("/profiles")
    def profiles():
        return service.profiles()

    @router.get("/ruleset")
    def ruleset(version: str = "", profile: str = "eCTD"):
        return service.ruleset(version, profile)

    @router.post("/run")
    def run(body: ValidateIn):
        return service.validate(body.model_dump())

    @router.post("/inline")
    def inline(body: InlineIn):
        return service.inline(body.model_dump())

    @router.post("/fix")
    def fix(body: FixIn):
        return service.fix(body.model_dump())

    @router.get("/report")
    def report(dossier_id: str = Query(...), sequence: str = "0000"):
        return service.report(dossier_id, sequence)

    # -- batch validation jobs (REQ-116) -------------------------------
    @router.post("/batch", status_code=201)
    def submit_batch(body: BatchIn):
        return service.submit_batch(body.model_dump())

    @router.get("/batch/{job_id}")
    def get_job(job_id: str):
        return service.get_job(job_id)

    app.include_router(router)
    return app
