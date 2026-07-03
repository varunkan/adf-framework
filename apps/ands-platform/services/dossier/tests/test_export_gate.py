"""WS1: export must FAIL CLOSED — never silently emit a transmissible package
when eCTD validation did not pass; overrides are explicit, reasoned, audited,
and flagged on the response. Panel round-4 validate_export blocker."""

import io
import zipfile


def _placeholder(client):
    # a 'd...' placeholder dossier id is a guaranteed hard validation block
    # (CA-REP-0001) — file a Dossier ID Request before filing.
    did = "d777"
    client.post("/api/dossier/dossiers", json={"dossier_id": did, "title": "X"})
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate", json={})
    return did


def test_export_blocked_when_validation_fails(client):
    did = _placeholder(client)
    r = client.get(f"/api/dossier/ectd/{did}/export/0000")
    assert r.status_code == 409
    body = r.json()
    assert body["title"] == "validation_not_passed"
    assert body["validation"]["passed"] is False
    assert body["validation"]["criteria"]["version"]
    # the specific blocking finding is surfaced, not hidden behind a checkmark
    assert any(e.get("rule_id") == "CA-REP-0001"
               for e in body["validation"]["errors"])


def test_export_override_produces_flagged_package(client):
    did = _placeholder(client)
    r = client.get(
        f"/api/dossier/ectd/{did}/export/0000",
        params={"override": "true", "reason": "urgent client resubmission"})
    assert r.status_code == 200
    assert r.headers["X-Export-Validation"] == "overridden"
    # it still emits a real zip, but the override is on the record
    zipfile.ZipFile(io.BytesIO(r.content))


def test_export_override_without_reason_is_refused(client):
    did = _placeholder(client)
    r = client.get(f"/api/dossier/ectd/{did}/export/0000",
                   params={"override": "true"})
    assert r.status_code == 422
    assert r.json()["title"] == "override_reason_required"
