"""End-to-end validation API via FastAPI TestClient (REQ-104)."""

from tests.conftest import clean_context


def test_list_rulesets(client):
    r = client.get("/api/validation/rulesets")
    assert r.status_code == 200
    assert r.json()["active"] == "5.3"


def test_ruleset_unknown_404(client):
    r = client.get("/api/validation/ruleset", params={"version": "9.9"})
    assert r.status_code == 404


def test_run_clean_is_not_blocking_and_persists(client):
    r = client.post("/api/validation/run",
                    json={"context": clean_context(), "dossier_id": "e123456"})
    assert r.status_code == 200
    body = r.json()
    assert body["blocking"] is False and body["error_count"] == 0
    assert body["run_id"]
    report = client.get("/api/validation/report",
                        params={"dossier_id": "e123456"}).json()
    assert report["result"]["error_count"] == 0


def test_run_blocking_reports_errors(client):
    ctx = clean_context()
    ctx["files"][0]["encrypted"] = True
    r = client.post("/api/validation/run",
                    json={"context": ctx, "dossier_id": "e123456"})
    body = r.json()
    assert body["blocking"] is True
    assert any(f["rule_id"] == "A09" for f in body["errors"])


def test_inline_endpoint(client):
    ctx = clean_context()
    ctx["files"][0]["encrypted"] = True
    r = client.post("/api/validation/inline", json={"context": ctx})
    assert r.status_code == 200
    assert r.json()["blocking"]


def test_fix_endpoint_clears_defect(client):
    ctx = clean_context()
    ctx["files"][0]["encrypted"] = True
    r = client.post("/api/validation/fix",
                    json={"context": ctx, "fix_id": "decrypt-pdf",
                          "file": "m1/ca/cover.pdf"})
    assert r.status_code == 200
    assert r.json()["inline"]["blocking"] is False


def test_report_missing_404(client):
    r = client.get("/api/validation/report", params={"dossier_id": "nope"})
    assert r.status_code == 404
