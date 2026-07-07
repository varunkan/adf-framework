"""FastAPI surface for the registry service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header, Query

from ands_shared import create_app

from .models import ChecklistItemIn, RegistrationIn, StatusIn
from .service import RegistryService


def build_app(service: RegistryService) -> FastAPI:
    app = create_app(title="registry",
                     description="ANDS marketed-product registration registry "
                                 "(REQ-111)")
    router = APIRouter(prefix="/api/registry", tags=["registry"])

    @router.post("/registrations", status_code=201)
    def create(body: RegistrationIn,
               x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.create(body.model_dump(), x_tenant_id or None)

    @router.get("/registrations")
    def list_registrations(product: str = "", country: str = "", din: str = "",
                           status: str = "", dossier_id: str = "",
                           x_tenant_id: str = Header(default="",
                                                     alias="X-Tenant-Id")):
        return service.list(product=product, country=country, din=din,
                            status=status, dossier_id=dossier_id,
                            tenant_id=x_tenant_id or None)

    @router.post("/registrations/status")
    def set_status(body: StatusIn,
                   x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.set_status(body.id, body.status, x_tenant_id or None)

    # server-tracked annual obligations: each tick records who + when
    @router.get("/annual-checklist")
    def annual_checklist(year: int = 0,
                         x_tenant_id: str = Header(default="",
                                                   alias="X-Tenant-Id")):
        return service.annual_checklist(year, x_tenant_id or None)

    @router.get("/annual-checklist/signing-log")
    def annual_signing_log(year: int = 0,
                           x_tenant_id: str = Header(default="",
                                                     alias="X-Tenant-Id")):
        return service.annual_signing_log(year, x_tenant_id or None)

    @router.post("/annual-checklist/items")
    def set_annual_item(body: ChecklistItemIn,
                        x_tenant_id: str = Header(default="",
                                                  alias="X-Tenant-Id"),
                        x_user_email: str = Header(default="",
                                                   alias="X-User-Email")):
        return service.set_annual_item(body.model_dump(), x_tenant_id or None,
                                       x_user_email)

    @router.get("/registrations/{reg_id}")
    def get(reg_id: str,
            x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.get(reg_id, x_tenant_id or None)

    @router.get("/registrations/{reg_id}/right-to-sell")
    def right_to_sell(reg_id: str, as_of: str = Query(...),
                      x_tenant_id: str = Header(default="",
                                                alias="X-Tenant-Id")):
        return service.right_to_sell(reg_id, as_of, x_tenant_id or None)

    app.include_router(router)
    return app
