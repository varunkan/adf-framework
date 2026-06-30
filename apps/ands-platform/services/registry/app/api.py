"""FastAPI surface for the registry service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Query

from ands_shared import create_app

from .models import RegistrationIn, StatusIn
from .service import RegistryService


def build_app(service: RegistryService) -> FastAPI:
    app = create_app(title="registry",
                     description="ANDS marketed-product registration registry "
                                 "(REQ-111)")
    router = APIRouter(prefix="/api/registry", tags=["registry"])

    @router.post("/registrations", status_code=201)
    def create(body: RegistrationIn):
        return service.create(body.model_dump())

    @router.get("/registrations")
    def list_registrations(product: str = "", country: str = "", din: str = "",
                           status: str = "", dossier_id: str = ""):
        return service.list(product=product, country=country, din=din,
                            status=status, dossier_id=dossier_id)

    @router.post("/registrations/status")
    def set_status(body: StatusIn):
        return service.set_status(body.id, body.status)

    @router.get("/registrations/{reg_id}")
    def get(reg_id: str):
        return service.get(reg_id)

    @router.get("/registrations/{reg_id}/right-to-sell")
    def right_to_sell(reg_id: str, as_of: str = Query(...)):
        return service.right_to_sell(reg_id, as_of)

    app.include_router(router)
    return app
