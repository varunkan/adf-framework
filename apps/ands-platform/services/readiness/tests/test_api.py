"""End-to-end readiness API via FastAPI TestClient."""

from ands_shared import EventEnvelope, EventType


def test_empty_dashboard(client):
    r = client.get("/api/readiness/dashboard")
    assert r.status_code == 200
    assert r.json()["empty"] is True


def test_dashboard_after_events(ctx):
    ctx.bus.publish(EventEnvelope.make(
        EventType.VALIDATION_FAILED, source="validation", dossier_id="e1",
        data={"error_count": 2}))
    dash = ctx.client.get("/api/readiness/dashboard").json()
    assert dash["total"] == 1 and dash["blocked"] == 1
    card = ctx.client.get("/api/readiness/dossier/e1").json()
    assert card["status"] == "BLOCKED"


def test_unknown_dossier_404(client):
    assert client.get("/api/readiness/dossier/nope").status_code == 404
