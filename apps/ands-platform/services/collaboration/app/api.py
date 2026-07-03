"""FastAPI surface for the collaboration service — thin glue over the service.

Every route parses the request, calls one application use-case, and shapes the
response. No business logic lives here (see :mod:`app.service`).
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Header, Query
from fastapi.responses import JSONResponse

from ands_shared import create_app

from .models import (BlockingDefectIn, CommentIn, HcAckIn, TaskIn,
                     TaskStatusIn)
from .service import CollaborationService


def build_app(service: CollaborationService) -> FastAPI:
    app = create_app(title="collaboration",
                     description="ANDS comments, tasks & notifications (REQ-109)")
    router = APIRouter(prefix="/api/collab", tags=["collaboration"])

    # Every authenticated request from the web proxy carries X-Tenant-Id.
    # Present → tenant-scoped isolation; absent → unscoped (mesh / tests).
    _Tenant = Header(default="", alias="X-Tenant-Id")

    # -- comments -------------------------------------------------------
    @router.post("/comments", status_code=201)
    def add_comment(body: CommentIn, x_tenant_id: str = _Tenant):
        return {"comment": service.add_comment(body.model_dump(),
                                               x_tenant_id or None)}

    @router.get("/comments")
    def list_comments(target_type: str = Query(...),
                      target_id: str = Query(...),
                      x_tenant_id: str = _Tenant):
        return service.list_comments(target_type, target_id, x_tenant_id or None)

    # -- tasks ----------------------------------------------------------
    @router.post("/tasks", status_code=201)
    def create_task(body: TaskIn, x_tenant_id: str = _Tenant):
        return {"task": service.create_task(body.model_dump(),
                                            x_tenant_id or None)}

    @router.get("/tasks")
    def list_tasks(assignee: str = "", dossier_id: str = "", status: str = "",
                   x_tenant_id: str = _Tenant):
        return service.list_tasks(assignee=assignee, dossier_id=dossier_id,
                                  status=status, tenant_id=x_tenant_id or None)

    @router.get("/tasks/summary")
    def tasks_summary(today: str = "", x_tenant_id: str = _Tenant):
        # portfolio roll-up: open tasks grouped by dossier → assignees +
        # blocked status (WS7). ``today`` optional (deterministic overdue).
        return service.task_summary(x_tenant_id or None, today=today)

    @router.post("/tasks/status")
    def update_status(body: TaskStatusIn, x_tenant_id: str = _Tenant):
        return {"task": service.update_task_status(body.id, body.status,
                                                   x_tenant_id or None)}

    # -- notification triggers -----------------------------------------
    @router.post("/notify/blocking-defect", status_code=201)
    def notify_blocking_defect(body: BlockingDefectIn,
                               x_tenant_id: str = _Tenant):
        notes = service.notify_blocking_defect(
            body.dossier_id, body.finding, body.recipients, x_tenant_id or None)
        return JSONResponse(status_code=201,
                            content={"notified": len(notes),
                                     "notifications": notes})

    @router.post("/notify/hc-ack", status_code=201)
    def notify_hc_ack(body: HcAckIn, x_tenant_id: str = _Tenant):
        notes = service.notify_hc_ack(
            body.dossier_id, body.core_id, body.recipients, x_tenant_id or None)
        return JSONResponse(status_code=201,
                            content={"notified": len(notes)})

    # -- inbox / outbox -------------------------------------------------
    @router.get("/inbox")
    def inbox(user: str = "", x_tenant_id: str = _Tenant):
        return service.inbox(user, x_tenant_id or None)

    @router.get("/outbox")
    def outbox(x_tenant_id: str = _Tenant):
        return service.outbox(x_tenant_id or None)

    app.include_router(router)
    return app
