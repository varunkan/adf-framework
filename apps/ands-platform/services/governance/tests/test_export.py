"""F10 / SAAS-REQ-004 — tenant data export, portability & legal hold."""

from ands_shared import EventEnvelope

from app import export


def test_bundle_checksum_and_manifest():
    b = export.build_bundle("t1", [{"action": "x"}],
                            attachments={"dossiers": [{"id": "e1"}]})
    assert b["checksum"].startswith("sha256:")
    assert b["manifest"]["audit_event_count"] == 1
    assert b["manifest"]["attachment_keys"] == ["dossiers"]
    # checksum is stable for the same content
    assert export.build_bundle("t1", [{"action": "x"}],
                               {"dossiers": [{"id": "e1"}]})["checksum"] \
        == b["checksum"]


def test_export_includes_tenant_audit_events(ctx):
    # two events for t1, one for t2
    ctx.bus.publish(EventEnvelope.make("validation.failed", source="validation",
                                       tenant_id="t1", dossier_id="e1"))
    ctx.bus.publish(EventEnvelope.make("transmission.hc_ack",
                                       source="transmission", tenant_id="t1"))
    ctx.bus.publish(EventEnvelope.make("validation.failed", source="validation",
                                       tenant_id="t2"))
    bundle = ctx.client.post("/api/governance/export",
                             json={"tenant_id": "t1",
                                   "attachments": {"registrations": []}}).json()
    assert bundle["manifest"]["audit_event_count"] == 2
    assert all(e["tenant_id"] == "t1" for e in bundle["audit_events"])
    assert "registrations" in bundle["attachments"]


def test_export_requires_tenant_422(client):
    assert client.post("/api/governance/export", json={}).status_code == 422


def test_legal_hold_blocks_deletion(client):
    client.post("/api/governance/legal-hold",
                json={"tenant_id": "t1", "active": True})
    blocked = client.post("/api/governance/deletion-request",
                          json={"tenant_id": "t1"})
    assert blocked.status_code == 409
    assert blocked.json()["rule"] == "legal_hold_active"
    # lift the hold → deletion proceeds
    client.post("/api/governance/legal-hold",
                json={"tenant_id": "t1", "active": False})
    ok = client.post("/api/governance/deletion-request",
                     json={"tenant_id": "t1"})
    assert ok.status_code == 200 and ok.json()["deletion"] == "scheduled"
