"""Lifecycle application service — start/transition + deadline helpers + events."""

from __future__ import annotations

from ands_shared import EventEnvelope, EventType, ProblemError

from . import hc_calendar, lifecycle
from .ports import LifecycleRepository


def _s(v) -> str:
    return str(v or "").strip()


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
