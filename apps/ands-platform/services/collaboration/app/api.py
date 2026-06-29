"""FastAPI surface for the collaboration service — thin glue over the service.

Every route parses the request, calls one application use-case, and shapes the
response. No business logic lives here (see :mod:`app.service`).
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Query
from fastapi.responses import JSONResponse

from ands_shared import create_app

from .models import (BlockingDefectIn, CommentIn, HcAckIn, TaskIn,
                     TaskStatusIn)
from .service import CollaborationService


def build_app(service: CollaborationService) -> FastAPI:
    app = create_app(title="collaboration",
                     description="ANDS comments, tasks & notifications (REQ-109)")
    router = APIRouter(prefix="/api/collab", tags=["collaboration"])

    # -- comments -------------------------------------------------------
    @router.post("/comments", status_code=201)
    def add_comment(body: CommentIn):
        return {"comment": service.add_comment(body.model_dump())}

    @router.get("/comments")
    def list_comments(target_type: str = Query(...),
                      target_id: str = Query(...)):
        return service.list_comments(target_type, target_id)

    # -- tasks ----------------------------------------------------------
    @router.post("/tasks", status_code=201)
    def create_task(body: TaskIn):
        return {"task": service.create_task(body.model_dump())}

    @router.get("/tasks")
    def list_tasks(assignee: str = "", dossier_id: str = "", status: str = ""):
        return service.list_tasks(assignee=assignee, dossier_id=dossier_id,
                                  status=status)

    @router.post("/tasks/status")
    def update_status(body: TaskStatusIn):
        return {"task": service.update_task_status(body.id, body.status)}

    # -- notification triggers -----------------------------------------
    @router.post("/notify/blocking-defect", status_code=201)
    def notify_blocking_defect(body: BlockingDefectIn):
        notes = service.notify_blocking_defect(
            body.dossier_id, body.finding, body.recipients)
        return JSONResponse(status_code=201,
                            content={"notified": len(notes),
                                     "notifications": notes})

    @router.post("/notify/hc-ack", status_code=201)
    def notify_hc_ack(body: HcAckIn):
        notes = service.notify_hc_ack(
            body.dossier_id, body.core_id, body.recipients)
        return JSONResponse(status_code=201,
                            content={"notified": len(notes)})

    # -- inbox / outbox -------------------------------------------------
    @router.get("/inbox")
    def inbox(user: str = ""):
        return service.inbox(user)

    @router.get("/outbox")
    def outbox():
        return service.outbox()

    app.include_router(router)
    return app
