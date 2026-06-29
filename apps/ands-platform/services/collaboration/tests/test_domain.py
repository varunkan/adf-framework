"""Pure domain logic — no HTTP, no sqlite (REQ-109)."""

from app import domain


# -- comments ----------------------------------------------------------------
def test_normalize_comment_accepts_valid():
    out = domain.normalize_comment({
        "target_type": "leaf", "target_id": "m1-3-1-product-monograph",
        "author": "alice", "body": "Please confirm the FR pairing."})
    assert out["valid"]
    assert out["comment"]["target_type"] == "leaf"
    assert out["comment"]["author"] == "alice"
    assert out["comment"]["parent_id"] is None


def test_normalize_comment_rejects_empty_body():
    out = domain.normalize_comment({
        "target_type": "leaf", "target_id": "x", "author": "a", "body": "  "})
    assert not out["valid"]
    assert any(e["rule"] == "comment_body_required" for e in out["errors"])


def test_normalize_comment_rejects_unknown_target_type():
    out = domain.normalize_comment({
        "target_type": "planet", "target_id": "x", "author": "a", "body": "hi"})
    assert not out["valid"]
    assert any(e["rule"] == "comment_target_invalid" for e in out["errors"])


def test_normalize_comment_keeps_finding_target_and_parent():
    out = domain.normalize_comment({
        "target_type": "finding", "target_id": "A09", "author": "qc",
        "body": "fixed in 0001", "parent_id": "abc123"})
    assert out["valid"]
    assert out["comment"]["parent_id"] == "abc123"


def test_thread_comments_nests_replies():
    rows = [
        {"id": "1", "parent_id": None, "body": "root"},
        {"id": "2", "parent_id": "1", "body": "reply"},
        {"id": "3", "parent_id": "2", "body": "reply-of-reply"},
        {"id": "4", "parent_id": None, "body": "second root"},
    ]
    tree = domain.thread_comments(rows)
    assert [n["id"] for n in tree] == ["1", "4"]
    assert tree[0]["replies"][0]["id"] == "2"
    assert tree[0]["replies"][0]["replies"][0]["id"] == "3"
    assert tree[1]["replies"] == []


# -- tasks -------------------------------------------------------------------
def test_build_task_accepts_valid_defaults_open():
    out = domain.build_task({
        "title": "Upload FR PM", "assignee": "bob",
        "due_date": "2026-08-01", "dossier_id": "e123456"})
    assert out["valid"]
    assert out["task"]["status"] == domain.TASK_OPEN
    assert out["task"]["assignee"] == "bob"
    assert out["task"]["due_date"] == "2026-08-01"


def test_build_task_rejects_empty_title():
    out = domain.build_task({"title": " ", "assignee": "bob"})
    assert not out["valid"]
    assert any(e["rule"] == "task_title_required" for e in out["errors"])


def test_build_task_rejects_missing_assignee():
    out = domain.build_task({"title": "x", "assignee": ""})
    assert not out["valid"]
    assert any(e["rule"] == "task_assignee_required" for e in out["errors"])


def test_build_task_rejects_bad_due_date():
    out = domain.build_task({
        "title": "x", "assignee": "b", "due_date": "next tuesday"})
    assert not out["valid"]
    assert any(e["rule"] == "task_due_date_invalid" for e in out["errors"])


def test_status_transition_open_to_done_ok():
    assert domain.validate_status_transition(
        domain.TASK_OPEN, domain.TASK_DONE)["valid"]


def test_status_transition_unknown_rejected():
    out = domain.validate_status_transition(domain.TASK_OPEN, "banana")
    assert not out["valid"]
    assert out["rule"] == "task_status_unknown"


def test_status_transition_illegal_rejected():
    out = domain.validate_status_transition(
        domain.TASK_DONE, domain.TASK_IN_PROGRESS)
    assert not out["valid"]
    assert out["rule"] == "task_status_illegal_transition"


# -- notifications -----------------------------------------------------------
def test_notification_for_assignment_carries_assignee_and_title():
    note = domain.notification_for_assignment({
        "id": "t5", "title": "Upload FR PM", "assignee": "bob",
        "due_date": "2026-08-01"})
    assert note["kind"] == domain.KIND_TASK_ASSIGNED
    assert note["recipient"] == "bob"
    assert "Upload FR PM" in note["subject"] + note["body"]
    assert "2026-08-01" in note["body"]


def test_notification_for_blocking_defect_carries_dossier_and_finding():
    note = domain.notification_for_blocking_defect(
        "e123456", {"rule": "A09", "message": "PDF is encrypted"}, "qc")
    assert note["kind"] == domain.KIND_BLOCKING_DEFECT
    assert note["recipient"] == "qc"
    assert "e123456" in note["subject"] + note["body"]
    assert "PDF is encrypted" in note["body"]


def test_notification_for_hc_ack_carries_core_id():
    note = domain.notification_for_hc_ack("e123456", "CORE-9988", "ra")
    assert note["kind"] == domain.KIND_HC_ACK
    assert "CORE-9988" in note["body"]


def test_format_email_maps_recipient_subject_body():
    note = domain.notification_for_hc_ack("e1", "C1", "ra")
    email = domain.format_email(note)
    assert email["to"] == "ra"
    assert email["subject"] == note["subject"]
    assert email["body"] == note["body"]
