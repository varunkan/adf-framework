"""Governance application service — e-sign gate + event-sourced audit trail."""

from __future__ import annotations

from datetime import datetime, timezone

from ands_shared import EventEnvelope, ProblemError

from . import esign, export
from .ports import AuditRepository


class GovernanceService:
    def __init__(self, repo: AuditRepository, bus,
                 *, source: str = "governance") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    def register(self) -> "GovernanceService":
        """Subscribe to EVERY event (``"*"``) and record it to the audit trail —
        the platform's immutable governance spine."""
        self.bus.subscribe("*", self.record_event)
        return self

    # -- audit --------------------------------------------------------------
    def record_event(self, event: EventEnvelope) -> dict:
        return self.repo.append({
            "at": event.occurred_at, "category": event.source,
            "action": event.type, "dossier_id": event.dossier_id or "",
            "tenant_id": event.tenant_id or "", "detail": event.data})

    def list_audit(self, *, category: str = "", dossier_id: str = "") -> dict:
        events = self.repo.list(category=category, dossier_id=dossier_id)
        return {"events": events, "count": len(events)}

    def export_audit(self) -> str:
        events = self.repo.list()
        lines = ["ANDS PLATFORM — AUDIT TRAIL (regulatory inspection export)",
                 f"Generated: {datetime.now(timezone.utc).isoformat()}",
                 f"Events: {len(events)}", "=" * 72]
        for e in events:
            lines.append(f"[{e['at']}] #{e.get('seq')} {e['category']}/"
                         f"{e['action']} dossier={e['dossier_id'] or '-'} "
                         f"tenant={e['tenant_id'] or '-'}")
            if e.get("detail"):
                import json
                lines.append("    detail: " + json.dumps(e["detail"],
                                                         sort_keys=True))
        return "\n".join(lines) + "\n"

    # -- tenant data export & portability (SAAS-REQ-004) -------------------
    def export_tenant(self, data: dict) -> dict:
        tenant_id = str(data.get("tenant_id") or "").strip()
        if not tenant_id:
            raise ProblemError(422, "tenant_id is required",
                               rule="tenant_id_required")
        audit = self.repo.list(tenant_id=tenant_id)
        return export.build_bundle(tenant_id, audit, data.get("attachments"))

    def set_legal_hold(self, data: dict) -> dict:
        tenant_id = str(data.get("tenant_id") or "").strip()
        if not tenant_id:
            raise ProblemError(422, "tenant_id is required",
                               rule="tenant_id_required")
        active = bool(data.get("active"))
        self.repo.set_legal_hold(tenant_id, active)
        return {"tenant_id": tenant_id, "legal_hold": active}

    def request_deletion(self, data: dict) -> dict:
        tenant_id = str(data.get("tenant_id") or "").strip()
        if self.repo.get_legal_hold(tenant_id):
            raise ProblemError(409, "deletion blocked by an active legal hold",
                               rule="legal_hold_active")
        return {"tenant_id": tenant_id, "deletion": "scheduled",
                "note": "tenant data will be deleted per the retention schedule"}

    # -- e-signature (thin wrappers; validation errors → problem+json) ------
    def policy(self) -> dict:
        return esign.policy()

    def qa_review(self, data: dict) -> dict:
        return self._guard(esign.qa_review(data), "review")

    def sign(self, data: dict) -> dict:
        return self._guard(esign.sign(data), "manifest")

    def verify(self, manifest: dict, current) -> dict:
        return esign.verify_manifest(manifest, current)

    def gate(self, data: dict) -> dict:
        return esign.transmission_gate(data)

    def request_hc_acceptance(self, data: dict) -> dict:
        return self._guard(esign.request_hc_acceptance(data), "request")

    def record_hc_acceptance(self, data: dict) -> dict:
        return self._guard(esign.record_hc_acceptance(data), "acceptance")

    @staticmethod
    def _guard(result: dict, payload_key: str) -> dict:
        if not result.get("valid"):
            raise ProblemError(422, "validation failed",
                               errors=result.get("errors") or [])
        return result
