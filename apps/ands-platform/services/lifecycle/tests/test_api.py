"""End-to-end lifecycle API via FastAPI TestClient."""


def _start(client, dossier="e123456", stype="ANDS", received="2025-01-06"):
    return client.post("/api/lifecycle/start",
                       json={"dossier_id": dossier, "submission_type": stype,
                             "received_date": received})


def test_start_then_get_state(client):
    r = _start(client)
    assert r.status_code == 201
    assert r.json()["phase"] == "Screening"
    got = client.get("/api/lifecycle/state/e123456")
    assert got.status_code == 200
    assert got.json()["status"] == "Active"


def test_start_duplicate_409(client):
    _start(client)
    assert _start(client).status_code == 409


def test_transition_screening_then_decision(client):
    _start(client)
    r = client.post("/api/lifecycle/transition",
                    json={"dossier_id": "e123456", "kind": "screening",
                          "value": "SAL", "date": "2025-01-10"})
    assert r.status_code == 200 and r.json()["phase"] == "Review"
    review_due = r.json()["review_due"]
    r = client.post("/api/lifecycle/transition",
                    json={"dossier_id": "e123456", "kind": "decision",
                          "value": "NOC", "date": review_due})
    assert r.json()["status"] == "Approved"


def test_transition_unknown_dossier_404(client):
    r = client.post("/api/lifecycle/transition",
                    json={"dossier_id": "nope", "kind": "screening",
                          "value": "SAL", "date": "2025-01-10"})
    assert r.status_code == 404


def test_illegal_transition_409(client):
    _start(client)
    # a decision before screening acceptance is illegal
    r = client.post("/api/lifecycle/transition",
                    json={"dossier_id": "e123456", "kind": "decision",
                          "value": "NOC", "date": "2025-02-01"})
    assert r.status_code == 409


def test_service_standard_endpoint(client):
    r = client.get("/api/lifecycle/service-standard",
                   params={"submission_type": "ANDS"})
    assert r.json()["review_target_days"] == 180


def test_deadline_endpoint(client):
    r = client.post("/api/lifecycle/deadline",
                    json={"start": "2025-06-27", "days": 1,
                          "notice_type": "clarifax"})
    assert r.json()["due"] == "2025-06-30"


def test_holidays_endpoint(client):
    r = client.get("/api/lifecycle/holidays", params={"year": 2025})
    assert r.json()["holidays"]["2025-07-01"] == "Canada Day"
