"""Company-ID pending path (usability-panel fix F3): an OSIP request in
flight must not wall the journey — only transmission truly needs the ID."""


def _start(client):
    return client.post("/api/journey/start", json={}).json()["id"]


def test_company_pending_advances_the_journey(client):
    sid = _start(client)
    client.post(f"/api/journey/{sid}/advance",
                json={"step": "orient", "data": {}})
    r = client.post(f"/api/journey/{sid}/advance",
                    json={"step": "company", "data": {"company_pending": True}})
    assert r.status_code == 200, r.text
    view = r.json()
    stages = {s["key"]: s for s in view["journey"]["stages"]}
    assert stages["company"]["done"] is True
    # the next step unlocked
    assert stages["dossier"]["locked"] is False


def test_empty_company_without_pending_still_rejected(client):
    sid = _start(client)
    r = client.post(f"/api/journey/{sid}/advance",
                    json={"step": "company", "data": {"company_id": ""}})
    assert r.status_code == 422


def test_real_id_clears_pending(client):
    sid = _start(client)
    client.post(f"/api/journey/{sid}/advance",
                json={"step": "company", "data": {"company_pending": True}})
    r = client.post(f"/api/journey/{sid}/advance",
                    json={"step": "company", "data": {"company_id": "54321"}})
    assert r.status_code == 200
