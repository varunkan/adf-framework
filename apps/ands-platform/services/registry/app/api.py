"""FastAPI surface for the registry service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header, Query

from ands_shared import create_app

from .models import RegistrationIn, StatusIn
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
