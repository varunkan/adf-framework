"""F7 / REQ-116 — batch validation jobs."""

from app import engine

from tests.conftest import clean_context


def test_run_batch_aggregates():
    bad = clean_context()
    bad["files"][0]["encrypted"] = True
    res = engine.run_batch([clean_context(), bad])
    assert res["count"] == 2 and res["blocking_count"] == 1
    assert res["all_clear"] is False
    assert res["total_errors"] >= 1


def test_batch_api_submit_and_fetch(client):
    bad = clean_context()
    bad["files"][0]["encrypted"] = True
    job = client.post("/api/validation/batch",
                      json={"contexts": [clean_context(), bad]})
    assert job.status_code == 201
    body = job.json()
    assert body["status"] == "complete"
    jid = body["id"]
    assert body["result"]["blocking_count"] == 1
    fetched = client.get(f"/api/validation/batch/{jid}").json()
    assert fetched["result"]["count"] == 2


def test_batch_all_clear(client):
    job = client.post("/api/validation/batch",
                      json={"contexts": [clean_context()]}).json()
    assert job["result"]["all_clear"] is True


def test_empty_batch_422(client):
    assert client.post("/api/validation/batch",
                       json={"contexts": []}).status_code == 422


def test_unknown_job_404(client):
    assert client.get("/api/validation/batch/nope").status_code == 404
