"""FastAPI surface — the guided session walk start → … → READY, over TestClient."""


def test_catalog_exposes_the_whole_spine(client):
    r = client.get("/api/journey/catalog")
    assert r.status_code == 200
    body = r.json()
    keys = [s["key"] for s in body["stages"]]
    assert keys[0] == "orient" and keys[-1] == "track" and len(keys) == 11
    assert "ANDS" in body["submission_types"]
    assert any(rs["version"] == "M13A" for rs in body["be_rulesets"])


def test_start_returns_new_journey(client):
    r = client.post("/api/journey/start", json={"title": "Acme generic"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"]
    assert body["journey"]["position"]["current"] == 0   # orient
    assert body["readiness"]["status"] == "BLOCKED"


def test_intake_endpoint_steers_off_ands(client):
    r = client.post("/api/journey/intake",
                    json={"submission_type": "ANDS", "new_indication": True})
    assert r.status_code == 200
    rules = {a["rule"] for a in r.json()["assessment"]["advisories"]}
    assert "ands_not_for_new_indication" in rules


def test_full_walk_to_ready(client):
    sid = client.post("/api/journey/start", json={}).json()["id"]

    def adv(step, **data):
        return client.post(f"/api/journey/{sid}/advance",
                           json={"step": step, "data": data})

    adv("orient")
    adv("company", company_id="12345")
    adv("dossier", dossier_id="e123456")
    adv("submission", applicant="Acme Pharma", drug_product="Drugazole 10mg")
    adv("content")
    adv("validate", errors=0)
    adv("fees")
    adv("review")
    last = adv("sign")
    assert last.status_code == 200
    body = last.json()
    assert body["readiness"]["status"] == "READY"
    assert body["journey"]["position"]["current_key"] == "transmit"
    # and transmit completes the filing path
    final = adv("transmit", state="SUBMITTED").json()
    assert final["journey"]["position"]["transmitted"] is True


def test_advance_rejects_bad_dossier_id(client):
    sid = client.post("/api/journey/start", json={}).json()["id"]
    client.post(f"/api/journey/{sid}/advance",
                json={"step": "company", "data": {"company_id": "1"}})
    bad = client.post(f"/api/journey/{sid}/advance",
                      json={"step": "dossier", "data": {"dossier_id": "nope"}})
    assert bad.status_code == 422


def test_advance_blocks_validation_with_errors(client):
    sid = client.post("/api/journey/start", json={}).json()["id"]
    for step, data in [("company", {"company_id": "1"}),
                       ("dossier", {"dossier_id": "e123456"}),
                       ("submission", {"applicant": "A", "drug_product": "D"}),
                       ("content", {})]:
        client.post(f"/api/journey/{sid}/advance",
                    json={"step": step, "data": data})
    r = client.post(f"/api/journey/{sid}/advance",
                    json={"step": "validate", "data": {"errors": 4}})
    assert r.status_code == 422


def test_get_unknown_session_404(client):
    assert client.get("/api/journey/does-not-exist").status_code == 404


def test_dossier_id_assess_endpoint(client):
    r = client.post("/api/journey/dossier-id/assess",
                    json={"dossier_id": "e123456", "request_date": "2026-01-01",
                          "first_filing_date": "2026-06-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["format_ok"] is True
    assert body["lead_time"]["too_early"] is True   # >8 weeks ahead -> warns


def test_intake_with_session_persists(ctx):
    client = ctx.client
    sid = client.post("/api/journey/start", json={}).json()["id"]
    client.post("/api/journey/intake",
                json={"session_id": sid, "submission_type": "ANDS",
                      "drug_product": "Drugazole"})
    body = client.get(f"/api/journey/{sid}").json()
    assert body["title"] == "Drugazole"
    assert body["intake"]["route"]["submission_type"] == "ANDS"
