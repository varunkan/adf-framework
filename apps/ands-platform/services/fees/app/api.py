"""FastAPI surface for the (stateless) fees service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Query

from ands_shared import create_app

from .models import MitigationIn
from .service import FeesService


def build_app(service: FeesService) -> FastAPI:
    app = create_app(title="fees",
                     description="ANDS HC drug-submission fees (REQ-035/036/037)")
    router = APIRouter(prefix="/api/fees", tags=["fees"])

    @router.get("/groupings")
    def groupings():
        return service.groupings()

    @router.get("/ands")
    def ands_fee(submission_date: str = Query(...)):
        return service.ands_fee(submission_date)

    @router.get("/grouping")
    def grouping(grouping: str = Query(...), submission_date: str = Query(...)):
        return service.fee(grouping, submission_date)

    @router.post("/mitigation")
    def mitigation(body: MitigationIn):
        return service.mitigation(body.model_dump())

    @router.get("/right-to-sell")
    def right_to_sell(drug_type: str = Query(...), as_of: str = Query(...),
                      paid: bool = False):
        return service.right_to_sell(drug_type, as_of, paid)

    app.include_router(router)
    return app
