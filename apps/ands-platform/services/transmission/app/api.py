"""FastAPI surface for the transmission service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header, Query

from ands_shared import create_app

from .models import AckIn, ConfigureIn, SubmitIn, TestRoundTripIn
from .service import TransmissionService


def build_app(service: TransmissionService) -> FastAPI:
    app = create_app(title="transmission",
                     description="ANDS FDA-ESG NextGen ride-along (REQ-003/025/046)")
    router = APIRouter(prefix="/api/transmission", tags=["transmission"])

    @router.post("/configure", status_code=201)
    def configure(body: ConfigureIn,
                  x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.configure(body.model_dump(), x_tenant_id or None)

    @router.post("/test-round-trip")
    def test_round_trip(body: TestRoundTripIn):
        return service.test_round_trip(body.model_dump())

    @router.get("/route")
    def route(size_gb: float = Query(...)):
        return service.route(size_gb)

    @router.post("/submit", status_code=201)
    def submit(body: SubmitIn,
               x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.submit(body.model_dump(), x_tenant_id or None)

    @router.post("/ack")
    def ack(body: AckIn,
            x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.ack(body.model_dump(), x_tenant_id or None)

    @router.get("/ledger/{dossier_id}")
    def ledger(dossier_id: str,
               x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.get(dossier_id, x_tenant_id or None)

    app.include_router(router)
    return app
