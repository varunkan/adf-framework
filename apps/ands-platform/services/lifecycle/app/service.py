"""Lifecycle application service — start/transition + deadline helpers + events."""

from __future__ import annotations

from ands_shared import EventEnvelope, EventType, ProblemError

from . import correspondence, hc_calendar, lifecycle, noa
from .ports import LifecycleRepository


def _s(v) -> str:
    return str(v or "").strip()


_SCREENING_NOTICES = {"SAL", "SDN", "SRL"}
_DECISION_NOTICES = {"NOC", "NOD", "NON"}
# REQ-096 — the next-action shortcut offered when each notice is ingested.
_RESPONSE_SHORTCUTS = {
    "SAL": {"action": "continue",
            "label": "Accepted at screening — proceeds to review"},
    "SDN": {"action": "file_response_sequence", "window_days": 45,
            "label": "Respond to the Screening Deficiency Notice within 45 days"},
    "SRL": {"action": "none", "label": "Rejected at screening"},
    "NOD": {"action": "file_clarifax_or_response", "window_days": 90,
            "label": "Respond to the Notice of Deficiency within 90 days "
                     "(45 for DIN)"},
    "NON": {"action": "file_response_sequence", "window_days": 90,
            "label": "Respond to the Notice of Non-compliance"},
    "NOC": {"action": "none", "label": "Approved — no response required"},
}


class LifecycleService:
    def __init__(self, repo: LifecycleRepository, bus,
                 *, source: str = "lifecycle") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    def register(self) -> "LifecycleService":
        return self

    # -- lifecycle ----------------------------------------------------------
    def start_lifecycle(self, data: dict) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        received = _s(data.get("received_date"))
        if not dossier_id or not received:
            raise ProblemError(422, "dossier_id and received_date are required",
                               rule="missing_fields")
        if self.repo.get(dossier_id):
            raise ProblemError(409, "lifecycle already started for dossier",
                               rule="already_started")
        try:
            state = lifecycle.start(dossier_id, data.get("submission_type"),
                                    received, fee_paid=data.get("fee_paid"))
        except ValueError as exc:
            raise ProblemError(422, str(exc), rule="invalid_start")
        self.repo.save(state)
        self._emit(state, "started")
        return state

    def transition(self, data: dict) -> dict:
        dossier_id = _s(data.get("dossier_id"))
        state = self.repo.get(dossier_id)
        if not state:
            raise ProblemError(404, "no lifecycle for dossier",
                               detail=dossier_id)
        kind = _s(data.get("kind")).lower()
        on_date = _s(data.get("date"))
        try:
            if kind == "screening":
                state = lifecycle.apply_screening(state, data.get("value"),
                                                  on_date)
            elif kind == "decision":
                state = lifecycle.apply_decision(state, data.get("value"),
                                                 on_date)
            elif kind == "withdraw":
                state = lifecycle.withdraw(state, _s(data.get("reason")))
            else:
                raise ProblemError(422, f"unknown transition kind: {kind}",
                                   rule="kind_unknown")
        except lifecycle.LifecycleError as exc:
            raise ProblemError(409, str(exc), rule="illegal_transition")
        self.repo.save(state)
        self._emit(state, f"{kind}:{_s(data.get('value')) or 'withdraw'}")
        if state.get("fee_credit"):
            self.bus.publish(EventEnvelope.make(
                EventType.SERVICE_STANDARD_MISSED, source=self.source,
                dossier_id=dossier_id, data=state["fee_credit"]))
        return state

    def get(self, dossier_id: str) -> dict:
        state = self.repo.get(_s(dossier_id))
        if not state:
            raise ProblemError(404, "no lifecycle for dossier",
                               detail=_s(dossier_id))
        return state

    def _emit(self, state: dict, event: str) -> None:
        self.bus.publish(EventEnvelope.make(
            EventType.LIFECYCLE_TRANSITIONED, source=self.source,
            dossier_id=state["dossier_id"],
            data={"event": event, "phase": state["phase"],
                  "status": state["status"], "decision": state.get("decision")}))

    # -- reference helpers --------------------------------------------------
    def service_standard(self, submission_type: str) -> dict:
        return {"submission_type": lifecycle.submission_class(submission_type),
                **lifecycle.service_standard(submission_type)}

    def deadline(self, data: dict) -> dict:
        start = _s(data.get("start"))
        if not start:
            raise ProblemError(422, "start is required", rule="start_required")
        try:
            return hc_calendar.compute_deadline(
                start, int(data.get("days") or 0),
                basis=data.get("basis"),
                notice_type=_s(data.get("notice_type")))
        except (ValueError, TypeError) as exc:
            raise ProblemError(422, f"invalid deadline input: {exc}",
                               rule="invalid_deadline")

    def holidays(self, year: int) -> dict:
        return {"year": year, "holidays": hc_calendar.statutory_holidays(year)}

    # -- HC notice ingestion (REQ-096) -------------------------------------
    def ingest_notice(self, data: dict) -> dict:
        """Ingest an HC notice: advance the DSTS state machine, log it as
        inbound correspondence, and return a response-sequence shortcut."""
        dossier_id = _s(data.get("dossier_id"))
        notice = _s(data.get("notice")).upper()
        date = _s(data.get("date"))
        if notice in _SCREENING_NOTICES:
            state = self.transition({"dossier_id": dossier_id, "kind": "screening",
                                     "value": notice, "date": date})
        elif notice in _DECISION_NOTICES:
            state = self.transition({"dossier_id": dossier_id, "kind": "decision",
                                     "value": notice, "date": date})
        else:
            raise ProblemError(422, f"unknown HC notice: {notice}",
                               rule="notice_unknown")
        corr = self.log_correspondence({
            "dossier_id": dossier_id, "kind": notice, "direction": "inbound",
            "subject": _s(data.get("subject")) or f"{notice} received",
            "received_at": date, "reference": _s(data.get("reference"))})
        return {"state": state, "correspondence": corr,
                "response": _RESPONSE_SHORTCUTS.get(notice, {})}

    # -- HC correspondence hub (REQ-112) -----------------------------------
    def log_correspondence(self, data: dict) -> dict:
        res = correspondence.validate_correspondence(data)
        if not res["valid"]:
            raise ProblemError(422, "Invalid correspondence",
                               errors=res["errors"])
        return self.repo.add_correspondence(res["record"])

    def list_correspondence(self, dossier_id: str, kind: str = "") -> dict:
        items = self.repo.list_correspondence(_s(dossier_id), kind)
        return {"correspondence": items, "count": len(items)}

    # -- Form V / NOA register (PM(NOC) Regulations) ------------------------
    def create_noa(self, data: dict) -> dict:
        res = noa.validate_allegation(data)
        if not res["valid"]:
            raise ProblemError(422, "Invalid Form V allegation",
                               errors=res["errors"])
        return self.repo.add_noa(res["record"])

    def serve_noa(self, noa_id: str, data: dict) -> dict:
        return self._noa_transition(
            noa_id, lambda r: noa.serve(r, _s(data.get("served_date"))))

    def action_noa(self, noa_id: str, data: dict) -> dict:
        return self._noa_transition(
            noa_id, lambda r: noa.commence_action(
                r, _s(data.get("action_date")), _s(data.get("court_file"))))

    def list_noa(self, dossier_id: str, as_of: str = "") -> dict:
        items = [noa.with_clocks(r, _s(as_of))
                 for r in self.repo.list_noa(_s(dossier_id))]
        return {"allegations": items, "count": len(items)}

    def _noa_transition(self, noa_id: str, apply) -> dict:
        record = self.repo.get_noa(_s(noa_id))
        if not record:
            raise ProblemError(404, "no NOA record", detail=_s(noa_id))
        try:
            record = apply(record)
        except noa.NoaError as exc:
            raise ProblemError(409, str(exc), rule=exc.rule)
        except ValueError as exc:
            raise ProblemError(422, f"invalid NOA input: {exc}",
                               rule="invalid_date")
        return self.repo.save_noa(record)
