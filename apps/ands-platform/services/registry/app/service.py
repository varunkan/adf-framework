"""Registry application service — registrations + status + Right-to-Sell."""

from __future__ import annotations

from ands_shared import EventEnvelope, EventType, ProblemError

from . import registry
from .ports import RegistrationRepository


def _s(v) -> str:
    return str(v or "").strip()


class RegistryService:
    def __init__(self, repo: RegistrationRepository, bus,
                 *, source: str = "registry") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    def register(self) -> "RegistryService":
        return self

    def create(self, data: dict) -> dict:
        res = registry.new_registration(data)
        if not res["valid"]:
            raise ProblemError(422, "Invalid registration",
                               errors=res["errors"])
        reg = self.repo.add(res["registration"])
        self._emit(reg, "created")
        return reg

    def get(self, reg_id: str) -> dict:
        reg = self.repo.get(_s(reg_id))
        if not reg:
            raise ProblemError(404, "registration not found", detail=_s(reg_id))
        return reg

    def list(self, **filters) -> dict:
        regs = self.repo.list(**filters)
        return {"registrations": regs, "count": len(regs)}

    def set_status(self, reg_id: str, status: str) -> dict:
        reg = self.repo.get(_s(reg_id))
        if not reg:
            raise ProblemError(404, "registration not found", detail=_s(reg_id))
        check = registry.validate_status_transition(reg["status"], status)
        if not check["valid"]:
            http = 422 if check["rule"] == "status_unknown" else 409
            raise ProblemError(http, check["message"], rule=check["rule"])
        reg = self.repo.set_status(reg_id, _s(status))
        self._emit(reg, "status_changed")
        return reg

    def right_to_sell(self, reg_id: str, as_of: str) -> dict:
        reg = self.get(reg_id)
        try:
            return registry.right_to_sell_obligation(reg, as_of)
        except ValueError as exc:
            raise ProblemError(422, f"invalid as_of date: {exc}",
                               rule="invalid_as_of")

    def _emit(self, reg: dict, event: str) -> None:
        self.bus.publish(EventEnvelope.make(
            EventType.REGISTRATION_STATUS_CHANGED, source=self.source,
            dossier_id=reg.get("dossier_id"),
            data={"registration_id": reg["id"], "event": event,
                  "status": reg["status"], "din": reg.get("din")}))
