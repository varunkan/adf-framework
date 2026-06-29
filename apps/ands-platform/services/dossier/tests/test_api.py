"""End-to-end dossier API via FastAPI TestClient — REQ-103 + REQ-098."""


def test_placement_endpoint(client):
    r = client.get("/api/dossier/placement")
    assert r.status_code == 200
    headings = [e["heading"] for e in r.json()["entries"]]
    assert "1.3.1" in headings


# -- content plans (REQ-103) -------------------------------------------------
def test_create_and_get_content_plan(client):
    r = client.post("/api/dossier/content-plans",
                    json={"dossier_id": "e123456", "submission_type": "ANDS"})
    assert r.status_code == 201
    plan = r.json()["plan"]
    assert plan["submission_type"] == "ANDS"
    assert plan["progress"]["total"] == 6 and plan["progress"]["pct"] == 0
    assert len(plan["items"]) == 6
    got = client.get("/api/dossier/content-plans",
                     params={"dossier_id": "e123456"}).json()["plan"]
    assert got["id"] == plan["id"]


def test_create_plan_unknown_type_422(client):
    r = client.post("/api/dossier/content-plans",
                    json={"dossier_id": "e1", "submission_type": "XYZ"})
    assert r.status_code == 422
    assert r.json()["rule"] == "submission_type_invalid"


def test_create_plan_missing_dossier_422(client):
    r = client.post("/api/dossier/content-plans",
                    json={"submission_type": "ANDS"})
    assert r.status_code == 422
    assert r.json()["rule"] == "dossier_id_required"


def test_assign_item_sets_assignee_and_due(client):
    plan = client.post("/api/dossier/content-plans",
                       json={"dossier_id": "e1",
                             "submission_type": "ANDS"}).json()["plan"]
    item_id = plan["items"][0]["id"]
    r = client.post("/api/dossier/content-plans/item/assign",
                    json={"id": item_id, "assignee": "bob",
                          "due_date": "2026-08-01"})
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["assignee"] == "bob" and item["due_date"] == "2026-08-01"


def test_assign_item_bad_due_date_422(client):
    plan = client.post("/api/dossier/content-plans",
                       json={"dossier_id": "e1",
                             "submission_type": "ANDS"}).json()["plan"]
    r = client.post("/api/dossier/content-plans/item/assign",
                    json={"id": plan["items"][0]["id"], "assignee": "b",
                          "due_date": "soon"})
    assert r.status_code == 422
    assert r.json()["rule"] == "item_due_date_invalid"


def test_item_status_update_rolls_up_progress(client):
    plan = client.post("/api/dossier/content-plans",
                       json={"dossier_id": "e1",
                             "submission_type": "ANDS"}).json()["plan"]
    item_id = plan["items"][0]["id"]
    r = client.post("/api/dossier/content-plans/item/status",
                    json={"id": item_id, "status": "complete"})
    assert r.status_code == 200
    body = r.json()
    assert body["item"]["status"] == "complete"
    assert body["progress"]["done"] == 1


def test_item_status_unknown_422(client):
    plan = client.post("/api/dossier/content-plans",
                       json={"dossier_id": "e1",
                             "submission_type": "ANDS"}).json()["plan"]
    r = client.post("/api/dossier/content-plans/item/status",
                    json={"id": plan["items"][0]["id"], "status": "banana"})
    assert r.status_code == 422


def test_assign_item_not_found_404(client):
    r = client.post("/api/dossier/content-plans/item/assign",
                    json={"id": "nope", "assignee": "b"})
    assert r.status_code == 404


# -- bilingual product monograph (REQ-098) ----------------------------------
def test_monograph_blocked_until_both_languages(client):
    client.post("/api/dossier/monograph/leaves",
                json={"dossier_id": "e9", "lang": "en", "title": "EN PM"})
    status = client.get("/api/dossier/monograph/status",
                        params={"dossier_id": "e9"}).json()
    assert status["status"] == "blocked"
    assert any(f["rule"] == "pm_fr_missing" for f in status["findings"])

    client.post("/api/dossier/monograph/leaves",
                json={"dossier_id": "e9", "lang": "fr", "title": "FR PM"})
    status = client.get("/api/dossier/monograph/status",
                        params={"dossier_id": "e9"}).json()
    assert status["status"] == "complete"


def test_monograph_leaf_invalid_lang_422(client):
    r = client.post("/api/dossier/monograph/leaves",
                    json={"dossier_id": "e9", "lang": "de", "title": "x"})
    assert r.status_code == 422
    assert any(e["rule"] == "pm_lang_invalid" for e in r.json()["errors"])
