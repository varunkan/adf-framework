"""End-to-end transmission API via FastAPI TestClient."""

from tests.conftest import VALID_CONFIG


def _configure(client, dossier="e1"):
    return client.post("/api/transmission/configure",
                       json={"dossier_id": dossier, **VALID_CONFIG})


def test_configure_then_test_round_trip(client):
    r = _configure(client)
    assert r.status_code == 201
    assert r.json()["config"]["production_enabled"] is False
    rt = client.post("/api/transmission/test-round-trip",
                     json={"dossier_id": "e1"})
    assert rt.json()["config"]["production_enabled"] is True


def test_configure_invalid_422(client):
    r = client.post("/api/transmission/configure",
                    json={"dossier_id": "e1", "account_type": "bogus"})
    assert r.status_code == 422


def test_route_endpoint(client):
    assert client.get("/api/transmission/route",
                      params={"size_gb": 12}).json()["route"] == "physical_media"


def test_submit_and_ack_chain(client):
    _configure(client)
    s = client.post("/api/transmission/submit",
                    json={"dossier_id": "e1", "sequence": "0000", "size_gb": 1})
    assert s.status_code == 201 and s.json()["state"] == "SENT"
    client.post("/api/transmission/ack",
                json={"dossier_id": "e1", "kind": "mdn", "sequence": "0000"})
    client.post("/api/transmission/ack",
                json={"dossier_id": "e1", "kind": "fda", "sequence": "0000",
                      "core_id": "CORE-1"})
    hc = client.post("/api/transmission/ack",
                     json={"dossier_id": "e1", "kind": "hc",
                           "core_id": "CORE-1"})
    assert hc.json()["state"] == "RECEIVED_BY_HC"


def test_submit_duplicate_409(client):
    client.post("/api/transmission/submit",
                json={"dossier_id": "e1", "sequence": "0000", "size_gb": 1})
    r = client.post("/api/transmission/submit",
                    json={"dossier_id": "e1", "sequence": "0000", "size_gb": 1})
    assert r.status_code == 409


def test_production_submit_blocked_409(client):
    _configure(client)  # configured but no test round-trip
    r = client.post("/api/transmission/submit",
                    json={"dossier_id": "e1", "sequence": "0000", "size_gb": 1,
                          "production": True})
    assert r.status_code == 409


def test_ack_unknown_dossier_404(client):
    r = client.post("/api/transmission/ack",
                    json={"dossier_id": "nope", "kind": "mdn",
                          "sequence": "0000"})
    assert r.status_code == 404
