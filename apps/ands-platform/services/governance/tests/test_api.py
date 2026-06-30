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


def test_audit_export_is_text(ctx):
    ctx.bus.publish(EventEnvelope.make("validation.failed", source="validation",
                                       dossier_id="e1"))
    r = ctx.client.get("/api/governance/audit/export")
    assert r.status_code == 200
    assert "AUDIT TRAIL" in r.text and "validation.failed" in r.text
