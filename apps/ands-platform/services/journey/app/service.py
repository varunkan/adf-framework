"""Journey application service — the guided-session orchestrator + façade.

Owns the guided session (the collected answers + per-step signals), exposes the
gated journey spine + the READY/BLOCKED card, and runs the pure decision-support
domains ('tell me about your drug' + Dossier-ID guidance). It optionally emits
journey.* domain events on the bus so the rest of the mesh can react; it adds no
new regulatory logic.
"""

from __future__ import annotations

from ands_shared import EventEnvelope, ProblemError, new_id

from . import drug_intake, dossier_id, journey, readiness_card
from .ports import SessionRepository

# step key -> the signal a successful CTA writes (validated below against STAGES).
_STEP_KEYS = {s["key"] for s in journey.STAGES}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


class JourneyService:
    def __init__(self, repo: SessionRepository, bus=None,
                 *, source: str = "journey") -> None:
        self.repo = repo
        self.bus = bus
        self.source = source

    # -- emit ---------------------------------------------------------------
    def _emit(self, event_type: str, session: dict, **data) -> None:
        if self.bus is None:
            return
        self.bus.publish(EventEnvelope.make(
            event_type, source=self.source,
            tenant_id=session.get("tenant_id") or None,
            dossier_id=(session.get("signals") or {}).get("dossier_id") or None,
            data=data))

    # -- views --------------------------------------------------------------
    def _view(self, session: dict) -> dict:
        signals = session.get("signals") or {}
        title = (session.get("title")
                 or _s(signals.get("drug_product")) or "New submission")
        return {
            "id": session["id"],
            "title": title,
            "tenant_id": session.get("tenant_id", ""),
            "journey": journey.journey(signals, sub_id=session["id"], title=title),
            "readiness": readiness_card.card(signals),
            "intake": session.get("intake"),
            "signals": signals,
        }

    def _load(self, session_id: str) -> dict:
        session = self.repo.get(_s(session_id))
        if session is None:
            raise ProblemError(404, "no such guided session", detail=session_id)
        return session

    # -- catalog (static, for the UI to render the whole spine) -------------
    def catalog(self) -> dict:
        return {
            "stages": [dict(s) for s in journey.STAGES],
            "submission_types": drug_intake.SUBMISSION_TYPES,
            "be_rulesets": drug_intake.list_be_rulesets(),
            "dossier_branches": dossier_id.list_branches(),
        }

    # -- lifecycle ----------------------------------------------------------
    def start(self, data: dict) -> dict:
        data = data or {}
        session_id = new_id()
        signals: dict = {"oriented": False}
        session = {
            "id": session_id,
            "title": _s(data.get("title")),
            "tenant_id": _s(data.get("tenant_id")),
            "signals": signals,
            "intake": None,
        }
        answers = data.get("answers")
        if answers:
            session["intake"] = drug_intake.assess(answers)
            self._apply_intake(session, answers)
        self.repo.create(session_id, session)
        self._emit("journey.started", session)
        return self._view(session)

    def get(self, session_id: str) -> dict:
        return self._view(self._load(session_id))

    def list_sessions(self) -> dict:
        sessions = self.repo.all()
        return {"sessions": [{
            "id": sid,
            "title": s.get("title") or "New submission",
            "position": journey.position(s.get("signals") or {}),
        } for sid, s in sessions.items()], "count": len(sessions)}

    # -- 'tell me about your drug' (decision support) -----------------------
    def intake(self, answers: dict, session_id: str = "") -> dict:
        assessment = drug_intake.assess(answers or {})
        if _s(session_id):
            session = self._load(session_id)
            session["intake"] = assessment
            self._apply_intake(session, answers or {})
            self.repo.update(session["id"], session)
            self._emit("journey.intake", session,
                       submission_type=assessment["route"].get("submission_type"),
                       eligible_ands=assessment.get("eligible_ands"))
            return {"assessment": assessment, "view": self._view(session)}
        return {"assessment": assessment, "view": None}

    def _apply_intake(self, session: dict, answers: dict) -> None:
        """Carry the decision-support answers into the journey signals so the
        story remembers the product (without advancing any gate)."""
        signals = session.setdefault("signals", {})
        product = _s(answers.get("drug_product") or answers.get("product_name"))
        if product:
            signals["drug_product"] = product
            if not session.get("title"):
                session["title"] = product
        stype = _s((session.get("intake") or {}).get("route", {}).get(
            "submission_type"))
        if stype:
            signals["submission_type"] = stype

    # -- dossier-id guidance ------------------------------------------------
    def assess_dossier_id(self, data: dict) -> dict:
        return dossier_id.assess(data or {})

    # -- advance the journey (perform a step's primary action) --------------
    def advance(self, session_id: str, step: str, data: dict) -> dict:
        session = self._load(session_id)
        step = _s(step)
        if step not in _STEP_KEYS:
            raise ProblemError(422, "unknown journey step", detail=step)
        signals = session.setdefault("signals", {})
        data = data or {}

        if step == "orient":
            signals["oriented"] = True
        elif step == "company":
            cid = _s(data.get("company_id"))
            if not cid:
                raise ProblemError(422, "company_id is required", detail="company")
            signals["company_id"] = cid
        elif step == "dossier":
            did = _s(data.get("dossier_id"))
            branch = _s(data.get("branch")) or "pharmaceutical"
            if not did:
                raise ProblemError(422, "dossier_id is required", detail="dossier")
            if not dossier_id.dossier_id_conforms(did, branch):
                raise ProblemError(
                    422, "dossier_id format is invalid",
                    detail=dossier_id.assess(data).get("format_error"))
            signals["dossier_id"] = did
        elif step == "submission":
            applicant = _s(data.get("applicant"))
            product = _s(data.get("drug_product")) or _s(signals.get("drug_product"))
            if not applicant or not product:
                raise ProblemError(422, "applicant and drug_product are required",
                                   detail="submission")
            signals["applicant"] = applicant
            signals["drug_product"] = product
            signals["sequence"] = _s(data.get("sequence")) or "0000"
            signals["submission_created"] = True
        elif step == "content":
            signals["content_done"] = True
        elif step == "validate":
            errors = data.get("errors", 0)
            try:
                errors = int(errors)
            except (TypeError, ValueError):
                errors = 0
            signals["validation"] = {"ran": True, "errors": errors,
                                     "warnings": int(data.get("warnings", 0) or 0)}
            if errors:
                raise ProblemError(422, "validation still has errors",
                                   detail=f"{errors} error(s) must be fixed")
        elif step == "fees":
            signals["fees"] = {"paid": True}
        elif step == "review":
            signals["reviews"] = {"approved": True}
        elif step == "sign":
            signals["esign"] = {"signed": True}
        elif step == "transmit":
            signals["transmission"] = {"state": _s(data.get("state")) or "SUBMITTED"}
        # 'track' is ongoing — nothing to write.

        self.repo.update(session["id"], session)
        self._emit(f"journey.step.{step}", session)
        return self._view(session)
