"""Collaboration application service — the use-cases (REQ-109).

Orchestrates the pure :mod:`app.domain` rules over a repository port and the
event bus. It is the single place that (a) validates via the domain, (b)
persists via the repo, (c) emits notifications to the in-app inbox + email
outbox, and (d) publishes/consumes domain events. It depends on *ports*, so the
same code runs over SQLite+in-memory-bus (dev/test) or Postgres+Redis (prod).
"""

from __future__ import annotations

from typing import Any

from ands_shared import EventEnvelope, EventType, ProblemError

from . import domain
from .ports import CollaborationRepository


class CollaborationService:
    def __init__(self, repo: CollaborationRepository, bus,
                 *, source: str = "collaboration") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    # -- wiring -------------------------------------------------------------
    def register(self) -> "CollaborationService":
        """Subscribe to the cross-service events that produce notifications.

        A blocking validation defect and a Health Canada acknowledgement are
        owned by other services; collaboration reacts to their events to notify
        the right people (REQ-109 triggers). Returns self for chaining.
        """
        self.bus.subscribe(EventType.VALIDATION_FAILED, self.on_validation_failed)
        self.bus.subscribe(EventType.TRANSMISSION_HC_ACK, self.on_hc_ack)
        return self

    # -- comments -----------------------------------------------------------
    def add_comment(self, data: dict) -> dict:
        res = domain.normalize_comment(data)
        if not res["valid"]:
            raise ProblemError(422, "Invalid comment",
                               detail="comment failed validation",
                               errors=res["errors"])
        comment = self.repo.add_comment(res["comment"])
        self.bus.publish(EventEnvelope.make(
            EventType.COLLAB_COMMENT_ADDED, source=self.source,
            dossier_id=comment.get("target_id"),
            data={"comment_id": comment["id"],
                  "target_type": comment["target_type"],
                  "target_id": comment["target_id"]}))
        return comment

    def list_comments(self, target_type: str, target_id: str) -> dict:
        rows = self.repo.list_comments(target_type, target_id)
        return {"comments": domain.thread_comments(rows), "count": len(rows)}

    # -- tasks --------------------------------------------------------------
    def create_task(self, data: dict) -> dict:
        res = domain.build_task(data)
        if not res["valid"]:
            raise ProblemError(422, "Invalid task",
                               detail="task failed validation",
                               errors=res["errors"])
        task = self.repo.add_task(res["task"])
        # Trigger 1: assignment notification.
        self._emit(domain.notification_for_assignment(task))
        self.bus.publish(EventEnvelope.make(
            EventType.COLLAB_TASK_ASSIGNED, source=self.source,
            dossier_id=task.get("dossier_id"),
            data={"task_id": task["id"], "assignee": task["assignee"]}))
        return task

    def list_tasks(self, *, assignee: str = "", dossier_id: str = "",
                   status: str = "") -> dict:
        tasks = self.repo.list_tasks(assignee=assignee, dossier_id=dossier_id,
                                     status=status)
        return {"tasks": tasks, "count": len(tasks)}

    def update_task_status(self, task_id: str, status: str) -> dict:
        task = self.repo.get_task(task_id)
        if not task:
            raise ProblemError(404, "Task not found",
                               detail=f"no task with id {task_id}")
        check = domain.validate_status_transition(task["status"], status)
        if not check["valid"]:
            http = 422 if check["rule"] == "task_status_unknown" else 409
            raise ProblemError(http, check["message"], rule=check["rule"])
        return self.repo.set_task_status(task_id, status)

    # -- notifications ------------------------------------------------------
    def notify_blocking_defect(self, dossier_id: str, finding: Any,
                               recipients: list[str]) -> list[dict]:
        notes = []
        for recipient in recipients or []:
            note = domain.notification_for_blocking_defect(
                dossier_id, finding, recipient)
            self._emit(note)
            notes.append(note)
        return notes

    def notify_hc_ack(self, dossier_id: str, core_id: str,
                      recipients: list[str]) -> list[dict]:
        notes = []
        for recipient in recipients or []:
            note = domain.notification_for_hc_ack(dossier_id, core_id, recipient)
            self._emit(note)
            notes.append(note)
        return notes

    def inbox(self, user: str) -> dict:
        rows = self.repo.inbox(user)
        unread = sum(1 for n in rows if not n["read"])
        return {"notifications": rows, "unread": unread, "count": len(rows)}

    def outbox(self) -> dict:
        rows = self.repo.outbox()
        pending = sum(1 for e in rows if not e["sent"])
        return {"emails": rows, "pending": pending, "count": len(rows)}

    # -- event handlers -----------------------------------------------------
    def on_validation_failed(self, event: EventEnvelope) -> None:
        """Trigger 2: a blocking validation defect → notify the owners."""
        data = event.data or {}
        finding = data.get("finding") or {"rule": data.get("rule"),
                                           "message": data.get("message")}
        self.notify_blocking_defect(
            event.dossier_id or data.get("dossier_id") or "",
            finding, data.get("recipients") or [])

    def on_hc_ack(self, event: EventEnvelope) -> None:
        """Trigger 3: a Health Canada acknowledgement → notify the filers."""
        data = event.data or {}
        self.notify_hc_ack(
            event.dossier_id or data.get("dossier_id") or "",
            data.get("core_id") or "", data.get("recipients") or [])

    # -- internal -----------------------------------------------------------
    def _emit(self, note: dict) -> None:
        """Fan a notification to the in-app inbox AND the email outbox."""
        self.repo.add_notification(note)
        self.repo.enqueue_email(domain.format_email(note))
