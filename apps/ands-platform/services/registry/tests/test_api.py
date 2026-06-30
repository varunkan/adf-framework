"""End-to-end registry API + events."""

from ands_shared import EventType


def _create(client, product="Metformin", dossier="e1", din="02431234"):
    return client.post("/api/registry/registrations",
                       json={"product": product, "dossier_id": dossier,
                             "din": din, "drug_type": "prescription"})


def test_create_list_and_filter(client):
    assert _create(client).status_code == 201
    _create(client, product="Atorvastatin", dossier="e2", din="02430000")
    all_regs = client.get("/api/registry/registrations").json()
    assert all_regs["count"] == 2
    one = client.get("/api/registry/registrations",
                     params={"din": "02431234"}).json()
    assert one["count"] == 1 and one["registrations"][0]["product"] == "Metformin"


def test_create_invalid_422(client):
    r = client.post("/api/registry/registrations", json={"product": ""})
    assert r.status_code == 422


def test_status_flow_and_right_to_sell(client):
    rid = _create(client).json()["id"]
    client.post("/api/registry/registrations/status",
                json={"id": rid, "status": "NOC-Issued"})
    marketed = client.post("/api/registry/registrations/status",
                           json={"id": rid, "status": "Marketed"})
    assert marketed.json()["status"] == "Marketed"
    rts = client.get(f"/api/registry/registrations/{rid}/right-to-sell",
                     params={"as_of": "2025-09-15"}).json()
    assert rts["applies"] and rts["due_date"] == "2025-10-01"


def test_illegal_status_409(client):
    rid = _create(client).json()["id"]
    client.post("/api/registry/registrations/status",
                json={"id": rid, "status": "Cancelled"})
    r = client.post("/api/registry/registrations/status",
                    json={"id": rid, "status": "Marketed"})
    assert r.status_code == 409


def test_get_unknown_404(client):
    assert client.get("/api/registry/registrations/nope").status_code == 404


def test_status_change_emits_event(ctx):
    rid = ctx.service.create({"product": "Metformin", "dossier_id": "e1"})["id"]
    ctx.service.set_status(rid, "NOC-Issued")
    events = ctx.bus.events_of(EventType.REGISTRATION_STATUS_CHANGED)
    # one on create, one on status change
    assert len(events) == 2
    assert events[-1].data["status"] == "NOC-Issued"
