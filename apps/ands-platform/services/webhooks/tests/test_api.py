"""End-to-end webhooks API + event-driven delivery."""

from ands_shared import EventEnvelope, EventType


def test_create_subscription_and_event_enqueues_signed_delivery(ctx):
    sub = ctx.client.post("/api/webhooks/subscriptions",
                          json={"url": "https://hooks.acme.io/ands",
                                "event_types": ["validation.failed"]}).json()
    assert sub["secret"]
    # an unrelated event does not deliver
    ctx.bus.publish(EventEnvelope.make(EventType.TRANSMISSION_SENT,
                                       source="transmission", dossier_id="e1"))
    assert ctx.client.get("/api/webhooks/deliveries").json()["count"] == 0
    # the subscribed event delivers, signed, pending
    ctx.bus.publish(EventEnvelope.make(EventType.VALIDATION_FAILED,
                                       source="validation", dossier_id="e1",
                                       data={"rule": "A09"}))
    dl = ctx.client.get("/api/webhooks/deliveries").json()
    assert dl["count"] == 1 and dl["pending"] == 1
    assert dl["deliveries"][0]["event_type"] == "validation.failed"
    assert dl["deliveries"][0]["signature"]


def test_wildcard_subscription_receives_everything(ctx):
    ctx.client.post("/api/webhooks/subscriptions",
                    json={"url": "https://hooks.acme.io/all"})
    for t in (EventType.VALIDATION_COMPLETED, EventType.TRANSMISSION_HC_ACK):
        ctx.bus.publish(EventEnvelope.make(t, source="s", dossier_id="e1"))
    assert ctx.client.get("/api/webhooks/deliveries").json()["count"] == 2


def test_tenant_scoped_subscription(ctx):
    ctx.client.post("/api/webhooks/subscriptions",
                    json={"url": "https://x/h", "tenant_id": "t1"})
    ctx.bus.publish(EventEnvelope.make("evt.x", source="s", tenant_id="t1"))
    ctx.bus.publish(EventEnvelope.make("evt.y", source="s", tenant_id="t2"))
    assert ctx.client.get("/api/webhooks/deliveries").json()["count"] == 1


def test_invalid_url_422(client):
    r = client.post("/api/webhooks/subscriptions", json={"url": "not-a-url"})
    assert r.status_code == 422


def test_list_and_delete_subscription(client):
    sid = client.post("/api/webhooks/subscriptions",
                      json={"url": "https://x/h"}).json()["id"]
    assert client.get("/api/webhooks/subscriptions").json()["count"] == 1
    assert client.delete(f"/api/webhooks/subscriptions/{sid}").json()["deleted"]
    assert client.get("/api/webhooks/subscriptions").json()["count"] == 0
    assert client.delete("/api/webhooks/subscriptions/nope").status_code == 404
