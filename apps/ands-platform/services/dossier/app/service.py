"""Dossier application service — content-plan + bilingual-PM use-cases."""

from __future__ import annotations

from ands_shared import EventEnvelope, EventType, ProblemError

from . import admin_sequence, content_plan, monograph, pm_xml, pm_xref
from .ports import DossierRepository


def _s(v) -> str:
    return str(v or "").strip()


class DossierService:
    def __init__(self, repo: DossierRepository, bus,
                 *, source: str = "dossier") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

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
