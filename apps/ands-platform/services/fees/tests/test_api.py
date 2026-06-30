"""End-to-end fees API via FastAPI TestClient."""


def test_groupings(client):
    r = client.get("/api/fees/groupings")
    assert r.status_code == 200
    keys = {g["key"] for g in r.json()["groupings"]}
    assert "comparative-studies" in keys


def test_ands_fee_endpoint(client):
    r = client.get("/api/fees/ands", params={"submission_date": "2025-06-01"})
    assert r.status_code == 200
    assert r.json()["amount"] == 70750.0


def test_ands_fee_bad_date_422(client):
    r = client.get("/api/fees/ands", params={"submission_date": "not-a-date"})
    assert r.status_code == 422


def test_mitigation_endpoint(client):
    r = client.post("/api/fees/mitigation",
                    json={"fee": 70750.0, "small_business": True,
                          "first_submission": True})
    assert r.json()["net_fee"] == 0.0


def test_right_to_sell_endpoint(client):
    r = client.get("/api/fees/right-to-sell",
                   params={"drug_type": "prescription", "as_of": "2025-09-15"})
    body = r.json()
    assert body["amount"] == 5531.0 and body["reminder_due"] is True


def test_right_to_sell_unknown_type_422(client):
    r = client.get("/api/fees/right-to-sell",
                   params={"drug_type": "moon-cheese", "as_of": "2025-09-15"})
    assert r.status_code == 422
