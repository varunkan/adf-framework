"""Webhooks application service — subscriptions + event-driven delivery outbox."""

from __future__ import annotations

from ands_shared import EventEnvelope, ProblemError

from . import webhooks
from .ports import WebhookRepository


class WebhookService:
    def __init__(self, repo: WebhookRepository, bus,
                 *, source: str = "webhooks") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    def register(self) -> "WebhookService":
        """Subscribe to EVERY event; matching subscriptions get a signed delivery."""
        self.bus.subscribe("*", self.on_event)
        return self

    def on_event(self, event: EventEnvelope) -> None:
        payload = event.model_dump()
        for sub in self.repo.all_subscriptions():
            if webhooks.matches(sub, event.type, event.tenant_id):
                delivery = webhooks.build_delivery(sub, event.type, payload)
                self.repo.enqueue_delivery({"subscription_id": sub["id"],
                                            **delivery})

    # -- subscriptions ------------------------------------------------------
    def create_subscription(self, data: dict) -> dict:
        res = webhooks.validate_subscription(data)
        if not res["valid"]:
            raise ProblemError(422, "Invalid webhook subscription",
                               errors=res["errors"])
        return self.repo.add_subscription(res["subscription"])

    def list_subscriptions(self, tenant_id: str = "") -> dict:
        subs = self.repo.list_subscriptions(tenant_id=tenant_id)
        return {"subscriptions": subs, "count": len(subs)}

    def delete_subscription(self, sub_id: str) -> dict:
        if not self.repo.delete_subscription(str(sub_id or "").strip()):
            raise ProblemError(404, "subscription not found", detail=sub_id)
        return {"deleted": True, "id": sub_id}

    def list_deliveries(self, subscription_id: str = "") -> dict:
        rows = self.repo.list_deliveries(subscription_id=subscription_id)
        pending = sum(1 for d in rows if d["status"] == "pending")
        return {"deliveries": rows, "count": len(rows), "pending": pending}
