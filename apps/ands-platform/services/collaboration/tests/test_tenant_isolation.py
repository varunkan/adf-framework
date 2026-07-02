"""Tenant-isolation contract (CRO regulatory rejection fix) — REQ-109.

Mirrors the dossier service's uniform contract: an authenticated request from
the web proxy carries ``X-Tenant-Id``. Rows created under tenant A must be
INVISIBLE to tenant B's list endpoints and 404 on B's mutate; A still sees its
own rows; a request with NO header stays UNSCOPED (in-process mesh / tests).
"""

TA = {"X-Tenant-Id": "tenant-A"}
TB = {"X-Tenant-Id": "tenant-B"}


# -- tasks -------------------------------------------------------------------
def test_task_list_is_partitioned_by_tenant(client):
    a = client.post("/api/collab/tasks", headers=TA, json={
        "title": "A secret task", "assignee": "bob",
        "dossier_id": "eAAAA"}).json()["task"]
    client.post("/api/collab/tasks", headers=TB, json={
        "title": "B task", "assignee": "carol", "dossier_id": "eBBBB"})

    # A sees only its own task
    mine = client.get("/api/collab/tasks", headers=TA).json()
    assert mine["count"] == 1
    assert mine["tasks"][0]["id"] == a["id"]

    # B never sees A's task
    theirs = client.get("/api/collab/tasks", headers=TB).json()
    assert all(t["id"] != a["id"] for t in theirs["tasks"])
    assert theirs["count"] == 1

    # no header = unscoped: both rows visible (mesh / existing tests)
    everyone = client.get("/api/collab/tasks").json()
    assert everyone["count"] == 2


def test_task_status_mutate_on_foreign_task_is_404(client):
    a = client.post("/api/collab/tasks", headers=TA, json={
        "title": "A task", "assignee": "bob"}).json()["task"]

    # B cannot mutate A's task — 404 (never 403; don't confirm existence)
    r = client.post("/api/collab/tasks/status", headers=TB,
                    json={"id": a["id"], "status": "done"})
    assert r.status_code == 404

    # A still can
    ok = client.post("/api/collab/tasks/status", headers=TA,
                     json={"id": a["id"], "status": "done"})
    assert ok.status_code == 200
    assert ok.json()["task"]["status"] == "done"


# -- comments ----------------------------------------------------------------
def test_comment_list_is_partitioned_by_tenant(client):
    client.post("/api/collab/comments", headers=TA, json={
        "target_type": "leaf", "target_id": "shared", "author": "a",
        "body": "A note"})
    client.post("/api/collab/comments", headers=TB, json={
        "target_type": "leaf", "target_id": "shared", "author": "b",
        "body": "B note"})

    a_view = client.get("/api/collab/comments", headers=TA,
                        params={"target_type": "leaf", "target_id": "shared"})
    assert a_view.json()["count"] == 1
    b_view = client.get("/api/collab/comments", headers=TB,
                        params={"target_type": "leaf", "target_id": "shared"})
    assert b_view.json()["count"] == 1
    # unscoped sees both
    both = client.get("/api/collab/comments",
                      params={"target_type": "leaf", "target_id": "shared"})
    assert both.json()["count"] == 2


# -- inbox / notifications ----------------------------------------------------
def test_inbox_is_partitioned_by_tenant(client):
    # task assignment produces a notification for the assignee
    client.post("/api/collab/tasks", headers=TA, json={
        "title": "A work", "assignee": "shared-user"})
    client.post("/api/collab/tasks", headers=TB, json={
        "title": "B work", "assignee": "shared-user"})

    a_inbox = client.get("/api/collab/inbox", headers=TA,
                         params={"user": "shared-user"}).json()
    assert a_inbox["count"] == 1
    assert a_inbox["unread"] == 1

    b_inbox = client.get("/api/collab/inbox", headers=TB,
                         params={"user": "shared-user"}).json()
    assert b_inbox["count"] == 1

    # unscoped: both notifications visible
    everyone = client.get("/api/collab/inbox",
                          params={"user": "shared-user"}).json()
    assert everyone["count"] == 2


# -- outbox ------------------------------------------------------------------
def test_outbox_is_partitioned_by_tenant(client):
    client.post("/api/collab/notify/hc-ack", headers=TA, json={
        "dossier_id": "eAAAA", "core_id": "CORE-A", "recipients": ["ra"]})
    client.post("/api/collab/notify/hc-ack", headers=TB, json={
        "dossier_id": "eBBBB", "core_id": "CORE-B", "recipients": ["ra"]})

    a_out = client.get("/api/collab/outbox", headers=TA).json()
    assert a_out["count"] == 1
    assert all("CORE-B" not in e["body"] for e in a_out["emails"])

    b_out = client.get("/api/collab/outbox", headers=TB).json()
    assert b_out["count"] == 1

    everyone = client.get("/api/collab/outbox").json()
    assert everyone["count"] == 2
