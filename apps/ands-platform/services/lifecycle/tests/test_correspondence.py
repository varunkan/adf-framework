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
