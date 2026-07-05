"""Dossier application service — content-plan + bilingual-PM use-cases."""

from __future__ import annotations

from ands_shared import EventEnvelope, EventType, ProblemError, utcnow_iso

import re
import secrets
from datetime import date

from . import (admin_sequence, archive, assembly, content_model, content_plan,
               dossier_state, drafting, ectd_validation, export_pkg, fees,
               form_review, form_samples, generators, llm_provider, monograph,
               pm_xml, pm_xref, section_tree)
from . import audit_hook
from .document_store import SqliteBlobStore
from .ports import DossierRepository

_DIN_RE = re.compile(r"^\d{8}$")
# HC Dossier ID: one letter + 6-7 digits. A 'd' prefix is our placeholder
# convention for "real ID not issued yet" — validation blocks filing on it.
_ID_RE = re.compile(r"^[a-z]\d{6,7}$")
# a lifecycle placement suffixes the working sequence onto the base leaf id
_SEQ_SUFFIX_RE = re.compile(r"^(?P<base>.+)-\d{4}$")

# regulatory activities a working sequence can belong to
SEQUENCE_PURPOSES = ("initial", "response", "supplement",
                     "annual-notification")


def _s(v) -> str:
    return str(v or "").strip()


def _seq4(v) -> str:
    """Normalize a sequence number the way assembly stores it (zero-filled)."""
    s = _s(v)
    return s.zfill(4) if s.isdigit() else s


class DossierService:
    def __init__(self, repo: DossierRepository, bus,
                 *, source: str = "dossier", store=None, policy=None) -> None:
        self.repo = repo
        self.bus = bus
        self.source = source
        self.store = store or SqliteBlobStore(repo)
        # TIER3-SOD-ENFORCE: an optional workspace-policy port. When wired, the
        # sign path (record_esign) reads a tenant's ``require_sod`` and, when on,
        # FORCES segregation-of-duties enforcement — the block no longer depends
        # on the signer opting into it via the manifest. Best-effort: an
        # unreachable port degrades to the manifest flag (advisory), never crashes.
        self.policy = policy

    def register(self) -> "DossierService":
        # No upstream subscriptions yet; reserved for sequence/assembly events.
        return self

    # -- content plans (REQ-103) -------------------------------------------
    def create_content_plan(self, data: dict,
                            tenant_id: str | None = None) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        if not dossier_id:
            raise ProblemError(422, "dossier_id is required",
                               rule="dossier_id_required")
        self._tenant_guard(dossier_id, tenant_id)
        try:
            items = content_plan.build_plan_items(
                data.get("submission_type"),
                cs_be_only=bool(data.get("cs_be_only")))
        except ValueError as exc:
            raise ProblemError(422, str(exc), rule="submission_type_invalid")
        plan = self.repo.create_plan(
            dossier_id, _s(data.get("submission_type")).upper(), items)
        return self._with_progress(plan)

    def get_content_plan(self, dossier_id: str,
                         tenant_id: str | None = None) -> dict:
        self._tenant_guard(_s(dossier_id), tenant_id)
        plan = self.repo.get_plan_by_dossier(_s(dossier_id))
        if not plan:
            raise ProblemError(404, "No content plan for dossier",
                               detail=_s(dossier_id))
        return self._with_progress(plan)

    def assign_item(self, item_id: str, assignee: str, due_date: str) -> dict:
        item = self.repo.get_item(_s(item_id))
        if not item:
            raise ProblemError(404, "Plan item not found", detail=_s(item_id))
        if not content_plan.validate_due_date(due_date):
            raise ProblemError(422, "due_date must be ISO YYYY-MM-DD",
                               rule="item_due_date_invalid")
        item = self.repo.update_item(
            item_id, {"assignee": _s(assignee), "due_date": _s(due_date) or None})
        # Cross-service intent: collaboration can turn this into a task/notice.
        self.bus.publish(EventEnvelope.make(
            EventType.CONTENT_PLAN_ITEM_ASSIGNED, source=self.source,
            dossier_id=item["dossier_id"],
            data={"item_id": item["id"], "title": item["title"],
                  "assignee": item["assignee"], "due_date": item["due_date"]}))
        return item

    def update_item_status(self, item_id: str, status: str) -> dict:
        item = self.repo.get_item(_s(item_id))
        if not item:
            raise ProblemError(404, "Plan item not found", detail=_s(item_id))
        if not content_plan.validate_item_status(status):
            raise ProblemError(422, "unknown item status",
                               rule="item_status_unknown")
        item = self.repo.update_item(item_id, {"status": _s(status)})
        plan = self.repo.get_plan(item["plan_id"])
        return {"item": item,
                "progress": content_plan.plan_progress(plan["items"])}

    def _with_progress(self, plan: dict) -> dict:
        plan["progress"] = content_plan.plan_progress(plan["items"])
        return plan

    # -- bilingual product monograph (REQ-098) -----------------------------
    def register_pm_leaf(self, data: dict,
                         tenant_id: str | None = None) -> dict:
        self._tenant_guard(_s(data.get("dossier_id")), tenant_id)
        res = monograph.normalize_pm_leaf(data)
        if not res["valid"]:
            raise ProblemError(422, "Invalid Product Monograph leaf",
                               errors=res["errors"])
        return self.repo.upsert_pm_leaf(res["leaf"])

    # -- administrative / corrective sequences (REQ-092) -------------------
    def build_admin_sequence(self, data: dict,
                             tenant_id: str | None = None) -> dict:
        self._tenant_guard(_s(data.get("dossier_id")), tenant_id)
        result = admin_sequence.build_admin_sequence(data)
        if "errors" in result:
            raise ProblemError(422, "Invalid administrative sequence",
                               errors=result["errors"])
        return result

    def monograph_status(self, dossier_id: str,
                         tenant_id: str | None = None) -> dict:
        self._tenant_guard(_s(dossier_id), tenant_id)
        leaves = self.repo.list_pm_leaves(_s(dossier_id))
        result = monograph.validate_bilingual_monograph(leaves)
        if result["blocking"]:
            # surface the blocker for downstream consumers (readiness, collab)
            self.bus.publish(EventEnvelope.make(
                EventType.BILINGUAL_PM_BLOCKED, source=self.source,
                dossier_id=_s(dossier_id),
                data={"findings": result["findings"]}))
        return result

    # -- XML Product Monograph (REQ-099) -----------------------------------
    def build_monograph_xml(self, data: dict) -> dict:
        xml = pm_xml.build_monograph_xml(data)
        return {"xml": xml, "validation": pm_xml.validate_monograph_xml(xml)}

    def validate_monograph_xml(self, xml: str) -> dict:
        return pm_xml.validate_monograph_xml(xml)

    def require_xml_pm(self, ctx: dict) -> dict:
        return pm_xml.require_xml_pm(ctx)

    # -- annotated PM cross-references (REQ-101) ---------------------------
    def xref_targets(self) -> dict:
        return {"targets": pm_xref.valid_targets()}

    def resolve_pm_xrefs(self, data: dict) -> dict:
        refs = pm_xref.build_pm_xrefs(data) if data.get("sections") or \
            data.get("refs") else (data.get("xrefs") or [])
        present = data.get("present_targets")
        return pm_xref.resolve_pm_xrefs(refs, present)

    # -- eCTD assembly + Application Viewer (REQ-107) ----------------------
    def _dossier_model(self, dossier_id: str, *, create: bool = False) -> dict:
        model = self.repo.get_dossier(_s(dossier_id))
        if model:
            return model
        if create:
            return assembly.new_dossier(dossier_id)
        raise ProblemError(404, "no eCTD dossier", detail=_s(dossier_id))

    def add_leaf(self, data: dict, tenant_id: str | None = None) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        sequence = _s(data.get("sequence")) or "0000"
        if not dossier_id:
            raise ProblemError(422, "dossier_id is required",
                               rule="dossier_id_required")
        self._tenant_guard(dossier_id, tenant_id)
        model = self._dossier_model(dossier_id, create=True)
        try:
            record = assembly.add_leaf(model, sequence, data.get("leaf") or data)
        except ValueError as exc:
            raise ProblemError(422, str(exc), rule="leaf_operation_invalid")
        self.repo.save_dossier(model)
        return {"leaf": record, "current_view": assembly.current_view(model)}

    def current_view(self, dossier_id: str) -> dict:
        return assembly.current_view(self._dossier_model(dossier_id))

    def files_view(self, dossier_id: str) -> dict:
        return assembly.build_files_view(self._dossier_model(dossier_id))

    def outline_view(self, dossier_id: str, sequence: str) -> dict:
        return assembly.build_outline_view(self._dossier_model(dossier_id),
                                           sequence)

    # -- submission archive / binder (REQ-110) -----------------------------
    def create_binder(self, data: dict, tenant_id: str | None = None) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        self._tenant_guard(dossier_id, tenant_id)
        sequence = _s(data.get("sequence")) or "0000"
        model = self._dossier_model(dossier_id)   # 404 if no eCTD dossier
        binder = archive.build_binder(
            model, sequence=sequence,
            validation_report=data.get("validation_report"),
            transmission=data.get("transmission"))
        return self.repo.save_binder(dossier_id, sequence, binder)

    def get_binder(self, binder_id: str, tenant_id: str | None = None) -> dict:
        rec = self.repo.get_binder(_s(binder_id))
        if not rec:
            raise ProblemError(404, "binder not found", detail=_s(binder_id))
        # a binder belongs to its dossier — 404 across tenants
        self._tenant_guard(_s(rec.get("dossier_id")), tenant_id)
        return rec

    def list_binders(self, dossier_id: str,
                     tenant_id: str | None = None) -> dict:
        self._tenant_guard(dossier_id, tenant_id)
        binders = self.repo.list_binders(_s(dossier_id))
        return {"binders": binders, "count": len(binders)}

    def share_binder(self, binder_id: str,
                     tenant_id: str | None = None) -> dict:
        rec = self.get_binder(binder_id, tenant_id)   # guards ownership
        token = rec.get("share_token") or secrets.token_urlsafe(24)
        self.repo.set_share_token(binder_id, token)
        return {"binder_id": binder_id, "share_token": token,
                "url": f"/api/dossier/archive/share/{token}"}

    def get_shared_binder(self, token: str) -> dict:
        rec = self.repo.get_by_share_token(_s(token))
        if not rec:
            raise ProblemError(404, "share link not found or revoked")
        return {"dossier_id": rec["dossier_id"], "sequence": rec["sequence"],
                "binder": rec["binder"], "read_only": True}

    # -- guided module builder: section tree + real documents --------------
    def _cs_be_only(self, dossier_id: str) -> bool:
        idx = self.repo.get_dossier_index(_s(dossier_id))
        return bool(idx["cs_be_only"]) if idx else True

    def get_section_tree(self, cs_be_only: bool = True) -> dict:
        return section_tree.section_tree(cs_be_only=bool(cs_be_only))

    def _ctx_for(self, dossier_id: str) -> dict:
        idx = self.repo.get_dossier_index(_s(dossier_id)) or {}
        return {"dossier_id": _s(dossier_id), "title": idx.get("title"),
                # the real product name (falls back to the title) — feeds the
                # REP RT <PRODUCT_NAME>, ca-regional <product>, Form V, PMs
                "drug_product": idx.get("drug_product") or idx.get("title"),
                "submission_type": idx.get("submission_type") or "ANDS",
                "activity_type": idx.get("submission_type") or "ANDS",
                "din": idx.get("din"),
                # REP identity: sponsor company (distinct from the product)
                "company_id": idx.get("company_id"),
                "sponsor": idx.get("sponsor")}

    def _node(self, dossier_id: str, section: str) -> dict:
        node = section_tree.node_for(
            _s(section), cs_be_only=self._cs_be_only(dossier_id))
        if not node:
            raise ProblemError(404, "unknown eCTD section", detail=_s(section))
        return node

    @staticmethod
    def _ext(filename: str, default: str = "pdf") -> str:
        name = _s(filename)
        return name.rsplit(".", 1)[-1].lower() if "." in name else default

    def _active_sequence(self, dossier_id: str) -> str:
        idx = self.repo.get_dossier_index(_s(dossier_id)) or {}
        return _s(idx.get("active_sequence")) or "0000"

    def _place(self, dossier_id: str, node: dict, leaf_id: str, body,
               ext: str = "pdf") -> None:
        model = self._dossier_model(dossier_id, create=True)
        # the leaf href must carry the stored file's real extension (a generated
        # REP form is .xml, not .pdf) so the eCTD leaf points at the right bytes.
        href = f"{node['folder']}/{leaf_id}.{_s(ext) or 'pdf'}"
        # placements target the ACTIVE working sequence; when the document is
        # already live from an earlier sequence this records a replace op
        assembly.set_leaf_lifecycle(model, self._active_sequence(dossier_id), {
            "leaf_id": leaf_id, "heading": node["section"],
            "title": node["title"], "href": href, "content": body})
        self.repo.save_dossier(model)

    def _write_entry(self, dossier_id, section, node, *, action, meta=None,
                     lang=None, leaf_id=None, na_reason=None,
                     content_origin=None, content_confirmed=None,
                     record_author=False) -> dict:
        entry = self.repo.get_section_state(_s(dossier_id), _s(section)) or {}
        entry["action"] = action
        if na_reason is not None:
            entry["na_reason"] = na_reason
        # SAFETY provenance: what produced this section's content, and whether
        # the filer has confirmed it as their own reviewed content. Sample/AI
        # content stays unconfirmed (blocking the gate) until confirm_content.
        if content_origin is not None:
            entry["content_origin"] = content_origin
        if content_confirmed is not None:
            entry["content_confirmed"] = bool(content_confirmed)
        # TIER2-ROLE-SEP: record WHO authored this section's content, so a later
        # e-signature can be checked for segregation of duties (the signer must
        # be a distinct authorized approver from the author). The acting user is
        # the per-request actor set from X-User-Email. Only content-producing
        # actions (upload/generate/confirm) pass record_author=True; an N/A mark
        # or a status-only rewrite must not claim authorship.
        if record_author:
            who = _s(audit_hook._actor.get())
            if who:
                entry["content_author"] = who
        if node["bilingual"] and lang:
            docs = dict(entry.get("documents") or {})
            if meta:
                docs[lang] = meta
            entry["documents"] = docs
            entry["languages"] = sorted(docs.keys())
        elif meta is not None:
            entry["doc_id"] = meta["doc_id"]
            entry["document"] = meta
            entry["languages"] = None
            if leaf_id:
                entry["leaf_id"] = leaf_id
        entry["status"] = dossier_state.resolve_status(node, entry)
        self.repo.upsert_section_state(_s(dossier_id), _s(section), entry)
        return entry

    def upload_document(self, dossier_id, section, filename, content_type,
                        body, lang=None) -> dict:
        node = self._node(dossier_id, section)
        if "upload" not in node["affordances"]:
            raise ProblemError(422, "this section is not uploadable",
                               rule="section_not_uploadable", detail=_s(section))
        lang = _s(lang) or None
        if node["bilingual"] and lang not in ("en", "fr"):
            raise ProblemError(422, "a bilingual section requires lang 'en' or "
                               "'fr'", rule="lang_required")
        # the dropzone's accept= only filters the file picker — drag-drop and
        # direct API calls bypass it, so the accepted formats are enforced here
        fmts = [str(f).lower() for f in (node.get("formats") or [])]
        ext = self._ext(filename, default="")
        if fmts and ext not in fmts:
            raise ProblemError(
                422, "this file type isn't accepted for this section",
                rule="file_format_invalid",
                detail=f"section {_s(section)} accepts: {', '.join(fmts)}")
        try:
            meta = self.store.put(_s(dossier_id), _s(section), filename,
                                  content_type, body, origin="uploaded", lang=lang)
        except ValueError as exc:
            raise ProblemError(413, str(exc), rule="file_too_large")
        leaf_id = node["leaf_id"] + (f"-{lang}" if node["bilingual"] and lang else "")
        self._place(dossier_id, node, leaf_id, body, self._ext(filename))
        # an upload is the filer's OWN content — origin uploaded, confirmed.
        self._write_entry(dossier_id, section, node, action="uploaded",
                          meta=meta, lang=lang, leaf_id=leaf_id,
                          content_origin="uploaded", content_confirmed=True,
                          record_author=True)
        audit_hook.record("dossier.document_uploaded", _s(dossier_id),
                          {"section": _s(section), "filename": _s(filename),
                           "lang": lang or ""})
        return self.content_state(dossier_id)

    def generate_document(self, dossier_id, section, payload) -> dict:
        node = self._node(dossier_id, section)
        key = node.get("generator_key")
        if "generate" not in node["affordances"] or not key:
            raise ProblemError(422, "this section cannot be authored in-app",
                               rule="section_not_generatable", detail=_s(section))
        payload = payload or {}
        ctx = {**self._ctx_for(dossier_id), **payload}
        try:
            doc = generators.generate(key, ctx)
        except KeyError:
            raise ProblemError(422, "no generator for this section", detail=key)
        # provenance travels with the document: an AI-assisted draft, a
        # sample-origin fill, and a deterministic template fill are distinct.
        # SAFETY: an AI draft OR a fill still carrying worked-example values is
        # UNCONFIRMED — it cannot complete the section or reach export until the
        # filer confirms it as reviewed content.
        #
        # The sample decision is made SERVER-SIDE, not from a client flag: the
        # server re-derives which fields still equal this generator's worked
        # example. So a client that omits/forges ``sample_origin`` cannot slip
        # example values into a filing. An explicit client hint still counts
        # (fail-safe OR) but is never required and can never turn the block off.
        is_ai = bool(_s(payload.get("llm_draft")))   # carries the AI text itself
        unedited_samples = form_samples.unedited_sample_fields(key, ctx)
        is_sample = bool(unedited_samples) or bool(payload.get("sample_origin"))
        origin = "ai_draft" if is_ai else "sample" if is_sample else "generated"
        # blob store keeps its own coarse origin (ai_draft|generated); a
        # sample-fill's bytes are template output, hence "generated" there.
        blob_origin = "ai_draft" if is_ai else "generated"
        meta = self.store.put(_s(dossier_id), _s(section), doc["filename"],
                              doc["content_type"], doc["body"],
                              origin=blob_origin)
        self._place(dossier_id, node, node["leaf_id"], doc["body"],
                    self._ext(doc["filename"]))
        confirmed = not (is_ai or is_sample)
        self._write_entry(dossier_id, section, node, action="generated",
                          meta=meta, leaf_id=node["leaf_id"],
                          content_origin=origin, content_confirmed=confirmed,
                          record_author=True)
        audit_hook.record("dossier.document_generated", _s(dossier_id),
                          {"section": _s(section),
                           "generator": _s(node.get("generator_key")),
                           "content_origin": origin,
                           "confirmed": confirmed,
                           "ai_draft": is_ai})
        return self.content_state(dossier_id)

    def confirm_content(self, dossier_id, section) -> dict:
        """The explicit 'I have reviewed this AI-assisted draft — it is my
        content' attestation, recorded to the audit stream.

        SAFETY: attestation is only meaningful for an AI draft (freeform prose a
        human must vouch for). A SAMPLE fill still carrying worked-example values
        CANNOT be attested away — that would be a rubber stamp letting a
        fabricated value file unedited. A sample block is cleared only by editing
        the fields and re-authoring, which the server re-derives as no-longer-
        sample. So confirm refuses a section whose content is still sample."""
        node = self._node(dossier_id, section)
        entry = self.repo.get_section_state(_s(dossier_id), _s(section))
        if not entry or not (entry.get("doc_id")
                             or entry.get("documents")
                             or entry.get("action") in ("uploaded",
                                                        "generated")):
            raise ProblemError(422, "there is no drafted content in this "
                               "section to confirm", rule="nothing_to_confirm",
                               detail=_s(section))
        origin = entry.get("content_origin") or "generated"
        if origin == "sample":
            raise ProblemError(
                422, "This section still shows worked-example values — replace "
                "them in the form and re-author. There is nothing to attest as "
                "your own content until the example is edited.",
                rule="worked_example_not_replaced", detail=_s(section))
        self._write_entry(dossier_id, section, node,
                          action=entry.get("action") or "generated",
                          content_confirmed=True, record_author=True)
        audit_hook.record("dossier.content_confirmed", _s(dossier_id),
                          {"section": _s(section), "prior_origin": origin})
        return self.content_state(dossier_id)

    def prepare_draft_chat(self, dossier_id: str, section: str) -> tuple[dict, dict]:
        """Validate eagerly (raises ProblemError) before any streaming starts,
        so a bad section/unconfigured LLM comes back as a clean JSON error
        instead of failing mid-stream."""
        node = self._node(dossier_id, section)
        key = node.get("generator_key")
        if "generate" not in node["affordances"] or not key:
            raise ProblemError(422, "this section cannot be authored in-app",
                               rule="section_not_generatable", detail=_s(section))
        if key not in generators.LLM_DRAFTABLE:
            raise ProblemError(422, "this document is a structured form — "
                               "AI chat drafting only applies to prose "
                               "documents", rule="section_not_ai_draftable",
                               detail=_s(section))
        if not llm_provider.is_configured():
            raise ProblemError(503, "AI drafting is not configured "
                               "(GROQ_API_KEY unset)", rule="llm_not_configured")
        return node, self._ctx_for(dossier_id)

    def stream_draft_chat(self, node: dict, ctx: dict, messages: list[dict]):
        system = drafting.system_prompt(node, ctx)
        return llm_provider.stream_chat([{"role": "system", "content": system},
                                         *messages])

    def mark_na(self, dossier_id, section, reason="") -> dict:
        node = self._node(dossier_id, section)
        if "mark_na" not in node["affordances"]:
            raise ProblemError(422, "this section cannot be marked N/A",
                               rule="section_not_na", detail=_s(section))
        self._write_entry(dossier_id, section, node, action="na",
                          na_reason=_s(reason))
        audit_hook.record("dossier.section_marked_na", _s(dossier_id),
                          {"section": _s(section), "reason": _s(reason)})
        return self.content_state(dossier_id)

    def _export_validation(self, dossier_id: str) -> dict:
        """Run the full eCTD validation for the export gate. Fails CLOSED: if
        the validator itself cannot run, the report is treated as not-passed."""
        try:
            r = self.validate_submission(dossier_id)
            return {"passed": bool(r.get("passed")), "ran": True,
                    "errors": r.get("errors", []),
                    "criteria": r.get("criteria") or ectd_validation.criteria()}
        except Exception as exc:  # noqa: BLE001 - validator unavailable => block
            return {"passed": False, "ran": False, "errors": [],
                    "criteria": ectd_validation.criteria(),
                    "unavailable": str(exc)}

    def export_sequence(self, dossier_id: str, sequence: str = "0000",
                        tenant_id: str | None = None, *,
                        override: bool = False, reason: str = "") -> dict:
        """The transmissible eCTD package for one sequence, as a zip.

        Fails CLOSED (WS1 trust fix): a package is emitted only when eCTD
        validation passes, or when the caller supplies an explicit override
        WITH a reason — which is flagged on the package and written to the
        audit stream. A silent export of an invalid submission is never done."""
        self._tenant_guard(dossier_id, tenant_id)
        model = self.repo.get_dossier(_s(dossier_id))
        if not model:
            raise ProblemError(404, "no eCTD dossier", detail=_s(dossier_id))
        report = self._export_validation(dossier_id)
        overridden = (not report["passed"]) and bool(override)
        if not report["passed"] and not override:
            raise ProblemError(
                409,
                "validation_not_passed" if report["ran"]
                else "validation_unavailable",
                detail=("Export is blocked — eCTD validation "
                        + ("did not pass. Resolve the findings below, or "
                           "export with an explicit override and a reason."
                           if report["ran"] else
                           "could not run, so export is blocked. Retry, or "
                           "export with an explicit override and a reason.")),
                validation={"passed": report["passed"], "ran": report["ran"],
                            "errors": report["errors"],
                            "criteria": report["criteria"]})
        if overridden and not _s(reason):
            raise ProblemError(
                422, "override_reason_required",
                detail="Overriding a failed-validation export requires a "
                       "written reason — it is recorded to the audit trail.")
        # leaf_id -> stored bytes, via the per-section state (incl. bilingual)
        doc_by_leaf: dict[str, str] = {}
        for section, state in self.repo.list_section_state(_s(dossier_id)).items():
            node = section_tree.node_for(section,
                                         cs_be_only=self._cs_be_only(dossier_id))
            base = (node or {}).get("leaf_id") or ""
            if state.get("doc_id") and (state.get("leaf_id") or base):
                doc_by_leaf[state.get("leaf_id") or base] = state["doc_id"]
            for lang, meta in (state.get("documents") or {}).items():
                if meta and base:
                    doc_by_leaf[f"{base}-{lang}"] = meta["doc_id"]

        def resolve(leaf_id: str):
            doc_id = doc_by_leaf.get(leaf_id)
            if not doc_id:
                # a lifecycle placement (working sequence 0001+) suffixes the
                # sequence onto the base leaf id; the section state still
                # carries the LATEST document under the base id
                m = _SEQ_SUFFIX_RE.match(_s(leaf_id))
                doc_id = doc_by_leaf.get(m.group("base")) if m else None
            if not doc_id:
                return None
            doc = self.store.get(doc_id)
            return doc["body"] if doc else None

        # REP RT XML travels inside every transaction (REP guidance)
        ctx = {**self._ctx_for(dossier_id), "sequence": _s(sequence) or "0000"}
        rt = generators.generate("rep_application_form", ctx)
        # give the CA-regional backbone the real product + company identity
        extra = {"product_names": [_s(ctx.get("drug_product"))]
                 if _s(ctx.get("drug_product")) else [],
                 "company_id": _s(ctx.get("company_id")),
                 "sponsor": _s(ctx.get("sponsor"))}
        pkg = export_pkg.build_package(model, _s(sequence) or "0000",
                                       resolve, rt["body"],
                                       ca_regional_extra=extra)
        audit_hook.record(
            "dossier.sequence_exported_override" if overridden
            else "dossier.sequence_exported", _s(dossier_id),
            {"sequence": _s(sequence) or "0000",
             "files": len(pkg["files"]),
             "missing": len(pkg["missing"]),
             "validation_passed": report["passed"],
             "validation_ran": report["ran"],
             "criteria_version": (report["criteria"] or {}).get("version"),
             **({"override_reason": _s(reason)} if overridden else {})})
        pkg["validation"] = {
            "passed": report["passed"], "ran": report["ran"],
            "overridden": overridden,
            "reason": _s(reason) if overridden else "",
            "criteria": report["criteria"]}
        return pkg

    def form_sample(self, dossier_id: str, section: str,
                    tenant_id: str | None = None) -> dict:
        """Realistic, editable pre-fill for an authorable section's form."""
        self._tenant_guard(dossier_id, tenant_id)
        node = self._node(dossier_id, section)
        key = node.get("generator_key")
        if "generate" not in node["affordances"] or not key:
            raise ProblemError(422, "this section is not authorable",
                               rule="section_not_generatable", detail=_s(section))
        ctx = self._ctx_for(dossier_id)
        return {"section": _s(section), "generator_key": key,
                **form_samples.sample_fields(key, ctx)}

    def form_review(self, dossier_id: str, section: str, fields: dict,
                    tenant_id: str | None = None) -> dict:
        """HC content review of a form's fields — required elements, canada.ca
        links, suggested edits (the 'review mechanism' before filing)."""
        self._tenant_guard(dossier_id, tenant_id)
        node = self._node(dossier_id, section)
        key = node.get("generator_key")
        if not key:
            raise ProblemError(422, "this section has no authorable form",
                               rule="section_not_generatable", detail=_s(section))
        merged = {**self._ctx_for(dossier_id), **(fields or {})}
        result = form_review.review(key, merged)
        result["section"] = _s(section)
        result["generator_key"] = key
        result["guidance_url"] = node.get("source_url")
        return result

    def get_document(self, doc_id: str, tenant_id: str | None = None) -> dict:
        # a document belongs to its dossier — enforce ownership before serving
        # bytes (the doc_id is disclosed in the owner's content response, so a
        # rival tenant could otherwise fetch it directly).
        meta = self.repo.get_document_meta(_s(doc_id))
        if not meta:
            raise ProblemError(404, "document not found", detail=_s(doc_id))
        self._tenant_guard(_s(meta.get("dossier_id")), tenant_id)
        doc = self.store.get(_s(doc_id))
        if not doc:
            raise ProblemError(404, "document not found", detail=_s(doc_id))
        return doc

    def set_fee_status(self, dossier_id, fee_paid, sme_granted) -> dict:
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        self.repo.set_fee_status(_s(dossier_id), bool(fee_paid), bool(sme_granted))
        return self.content_state(dossier_id)

    # -- ADOPT-EVALIDATOR: user-attested external validator result ---------
    # We cannot run Health Canada's official eValidator here, so the honest
    # loop-closer is a USER-ATTESTED external result: the filer runs HC
    # eValidator (or their publisher's validator) on the EXPORTED package and
    # attaches the real outcome. ANDS Studio records it and surfaces it as
    # external, user-attested evidence — NEVER a tool self-claim of parity.
    _ATTESTATION_RESULTS = ("pass", "fail")
    _ATTESTATION_DISCLAIMER = (
        "This is a USER-ATTESTED external result. ANDS Studio did NOT run "
        "Health Canada's eValidator — the filer ran it (or their publisher's "
        "validator) on the exported package and attached the outcome. ANDS "
        "Studio records the attestation; it does not verify or reproduce it."
    )

    def set_evalidator_attestation(self, dossier_id: str, data: dict,
                                   *, actor: str = "",
                                   tenant_id: str | None = None) -> dict:
        """Record the current user-attested external eValidator result. Validates
        the payload, stamps it as external/user-attested (never a tool claim),
        persists it and writes a durable audit-ledger event."""
        self._tenant_guard(dossier_id, tenant_id)
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        result = _s(data.get("result")).lower()
        if result not in self._ATTESTATION_RESULTS:
            raise ProblemError(
                422, "result must be 'pass' or 'fail'",
                rule="attestation_result_invalid", detail=result or "(empty)")
        validator_name = _s(data.get("validator_name"))
        if not validator_name:
            raise ProblemError(
                422, "the validator name is required (e.g. 'HC eValidator', "
                     "'Lorenz eValidator', 'docuBridge')",
                rule="attestation_validator_required")
        attestation = {
            # honesty: this is external evidence the USER supplies, not a tool
            # self-claim. The source label is fixed and is what the UI keys off
            # to render "(external result)".
            "source": "user_attested_external",
            "result": result,
            "validator_name": validator_name,
            "validator_version": _s(data.get("validator_version")) or None,
            "validated_on": _s(data.get("validated_on")) or None,
            "attested_by": _s(actor) or _s(data.get("attested_by")) or None,
            "notes": _s(data.get("notes")) or None,
            "report_filename": _s(data.get("report_filename")) or None,
            "disclaimer": self._ATTESTATION_DISCLAIMER,
            "recorded_at": utcnow_iso(),
        }
        event_data = {"result": result, "validator_name": validator_name,
                      "validator_version": attestation["validator_version"],
                      "validated_on": attestation["validated_on"],
                      "attested_by": attestation["attested_by"]}
        # DURABLE Part-11 record + persistence commit atomically (same local DB).
        saved = self.repo.set_attestation_with_event(
            _s(dossier_id), attestation, actor=_s(actor),
            event_type="dossier.evalidator_attestation_recorded",
            tenant_id=_s(tenant_id), data=event_data)
        # SECONDARY best-effort forward to governance (may fail silently).
        audit_hook.record("dossier.evalidator_attestation_recorded",
                          _s(dossier_id), event_data)
        return saved

    def get_evalidator_attestation(self, dossier_id: str,
                                   tenant_id: str | None = None) -> dict:
        """The current user-attested external eValidator result (or null)."""
        self._tenant_guard(dossier_id, tenant_id)
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        return {"dossier_id": _s(dossier_id),
                "attestation": self.repo.get_evalidator_attestation(
                    _s(dossier_id))}

    # TIER2-PARITY-UX: attach the ACTUAL eValidator report FILE (bytes +
    # filename), not just a filename string. The report bytes go to the blob
    # store (the same durable, tenant-guarded byte store the eCTD documents use)
    # and the resulting doc-id/checksum/filename are recorded ON the user-
    # attested external attestation, so the report is surfaced as downloadable
    # attached evidence. Honesty: the source label + disclaimer are preserved —
    # attaching the file never turns the attestation into a tool self-claim, and
    # the recorded pass/fail + validator fields (if any) are left intact.
    def attach_evalidator_report(self, dossier_id: str, *, filename: str,
                                 content_type: str, body: bytes,
                                 actor: str = "",
                                 tenant_id: str | None = None) -> dict:
        self._tenant_guard(dossier_id, tenant_id)
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        raw = body if isinstance(body, (bytes, bytearray)) else \
            _s(body).encode("utf-8")
        raw = bytes(raw)
        if not raw:
            raise ProblemError(422, "the eValidator report file is empty",
                               rule="evalidator_report_empty")
        try:
            meta = self.store.put(_s(dossier_id), "evalidator-report",
                                  _s(filename) or "evalidator-report.pdf",
                                  _s(content_type) or "application/octet-stream",
                                  raw, origin="evalidator_report")
        except ValueError as exc:
            raise ProblemError(413, str(exc), rule="file_too_large")
        # merge onto the existing attestation (or seed a fresh one). We keep the
        # recorded result/validator fields untouched — only the report file
        # linkage is (re)written here.
        existing = self.repo.get_evalidator_attestation(_s(dossier_id)) or {}
        attestation = {
            **existing,
            "source": "user_attested_external",
            "report_doc_id": meta["doc_id"],
            "report_filename": meta["filename"],
            "report_content_type": meta["content_type"],
            "report_size": meta["size"],
            "report_checksum": meta["checksum"],
            "report_attached_by": _s(actor)
            or existing.get("report_attested_by") or None,
            "report_attached_at": utcnow_iso(),
            "disclaimer": self._ATTESTATION_DISCLAIMER,
        }
        event_data = {"report_doc_id": meta["doc_id"],
                      "report_filename": meta["filename"],
                      "report_size": meta["size"],
                      "report_checksum": meta["checksum"]}
        saved = self.repo.set_attestation_with_event(
            _s(dossier_id), attestation, actor=_s(actor),
            event_type="dossier.evalidator_report_attached",
            tenant_id=_s(tenant_id), data=event_data)
        audit_hook.record("dossier.evalidator_report_attached",
                          _s(dossier_id), event_data)
        return {"dossier_id": _s(dossier_id), "attestation": saved}

    # TIER2-PARITY-UX: self-serve "validate a known-good sequence". The filer
    # points the SAME structural validator at a prior/known-good sequence and
    # sees it pass too — honest confidence-building before trusting a new export.
    # This scopes the assembled model to ONE sequence and runs the exact same
    # ectd_validation.validate the whole-dossier gate uses. It is STRUCTURAL
    # only (the honest criteria/disclaimer travels) — never an HC eValidator
    # parity claim, and it does NOT drive the filing gate.
    def _sequence_scoped_model(self, dossier_id: str,
                               sequence: str) -> tuple[dict, str]:
        model = self.repo.get_dossier(_s(dossier_id))
        if not model:
            raise ProblemError(404, "no eCTD dossier", detail=_s(dossier_id))
        key = _seq4(sequence)
        seq = next((s for s in model.get("sequences", [])
                    if s["sequence"] == key), None)
        if seq is None:
            raise ProblemError(404, "no such sequence on this dossier",
                               detail=key)
        # a single-sequence copy of the model — the validator replays only this
        # sequence's own leaves, exactly what a per-sequence conformance check is.
        return {"dossier_id": model["dossier_id"], "sequences": [seq]}, key

    def validate_sequence(self, dossier_id: str, sequence: str,
                          tenant_id: str | None = None) -> dict:
        self._tenant_guard(dossier_id, tenant_id)
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        scoped, key = self._sequence_scoped_model(dossier_id, sequence)
        result = ectd_validation.validate(scoped)
        result["dossier_id"] = _s(dossier_id)
        result["sequence"] = key
        # honest framing: this is a scoped STRUCTURAL check on one sequence, not
        # a filing-gate verdict and not an HC eValidator parity claim.
        result["scope"] = "sequence"
        return result

    # TIER2-PARITY-UX: file the REP (Regulatory Enrolment Process) Dossier-ID
    # Request from inside the placeholder banner. HONEST: this PREPARES and
    # RECORDS the request intent + returns concrete REP/CESG guidance — it does
    # NOT transmit anything to Health Canada. The recorded intent + guidance
    # land on the durable audit ledger so the filing story is legible.
    _REP_GUIDANCE_STEPS = (
        "Sign in to Health Canada's Common Electronic Submissions Gateway "
        "(CESG) with your company's account.",
        "In the Regulatory Enrolment Process (REP), file a Dossier ID Request "
        "for this regulatory activity (company-id + activity type).",
        "Health Canada issues the real Dossier ID (one letter + 6-7 digits). "
        "It is NOT minted or confirmed by any validator.",
        "Come back and set the real ID on this dossier (the placeholder "
        "→ real-ID Rename) before you export or transmit.",
    )
    _REP_GUIDANCE_URL = ("https://www.canada.ca/en/health-canada/services/"
                         "drugs-health-products/drug-products/"
                         "regulatory-enrolment-process.html")

    def request_rep_dossier_id(self, dossier_id: str, data: dict, *,
                               actor: str = "",
                               tenant_id: str | None = None) -> dict:
        self._tenant_guard(dossier_id, tenant_id)
        idx = self.repo.get_dossier_index(_s(dossier_id))
        if not idx:
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        data = data or {}
        # fall back to the identity already on the dossier index where the
        # caller does not re-supply it — the REP request needs the sponsor's
        # company identity + activity type.
        rep_request = {
            # HONEST, load-bearing flag: this is a prepared intent, never a
            # transmission to Health Canada.
            "transmitted": False,
            "dossier_id": _s(dossier_id),
            "placeholder": _s(dossier_id).startswith("d"),
            "company_id": _s(data.get("company_id")) or _s(idx.get("company_id"))
            or None,
            "sponsor": _s(data.get("sponsor")) or _s(idx.get("sponsor")) or None,
            "activity_type": _s(data.get("activity_type"))
            or _s(idx.get("submission_type")) or "ANDS",
            "contact_email": _s(data.get("contact_email")) or _s(actor) or None,
            "note": _s(data.get("note")) or None,
            "requested_by": _s(actor) or None,
            "requested_at": utcnow_iso(),
            "guidance": {
                "summary": "Prepared REP Dossier-ID Request. ANDS Studio does "
                           "NOT transmit to Health Canada — file this "
                           "through REP (via CESG WebTrader), then set the "
                           "issued ID here.",
                "steps": list(self._REP_GUIDANCE_STEPS),
                "url": self._REP_GUIDANCE_URL,
            },
        }
        event_data = {"company_id": rep_request["company_id"],
                      "activity_type": rep_request["activity_type"],
                      "transmitted": False}
        self.repo.set_rep_request_with_event(
            _s(dossier_id), rep_request, actor=_s(actor),
            event_type="dossier.rep_dossier_id_requested",
            tenant_id=_s(tenant_id), data=event_data)
        audit_hook.record("dossier.rep_dossier_id_requested",
                          _s(dossier_id), event_data)
        return rep_request

    def get_rep_request(self, dossier_id: str,
                        tenant_id: str | None = None) -> dict:
        """The current prepared REP Dossier-ID Request for a dossier (or null).
        HONEST: a recorded intent + guidance, not a transmission."""
        self._tenant_guard(dossier_id, tenant_id)
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        return {"dossier_id": _s(dossier_id),
                "rep_request": self.repo.get_rep_request(_s(dossier_id))}

    # -- ADOPT-PART11-ESIGN: a REAL 21 CFR Part 11 e-signature, end to end --
    # The governance service owns the pure signature domain (identity + reason +
    # UTC + a tamper-evident manifest hash over the checksummed eCTD leaves).
    # This is the DURABLE, dossier-local side: it persists the resulting signed
    # manifest and writes an immutable Part-11 audit-ledger event (who / what /
    # when / why + the manifest hash), and re-verifies the manifest against the
    # live leaf checksums to detect tampering. Honesty: this is Part-11-ALIGNED
    # and verifiable — it is NOT an external certification claim.
    def _current_leaf_checksums(self, dossier_id: str) -> dict:
        """The live leaf_id -> checksum map for a dossier, from the real
        assembled files view — the exact set a manifest is verified against."""
        fv = self.files_view(_s(dossier_id)) or {}
        out: dict = {}
        for node in fv.get("nodes") or []:
            for leaf in node.get("leaves") or []:
                lid = _s(leaf.get("leaf_id")) or _s(leaf.get("href"))
                cs = _s(leaf.get("checksum"))
                if lid and cs:
                    out[lid] = cs
        return out

    def content_authors(self, dossier_id: str,
                         tenant_id: str | None = None) -> dict:
        """The distinct identities that AUTHORED this dossier's content — from
        the ``content_author`` stamped on each section when it was uploaded /
        generated / confirmed. This is the author set a Part-11 e-signature is
        checked against for segregation of duties.

        Honesty: these are the recorded author identity strings — NOT an
        SSO/IdP-verified identity. Where no author was recorded (older content,
        in-process mesh with no actor), the section simply contributes none."""
        self._tenant_guard(dossier_id, tenant_id)
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        seen: dict[str, str] = {}
        by_section: dict[str, str] = {}
        for section, state in self.repo.list_section_state(
                _s(dossier_id)).items():
            who = _s((state or {}).get("content_author"))
            if not who:
                continue
            by_section[_s(section)] = who
            key = who.lower()
            if key not in seen:
                seen[key] = who
        authors = list(seen.values())
        return {"dossier_id": _s(dossier_id), "authors": authors,
                "author_count": len(authors), "by_section": by_section}

    @staticmethod
    def _sod_check(signer: str, authors: list) -> dict:
        """TIER2-ROLE-SEP: a segregation-of-duties check — the signer must be a
        DISTINCT authorized approver from the author(s) of the signed content.
        Mirrors the governance e-sign domain's semantics on the DURABLE side so
        the record is authoritative even when the manifest was minted elsewhere.
        Identity comparison is case/whitespace-insensitive (same person).

        Honesty: a role-SEPARATION check ("the signer attests as a distinct
        approver"), NOT an SSO/IdP identity assertion."""
        signer_key = _s(signer).lower()
        by_key: dict[str, str] = {}
        for a in (authors or []):
            key = _s(a).lower()
            if key and key not in by_key:
                by_key[key] = _s(a)
        authorship_known = bool(by_key)
        conflicting = [disp for k, disp in by_key.items() if k == signer_key]
        conflict = bool(conflicting)
        separated = authorship_known and not conflict
        reason = (
            "The signer is also an author of the content being signed — a "
            "segregation-of-duties conflict. A 21 CFR Part 11 signature is most "
            "defensible when the signer is a distinct authorized approver from "
            "the author(s)." if conflict else
            ("The signer is distinct from all recorded author(s) of the signed "
             "content." if separated else
             "No author identity is recorded for the signed content, so "
             "separation of duties cannot be proven from the record."))
        return {"separated": separated, "conflict": conflict,
                "authorship_known": authorship_known, "signer": _s(signer),
                "authors": list(by_key.values()), "author_count": len(by_key),
                "conflicting_authors": conflicting, "reason": reason}

    def _workspace_requires_sod(self, tenant_id: str) -> bool:
        """TIER3-SOD-ENFORCE: does this workspace's policy REQUIRE segregation of
        duties? Read best-effort from the injected identity policy port. No
        tenant context (in-process mesh / owner) or no port wired => False.
        Any read error degrades to False (advisory) — a policy read that fails
        must never break the sign path."""
        if not tenant_id or self.policy is None:
            return False
        try:
            pol = self.policy.workspace_policy(tenant_id) or {}
            return bool(pol.get("require_sod"))
        except Exception:
            return False

    def record_esign(self, dossier_id: str, manifest: dict, *,
                     actor: str = "", tenant_id: str | None = None) -> dict:
        """Persist a signed e-signature manifest and write its durable Part-11
        audit-ledger event atomically. The manifest is produced by the
        governance e-sign domain (bound over the checksummed eCTD leaves); here
        we make it a durable, verifiable, immutably-recorded signing act.

        TIER2-ROLE-SEP: a segregation-of-duties check runs here too — the signer
        is compared against the recorded author(s) of the dossier's content. The
        default posture SURFACES + WARNS (recording the outcome on the manifest
        and audit event); when the tenant enforces SoD (``enforce_segregation``
        on the manifest) a signer who is also an author is REJECTED."""
        self._tenant_guard(dossier_id, tenant_id)
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        manifest = dict(manifest or {})
        artifacts = manifest.get("artifacts") or []
        if not artifacts:
            raise ProblemError(
                422, "a signed manifest must bind at least one checksummed leaf",
                rule="esign_artifacts_required")
        manifest_id = _s(manifest.get("manifest_id"))
        if not manifest_id:
            raise ProblemError(422, "the manifest hash is required",
                               rule="esign_manifest_id_required")
        signer = _s(manifest.get("signer"))
        reason = _s(manifest.get("reason"))
        signed_at = _s(manifest.get("at")) or utcnow_iso()
        manifest["at"] = signed_at
        # CAMP-SSO-OIDC: the signer's identity assurance travels on the manifest
        # (stamped by the governance sign domain). Default to the honest
        # 'recorded_email' posture when a caller signs a bare manifest.
        identity = manifest.get("identity") or {
            "assurance": "recorded_email", "verified": False,
            "statement": "identity: recorded email (not SSO-verified)"}
        manifest["identity"] = identity
        # TIER2-ROLE-SEP: re-derive the authors from the durable record (a caller
        # may also supply them inline on the manifest; the union is checked so a
        # signer cannot dodge SoD by withholding one). Then run the check and
        # stamp the outcome onto the manifest for the immutable Part-11 record.
        derived = self.content_authors(_s(dossier_id),
                                       tenant_id=tenant_id)["authors"]
        supplied = [a for a in (manifest.get("authors") or [])]
        # TIER3-SOD-ENFORCE: effective enforcement is the OR of the manifest's
        # own opt-in flag (TIER2) and the per-WORKSPACE policy (require_sod). The
        # workspace policy is the single source of truth an admin toggles once;
        # the manifest flag remains an honored per-signature opt-in for callers
        # that already know. We record WHICH source drove enforcement.
        manifest_enforce = bool(manifest.get("enforce_segregation"))
        policy_enforce = self._workspace_requires_sod(_s(tenant_id))
        enforce_sod = manifest_enforce or policy_enforce
        sod_policy_source = ("workspace_policy" if policy_enforce
                             else "manifest" if manifest_enforce else "off")
        sod = self._sod_check(signer, list(derived) + list(supplied))
        sod["enforced"] = enforce_sod
        if enforce_sod and sod["conflict"]:
            raise ProblemError(
                422, "Segregation of duties is required: the signer "
                     f"({signer}) is also an author of the content being "
                     "signed. A distinct authorized approver must apply this "
                     "signature.",
                rule="segregation_of_duties")
        manifest["segregation_of_duties"] = sod
        # who/what/when/why on the immutable trail — the Part-11 signing record
        event_data = {
            "signer": signer, "meaning": _s(manifest.get("meaning")),
            "reason": reason, "manifest_id": manifest_id,
            "leaf_count": len(artifacts), "signed_at": signed_at,
            "auth_method": _s(manifest.get("auth_method")),
            # CAMP-SSO-OIDC: the identity assurance on the immutable Part-11
            # record — 'sso_verified (issuer)' vs 'recorded_email'.
            "identity_assurance": _s(identity.get("assurance")),
            "identity_verified": bool(identity.get("verified")),
            "identity_issuer": _s(identity.get("issuer")),
            "identity_statement": _s(identity.get("statement")),
            # SoD outcome is part of the Part-11 record — who authored vs signed
            "sod_conflict": sod["conflict"], "sod_separated": sod["separated"],
            "sod_conflicting_authors": sod["conflicting_authors"],
            "sod_enforced": enforce_sod,
            # TIER3-SOD-ENFORCE: what drove enforcement — the immutable Part-11
            # record shows whether the workspace policy or a manifest opt-in
            # (or nothing) governed this signing.
            "sod_policy_source": sod_policy_source,
        }
        self.repo.set_esign_with_event(
            _s(dossier_id), manifest, actor=_s(actor) or signer,
            event_type="dossier.esign_signed", tenant_id=_s(tenant_id),
            data=event_data)
        # SECONDARY best-effort forward to the central governance audit trail.
        audit_hook.record("dossier.esign_signed", _s(dossier_id), event_data)
        return {
            "dossier_id": _s(dossier_id), "signer": signer, "reason": reason,
            "meaning": _s(manifest.get("meaning")), "manifest_id": manifest_id,
            "leaf_count": len(artifacts), "signed_at": signed_at,
            "tz": _s(manifest.get("tz")) or "UTC",
            "policy": _s(manifest.get("policy")),
            "segregation_of_duties": sod,
            # honesty guardrail surfaced with the record itself
            "alignment": ("21 CFR Part 11 / GxP aligned — immutable, "
                          "meaning-bearing, verifiable. Not an external "
                          "certification."),
        }

    def get_esign(self, dossier_id: str,
                  tenant_id: str | None = None) -> dict:
        """The current signed manifest for a dossier (or null)."""
        self._tenant_guard(dossier_id, tenant_id)
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        return {"dossier_id": _s(dossier_id),
                "manifest": self.repo.get_esign_manifest(_s(dossier_id))}

    def verify_esign(self, dossier_id: str, *, current: dict | None = None,
                     tenant_id: str | None = None) -> dict:
        """Re-verify the signed manifest by comparing each signed leaf checksum
        against the CURRENT checksum — a modified or removed leaf invalidates the
        signature. ``current`` may be supplied (the exact set to check against);
        when omitted it is re-derived from the live assembled files view."""
        self._tenant_guard(dossier_id, tenant_id)
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        manifest = self.repo.get_esign_manifest(_s(dossier_id))
        if not manifest:
            return {"signed": False, "verified": False, "tampered": False,
                    "findings": [], "manifest_id": ""}
        live = current if current is not None else \
            self._current_leaf_checksums(dossier_id)
        live = {str(k): _s(v) for k, v in (live or {}).items()}
        findings = []
        for art in manifest.get("artifacts") or []:
            lid = _s(art.get("id"))
            signed = _s(art.get("checksum"))
            now = live.get(lid)
            if now is None:
                findings.append({
                    "rule": "signed_artifact_missing", "artifact": lid,
                    "message": f"Signed artifact '{lid}' is no longer present — "
                               "the signature is invalidated"})
            elif now != signed:
                findings.append({
                    "rule": "signed_content_modified", "artifact": lid,
                    "signed_checksum": signed, "current_checksum": now,
                    "message": f"Artifact '{lid}' was modified after signing — "
                               "the signature is invalidated"})
        tampered = bool(findings)
        return {
            "signed": True, "verified": not tampered, "tampered": tampered,
            "findings": findings, "manifest_id": _s(manifest.get("manifest_id")),
            "signer": _s(manifest.get("signer")),
            "reason": _s(manifest.get("reason")),
            "signed_at": _s(manifest.get("at")),
            "leaf_count": len(manifest.get("artifacts") or []),
        }

    def validate_submission(self, dossier_id: str) -> dict:
        """Full eCTD technical validation — includes PDF conformance on the
        stored bytes (heavier than the structural check in content_state)."""
        # ADOPT-EVALIDATOR: the user-attested external eValidator result travels
        # ALONGSIDE the structural check as a distinct, clearly-labeled signal.
        # It NEVER drives the structural `passed` flag — it is external evidence
        # the filer supplied, surfaced so the UI can show
        # "HC eValidator: PASSED — attested by <user> on <date> (external result)".
        external = self.repo.get_evalidator_attestation(_s(dossier_id))
        model = self.repo.get_dossier(_s(dossier_id))
        if not model:
            return {"passed": True, "errors": [], "warnings": [], "checked": 0,
                    "external_attestation": external}
        documents = {}
        for state in self.repo.list_section_state(_s(dossier_id)).values():
            for meta in ([state.get("document")]
                         + list((state.get("documents") or {}).values())):
                if not meta:
                    continue
                doc = self.store.get(meta["doc_id"])
                if doc:
                    documents[meta.get("filename") or meta["doc_id"]] = doc["body"]
        result = ectd_validation.validate(model, documents=documents)
        # SAFETY (WS2): the export gate fails closed on unconfirmed sample/AI
        # content. Surface each such section as a hard validation error so a
        # worked example is structurally incapable of reaching a filing — WS1's
        # export gate already blocks on any error, so no WS1 code is touched.
        for section, state in self.repo.list_section_state(
                _s(dossier_id)).items():
            if dossier_state.needs_review(state):
                origin = state.get("content_origin") or "sample"
                label = ("AI-drafted" if origin == "ai_draft"
                         else "sample-origin")
                result["errors"].append({
                    "rule": "unconfirmed_sample_content",
                    "rule_id": "CA-WS2-0001",
                    "message": f"Section {section} holds {label} content that "
                               "has not been reviewed and confirmed. Open the "
                               "section and confirm it as your own content "
                               "before filing.",
                    "leaf": section})
                result["passed"] = False
        if _s(dossier_id).startswith("d"):
            result["errors"].insert(0, {
                "rule": "placeholder_dossier_id", "rule_id": "CA-REP-0001",
                "message": "This dossier still uses a placeholder ID "
                           f"({_s(dossier_id)}). File a Dossier ID Request "
                           "through REP, then set the real Health Canada ID "
                           "(Rename) before filing.", "leaf": None})
            result["passed"] = False
        result["external_attestation"] = external
        return result

    # -- TIER3-PREFLIGHT: ONE consolidated pre-flight / QA hand-off report ----
    # Tier-2 respondents (multiple, verbatim): "give me ONE consolidated
    # pre-flight report I can hand to QA rather than re-running validate at each
    # step." This ASSEMBLES the whole filing-readiness picture into a single
    # object a QA reviewer or client can archive — RESOLVING the "re-run validate
    # everywhere" limit instead of disclosing yet another caveat.
    #
    # HONESTY: this consolidates already-honest pieces; it never launders a
    # caveat away. Every disclaimer travels INLINE (structural-only, external
    # attestation, e-sign is Part-11-aligned but NOT an external certification,
    # REP is prepared but NOT transmitted). The readiness summary is a STRUCTURAL
    # statement and always names the still-required HC eValidator step — it never
    # claims Health Canada acceptance. No new persistence: pure read + compose
    # over the existing service methods (each keeps its own tenant guard).
    _PREFLIGHT_DISCLAIMERS = {
        "validation": (
            "The eCTD validation here is ANDS Studio's own STRUCTURAL/technical "
            "check, not Health Canada's official eValidator. A clean result "
            "means the sequence is structurally plausible — it does NOT mean it "
            "will pass HC's eValidator or be accepted on screening."),
        "evalidator": (
            "Any eValidator result shown is a USER-ATTESTED external result the "
            "filer supplied — ANDS Studio did not run HC's eValidator and does "
            "not verify or reproduce it."),
        "esign": (
            "The e-signature is 21 CFR Part 11 / GxP ALIGNED (immutable, "
            "meaning-bearing, verifiable) — it is NOT an external certification, "
            "and the segregation-of-duties check is a role-separation signal, "
            "not an SSO/IdP identity assertion."),
        "rep": (
            "The Dossier-ID / REP status reflects a PREPARED request and "
            "guidance — ANDS Studio does NOT transmit anything to Health Canada. "
            "File through REP (via CESG WebTrader) and set the issued real "
            "Dossier ID before you transmit."),
        "scope": (
            "This is a consolidated readiness snapshot for QA hand-off. It is "
            "not a Health Canada review, not a filing acceptance, and not a "
            "certification. Archive it alongside — not instead of — the official "
            "HC eValidator run on the exported package."),
    }

    def preflight_report(self, dossier_id: str,
                         tenant_id: str | None = None) -> dict:
        """Assemble the single consolidated pre-flight / QA hand-off report.

        Composes (each already honest, each behind its own tenant guard):
          - the named/versioned eCTD STRUCTURAL validation (report + criteria +
            synced), incl. the user-attested external eValidator attestation it
            already carries;
          - the Part-11 e-sign manifest + SoD outcome + a LIVE verification
            against the current leaf checksums (tamper-evidence);
          - the fee / small-business state;
          - the lifecycle / sequence view;
          - the placeholder/real Dossier-ID + REP request status.
        A top-level readiness summary reflects the STRUCTURAL gate only.
        """
        dossier_id = _s(dossier_id)
        self._tenant_guard(dossier_id, tenant_id)
        idx = self.repo.get_dossier_index(dossier_id)
        if not idx:
            raise ProblemError(404, "no such dossier", detail=dossier_id)

        # full technical validation (PDF-byte checks + sample/placeholder gates);
        # it already embeds the versioned criteria and the external attestation.
        validation = self.validate_submission(dossier_id)
        evalidator = self.repo.get_evalidator_attestation(dossier_id)

        # e-sign: the signed manifest + a LIVE re-verification (tamper-evidence)
        manifest = self.repo.get_esign_manifest(dossier_id)
        verification = self.verify_esign(dossier_id, tenant_id=tenant_id)
        esign = {
            "signed": bool(manifest),
            "manifest": manifest,
            "segregation_of_duties": (manifest or {}).get(
                "segregation_of_duties"),
            "verification": verification,
        }

        # fee / lifecycle: reuse content_state's already-computed blocks.
        state = self.content_state(dossier_id)
        fees_block = state.get("fees")
        sequences = self.list_sequences(dossier_id)

        # REP / Dossier-ID identity
        placeholder = dossier_id.startswith("d")
        rep = {
            "dossier_id": dossier_id,
            "placeholder": placeholder,
            "rep_request": self.repo.get_rep_request(dossier_id),
        }

        # readiness: a STRUCTURAL statement — never an HC acceptance claim.
        passed = bool(validation.get("passed"))
        n_err = len(validation.get("errors") or [])
        if passed:
            summary = ("No structural issues — the dossier is structurally "
                       "plausible for filing. This is NOT a Health Canada "
                       "review or acceptance.")
        else:
            summary = (f"{n_err} structural issue(s) remain — resolve them "
                       "before filing. This is a structural check, not a "
                       "Health Canada review.")
        readiness = {
            "ready": passed,
            "structural_errors": n_err,
            "structural_warnings": len(validation.get("warnings") or []),
            "signed": bool(manifest),
            "signature_verified": bool(verification.get("verified")),
            "fee_arranged": bool((fees_block or {}).get("fee_paid")),
            "evalidator_attested": bool(evalidator),
            "placeholder_dossier_id": placeholder,
            "summary": summary,
            "claim": "Structural readiness snapshot — not a Health Canada "
                     "acceptance or certification.",
            "next_step": ("Run Health Canada's official eValidator on the "
                          "exported package before you transmit. A clean check "
                          "here does not replace it."),
        }

        return {
            "dossier_id": dossier_id,
            "title": _s(idx.get("title")) or dossier_id,
            "drug_product": _s(idx.get("drug_product")) or None,
            "sponsor": _s(idx.get("sponsor")) or None,
            "submission_type": _s(idx.get("submission_type")) or None,
            "din": idx.get("din"),
            "generated_at": utcnow_iso(),
            "readiness": readiness,
            "validation": validation,
            "evalidator_attestation": evalidator,
            "esign": esign,
            "fees": fees_block,
            "sequences": sequences,
            "rep": rep,
            "disclaimers": dict(self._PREFLIGHT_DISCLAIMERS),
        }

    def content_state(self, dossier_id: str) -> dict:
        dossier_id = _s(dossier_id)
        idx = self.repo.get_dossier_index(dossier_id) or {}
        cs_be_only = self._cs_be_only(dossier_id)
        states = self.repo.list_section_state(dossier_id)
        tree = section_tree.section_tree(cs_be_only=cs_be_only)
        modules = []
        for m in tree["modules"]:
            modules.append({
                "module": m["module"], "title": m["title"],
                "nodes": dossier_state.annotate(m["nodes"], states),
                "progress": dossier_state.module_progress(m["nodes"], states)})
        model = self.repo.get_dossier(dossier_id)

        section_gate = dossier_state.completeness_gate(cs_be_only=cs_be_only,
                                                       states=states)
        today = date.today().isoformat()
        review_fee = fees.ands_review_fee(today)
        fee_paid = bool(idx.get("fee_paid"))
        sme_granted = bool(idx.get("sme_granted"))
        fees_block = {
            "review_fee": review_fee,
            "mitigation": fees.small_business_mitigation(
                review_fee["amount"], sme_granted=sme_granted,
                first_ever_submission=False),
            "right_to_sell": fees.right_to_sell(today, sme_granted=sme_granted),
            "fee_paid": fee_paid, "sme_granted": sme_granted}
        # structural eCTD validation (PDF-byte checks are in validate_submission)
        validation = (ectd_validation.validate(model) if model
                      else {"passed": True, "errors": [], "warnings": [],
                            "checked": 0})
        # combined "ready to file" gate: content + fee arranged + validation clean
        missing = list(section_gate["missing"])
        # SAFETY: surface the unconfirmed sample/AI drafts as an explicit
        # pre-file blocker ("N sample values remain") so a worked example can
        # never silently ride into a real Health Canada filing.
        sample_count = section_gate.get("unconfirmed_sample_count", 0)
        if sample_count:
            missing.append({
                "section": "unconfirmed_sample", "module": "",
                "needs_review": True,
                "title": f"{sample_count} sample/AI draft value(s) still need "
                         "your review — confirm each as your own content "
                         "before filing"})
        if not fee_paid:
            missing.append({"section": "1.2.2", "module": "1",
                            "title": "Fee payment / small-business status "
                                     "(arrange before filing)"})
        for e in validation.get("errors", []):
            missing.append({"section": "validation", "module": "",
                            "title": e.get("message", "eCTD validation error")})
        gate = {"complete": (section_gate["complete"] and fee_paid
                             and validation.get("passed", True)),
                "missing": missing,
                "section_complete": section_gate["complete"],
                "fee_paid": fee_paid,
                "validation_passed": validation.get("passed", True),
                "unconfirmed_sample_count": sample_count}
        return {
            "dossier_id": dossier_id, "cs_be_only": cs_be_only,
            "version": tree["version"], "modules": modules, "gate": gate,
            "tower": dossier_state.tower_view(cs_be_only=cs_be_only, states=states),
            "fees": fees_block, "validation": validation, "din": idx.get("din"),
            "files_view": assembly.build_files_view(model) if model else None}

    # -- dossier + sequence management (home catalog) ----------------------
    def create_dossier(self, data: dict, tenant_id: str | None = None) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        if not dossier_id:
            raise ProblemError(422, "dossier_id is required",
                               rule="dossier_id_required")
        din = _s(data.get("din"))
        if din and not _DIN_RE.match(din):
            raise ProblemError(422, "DIN must be exactly 8 digits (note: a DIN "
                               "is assigned by Health Canada at NOC, not filed)",
                               rule="din_invalid")
        self._tenant_guard(dossier_id, tenant_id)   # no cross-tenant upsert
        rec = self.repo.create_dossier_index({
            "dossier_id": dossier_id,
            "title": _s(data.get("title")) or dossier_id,
            "submission_type": _s(data.get("submission_type")).upper() or "ANDS",
            "cs_be_only": bool(data.get("cs_be_only", True)),
            "din": din or None,
            # the real product name — distinct from a display title
            "drug_product": (_s(data.get("drug_product"))
                             or _s(data.get("title")) or None),
            # REP identity — sponsor company (distinct from the product title)
            "company_id": _s(data.get("company_id")) or None,
            "sponsor": _s(data.get("sponsor")) or None,
            # WS6 portfolio: the accountable PM/owner for this dossier
            "owner": _s(data.get("owner")) or None,
            "tenant_id": _s(tenant_id) or None})
        model = self._dossier_model(dossier_id, create=True)
        assembly.add_sequence(model, "0000")
        self.repo.save_dossier(model)
        return rec

    def _tenant_guard(self, dossier_id: str, tenant_id: str | None) -> None:
        """Enforce per-dossier tenant ownership. When a tenant context is
        present (every authenticated request via the web proxy carries one), a
        dossier owned by a DIFFERENT tenant — or by no tenant at all — is
        invisible (404, not 403, to avoid confirming existence). tenant_id
        empty = no scoping (in-process mesh / tests only)."""
        if not tenant_id:
            return
        idx = self.repo.get_dossier_index(_s(dossier_id))
        if idx is None:
            return   # genuinely absent — let the caller's own 404 handle it
        owner = _s(idx.get("tenant_id"))
        if owner != _s(tenant_id):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))

    def assert_access(self, dossier_id: str, tenant_id: str | None) -> None:
        """Public tenant-ownership gate — the API layer calls this on every
        dossier-scoped route before delegating."""
        self._tenant_guard(dossier_id, tenant_id)

    def _forward_governance(self, event_type: str, dossier_id: str, *,
                            reason: str = "", data: dict | None = None) -> None:
        """SECONDARY, best-effort sink: forward an already-durably-recorded
        event to governance. Runs AFTER the atomic ledger+mutation transaction
        has committed, and is free to fail — the local uid-keyed ledger is the
        authoritative Part-11 record QA/inspectors read."""
        audit_hook.record(event_type, _s(dossier_id),
                          {**(data or {}), "reason": reason})

    def dossier_history(self, dossier_id: str,
                        tenant_id: str | None = None) -> dict:
        """The DURABLE local Part-11 ledger for a dossier (chained across any
        rename so the previous_id still resolves). This is the tamper-evident
        record that cannot be silently lost when governance is unreachable."""
        self._tenant_guard(dossier_id, tenant_id)
        events = self.repo.list_events(_s(dossier_id))
        return {"dossier_id": _s(dossier_id), "events": events,
                "count": len(events)}

    def delete_dossier(self, dossier_id: str, tenant_id: str | None = None,
                       reason: str = "", confirm_id: str = "") -> dict:
        """RECORD-INTEGRITY (WS3): a destructive delete on a regulated dossier
        is RECOVERABLE — it soft-archives (actor + timestamp + reason) instead
        of purging. The dossier drops out of the working catalog but stays
        restorable, and the archive lands on the DURABLE local audit ledger with
        a reason-for-change field. A written reason is REQUIRED (Part-11 why).

        SERVER-SIDE typed-id gate: the caller must echo the exact dossier_id as
        ``confirm_id``. The client's 'type the ID to delete' box is not enough —
        a direct API DELETE would otherwise bypass it — so the destructive
        confirmation is enforced here on the server."""
        self._tenant_guard(dossier_id, tenant_id)
        reason = _s(reason)
        if not reason:
            raise ProblemError(
                422, "a reason is required to archive a dossier",
                rule="archive_reason_required",
                detail="Deleting a regulated dossier archives it (recoverable) "
                       "and is recorded to the audit trail — state why.")
        if str(confirm_id or "") != _s(dossier_id):
            raise ProblemError(
                422, "confirm_id must match the dossier ID",
                rule="delete_confirm_id_mismatch",
                detail="Type the exact Dossier ID to confirm this destructive "
                       "delete. The typed confirmation is enforced on the "
                       "server, not just in the browser (exact match — no "
                       "leading/trailing spaces).")
        # existence + not-already-archived guard BEFORE the durable write, so we
        # never log a phantom archive for a missing/already-archived dossier.
        idx = self.repo.get_dossier_index(_s(dossier_id))
        if not idx or idx.get("archived_at"):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        # actor from the request contextvar so the stored stamp is
        # reconstructable offline (who), independent of the audit forward.
        actor = audit_hook._actor.get()
        # ATOMIC: the soft-archive state flip AND the durable audit write commit
        # in ONE transaction — either both persist or neither. A ledger-write
        # failure rolls the archive back (no mutation without a record); a
        # raced/absent dossier (archive is a no-op -> None) commits nothing (no
        # phantom audit). The local uid-keyed ledger survives a governance
        # outage; the governance forward below is a secondary best-effort sink.
        ev = self.repo.archive_with_event(
            _s(dossier_id), actor=actor, reason=reason,
            event_type="dossier.archived",
            tenant_id=audit_hook._tenant.get(), data={"recoverable": True})
        if ev is None:
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        self._forward_governance("dossier.archived", _s(dossier_id),
                                 reason=reason, data={"recoverable": True})
        return {"archived": _s(dossier_id), "reason": reason,
                "recoverable": True}

    def restore_dossier(self, dossier_id: str, tenant_id: str | None = None,
                        reason: str = "") -> dict:
        """Undo a soft-delete: return the dossier to the working catalog. The
        restore is itself recorded to the DURABLE local audit ledger (who/when/
        why). RESTORE MUST NOT DESTROY EVIDENCE: flipping ``archived_at`` back
        to NULL clears the 'currently archived' flag, but the ledger still
        carries the archive event (who/when/why) AND the restore event captures
        the prior archive stamp it undid, so the record the dossier was ever
        archived is never erased."""
        self._tenant_guard(dossier_id, tenant_id)
        # capture the archive stamp being undone BEFORE the repo NULLs it, so
        # the durable restore event preserves that evidence.
        idx = self.repo.get_dossier_index(_s(dossier_id)) or {}
        if not idx.get("archived_at"):
            # absent, or not currently archived — don't log a phantom restore
            raise ProblemError(404, "no archived dossier to restore",
                               detail=_s(dossier_id))
        prior = {"prior_archived_at": idx.get("archived_at"),
                 "prior_archived_by": idx.get("archived_by"),
                 "prior_archive_reason": idx.get("archive_reason")}
        actor = audit_hook._actor.get()
        # ATOMIC restore + durable audit (prior archive evidence captured above,
        # BEFORE the repo NULLs it). One transaction: a raced/failed restore
        # (no-op -> None) leaves no phantom restore entry; a ledger failure rolls
        # the restore back. Governance forward is a secondary best-effort sink.
        ev = self.repo.restore_with_event(
            _s(dossier_id), actor=actor, reason=_s(reason),
            event_type="dossier.restored",
            tenant_id=audit_hook._tenant.get(), data=prior)
        if ev is None:
            # absent, or not currently archived
            raise ProblemError(404, "no archived dossier to restore",
                               detail=_s(dossier_id))
        self._forward_governance("dossier.restored", _s(dossier_id),
                                 reason=_s(reason), data=prior)
        return {"restored": _s(dossier_id), "reason": _s(reason)}

    def list_archived(self, tenant_id: str | None = None) -> dict:
        """The recoverable 'trash' view — soft-archived dossiers a user can
        restore, each carrying its archive stamp (who/when/why)."""
        rows = self.repo.list_archived_index(_s(tenant_id) or None)
        return {"dossiers": rows, "count": len(rows)}

    def rename_dossier(self, dossier_id: str, new_id: str,
                       tenant_id: str | None = None, reason: str = "") -> dict:
        """Re-key a dossier — the 'placeholder to real HC Dossier ID' path.
        Users can start work before Health Canada issues their ID (REP
        Dossier ID Request) and set the real one here later. The before/after
        IDs and an optional reason-for-change land on the audit trail."""
        old, new = _s(dossier_id), _s(new_id).lower()
        self._tenant_guard(old, tenant_id)
        if not _ID_RE.match(new):
            raise ProblemError(422, "Dossier ID must be one letter + 6-7 "
                               "digits (e.g. e123456)", rule="dossier_id_format")
        if new == old:
            raise ProblemError(422, "new ID is identical",
                               rule="dossier_id_same")
        if self.repo.get_dossier_index(new):
            raise ProblemError(409, f"a dossier with ID {new} already exists",
                               rule="dossier_id_taken")
        if not self.repo.get_dossier_index(old):
            raise ProblemError(404, "no such dossier", detail=old)
        actor = audit_hook._actor.get()
        data = {"previous_id": old, "new_id": new,
                # a 'd' placeholder -> real HC id is the distinctive regulatory
                # event; flag it for the trail readers
                "placeholder_to_real": old.startswith("d")}
        # ATOMIC re-key + durable 'renamed' event + rename-chain in ONE
        # transaction. The dossier's uid is IMMUTABLE across the re-key, so the
        # event (appended under the NEW id) lands on the SAME uid as its prior
        # events — a history read for the new id surfaces the whole life, while a
        # DIFFERENT dossier later reusing a freed id has its own uid and inherits
        # nothing. A raced/failed re-key (no-op -> None) commits nothing: no
        # orphan chain, no phantom 'renamed' event that could mis-attribute
        # another dossier's history to a reused id.
        ev = self.repo.rename_with_event(
            old, new, actor=actor, reason=_s(reason),
            event_type="dossier.renamed",
            tenant_id=audit_hook._tenant.get(), data=data)
        if ev is None:
            raise ProblemError(404, "no such dossier", detail=old)
        # SECONDARY sink: governance forward stays, best-effort.
        self._forward_governance("dossier.renamed", new, reason=_s(reason),
                                 data=data)
        return {"renamed": old, "dossier_id": new}

    def list_dossiers(self, tenant_id: str | None = None) -> dict:
        out = []
        for idx in self.repo.list_dossier_index(_s(tenant_id) or None):
            states = self.repo.list_section_state(idx["dossier_id"])
            out.append({**idx,
                        # WS6 portfolio: the soonest upcoming deadline for this
                        # dossier — DERIVED from its content-plan items, not
                        # stored (owner/sponsor pass through from the index).
                        "soonest_due": self._soonest_due(idx["dossier_id"]),
                        "tower": dossier_state.tower_view(
                            cs_be_only=idx["cs_be_only"], states=states),
                        "gate": dossier_state.completeness_gate(
                            cs_be_only=idx["cs_be_only"], states=states)})
        return {"dossiers": out, "count": len(out)}

    def _soonest_due(self, dossier_id: str) -> str | None:
        """Earliest ISO ``due_date`` across the dossier's OPEN (non-complete)
        content-plan items, or None. A completed item is not an upcoming
        deadline. Pure read — no new storage; the deadline is the truth already
        held on the plan items (see ``assign_item``)."""
        plan = self.repo.get_plan_by_dossier(_s(dossier_id))
        if not plan:
            return None
        due = [d for d in (
                _s(i.get("due_date")) for i in plan.get("items", [])
                if i.get("status") != content_plan.ITEM_COMPLETE)
               if d]
        return min(due) if due else None

    def get_dossier_full(self, dossier_id: str,
                         tenant_id: str | None = None) -> dict:
        dossier_id = _s(dossier_id)
        self._tenant_guard(dossier_id, tenant_id)
        idx = self.repo.get_dossier_index(dossier_id)
        if not idx:
            # tolerate a dossier that exists as an eCTD model but has no index yet
            idx = {"dossier_id": dossier_id, "title": dossier_id,
                   "submission_type": "ANDS", "cs_be_only": True}
        return {"index": idx, "content": self.content_state(dossier_id)}

    def list_sequences(self, dossier_id: str) -> dict:
        model = self.repo.get_dossier(_s(dossier_id)) or \
            assembly.new_dossier(_s(dossier_id))
        active = self._active_sequence(dossier_id)
        return {"dossier_id": _s(dossier_id), "active_sequence": active,
                "sequences": [{"sequence": s["sequence"],
                               "purpose": s.get("purpose") or "initial",
                               "note": s.get("note") or "",
                               "leaf_count": len(s["leaves"]),
                               "active": s["sequence"] == active}
                              for s in model["sequences"]]}

    def create_sequence(self, dossier_id: str, sequence: str,
                        purpose: str = "", note: str = "") -> dict:
        purpose = _s(purpose)
        if purpose and purpose not in SEQUENCE_PURPOSES:
            raise ProblemError(422, "purpose must be one of "
                               + ", ".join(SEQUENCE_PURPOSES),
                               rule="sequence_purpose_invalid")
        model = self._dossier_model(dossier_id, create=True)
        seq = _s(sequence) or "0000"
        assembly.add_sequence(model, seq, purpose=purpose, note=_s(note))
        self.repo.save_dossier(model)
        # the newly opened sequence becomes the ACTIVE working sequence
        self.repo.set_active_sequence(_s(dossier_id), _seq4(seq))
        return self.list_sequences(dossier_id)

    def activate_sequence(self, dossier_id: str, sequence: str) -> dict:
        model = self.repo.get_dossier(_s(dossier_id))
        key = _seq4(sequence)
        known = {s["sequence"] for s in (model or {}).get("sequences", [])}
        if key not in known:
            raise ProblemError(404, "no such sequence on this dossier",
                               detail=key)
        self.repo.set_active_sequence(_s(dossier_id), key)
        return self.list_sequences(dossier_id)
