"""FastAPI surface for the webhooks service."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from ands_shared import create_app

from .models import SubscriptionIn
from .service import WebhookService


def build_app(service: WebhookService) -> FastAPI:
    app = create_app(title="webhooks",
                     description="ANDS outbound webhooks on domain events")
    router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

    @router.post("/subscriptions", status_code=201)
    def create(body: SubscriptionIn):
        return service.create_subscription(body.model_dump())

    @router.get("/subscriptions")
    def list_subscriptions(tenant_id: str = ""):
        return service.list_subscriptions(tenant_id)

    @router.delete("/subscriptions/{sub_id}")
    def delete(sub_id: str):
        return service.delete_subscription(sub_id)

    @router.get("/deliveries")
    def deliveries(subscription_id: str = ""):
        return service.list_deliveries(subscription_id)

    app.include_router(router)
    return app
