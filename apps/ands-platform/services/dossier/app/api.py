"""FastAPI surface for the dossier service — thin glue over the service."""

from __future__ import annotations

import json

from fastapi import (APIRouter, FastAPI, File, Form, Query, Response,
                     UploadFile)
from fastapi.responses import StreamingResponse

from ands_shared import create_app

from . import ectd, llm_provider
from .models import (AdminSequenceIn, BinderIn, ContentPlanIn, CreateDossierIn,
                     DraftChatIn, FeeStatusIn, GenerateIn, ItemAssignIn,
                     ItemStatusIn, LeafIn, MarkNaIn, PmLeafIn, PmXmlBuildIn,
                     PmXmlGateIn, PmXmlValidateIn, PmXrefIn, SequenceIn)
from .service import DossierService


def build_app(service: DossierService) -> FastAPI:
    app = create_app(title="dossier",
                     description="ANDS eCTD content plans (REQ-103) & "
                                 "bilingual Product Monograph (REQ-098)")
    router = APIRouter(prefix="/api/dossier", tags=["dossier"])

    @router.get("/placement")
    def placement():
        return ectd.module1_placement_table()

    # -- content plans (REQ-103) ----------------------------------------
    @router.post("/content-plans", status_code=201)
    def create_plan(body: ContentPlanIn):
        return {"plan": service.create_content_plan(body.model_dump())}

    @router.get("/content-plans")
    def get_plan(dossier_id: str = Query(...)):
        return {"plan": service.get_content_plan(dossier_id)}

    @router.post("/content-plans/item/assign")
    def assign_item(body: ItemAssignIn):
        return {"item": service.assign_item(body.id, body.assignee,
                                            body.due_date or "")}

    @router.post("/content-plans/item/status")
    def item_status(body: ItemStatusIn):
        return service.update_item_status(body.id, body.status)

    # -- bilingual product monograph (REQ-098) --------------------------
    @router.post("/monograph/leaves", status_code=201)
    def register_pm_leaf(body: PmLeafIn):
        return {"leaf": service.register_pm_leaf(body.model_dump())}

    @router.get("/monograph/status")
    def monograph_status(dossier_id: str = Query(...)):
        return service.monograph_status(dossier_id)

    # -- administrative / corrective sequences (REQ-092) ----------------
    @router.post("/admin-sequence", status_code=201)
    def admin_sequence(body: AdminSequenceIn):
        return service.build_admin_sequence(body.model_dump())

    # -- XML Product Monograph (REQ-099) --------------------------------
    @router.post("/monograph/xml/build")
    def pm_xml_build(body: PmXmlBuildIn):
        return service.build_monograph_xml(body.model_dump())

    @router.post("/monograph/xml/validate")
    def pm_xml_validate(body: PmXmlValidateIn):
        return service.validate_monograph_xml(body.xml)

    @router.post("/monograph/xml/gate")
    def pm_xml_gate(body: PmXmlGateIn):
        return service.require_xml_pm(body.model_dump())

    # -- annotated PM cross-references (REQ-101) ------------------------
    @router.get("/monograph/xref/targets")
    def pm_xref_targets():
        return service.xref_targets()

    @router.post("/monograph/xref/resolve")
    def pm_xref_resolve(body: PmXrefIn):
        return service.resolve_pm_xrefs(body.model_dump())

    # -- eCTD assembly + Application Viewer (REQ-107) ------------------
    @router.post("/ectd/leaf", status_code=201)
    def add_leaf(body: LeafIn):
        return service.add_leaf(body.model_dump())

    @router.get("/ectd/{dossier_id}/current-view")
    def current_view(dossier_id: str):
        return service.current_view(dossier_id)

    @router.get("/ectd/{dossier_id}/viewer/files")
    def files_view(dossier_id: str):
        return service.files_view(dossier_id)

    @router.get("/ectd/{dossier_id}/viewer/outline/{sequence}")
    def outline_view(dossier_id: str, sequence: str):
        return service.outline_view(dossier_id, sequence)

    # -- submission archive / binder (REQ-110) ------------------------
    @router.post("/archive", status_code=201)
    def create_binder(body: BinderIn):
        return service.create_binder(body.model_dump())

    @router.get("/archive")
    def list_binders(dossier_id: str = Query(...)):
        return service.list_binders(dossier_id)

    @router.get("/archive/share/{token}")
    def shared_binder(token: str):
        return service.get_shared_binder(token)

    @router.get("/archive/{binder_id}")
    def get_binder(binder_id: str):
        return service.get_binder(binder_id)

    @router.post("/archive/{binder_id}/share", status_code=201)
    def share_binder(binder_id: str):
        return service.share_binder(binder_id)

    # -- guided module builder: section tree + real documents -----------
    @router.get("/section-tree")
    def section_tree(cs_be_only: bool = True):
        return service.get_section_tree(cs_be_only)

    @router.get("/dossiers")
    def list_dossiers():
        return service.list_dossiers()

    @router.post("/dossiers", status_code=201)
    def create_dossier(body: CreateDossierIn):
        return service.create_dossier(body.model_dump())

    @router.get("/dossiers/{dossier_id}")
    def get_dossier(dossier_id: str):
        return service.get_dossier_full(dossier_id)

    @router.delete("/dossiers/{dossier_id}")
    def delete_dossier(dossier_id: str):
        return service.delete_dossier(dossier_id)

    @router.get("/dossiers/{dossier_id}/content")
    def dossier_content(dossier_id: str):
        return service.content_state(dossier_id)

    @router.post("/dossiers/{dossier_id}/fees")
    def set_fees(dossier_id: str, body: FeeStatusIn):
        return service.set_fee_status(dossier_id, body.fee_paid, body.sme_granted)

    @router.get("/dossiers/{dossier_id}/validate")
    def validate_submission(dossier_id: str):
        return service.validate_submission(dossier_id)

    @router.get("/dossiers/{dossier_id}/sequences")
    def list_sequences(dossier_id: str):
        return service.list_sequences(dossier_id)

    @router.post("/dossiers/{dossier_id}/sequences", status_code=201)
    def create_sequence(dossier_id: str, body: SequenceIn):
        return service.create_sequence(dossier_id, body.sequence)

    @router.post("/ectd/{dossier_id}/section/{section}/upload")
    async def upload_section(dossier_id: str, section: str,
                             file: UploadFile = File(...),
                             lang: str = Form("")):
        body = await file.read()
        return service.upload_document(
            dossier_id, section, file.filename or "document",
            file.content_type or "application/octet-stream", body, lang or None)

    @router.post("/ectd/{dossier_id}/section/{section}/generate")
    def generate_section(dossier_id: str, section: str, body: GenerateIn):
        return service.generate_document(dossier_id, section, body.model_dump())

    # -- interactive (LLM chat) drafting --------------------------------
    @router.post("/ectd/{dossier_id}/section/{section}/draft-chat")
    async def draft_chat(dossier_id: str, section: str, body: DraftChatIn):
        # validated eagerly: bad section / missing GROQ_API_KEY -> clean
        # JSON error, not a broken stream
        node, ctx = service.prepare_draft_chat(dossier_id, section)
        messages = [m.model_dump() for m in body.messages]

        async def gen():
            try:
                async for delta in service.stream_draft_chat(node, ctx, messages):
                    yield f"data: {json.dumps({'delta': delta})}\n\n"
                yield "data: [DONE]\n\n"
            except llm_provider.LlmNotConfigured as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            except Exception as exc:  # upstream/network errors mid-stream
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @router.post("/ectd/{dossier_id}/section/{section}/mark-na")
    def mark_na_section(dossier_id: str, section: str, body: MarkNaIn):
        return service.mark_na(dossier_id, section, body.reason)

    @router.get("/documents/{doc_id}")
    def download_document(doc_id: str):
        doc = service.get_document(doc_id)
        return Response(
            content=doc["body"], media_type=doc["content_type"],
            headers={"Content-Disposition":
                     f'attachment; filename="{doc["filename"]}"'})

    app.include_router(router)
    return app
