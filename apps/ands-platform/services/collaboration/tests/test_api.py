"""End-to-end HTTP API via FastAPI TestClient (real ASGI) — REQ-109."""

from app import domain


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "collaboration"


# -- comments ----------------------------------------------------------------
def test_post_comment_then_list(client):
    r = client.post("/api/collab/comments", json={
        "target_type": "leaf", "target_id": "m1-3-1-pm",
        "author": "alice", "body": "Confirm FR pairing"})
    assert r.status_code == 201
    assert r.json()["comment"]["author"] == "alice"
    r = client.get("/api/collab/comments",
                   params={"target_type": "leaf", "target_id": "m1-3-1-pm"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["comments"][0]["body"] == "Confirm FR pairing"


def test_reply_is_threaded(client):
    root = client.post("/api/collab/comments", json={
        "target_type": "finding", "target_id": "A09",
        "author": "qc", "body": "still failing?"}).json()
    parent_id = root["comment"]["id"]
    r = client.post("/api/collab/comments", json={
        "target_type": "finding", "target_id": "A09",
        "author": "ra", "body": "fixed in 0001", "parent_id": parent_id})
    assert r.status_code == 201
    listing = client.get("/api/collab/comments",
                         params={"target_type": "finding",
                                 "target_id": "A09"}).json()
    assert listing["count"] == 2
    roots = listing["comments"]
    assert len(roots) == 1
    assert roots[0]["replies"][0]["body"] == "fixed in 0001"


def test_comment_empty_body_is_problem_422(client):
    r = client.post("/api/collab/comments", json={
        "target_type": "leaf", "target_id": "x", "author": "a", "body": ""})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert any(e["rule"] == "comment_body_required"
               for e in r.json()["errors"])


# -- tasks + assignment notification ----------------------------------------
def test_create_task_notifies_assignee_inbox(client):
    r = client.post("/api/collab/tasks", json={
        "title": "Upload FR Product Monograph", "assignee": "bob",
        "due_date": "2026-08-01", "dossier_id": "e123456"})
    assert r.status_code == 201
    assert r.json()["task"]["status"] == "open"
    inbox = client.get("/api/collab/inbox", params={"user": "bob"}).json()
    assert inbox["unread"] == 1
    note = inbox["notifications"][0]
    assert "Upload FR Product Monograph" in note["subject"] + note["body"]
    assert note["kind"] == domain.KIND_TASK_ASSIGNED


def test_create_task_invalid_is_422(client):
    r = client.post("/api/collab/tasks", json={"title": "", "assignee": "bob"})
    assert r.status_code == 422
    assert any(e["rule"] == "task_title_required" for e in r.json()["errors"])


def test_list_tasks_filtered(client):
    client.post("/api/collab/tasks", json={"title": "t1", "assignee": "bob"})
    client.post("/api/collab/tasks", json={"title": "t2", "assignee": "carol"})
    mine = client.get("/api/collab/tasks", params={"assignee": "bob"}).json()
    assert mine["count"] == 1
    assert mine["tasks"][0]["title"] == "t1"
    opened = client.get("/api/collab/tasks", params={"status": "open"}).json()
    assert opened["count"] == 2


def test_task_status_update_open_to_done(client):
    tid = client.post("/api/collab/tasks",
                      json={"title": "t", "assignee": "bob"}).json()["task"]["id"]
    r = client.post("/api/collab/tasks/status", json={"id": tid, "status": "done"})
    assert r.status_code == 200
    assert r.json()["task"]["status"] == "done"


def test_task_status_unknown_422(client):
    tid = client.post("/api/collab/tasks",
                      json={"title": "t", "assignee": "bob"}).json()["task"]["id"]
    r = client.post("/api/collab/tasks/status",
                    json={"id": tid, "status": "banana"})
    assert r.status_code == 422


def test_task_status_illegal_transition_409(client):
    tid = client.post("/api/collab/tasks",
                      json={"title": "t", "assignee": "bob"}).json()["task"]["id"]
    client.post("/api/collab/tasks/status", json={"id": tid, "status": "done"})
    r = client.post("/api/collab/tasks/status",
                    json={"id": tid, "status": "in_progress"})
    assert r.status_code == 409


def test_task_status_not_found_404(client):
    r = client.post("/api/collab/tasks/status",
                    json={"id": "nope", "status": "done"})
    assert r.status_code == 404


# -- notification triggers + outbox -----------------------------------------
def test_blocking_defect_notifies_recipients(client):
    r = client.post("/api/collab/notify/blocking-defect", json={
        "dossier_id": "e123456",
        "finding": {"rule": "A09", "message": "PDF is encrypted"},
        "recipients": ["alice", "bob"]})
    assert r.status_code == 201
    assert r.json()["notified"] == 2
    inbox = client.get("/api/collab/inbox", params={"user": "alice"}).json()
    assert inbox["unread"] == 1
    assert inbox["notifications"][0]["kind"] == domain.KIND_BLOCKING_DEFECT


def test_hc_ack_enqueues_email_outbox(client):
    r = client.post("/api/collab/notify/hc-ack", json={
        "dossier_id": "e123456", "core_id": "CORE-9988",
        "recipients": ["ra"]})
    assert r.status_code == 201
    outbox = client.get("/api/collab/outbox").json()
    assert outbox["pending"] >= 1
    assert any("CORE-9988" in e["body"] for e in outbox["emails"])


def test_inbox_empty_for_unknown_user(client):
    inbox = client.get("/api/collab/inbox", params={"user": "nobody"}).json()
    assert inbox["unread"] == 0
    assert inbox["notifications"] == []


# -- portfolio open-task summary (WS7) ---------------------------------------
def test_tasks_summary_groups_open_tasks_by_dossier(client):
    client.post("/api/collab/tasks", json={
        "title": "Draft 1.3.1 FR PM", "assignee": "alice",
        "dossier_id": "e100001", "due_date": "2026-08-01"})
    client.post("/api/collab/tasks", json={
        "title": "Review CQAs", "assignee": "bob", "dossier_id": "e100001"})
    client.post("/api/collab/tasks", json={
        "title": "Unrelated", "assignee": "carol", "dossier_id": "e200002"})
    body = client.get("/api/collab/tasks/summary").json()
    by = body["by_dossier"]
    assert by["e100001"]["open"] == 2
    assert by["e100001"]["assignees"] == ["alice", "bob"]
    assert set(by) == {"e100001", "e200002"}


def test_tasks_summary_excludes_completed_tasks(client):
    tid = client.post("/api/collab/tasks", json={
        "title": "t", "assignee": "z", "dossier_id": "e300003"
    }).json()["task"]["id"]
    client.post("/api/collab/tasks/status", json={"id": tid, "status": "done"})
    body = client.get("/api/collab/tasks/summary").json()
    assert "e300003" not in body["by_dossier"]
