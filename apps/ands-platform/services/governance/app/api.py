"""FastAPI surface for the governance service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.responses import PlainTextResponse

from ands_shared import create_app

from .models import (AuditRecordIn, DeletionIn, ExportIn, GateIn, HcRecordIn,
                     HcRequestIn, LegalHoldIn, QaReviewIn, SignIn, VerifyIn)
from .service import GovernanceService


def build_app(service: GovernanceService) -> FastAPI:
    app = create_app(title="governance",
                     description="ANDS e-signature gate + event-sourced audit")
    router = APIRouter(prefix="/api/governance", tags=["governance"])

    # -- e-signature ----------------------------------------------------
    @router.get("/esign/policy")
    def policy():
        return service.policy()

    @router.post("/esign/qa-review")
    def qa_review(body: QaReviewIn):
        return service.qa_review(body.model_dump())

    @router.post("/esign/sign")
    def sign(body: SignIn):
        return service.sign(body.model_dump())

    @router.post("/esign/verify")
    def verify(body: VerifyIn):
        return service.verify(body.manifest, body.current)

    @router.post("/esign/gate")
    def gate(body: GateIn):
        return service.gate(body.model_dump())

    @router.post("/esign/hc-acceptance/request")
    def hc_request(body: HcRequestIn):
        return service.request_hc_acceptance(body.model_dump())

    @router.post("/esign/hc-acceptance/record")
    def hc_record(body: HcRecordIn):
        return service.record_hc_acceptance(body.model_dump())

    # -- audit ----------------------------------------------------------
    @router.post("/audit/record")
    def audit_record(body: AuditRecordIn):
        return service.record_external(body.model_dump())

    @router.get("/audit")
    def audit(category: str = "", dossier_id: str = "", limit: int = 0):
        return service.list_audit(category=category, dossier_id=dossier_id,
                                  limit=limit, newest_first=True)

    @router.get("/audit/export", response_class=PlainTextResponse)
    def audit_export():
        return service.export_audit()

    # -- tenant data export & portability (SAAS-REQ-004) ---------------
    @router.post("/export")
    def export_tenant(body: ExportIn):
        return service.export_tenant(body.model_dump())

    @router.post("/legal-hold")
    def legal_hold(body: LegalHoldIn):
        return service.set_legal_hold(body.model_dump())

    @router.post("/deletion-request")
    def deletion_request(body: DeletionIn):
        return service.request_deletion(body.model_dump())

    app.include_router(router)
    return app
