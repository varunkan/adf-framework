"""Readiness application service — event projection + dashboard (REQ-071)."""

from __future__ import annotations

from ands_shared import EventEnvelope, EventType, ProblemError

from . import readiness
from .ports import ProjectionRepository


class ReadinessService:
    def __init__(self, repo: ProjectionRepository, bus,
                 *, source: str = "readiness") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    def register(self) -> "ReadinessService":
        """Subscribe to the domain events that feed the readiness projection."""
        self.bus.subscribe(EventType.VALIDATION_COMPLETED, self.on_validation)
        self.bus.subscribe(EventType.VALIDATION_FAILED, self.on_validation)
        self.bus.subscribe(EventType.TRANSMISSION_SENT, self.on_transmission)
        self.bus.subscribe(EventType.TRANSMISSION_HC_ACK, self.on_transmission)
        self.bus.subscribe(EventType.LIFECYCLE_TRANSITIONED, self.on_lifecycle)
        self.bus.subscribe(EventType.BILINGUAL_PM_BLOCKED, self.on_pm_blocked)
        return self

    # -- projection updates -------------------------------------------------
    def _update(self, dossier_id: str, key: str, value: dict) -> None:
        if not dossier_id:
            return
        signals = self.repo.get(dossier_id) or {}
        signals[key] = value
        self.repo.upsert(dossier_id, signals)

    def on_validation(self, event: EventEnvelope) -> None:
        d = event.data or {}
        self._update(event.dossier_id, "validation", {
            "ran": True, "errors": d.get("error_count", 0),
            "warnings": d.get("warning_count", 0),
            "blocking": bool(d.get("blocking"))})

    def on_transmission(self, event: EventEnvelope) -> None:
        state = ("RECEIVED_BY_HC" if event.type == EventType.TRANSMISSION_HC_ACK
                 else "SENT")
        self._update(event.dossier_id, "transmission", {"state": state})

    def on_lifecycle(self, event: EventEnvelope) -> None:
        d = event.data or {}
        self._update(event.dossier_id, "lifecycle",
                     {"phase": d.get("phase"), "status": d.get("status")})

    def on_pm_blocked(self, event: EventEnvelope) -> None:
        self._update(event.dossier_id, "bilingual_pm",
                     {"blocked": True, "findings": (event.data or {}).get("findings")})

    # -- queries ------------------------------------------------------------
    def dashboard(self) -> dict:
        return readiness.dashboard(self.repo.all())

    def get(self, dossier_id: str) -> dict:
        signals = self.repo.get(str(dossier_id or "").strip())
        if signals is None:
            raise ProblemError(404, "no readiness projection for dossier",
                               detail=dossier_id)
        return readiness.readiness(dossier_id, signals)
