"""FastAPI surface for the dossier service — thin glue over the service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Query

from ands_shared import create_app

from . import ectd
from .models import (AdminSequenceIn, BinderIn, ContentPlanIn, ItemAssignIn,
                     ItemStatusIn, LeafIn, PmLeafIn, PmXmlBuildIn, PmXmlGateIn,
                     PmXmlValidateIn, PmXrefIn)
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

    # -- XML Product Monograph (REQ-099) --------------------------------
    @router.post("/monograph/xml/build")
    def pm_xml_build(body: PmXmlBuildIn):
        return service.build_monograph_xml(body.model_dump())

    @router.post("/monograph/xml/validate")
    def pm_xml_validate(body: PmXmlValidateIn):
        return service.validate_monograph_xml(body.xml)

    @router.post("/monograph/xml/gate")
    def pm_xml_gate(body: PmXmlGateIn):
        return service.require_xml_pm(body.model_dump())

    # -- annotated PM cross-references (REQ-101) ------------------------
    @router.get("/monograph/xref/targets")
    def pm_xref_targets():
        return service.xref_targets()

    @router.post("/monograph/xref/resolve")
    def pm_xref_resolve(body: PmXrefIn):
        return service.resolve_pm_xrefs(body.model_dump())

    # -- eCTD assembly + Application Viewer (REQ-107) ------------------
    @router.post("/ectd/leaf", status_code=201)
    def add_leaf(body: LeafIn):
        return service.add_leaf(body.model_dump())

    @router.get("/ectd/{dossier_id}/current-view")
    def current_view(dossier_id: str):
        return service.current_view(dossier_id)

    @router.get("/ectd/{dossier_id}/viewer/files")
    def files_view(dossier_id: str):
        return service.files_view(dossier_id)

    @router.get("/ectd/{dossier_id}/viewer/outline/{sequence}")
    def outline_view(dossier_id: str, sequence: str):
        return service.outline_view(dossier_id, sequence)

    # -- submission archive / binder (REQ-110) ------------------------
    @router.post("/archive", status_code=201)
    def create_binder(body: BinderIn):
        return service.create_binder(body.model_dump())

    @router.get("/archive")
    def list_binders(dossier_id: str = Query(...)):
        return service.list_binders(dossier_id)

    @router.get("/archive/share/{token}")
    def shared_binder(token: str):
        return service.get_shared_binder(token)

    @router.get("/archive/{binder_id}")
    def get_binder(binder_id: str):
        return service.get_binder(binder_id)

    @router.post("/archive/{binder_id}/share", status_code=201)
    def share_binder(binder_id: str):
        return service.share_binder(binder_id)

    app.include_router(router)
    return app
