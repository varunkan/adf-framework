"""F6 / REQ-096 — HC notice ingestion advances DSTS + logs correspondence."""


def _start(client, dossier="e1"):
    client.post("/api/lifecycle/start",
                json={"dossier_id": dossier, "submission_type": "ANDS",
                      "received_date": "2025-01-06"})


def test_sal_notice_moves_to_review_and_logs_correspondence(client):
    _start(client)
    r = client.post("/api/lifecycle/notice",
                    json={"dossier_id": "e1", "notice": "SAL",
                          "date": "2025-01-10"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["phase"] == "Review"
    assert body["response"]["action"] == "continue"
    # logged as inbound correspondence in the hub
    corr = client.get("/api/lifecycle/correspondence",
                      params={"dossier_id": "e1", "kind": "SAL"}).json()
    assert corr["count"] == 1 and corr["correspondence"][0]["direction"] == "inbound"


def test_sdn_notice_offers_45_day_response(client):
    _start(client)
    r = client.post("/api/lifecycle/notice",
                    json={"dossier_id": "e1", "notice": "SDN",
                          "date": "2025-01-10"}).json()
    assert r["state"]["status"] == "Inactive-90"
    assert r["response"]["window_days"] == 45


def test_noc_notice_approves(client):
    _start(client)
    sal = client.post("/api/lifecycle/notice",
                      json={"dossier_id": "e1", "notice": "SAL",
                            "date": "2025-01-10"}).json()
    noc = client.post("/api/lifecycle/notice",
                      json={"dossier_id": "e1", "notice": "NOC",
                            "date": sal["state"]["review_due"]}).json()
    assert noc["state"]["status"] == "Approved"


def test_unknown_notice_422(client):
    _start(client)
    r = client.post("/api/lifecycle/notice",
                    json={"dossier_id": "e1", "notice": "PIZZA"})
    assert r.status_code == 422


def test_notice_without_lifecycle_404(client):
    r = client.post("/api/lifecycle/notice",
                    json={"dossier_id": "ghost", "notice": "SAL",
                          "date": "2025-01-10"})
    assert r.status_code == 404
