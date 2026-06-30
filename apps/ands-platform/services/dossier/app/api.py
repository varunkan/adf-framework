"""FastAPI surface for the dossier service — thin glue over the service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Query

from ands_shared import create_app

from . import ectd
from .models import (AdminSequenceIn, ContentPlanIn, ItemAssignIn, ItemStatusIn,
                     PmLeafIn)
from .service import DossierService


def build_app(service: DossierService) -> FastAPI:
    app = create_app(title="dossier",
                     description="ANDS eCTD content plans (REQ-103) & "
                                 "bilingual Product Monograph (REQ-098)")
    router = APIRouter(prefix="/api/dossier", tags=["dossier"])

    @router.get("/placement")
    def placement():
        return ectd.module1_placement_table()

    # -- content plans (REQ-103) ----------------------------------------
    @router.post("/content-plans", status_code=201)
    def create_plan(body: ContentPlanIn):
        return {"plan": service.create_content_plan(body.model_dump())}

    @router.get("/content-plans")
    def get_plan(dossier_id: str = Query(...)):
        return {"plan": service.get_content_plan(dossier_id)}

    @router.post("/content-plans/item/assign")
    def assign_item(body: ItemAssignIn):
        return {"item": service.assign_item(body.id, body.assignee,
                                            body.due_date or "")}

    @router.post("/content-plans/item/status")
    def item_status(body: ItemStatusIn):
        return service.update_item_status(body.id, body.status)

    # -- bilingual product monograph (REQ-098) --------------------------
    @router.post("/monograph/leaves", status_code=201)
    def register_pm_leaf(body: PmLeafIn):
        return {"leaf": service.register_pm_leaf(body.model_dump())}

    @router.get("/monograph/status")
    def monograph_status(dossier_id: str = Query(...)):
        return service.monograph_status(dossier_id)

    # -- administrative / corrective sequences (REQ-092) ----------------
    @router.post("/admin-sequence", status_code=201)
    def admin_sequence(body: AdminSequenceIn):
        return service.build_admin_sequence(body.model_dump())

    app.include_router(router)
    return app
