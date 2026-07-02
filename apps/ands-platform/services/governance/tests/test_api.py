"""End-to-end governance API via FastAPI TestClient."""

from ands_shared import EventEnvelope


def test_policy_endpoint(client):
    r = client.get("/api/governance/esign/policy")
    assert r.json()["acceptance"] == "case-by-case"


def test_sign_and_verify_via_api(client):
    signed = client.post("/api/governance/esign/sign",
                         json={"signer": "vp", "auth_method": "mfa",
                               "meaning": "approved",
                               "artifacts": [{"id": "l1", "content": "x"}]})
    assert signed.status_code == 200
    manifest = signed.json()["manifest"]
    chk = manifest["artifacts"][0]["checksum"]
    ok = client.post("/api/governance/esign/verify",
                     json={"manifest": manifest, "current": {"l1": chk}})
    assert ok.json()["tampered"] is False


def test_sign_invalid_422(client):
    r = client.post("/api/governance/esign/sign",
                    json={"signer": "", "artifacts": []})
    assert r.status_code == 422


def test_gate_endpoint(client):
    r = client.post("/api/governance/esign/gate", json={})
    assert r.json()["can_transmit"] is False


def test_audit_endpoint_lists_events(ctx):
    ctx.bus.publish(EventEnvelope.make("validation.failed", source="validation",
                                       dossier_id="e1"))
    r = ctx.client.get("/api/governance/audit", params={"dossier_id": "e1"})
    assert r.json()["count"] == 1


def test_audit_record_endpoint_ingests_event(ctx):
    r = ctx.client.post("/api/governance/audit/record", json={
        "source": "dossier", "event_type": "document.uploaded",
        "dossier_id": "e7", "data": {"leaf": "l1"}})
    assert r.status_code == 200
    assert r.json()["action"] == "document.uploaded"
    listed = ctx.client.get("/api/governance/audit",
                            params={"dossier_id": "e7"}).json()
    assert listed["count"] == 1
    assert listed["events"][0]["category"] == "dossier"


def test_audit_record_endpoint_422_on_missing_fields(client):
    r = client.post("/api/governance/audit/record", json={"source": "dossier"})
    assert r.status_code == 422


def test_audit_endpoint_newest_first_and_limit(ctx):
    for i in range(4):
        ctx.bus.publish(EventEnvelope.make(f"evt.{i}", source="s",
                                           dossier_id="e8"))
    r = ctx.client.get("/api/governance/audit",
                       params={"dossier_id": "e8", "limit": 2})
    body = r.json()
    assert body["count"] == 2
    assert [e["action"] for e in body["events"]] == ["evt.3", "evt.2"]


def test_audit_export_is_text(ctx):
    ctx.bus.publish(EventEnvelope.make("validation.failed", source="validation",
                                       dossier_id="e1"))
    r = ctx.client.get("/api/governance/audit/export")
    assert r.status_code == 200
    assert "AUDIT TRAIL" in r.text and "validation.failed" in r.text
