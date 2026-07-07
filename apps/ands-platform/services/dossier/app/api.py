"""FastAPI surface for the dossier service — thin glue over the service."""

from __future__ import annotations

import json

from fastapi import (APIRouter, FastAPI, File, Form, Header, Query, Response,
                     UploadFile)
from fastapi.responses import StreamingResponse

from ands_shared import create_app

from . import ectd, llm_provider
from .models import (AdminSequenceIn, BinderIn, ContentPlanIn, CreateDossierIn,
                     DraftChatIn, DraftFieldIn, FeeStatusIn, GenerateIn,
                     ItemAssignIn, ItemStatusIn, LeafIn, MarkNaIn, PmLeafIn,
                     PmXmlBuildIn, PmXmlGateIn, PmXmlValidateIn, PmXrefIn,
                     SequenceIn)
from .service import DossierService


def build_app(service: DossierService) -> FastAPI:
    app = create_app(title="dossier",
                     description="ANDS eCTD content plans (REQ-103) & "
                                 "bilingual Product Monograph (REQ-098)")

    from . import audit_hook

    @app.middleware("http")
    async def _capture_actor(request, call_next):
        # who + which tenant is acting — from the web proxy's X-User-Email /
        # X-Tenant-Id — so every audit event this request records carries actor
        # attribution AND is owned by the tenant (else the tenant-scoped audit
        # read hides it and the Part-11 trail is blank).
        audit_hook.set_actor(request.headers.get("x-user-email", ""))
        audit_hook.set_tenant(request.headers.get("x-tenant-id", ""))
        return await call_next(request)

    router = APIRouter(prefix="/api/dossier", tags=["dossier"])

    @router.get("/placement")
    def placement():
        return ectd.module1_placement_table()

    # Round-9 ai_draft BLOCKER "AI provider identity, data residency and DPA
    # not verifiable" (n=8): the inspectable AI-provider disclosure — named
    # provider, model, region, leaves-Canada answer, retention, and the
    # downloadable data-processing document. Static (no dossier/tenant scope).
    @router.get("/ai-provider")
    def ai_provider():
        from . import ai_draft_meta
        return {**ai_draft_meta.provider_disclosure(),
                "dpa_text": ai_draft_meta.dpa_text()}

    # -- content plans (REQ-103) ----------------------------------------
    @router.post("/content-plans", status_code=201)
    def create_plan(body: ContentPlanIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return {"plan": service.create_content_plan(body.model_dump(),
                                                    x_tenant_id or None)}

    @router.get("/content-plans")
    def get_plan(dossier_id: str = Query(...), x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return {"plan": service.get_content_plan(dossier_id,
                                                 x_tenant_id or None)}

    @router.post("/content-plans/item/assign")
    def assign_item(body: ItemAssignIn):
        return {"item": service.assign_item(body.id, body.assignee,
                                            body.due_date or "")}

    @router.post("/content-plans/item/status")
    def item_status(body: ItemStatusIn):
        return service.update_item_status(body.id, body.status)

    # -- bilingual product monograph (REQ-098) --------------------------
    @router.post("/monograph/leaves", status_code=201)
    def register_pm_leaf(body: PmLeafIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return {"leaf": service.register_pm_leaf(body.model_dump(),
                                                 x_tenant_id or None)}

    @router.get("/monograph/status")
    def monograph_status(dossier_id: str = Query(...), x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.monograph_status(dossier_id, x_tenant_id or None)

    # -- administrative / corrective sequences (REQ-092) ----------------
    @router.post("/admin-sequence", status_code=201)
    def admin_sequence(body: AdminSequenceIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.build_admin_sequence(body.model_dump(),
                                            x_tenant_id or None)

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
    def add_leaf(body: LeafIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.add_leaf(body.model_dump(), x_tenant_id or None)

    @router.get("/ectd/{dossier_id}/current-view")
    def current_view(dossier_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.current_view(dossier_id)

    @router.get("/ectd/{dossier_id}/viewer/files")
    def files_view(dossier_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.files_view(dossier_id)

    @router.get("/ectd/{dossier_id}/viewer/outline/{sequence}")
    def outline_view(dossier_id: str, sequence: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.outline_view(dossier_id, sequence)

    # -- submission archive / binder (REQ-110) ------------------------
    @router.post("/archive", status_code=201)
    def create_binder(body: BinderIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.create_binder(body.model_dump(), x_tenant_id or None)

    @router.get("/archive")
    def list_binders(dossier_id: str = Query(...), x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.list_binders(dossier_id, x_tenant_id or None)

    @router.get("/archive/share/{token}")
    def shared_binder(token: str):
        return service.get_shared_binder(token)

    @router.get("/archive/{binder_id}")
    def get_binder(binder_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.get_binder(binder_id, x_tenant_id or None)

    @router.post("/archive/{binder_id}/share", status_code=201)
    def share_binder(binder_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.share_binder(binder_id, x_tenant_id or None)

    # -- guided module builder: section tree + real documents -----------
    @router.get("/section-tree")
    def section_tree(cs_be_only: bool = True):
        return service.get_section_tree(cs_be_only)

    # FORMS-WEB: the declarative form schema for ONE content section — the
    # contract the web renders every field by (upload + form-fill + per-field
    # AI-draft + generate). Static (no dossier / tenant scope); a group node or
    # backbone section with no authorable form returns 404.
    @router.get("/section-form-schema/{section}")
    def section_form_schema(section: str):
        return {"schema": service.form_schema(section)}

    @router.get("/dossiers")
    def list_dossiers(x_tenant_id: str = Header(default="",
                                                alias="X-Tenant-Id")):
        return service.list_dossiers(x_tenant_id or None)

    @router.post("/dossiers", status_code=201)
    def create_dossier(body: CreateDossierIn,
                       x_tenant_id: str = Header(default="",
                                                 alias="X-Tenant-Id")):
        return service.create_dossier(body.model_dump(), x_tenant_id or None)

    # NB: /dossiers/archived is declared BEFORE /dossiers/{dossier_id} so the
    # literal path wins over the {dossier_id} capture.
    @router.get("/dossiers/archived")
    def list_archived(x_tenant_id: str = Header(default="",
                                                alias="X-Tenant-Id")):
        return service.list_archived(x_tenant_id or None)

    @router.get("/dossiers/{dossier_id}")
    def get_dossier(dossier_id: str,
                    x_tenant_id: str = Header(default="",
                                              alias="X-Tenant-Id")):
        return service.get_dossier_full(dossier_id, x_tenant_id or None)

    @router.delete("/dossiers/{dossier_id}")
    def delete_dossier(dossier_id: str, body: dict | None = None,
                       x_tenant_id: str = Header(default="",
                                                 alias="X-Tenant-Id")):
        # WS3: a delete is a RECOVERABLE soft-archive requiring a reason AND a
        # server-side typed-id confirmation (confirm_id must equal dossier_id) —
        # a direct API DELETE cannot bypass the client's "type the ID" gate.
        # R9-CATALOG "No user roles, permissions, or e-signatures on workspace
        # actions" (n=6): the optional typed-name e-signature capture rides
        # along and lands verbatim on the durable ledger event.
        return service.delete_dossier(
            dossier_id, x_tenant_id or None,
            reason=str((body or {}).get("reason", "")),
            confirm_id=str((body or {}).get("confirm_id", "")),
            esign=(body or {}).get("esign"))

    @router.get("/dossiers/{dossier_id}/history")
    def dossier_history(dossier_id: str,
                        x_tenant_id: str = Header(default="",
                                                  alias="X-Tenant-Id")):
        # the DURABLE local Part-11 ledger (chained across renames) — the
        # authoritative record that cannot be lost when governance is down.
        return service.dossier_history(dossier_id, x_tenant_id or None)

    @router.post("/dossiers/{dossier_id}/restore")
    def restore_dossier(dossier_id: str, body: dict | None = None,
                        x_tenant_id: str = Header(default="",
                                                  alias="X-Tenant-Id")):
        # R9-CATALOG (n=6): optional typed-name e-signature capture on restore.
        return service.restore_dossier(
            dossier_id, x_tenant_id or None,
            reason=str((body or {}).get("reason", "")),
            esign=(body or {}).get("esign"))

    # R9-CATALOG "No user roles, permissions, or e-signatures on workspace
    # actions" (n=6): Owner (PM) is reassignable after creation — an
    # accountability label (NOT a permission source; roles govern permissions),
    # with the old/new values + reason on the durable ledger.
    @router.post("/dossiers/{dossier_id}/owner")
    def set_owner(dossier_id: str, body: dict | None = None,
                  x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.set_owner(
            dossier_id, str((body or {}).get("owner", "")),
            str((body or {}).get("reason", "")), x_tenant_id or None)

    @router.get("/validation/rules")
    def validation_rules():
        # static catalogue — the depth surface regulatory ops evaluate on
        from . import ectd_validation
        return ectd_validation.rule_catalog()

    @router.get("/validation/criteria-history")
    def validation_criteria_history():
        # CAMP-CRITERIA-SYNC: the auditable criteria-sync trail + review cadence
        # — proves the ruleset stays synced to HC criteria versions (maintained,
        # not stale). A buyer's adoption ask; static + honest, no tenant scope.
        from . import ectd_validation
        return ectd_validation.criteria_history()

    @router.post("/dossiers/{dossier_id}/rename")
    def rename_dossier(dossier_id: str, body: dict,
                       x_tenant_id: str = Header(default="",
                                                 alias="X-Tenant-Id")):
        return service.rename_dossier(dossier_id,
                                      str(body.get("new_id", "")),
                                      x_tenant_id or None,
                                      reason=str(body.get("reason", "")))

    @router.get("/dossiers/{dossier_id}/content")
    def dossier_content(dossier_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.content_state(dossier_id)

    @router.post("/dossiers/{dossier_id}/fees")
    def set_fees(dossier_id: str, body: FeeStatusIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.set_fee_status(dossier_id, body.fee_paid, body.sme_granted)

    @router.get("/dossiers/{dossier_id}/validate")
    def validate_submission(dossier_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.validate_submission(dossier_id)

    # TIER3-PREFLIGHT: ONE consolidated pre-flight / QA hand-off report — the
    # whole filing-readiness picture (structural validation + eValidator
    # attestation + Part-11 e-sign + SoD + fees + sequences + REP/Dossier-ID)
    # assembled into a single archivable object, disclaimers inline. Resolves
    # the "re-run validate at each step" limit.
    @router.get("/dossiers/{dossier_id}/preflight-report")
    def preflight_report(dossier_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.preflight_report(dossier_id, x_tenant_id or None)

    # ADOPT-EVALIDATOR: record / read the USER-ATTESTED external eValidator
    # result. ANDS Studio cannot run HC's official eValidator, so this is where
    # the filer attaches the REAL outcome of running it on the exported package.
    @router.get("/dossiers/{dossier_id}/evalidator-attestation")
    def get_evalidator_attestation(dossier_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.get_evalidator_attestation(dossier_id, x_tenant_id or None)

    @router.post("/dossiers/{dossier_id}/evalidator-attestation")
    def set_evalidator_attestation(dossier_id: str, body: dict,
                                   x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
                                   x_user_email: str = Header(default="", alias="X-User-Email")):
        return service.set_evalidator_attestation(
            dossier_id, body or {}, actor=x_user_email or "",
            tenant_id=x_tenant_id or None)

    # TIER2-PARITY-UX: attach the ACTUAL eValidator report FILE (bytes) — the
    # real report, not just a filename string. Stored in the tenant-guarded byte
    # store and linked on the user-attested external attestation as downloadable
    # evidence (a durable audit event is written).
    @router.post("/dossiers/{dossier_id}/evalidator-attestation/report",
                 status_code=201)
    async def attach_evalidator_report(
            dossier_id: str, file: UploadFile = File(...),
            x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
            x_user_email: str = Header(default="", alias="X-User-Email")):
        service.assert_access(dossier_id, x_tenant_id or None)
        raw = await file.read()
        return service.attach_evalidator_report(
            dossier_id, filename=file.filename or "evalidator-report.pdf",
            content_type=file.content_type or "application/octet-stream",
            body=raw, actor=x_user_email or "", tenant_id=x_tenant_id or None)

    # TIER2-PARITY-UX: self-serve STRUCTURAL validation of a single (known-good)
    # sequence — the confidence-building "it passes here too" affordance. Same
    # structural validator, scoped to one sequence; never a filing verdict or an
    # HC eValidator parity claim.
    @router.get("/dossiers/{dossier_id}/validate/sequence/{sequence}")
    def validate_sequence(dossier_id: str, sequence: str,
                          x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.validate_sequence(dossier_id, sequence,
                                         x_tenant_id or None)

    # TIER2-PARITY-UX: prepare + record an in-app REP Dossier-ID Request from the
    # placeholder banner. HONEST — it records the request intent + returns
    # guidance; it does NOT transmit to Health Canada.
    @router.get("/dossiers/{dossier_id}/rep-request")
    def get_rep_request(dossier_id: str,
                        x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.get_rep_request(dossier_id, x_tenant_id or None)

    @router.post("/dossiers/{dossier_id}/rep-request", status_code=201)
    def request_rep_dossier_id(dossier_id: str, body: dict,
                               x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
                               x_user_email: str = Header(default="", alias="X-User-Email")):
        return service.request_rep_dossier_id(
            dossier_id, body or {}, actor=x_user_email or "",
            tenant_id=x_tenant_id or None)

    # ADOPT-PART11-ESIGN: record a REAL e-signature manifest (bound over the
    # checksummed eCTD leaves) as a durable, verifiable Part-11 signing act, and
    # re-verify it against the live leaf checksums to detect tampering.
    @router.post("/dossiers/{dossier_id}/esign")
    def record_esign(dossier_id: str, body: dict,
                     x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
                     x_user_email: str = Header(default="", alias="X-User-Email")):
        return service.record_esign(
            dossier_id, (body or {}).get("manifest") or {},
            actor=x_user_email or "", tenant_id=x_tenant_id or None)

    @router.get("/dossiers/{dossier_id}/esign")
    def get_esign(dossier_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.get_esign(dossier_id, x_tenant_id or None)

    # TIER2-ROLE-SEP: the distinct author identities recorded for this dossier's
    # content — the set a signer is checked against for segregation of duties.
    @router.get("/dossiers/{dossier_id}/content-authors")
    def content_authors(dossier_id: str,
                        x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.content_authors(dossier_id, x_tenant_id or None)

    @router.post("/dossiers/{dossier_id}/esign/verify")
    def verify_esign(dossier_id: str, body: dict = None,
                     x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        current = (body or {}).get("current")
        return service.verify_esign(dossier_id, current=current,
                                    tenant_id=x_tenant_id or None)

    @router.get("/dossiers/{dossier_id}/sequences")
    def list_sequences(dossier_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.list_sequences(dossier_id)

    @router.post("/dossiers/{dossier_id}/sequences", status_code=201)
    def create_sequence(dossier_id: str, body: SequenceIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.create_sequence(dossier_id, body.sequence,
                                       body.purpose, body.note)

    @router.post("/dossiers/{dossier_id}/sequences/{sequence}/activate")
    def activate_sequence(dossier_id: str, sequence: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.activate_sequence(dossier_id, sequence)

    @router.post("/ectd/{dossier_id}/section/{section}/upload")
    async def upload_section(dossier_id: str, section: str,
                             file: UploadFile = File(...),
                             lang: str = Form(""), x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        body = await file.read()
        return service.upload_document(
            dossier_id, section, file.filename or "document",
            file.content_type or "application/octet-stream", body, lang or None)

    @router.post("/ectd/{dossier_id}/section/{section}/generate")
    def generate_section(dossier_id: str, section: str, body: GenerateIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.generate_document(dossier_id, section, body.model_dump())

    # -- interactive (LLM chat) drafting --------------------------------
    @router.post("/ectd/{dossier_id}/section/{section}/draft-chat")
    async def draft_chat(dossier_id: str, section: str, body: DraftChatIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
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

    # FORMS-WEB: AI-draft ONE prose field of a section's form. Reuses the same
    # AI path (and honesty prompt) as chat drafting; validated eagerly so a bad
    # field / unconfigured LLM comes back as a clean JSON error, not a broken
    # stream. Streams the drafted text as SSE {delta}/{error} chunks. HONEST: a
    # draft for the filer to review, never a filable value.
    @router.post("/ectd/{dossier_id}/section/{section}/draft-field")
    def draft_field(dossier_id: str, section: str, body: DraftFieldIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        system, _ctx = service.prepare_draft_field(dossier_id, section,
                                                   body.field)

        async def gen():
            try:
                async for delta in service.stream_draft_field(system):
                    yield f"data: {json.dumps({'delta': delta})}\n\n"
                yield "data: [DONE]\n\n"
            except llm_provider.LlmNotConfigured as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            except Exception as exc:  # upstream/network errors mid-stream
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @router.get("/ectd/{dossier_id}/section/{section}/sample")
    def form_sample(dossier_id: str, section: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.form_sample(dossier_id, section, x_tenant_id or None)

    @router.post("/ectd/{dossier_id}/section/{section}/review")
    def form_review(dossier_id: str, section: str, body: GenerateIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.form_review(dossier_id, section, body.model_dump(),
                                   x_tenant_id or None)

    @router.post("/ectd/{dossier_id}/section/{section}/confirm-content")
    def confirm_content(dossier_id: str, section: str, body: dict | None = None,
                        x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        # the explicit "I reviewed & edited this — it is my content" action that
        # clears the sample/AI review block (recorded to the audit trail).
        # Round-9 ai_draft BLOCKER (n=4): the optional attest body carries the
        # reviewer's typed name + credential for an inspection-grade record.
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.confirm_content(dossier_id, section, attest=body or {})

    # Round-9 builder_forms MAJOR (n=3, ask 2): per-section AI off-switch.
    @router.post("/ectd/{dossier_id}/section/{section}/ai-policy")
    def set_ai_policy(dossier_id: str, section: str, body: dict | None = None,
                      x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.set_ai_policy(
            dossier_id, section, bool((body or {}).get("disabled")),
            reason=str((body or {}).get("reason", "")))

    # Round-9 builder_forms MAJOR (n=3, ask 1): what ONE draft is generated
    # from — the per-draft source/context disclosure.
    @router.get("/ectd/{dossier_id}/section/{section}/draft-context")
    def draft_context(dossier_id: str, section: str,
                      x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.draft_context(dossier_id, section)

    # Round-9 ai_draft BLOCKER (n=4): one-click per-section audit record.
    @router.get("/ectd/{dossier_id}/section/{section}/audit-record")
    def section_audit_record(dossier_id: str, section: str,
                             x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.section_audit_record(dossier_id, section,
                                            x_tenant_id or None)

    # Round-9 ai_draft BLOCKER (n=2) + MAJOR (n=6): the cross-section roll-up
    # (state / owner / last-touched) + the bulk-attest review queue.
    @router.get("/dossiers/{dossier_id}/sections-rollup")
    def sections_rollup(dossier_id: str,
                        x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        return service.sections_rollup(dossier_id, x_tenant_id or None)

    @router.post("/ectd/{dossier_id}/section/{section}/mark-na")
    def mark_na_section(dossier_id: str, section: str, body: MarkNaIn, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.mark_na(dossier_id, section, body.reason)

    @router.get("/ectd/{dossier_id}/export/{sequence}")
    def export_sequence(dossier_id: str, sequence: str,
                        override: bool = False, reason: str = "",
                        x_tenant_id: str = Header(default="",
                                                  alias="X-Tenant-Id")):
        pkg = service.export_sequence(dossier_id, sequence,
                                      x_tenant_id or None,
                                      override=override, reason=reason)
        v = pkg.get("validation", {})
        stamp = ("overridden" if v.get("overridden")
                 else "passed" if v.get("passed") else "unknown")
        return Response(
            content=pkg["body"], media_type=pkg["content_type"],
            headers={"Content-Disposition":
                     f'attachment; filename="{pkg["filename"]}"',
                     "X-Export-Missing": str(len(pkg["missing"])),
                     "X-Export-Validation": stamp})

    # CAMP-INTEROP: import-compatibility self-check over the tool's OWN export.
    # Answers the repeated adoption ask — "confirm the exported package imports
    # clean into our Vault RIM / docuBridge lifecycle." Read-only structural
    # report (no download, no gate): what a compliant ICH eCTD 3.2.2 / CA M1 v2.2
    # importer will find. HONEST: verifies the STANDARD contract, not a vendor.
    @router.get("/ectd/{dossier_id}/import-compat/{sequence}")
    def import_compatibility(dossier_id: str, sequence: str,
                             x_tenant_id: str = Header(default="",
                                                       alias="X-Tenant-Id")):
        service.assert_access(dossier_id, x_tenant_id or None)
        return service.import_compatibility(dossier_id, sequence,
                                            x_tenant_id or None)

    # CAMP-SHADOW: shadow / parallel-run affordance. Points the tool at a
    # prior/known-good sequence, runs the SAME structural validator + import-
    # compat self-check over the real package bytes, and returns a STRUCTURED
    # comparison (structural findings, leaf inventory, lifecycle ops, package
    # inventory) so the filer can diff the tool's view against their validated
    # publisher's output. An optional known-good ``reference`` (leaf list) in
    # the body drives a leaf-level diff. HONEST — a confidence-building
    # comparison, never a guarantee, and it never drives the filing gate.
    @router.post("/dossiers/{dossier_id}/shadow-run/{sequence}")
    def shadow_run(dossier_id: str, sequence: str, body: dict = None,
                   x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
                   x_user_email: str = Header(default="", alias="X-User-Email")):
        service.assert_access(dossier_id, x_tenant_id or None)
        reference = (body or {}).get("reference")
        return service.shadow_run(dossier_id, sequence, reference,
                                  actor=x_user_email or "",
                                  tenant_id=x_tenant_id or None)

    @router.get("/documents/{doc_id}")
    def download_document(doc_id: str, x_tenant_id: str = Header(default="", alias="X-Tenant-Id")):
        doc = service.get_document(doc_id, x_tenant_id or None)
        return Response(
            content=doc["body"], media_type=doc["content_type"],
            headers={"Content-Disposition":
                     f'attachment; filename="{doc["filename"]}"'})

    app.include_router(router)
    return app
