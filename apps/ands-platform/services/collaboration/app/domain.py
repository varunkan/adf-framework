"""Collaboration domain logic — pure, framework-free, deterministic (REQ-109).

No FastAPI, no SQL, no I/O: just the rules for validating a comment, threading a
comment tree, building/validating a task and its status transitions, and shaping
the three notification kinds (task-assigned, blocking-defect, HC-ack) into inbox
items and outbound emails. The application layer persists and dispatches; this
module decides *what is valid* and *what a notification says*.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# -- comments ----------------------------------------------------------------
TARGET_LEAF = "leaf"
TARGET_FINDING = "finding"
TARGET_DOSSIER = "dossier"
TARGET_SEQUENCE = "sequence"
TARGET_TYPES = (TARGET_LEAF, TARGET_FINDING, TARGET_DOSSIER, TARGET_SEQUENCE)

# -- tasks -------------------------------------------------------------------
TASK_OPEN = "open"
TASK_IN_PROGRESS = "in_progress"
TASK_DONE = "done"
TASK_STATUSES = (TASK_OPEN, TASK_IN_PROGRESS, TASK_DONE)

# Allowed status moves. Reopening a done task is permitted; jumping straight from
# done back to in_progress is not (must reopen first) — a small workflow guard.
_ALLOWED_TRANSITIONS = {
    TASK_OPEN: {TASK_IN_PROGRESS, TASK_DONE},
    TASK_IN_PROGRESS: {TASK_OPEN, TASK_DONE},
    TASK_DONE: {TASK_OPEN},
}

# -- notification kinds ------------------------------------------------------
KIND_TASK_ASSIGNED = "task_assigned"
KIND_BLOCKING_DEFECT = "blocking_defect"
KIND_HC_ACK = "hc_ack"


def _s(value: Any) -> str:
    return str(value or "").strip()


# ---------------------------------------------------------------------------
# comments
# ---------------------------------------------------------------------------
def normalize_comment(data: dict) -> dict:
    """Validate + clean a comment. Returns ``{"valid", "comment"|"errors"}``.

    A comment must target one of :data:`TARGET_TYPES`, name a target, carry an
    author, and have non-empty body. ``parent_id`` (optional) threads a reply.
    """
    data = data or {}
    errors = []
    target_type = _s(data.get("target_type")).lower()
    target_id = _s(data.get("target_id"))
    author = _s(data.get("author"))
    body = _s(data.get("body"))
    if target_type not in TARGET_TYPES:
        errors.append({"rule": "comment_target_invalid",
                       "message": ("target_type must be one of "
                                   + ", ".join(TARGET_TYPES))})
    if not target_id:
        errors.append({"rule": "comment_target_id_required",
                       "message": "target_id is required"})
    if not author:
        errors.append({"rule": "comment_author_required",
                       "message": "author is required"})
    if not body:
        errors.append({"rule": "comment_body_required",
                       "message": "comment body must not be empty"})
    if errors:
        return {"valid": False, "errors": errors}
    parent_id = data.get("parent_id")
    return {"valid": True, "comment": {
        "target_type": target_type, "target_id": target_id,
        "author": author, "body": body,
        "parent_id": parent_id if parent_id not in ("", None) else None}}


def thread_comments(rows: list) -> list:
    """Nest a flat list of comment rows into a reply tree by ``parent_id``.

    Each returned node gains a ``replies`` list (recursively). Roots are rows
    with a falsy ``parent_id``, preserved in input order.
    """
    nodes = {r["id"]: {**r, "replies": []} for r in rows}
    roots = []
    for r in rows:
        node = nodes[r["id"]]
        parent = r.get("parent_id")
        if parent and parent in nodes:
            nodes[parent]["replies"].append(node)
        else:
            roots.append(node)
    return roots


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------
def build_task(data: dict) -> dict:
    """Validate + clean a task. Returns ``{"valid", "task"|"errors"}``.

    A task needs a title and an assignee; ``due_date`` (optional) must be an
    ISO ``YYYY-MM-DD`` date; status defaults to :data:`TASK_OPEN`.
    """
    data = data or {}
    errors = []
    title = _s(data.get("title"))
    assignee = _s(data.get("assignee"))
    if not title:
        errors.append({"rule": "task_title_required",
                       "message": "task title is required"})
    if not assignee:
        errors.append({"rule": "task_assignee_required",
                       "message": "task assignee is required"})
    due_date = _s(data.get("due_date"))
    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError:
            errors.append({"rule": "task_due_date_invalid",
                           "message": "due_date must be ISO YYYY-MM-DD"})
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "task": {
        "title": title, "assignee": assignee,
        "created_by": _s(data.get("created_by")),
        "due_date": due_date or None,
        "target_type": _s(data.get("target_type")).lower() or None,
        "target_id": _s(data.get("target_id")) or None,
        "dossier_id": _s(data.get("dossier_id")) or None,
        "status": TASK_OPEN}}


def summarize_open_tasks(tasks: list, today: str = "") -> dict:
    """Portfolio roll-up of live (non-done) tasks, grouped by dossier (WS7).

    Surfaces — from the REAL task store — who is on the hook and whether a
    dossier is blocked, so a CRO/CDMO PM sees the team at a glance without
    opening each dossier. A dossier with only completed (or no) tasks is
    omitted. ``blocked`` is derived: any open task whose ``due_date`` is on or
    before ``today`` is overdue → the dossier reads as blocked. Assignees are
    distinct and sorted for a stable display.
    """
    today = _s(today)
    out: dict = {}
    for t in tasks or []:
        if _s(t.get("status")) == TASK_DONE:
            continue
        did = _s(t.get("dossier_id"))
        if not did:
            continue
        row = out.setdefault(did, {"open": 0, "overdue": 0,
                                   "assignees": set(), "blocked": False})
        row["open"] += 1
        assignee = _s(t.get("assignee"))
        if assignee:
            row["assignees"].add(assignee)
        due = _s(t.get("due_date"))
        if due and today and due < today:   # strictly past due = overdue
            row["overdue"] += 1
            row["blocked"] = True
    return {did: {"open": r["open"], "overdue": r["overdue"],
                  "assignees": sorted(r["assignees"]), "blocked": r["blocked"]}
            for did, r in out.items()}


def validate_status_transition(old: str, new: str) -> dict:
    """Is moving a task from ``old`` to ``new`` allowed? ``{"valid", "rule"?}``."""
    new = _s(new)
    if new not in TASK_STATUSES:
        return {"valid": False, "rule": "task_status_unknown",
                "message": ("status must be one of " + ", ".join(TASK_STATUSES))}
    if new not in _ALLOWED_TRANSITIONS.get(old, set()):
        return {"valid": False, "rule": "task_status_illegal_transition",
                "message": f"cannot move a task from {old} to {new}"}
    return {"valid": True}


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------
def notification_for_assignment(task: dict) -> dict:
    """In-app/email notification for a newly assigned task."""
    title = _s(task.get("title"))
    due = _s(task.get("due_date"))
    body = f"You have been assigned the task “{title}”."
    if due:
        body += f" Due {due}."
    return {"kind": KIND_TASK_ASSIGNED, "recipient": _s(task.get("assignee")),
            "subject": f"Task assigned: {title}", "body": body,
            "meta": {"task_id": task.get("id"), "due_date": task.get("due_date")}}


def notification_for_blocking_defect(dossier_id: str, finding: Any,
                                     recipient: str) -> dict:
    """Notification that a blocking validation defect needs attention."""
    if isinstance(finding, dict):
        rule = _s(finding.get("rule"))
        message = _s(finding.get("message")) or rule
    else:
        rule = ""
        message = _s(finding)
    dossier_id = _s(dossier_id)
    return {"kind": KIND_BLOCKING_DEFECT, "recipient": _s(recipient),
            "subject": f"Blocking defect on dossier {dossier_id}",
            "body": (f"Dossier {dossier_id} has a blocking validation defect "
                     f"{('[' + rule + '] ') if rule else ''}{message}".strip()),
            "meta": {"dossier_id": dossier_id, "rule": rule}}


def notification_for_hc_ack(dossier_id: str, core_id: str,
                            recipient: str) -> dict:
    """Notification that Health Canada acknowledged a transmission."""
    dossier_id = _s(dossier_id)
    core_id = _s(core_id)
    return {"kind": KIND_HC_ACK, "recipient": _s(recipient),
            "subject": f"Health Canada acknowledged dossier {dossier_id}",
            "body": (f"A Health Canada Acknowledgement Receipt was received for "
                     f"dossier {dossier_id} (Core ID {core_id})."),
            "meta": {"dossier_id": dossier_id, "core_id": core_id}}


def format_email(notification: dict) -> dict:
    """Project a notification into an outbound email payload."""
    return {"to": _s(notification.get("recipient")),
            "subject": _s(notification.get("subject")),
            "body": _s(notification.get("body"))}
