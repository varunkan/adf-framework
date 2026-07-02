"""Dossier application service — content-plan + bilingual-PM use-cases."""

from __future__ import annotations

from ands_shared import EventEnvelope, EventType, ProblemError

import re
import secrets
from datetime import date

from . import (admin_sequence, archive, assembly, content_model, content_plan,
               dossier_state, drafting, ectd_validation, fees, generators,
               llm_provider, monograph, pm_xml, pm_xref, section_tree)
from .document_store import SqliteBlobStore
from .ports import DossierRepository

_DIN_RE = re.compile(r"^\d{8}$")


def _s(v) -> str:
    return str(v or "").strip()


class DossierService:
    def __init__(self, repo: DossierRepository, bus,
                 *, source: str = "dossier", store=None) -> None:
        self.repo = repo
        self.bus = bus
        self.source = source
        self.store = store or SqliteBlobStore(repo)

    def register(self) -> "DossierService":
        # No upstream subscriptions yet; reserved for sequence/assembly events.
        return self

    # -- content plans (REQ-103) -------------------------------------------
    def create_content_plan(self, data: dict) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        if not dossier_id:
            raise ProblemError(422, "dossier_id is required",
                               rule="dossier_id_required")
        try:
            items = content_plan.build_plan_items(
                data.get("submission_type"),
                cs_be_only=bool(data.get("cs_be_only")))
        except ValueError as exc:
            raise ProblemError(422, str(exc), rule="submission_type_invalid")
        plan = self.repo.create_plan(
            dossier_id, _s(data.get("submission_type")).upper(), items)
        return self._with_progress(plan)

    def get_content_plan(self, dossier_id: str) -> dict:
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
    def register_pm_leaf(self, data: dict) -> dict:
        res = monograph.normalize_pm_leaf(data)
        if not res["valid"]:
            raise ProblemError(422, "Invalid Product Monograph leaf",
                               errors=res["errors"])
        return self.repo.upsert_pm_leaf(res["leaf"])

    # -- administrative / corrective sequences (REQ-092) -------------------
    def build_admin_sequence(self, data: dict) -> dict:
        result = admin_sequence.build_admin_sequence(data)
        if "errors" in result:
            raise ProblemError(422, "Invalid administrative sequence",
                               errors=result["errors"])
        return result

    def monograph_status(self, dossier_id: str) -> dict:
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

    def add_leaf(self, data: dict) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        sequence = _s(data.get("sequence")) or "0000"
        if not dossier_id:
            raise ProblemError(422, "dossier_id is required",
                               rule="dossier_id_required")
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
    def create_binder(self, data: dict) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        sequence = _s(data.get("sequence")) or "0000"
        model = self._dossier_model(dossier_id)   # 404 if no eCTD dossier
        binder = archive.build_binder(
            model, sequence=sequence,
            validation_report=data.get("validation_report"),
            transmission=data.get("transmission"))
        return self.repo.save_binder(dossier_id, sequence, binder)

    def get_binder(self, binder_id: str) -> dict:
        rec = self.repo.get_binder(_s(binder_id))
        if not rec:
            raise ProblemError(404, "binder not found", detail=_s(binder_id))
        return rec

    def list_binders(self, dossier_id: str) -> dict:
        binders = self.repo.list_binders(_s(dossier_id))
        return {"binders": binders, "count": len(binders)}

    def share_binder(self, binder_id: str) -> dict:
        rec = self.get_binder(binder_id)
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
                "drug_product": idx.get("title"),
                "submission_type": idx.get("submission_type") or "ANDS",
                "activity_type": idx.get("submission_type") or "ANDS",
                "din": idx.get("din")}

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

    def _place(self, dossier_id: str, node: dict, leaf_id: str, body,
               ext: str = "pdf") -> None:
        model = self._dossier_model(dossier_id, create=True)
        # the leaf href must carry the stored file's real extension (a generated
        # REP form is .xml, not .pdf) so the eCTD leaf points at the right bytes.
        href = f"{node['folder']}/{leaf_id}.{_s(ext) or 'pdf'}"
        assembly.set_leaf(model, "0000", {
            "leaf_id": leaf_id, "heading": node["section"],
            "title": node["title"], "href": href, "content": body})
        self.repo.save_dossier(model)

    def _write_entry(self, dossier_id, section, node, *, action, meta=None,
                     lang=None, leaf_id=None, na_reason=None) -> dict:
        entry = self.repo.get_section_state(_s(dossier_id), _s(section)) or {}
        entry["action"] = action
        if na_reason is not None:
            entry["na_reason"] = na_reason
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
        self._write_entry(dossier_id, section, node, action="uploaded",
                          meta=meta, lang=lang, leaf_id=leaf_id)
        return self.content_state(dossier_id)

    def generate_document(self, dossier_id, section, payload) -> dict:
        node = self._node(dossier_id, section)
        key = node.get("generator_key")
        if "generate" not in node["affordances"] or not key:
            raise ProblemError(422, "this section cannot be authored in-app",
                               rule="section_not_generatable", detail=_s(section))
        ctx = {**self._ctx_for(dossier_id), **(payload or {})}
        try:
            doc = generators.generate(key, ctx)
        except KeyError:
            raise ProblemError(422, "no generator for this section", detail=key)
        meta = self.store.put(_s(dossier_id), _s(section), doc["filename"],
                              doc["content_type"], doc["body"], origin="generated")
        self._place(dossier_id, node, node["leaf_id"], doc["body"],
                    self._ext(doc["filename"]))
        self._write_entry(dossier_id, section, node, action="generated",
                          meta=meta, leaf_id=node["leaf_id"])
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
        return self.content_state(dossier_id)

    def get_document(self, doc_id: str) -> dict:
        doc = self.store.get(_s(doc_id))
        if not doc:
            raise ProblemError(404, "document not found", detail=_s(doc_id))
        return doc

    def set_fee_status(self, dossier_id, fee_paid, sme_granted) -> dict:
        if not self.repo.get_dossier_index(_s(dossier_id)):
            raise ProblemError(404, "no such dossier", detail=_s(dossier_id))
        self.repo.set_fee_status(_s(dossier_id), bool(fee_paid), bool(sme_granted))
        return self.content_state(dossier_id)

    def validate_submission(self, dossier_id: str) -> dict:
        """Full eCTD technical validation — includes PDF conformance on the
        stored bytes (heavier than the structural check in content_state)."""
        model = self.repo.get_dossier(_s(dossier_id))
        if not model:
            return {"passed": True, "errors": [], "warnings": [], "checked": 0}
        documents = {}
        for state in self.repo.list_section_state(_s(dossier_id)).values():
            for meta in ([state.get("document")]
                         + list((state.get("documents") or {}).values())):
                if not meta:
                    continue
                doc = self.store.get(meta["doc_id"])
                if doc:
                    documents[meta.get("filename") or meta["doc_id"]] = doc["body"]
        return ectd_validation.validate(model, documents=documents)

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
                "validation_passed": validation.get("passed", True)}
        return {
            "dossier_id": dossier_id, "cs_be_only": cs_be_only,
            "version": tree["version"], "modules": modules, "gate": gate,
            "tower": dossier_state.tower_view(cs_be_only=cs_be_only, states=states),
            "fees": fees_block, "validation": validation, "din": idx.get("din"),
            "files_view": assembly.build_files_view(model) if model else None}

    # -- dossier + sequence management (home catalog) ----------------------
    def create_dossier(self, data: dict) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        if not dossier_id:
            raise ProblemError(422, "dossier_id is required",
                               rule="dossier_id_required")
        din = _s(data.get("din"))
        if din and not _DIN_RE.match(din):
            raise ProblemError(422, "DIN must be exactly 8 digits (note: a DIN "
                               "is assigned by Health Canada at NOC, not filed)",
                               rule="din_invalid")
        rec = self.repo.create_dossier_index({
            "dossier_id": dossier_id,
            "title": _s(data.get("title")) or dossier_id,
            "submission_type": _s(data.get("submission_type")).upper() or "ANDS",
            "cs_be_only": bool(data.get("cs_be_only", True)),
            "din": din or None})
        model = self._dossier_model(dossier_id, create=True)
        assembly.add_sequence(model, "0000")
        self.repo.save_dossier(model)
        return rec

    def list_dossiers(self) -> dict:
        out = []
        for idx in self.repo.list_dossier_index():
            states = self.repo.list_section_state(idx["dossier_id"])
            out.append({**idx,
                        "tower": dossier_state.tower_view(
                            cs_be_only=idx["cs_be_only"], states=states),
                        "gate": dossier_state.completeness_gate(
                            cs_be_only=idx["cs_be_only"], states=states)})
        return {"dossiers": out, "count": len(out)}

    def get_dossier_full(self, dossier_id: str) -> dict:
        dossier_id = _s(dossier_id)
        idx = self.repo.get_dossier_index(dossier_id)
        if not idx:
            # tolerate a dossier that exists as an eCTD model but has no index yet
            idx = {"dossier_id": dossier_id, "title": dossier_id,
                   "submission_type": "ANDS", "cs_be_only": True}
        return {"index": idx, "content": self.content_state(dossier_id)}

    def list_sequences(self, dossier_id: str) -> dict:
        model = self.repo.get_dossier(_s(dossier_id)) or \
            assembly.new_dossier(_s(dossier_id))
        return {"dossier_id": _s(dossier_id),
                "sequences": [s["sequence"] for s in model["sequences"]]}

    def create_sequence(self, dossier_id: str, sequence: str) -> dict:
        model = self._dossier_model(dossier_id, create=True)
        assembly.add_sequence(model, _s(sequence) or "0000")
        self.repo.save_dossier(model)
        return self.list_sequences(dossier_id)
