"""F5 / REQ-112 — HC correspondence hub."""

from app import correspondence


def test_validate_requires_kind_dossier_subject():
    bad = correspondence.validate_correspondence({"kind": "FOO"})
    rules = {e["rule"] for e in bad["errors"]}
    assert {"kind_invalid", "dossier_id_required", "subject_required"} <= rules


def test_validate_ok_defaults_inbound():
    ok = correspondence.validate_correspondence({
        "kind": "NOD", "dossier_id": "e1", "subject": "Deficiencies"})
    assert ok["valid"]
    assert ok["record"]["direction"] == "inbound"
    assert ok["record"]["kind_label"] == "Notice of Deficiency"


def test_log_list_and_filter_via_api(client):
    client.post("/api/lifecycle/correspondence",
                json={"kind": "SDN", "dossier_id": "e1",
                      "subject": "Screening deficiency", "received_at": "2025-02-01"})
    client.post("/api/lifecycle/correspondence",
                json={"kind": "clarifax", "dossier_id": "e1",
                      "subject": "Please clarify section 3.2",
                      "direction": "inbound"})
    allc = client.get("/api/lifecycle/correspondence",
                      params={"dossier_id": "e1"}).json()
    assert allc["count"] == 2
    sdn = client.get("/api/lifecycle/correspondence",
                     params={"dossier_id": "e1", "kind": "SDN"}).json()
    assert sdn["count"] == 1 and sdn["correspondence"][0]["kind"] == "SDN"


def test_invalid_kind_422(client):
    r = client.post("/api/lifecycle/correspondence",
                    json={"kind": "spam", "dossier_id": "e1", "subject": "x"})
    assert r.status_code == 422


# -- round-9 (BLOCKER, ra_officer_generic): attach the actual SDN/SAL/NON
#    document to the record — "the first thing an inspector asks for".
import base64

PDF = b"%PDF-1.4 fake notice bytes for the attachment test"
B64 = base64.b64encode(PDF).decode()


def _log_one(client, **over):
    body = {"kind": "SDN", "dossier_id": "e1",
            "subject": "Screening deficiency", **over}
    return client.post("/api/lifecycle/correspondence", json=body).json()


def test_attach_and_fetch_notice_document(client):
    rec = _log_one(client)
    r = client.post(f"/api/lifecycle/correspondence/{rec['id']}/attachment",
                    json={"filename": "sdn-2026-001.pdf",
                          "content_type": "application/pdf",
                          "data_base64": B64})
    assert r.status_code == 201
    meta = r.json()
    assert meta["filename"] == "sdn-2026-001.pdf"
    assert meta["sha256"] and len(meta["sha256"]) == 64

    got = client.get(
        f"/api/lifecycle/correspondence/{rec['id']}/attachment").json()
    assert base64.b64decode(got["data_base64"]) == PDF
    assert got["sha256"] == meta["sha256"]

    # the row itself advertises the attachment for the list view
    row = next(c for c in client.get(
        "/api/lifecycle/correspondence",
        params={"dossier_id": "e1"}).json()["correspondence"]
        if c["id"] == rec["id"])
    assert row["has_attachment"] is True
    assert row["attachment_filename"] == "sdn-2026-001.pdf"


def test_attachment_missing_and_bad_input(client):
    rec = _log_one(client, kind="NOD", subject="Deficiencies")
    assert client.get(
        f"/api/lifecycle/correspondence/{rec['id']}/attachment"
    ).status_code == 404
    assert client.post(
        f"/api/lifecycle/correspondence/{rec['id']}/attachment",
        json={"filename": "", "data_base64": B64}).status_code == 422
    assert client.post(
        f"/api/lifecycle/correspondence/{rec['id']}/attachment",
        json={"filename": "x.pdf", "data_base64": "@@not-base64@@"}
    ).status_code == 422
    assert client.post(
        "/api/lifecycle/correspondence/nope/attachment",
        json={"filename": "x.pdf", "data_base64": B64}).status_code == 404


def test_attachment_is_tenant_guarded(client):
    rec = _log_one(client)  # unowned record (no tenant header)
    ra = client.post(f"/api/lifecycle/correspondence/{rec['id']}/attachment",
                     json={"filename": "x.pdf", "data_base64": B64},
                     headers={"X-Tenant-Id": "t-intruder"})
    assert ra.status_code == 404   # invisible across the tenant wall
    assert client.get(
        f"/api/lifecycle/correspondence/{rec['id']}/attachment",
        headers={"X-Tenant-Id": "t-intruder"}).status_code == 404
