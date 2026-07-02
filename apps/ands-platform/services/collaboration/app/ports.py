"""Repository port for the collaboration service (hexagonal).

The application :class:`~app.service.CollaborationService` depends only on this
Protocol — never a concrete store. SQLite (dev/test) and Postgres (prod) adapters
both satisfy it, so they are interchangeable and share one contract test.
"""

from __future__ import annotations

from typing import Protocol


class CollaborationRepository(Protocol):
    # ``tenant_id`` follows the uniform isolation contract: persisted on create,
    # and — when present on a list — restricts results to that tenant. Absent
    # (None/"") means UNSCOPED (in-process mesh / tests): return everything.

    # comments
    def add_comment(self, comment: dict,
                    tenant_id: str | None = None) -> dict: ...
    def list_comments(self, target_type: str, target_id: str,
                      tenant_id: str | None = None) -> list[dict]: ...

    # tasks
    def add_task(self, task: dict, tenant_id: str | None = None) -> dict: ...
    def list_tasks(self, *, assignee: str = "", dossier_id: str = "",
                   status: str = "",
                   tenant_id: str | None = None) -> list[dict]: ...
    def get_task(self, task_id: str) -> dict | None: ...
    def set_task_status(self, task_id: str, status: str) -> dict | None: ...

    # notifications (in-app inbox) + email outbox
    def add_notification(self, note: dict,
                         tenant_id: str | None = None) -> dict: ...
    def enqueue_email(self, email: dict,
                      tenant_id: str | None = None) -> dict: ...
    def inbox(self, user: str, tenant_id: str | None = None) -> list[dict]: ...
    def outbox(self, tenant_id: str | None = None) -> list[dict]: ...
