"""FastAPI surface for the lifecycle service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header, Query

from ands_shared import create_app

from .models import (AttachmentIn, CorrespondenceIn, DeadlineIn, DelLinkIn, NoaActionIn,
                     NoaIn, NoaServeIn, NoticeIn, ShortageIn, StartIn,
                     TransitionIn, VerifiedDateIn)
from .service import LifecycleService


# The web proxy injects the caller's tenant (X-Tenant-Id) on every
# authenticated request; an empty value (in-process mesh / tests) means
# "unscoped" — see LifecycleService for the ownership contract.
def build_app(service: LifecycleService) -> FastAPI:
    app = create_app(title="lifecycle",
                     description="ANDS DSTS lifecycle + HC deadline calendar")
    router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])

    @router.post("/start", status_code=201)
    def start(body: StartIn,
              x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.start_lifecycle(body.model_dump(), x_tenant_id or None)

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
    def state(dossier_id: str,
              x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        # proxy already guards this dossier-id read; defence-in-depth: hide a
        # lifecycle owned by another tenant (404) as well.
        if x_tenant_id:
            service._tenant_guard(service.repo.get_tenant(dossier_id),
                                  x_tenant_id, dossier_id)
        return service.get(dossier_id)

    # -- HC correspondence hub (REQ-112) -------------------------------
    @router.post("/correspondence", status_code=201)
    def log_correspondence(body: CorrespondenceIn,
                           x_tenant_id: str = Header(
                               default="", alias="X-Tenant-Id")):
        return service.log_correspondence(body.model_dump(),
                                          x_tenant_id or None)

    @router.post("/correspondence/{cid}/attachment", status_code=201)
    def attach_document(cid: str, body: AttachmentIn,
                        x_tenant_id: str = Header(default="",
                                                  alias="X-Tenant-Id"),
                        x_user_email: str = Header(default="",
                                                   alias="X-User-Email")):
        return service.attach_correspondence_document(
            cid, body.model_dump(), x_tenant_id or None, x_user_email)

    @router.get("/correspondence/{cid}/attachment")
    def get_document(cid: str,
                     x_tenant_id: str = Header(default="",
                                               alias="X-Tenant-Id")):
        return service.get_correspondence_document(cid, x_tenant_id or None)

    @router.get("/correspondence")
    def list_correspondence(dossier_id: str = Query(...), kind: str = "",
                            x_tenant_id: str = Header(
                                default="", alias="X-Tenant-Id")):
        return service.list_correspondence(dossier_id, kind,
                                           x_tenant_id or None)

    # -- verified-date overrides + reconciliation (round-9, n=4) --------
    @router.post("/verified-date", status_code=201)
    def record_verified_date(body: VerifiedDateIn,
                             x_tenant_id: str = Header(
                                 default="", alias="X-Tenant-Id"),
                             x_user_email: str = Header(
                                 default="", alias="X-User-Email")):
        return service.record_verified_date(body.model_dump(),
                                            x_tenant_id or None, x_user_email)

    @router.get("/verified-dates")
    def list_verified_dates(dossier_id: str = Query(...),
                            x_tenant_id: str = Header(
                                default="", alias="X-Tenant-Id")):
        return service.list_verified_dates(dossier_id, x_tenant_id or None)

    # -- Form V / NOA register (PM(NOC) Regulations) --------------------
    @router.post("/noa", status_code=201)
    def create_noa(body: NoaIn,
                   x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.create_noa(body.model_dump(), x_tenant_id or None)

    @router.post("/noa/{noa_id}/serve")
    def serve_noa(noa_id: str, body: NoaServeIn,
                  x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.serve_noa(noa_id, body.model_dump(), x_tenant_id or None)

    @router.post("/noa/{noa_id}/action")
    def action_noa(noa_id: str, body: NoaActionIn,
                   x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.action_noa(noa_id, body.model_dump(),
                                  x_tenant_id or None)

    @router.get("/noa")
    def list_noa(dossier_id: str = Query(...), as_of: str = "",
                 x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.list_noa(dossier_id, as_of, x_tenant_id or None)

    # -- drug shortage / discontinuation + DEL linkage ------------------
    @router.post("/shortage", status_code=201)
    def report_shortage(body: ShortageIn,
                        x_tenant_id: str = Header(
                            default="", alias="X-Tenant-Id")):
        return service.report_shortage(body.model_dump(), x_tenant_id or None)

    @router.get("/shortage")
    def list_shortage(dossier_id: str = Query(...), as_of: str = "",
                      x_tenant_id: str = Header(
                          default="", alias="X-Tenant-Id")):
        return service.list_shortage(dossier_id, as_of, x_tenant_id or None)

    @router.post("/del", status_code=201)
    def link_del(body: DelLinkIn,
                 x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.link_del(body.model_dump(), x_tenant_id or None)

    @router.get("/del")
    def list_del(dossier_id: str = Query(...),
                 x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.list_del(dossier_id, x_tenant_id or None)

    app.include_router(router)
    return app
