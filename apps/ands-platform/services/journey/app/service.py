"""Journey application service — the guided-session orchestrator + façade.

Owns the guided session (the collected answers + per-step signals), exposes the
gated journey spine + the READY/BLOCKED card, and runs the pure decision-support
domains ('tell me about your drug' + Dossier-ID guidance). It optionally emits
journey.* domain events on the bus so the rest of the mesh can react; it adds no
new regulatory logic.
"""

from __future__ import annotations

from ands_shared import EventEnvelope, ProblemError, new_id

from . import content_slots, drug_intake, dossier_id, journey, readiness_card, tracking
from .ports import SessionRepository

# step key -> the signal a successful CTA writes (validated below against STAGES).
_STEP_KEYS = {s["key"] for s in journey.STAGES}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


class JourneyService:
    def __init__(self, repo: SessionRepository, bus=None,
                 *, source: str = "journey", dossier=None,
                 governance=None, transmission=None) -> None:
        self.repo = repo
        self.bus = bus
        self.source = source
        self.dossier = dossier          # DossierClient port (optional)
        self.governance = governance    # GovernanceClient port (optional)
        self.transmission = transmission  # TransmissionClient port (optional)

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
    def _dossier_content(self, dossier_id: str) -> dict | None:
        """The real per-module tower/gate from the dossier service (composition)."""
        if self.dossier is None or not dossier_id:
            return None
        cs = self.dossier.content_state(dossier_id)
        if not cs:
            return None
        gate = cs.get("gate") or {"complete": False, "missing": []}
        tower = cs.get("tower") or []
        req = sum(t.get("required_total", 0) for t in tower)
        fil = sum(t.get("required_filled", 0) for t in tower)
        return {"source": "dossier", "dossier_id": dossier_id, "slots": [],
                "tower": tower, "gate": gate,
                "progress": {"required_total": req, "required_filled": fil,
                             "percent": round(fil * 100 / req) if req else 0,
                             "complete": bool(gate.get("complete"))}}

    def _content(self, signals: dict) -> dict:
        """The eCTD content view: the real dossier state when a dossier exists +
        the dossier service is reachable, else the pure flat content model."""
        content = self._dossier_content(_s(signals.get("dossier_id")))
        if content is not None:
            return content
        slots = signals.get("content_slots") or content_slots.plan(
            cs_be_only=bool(signals.get("cs_be_only")))
        return {
            "source": "slots",
            "slots": slots,
            "progress": content_slots.progress(slots),
            "gate": content_slots.checklist_gate(slots),
            "tower": content_slots.tower_view(slots),
        }

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
            "content": self._content(signals),
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
        # Carry CS-BE-only into the content plan (suppresses Modules 2.4-2.7).
        # Rebuild the plan only while it is still untouched (no docs placed yet).
        if "cs_be_only" in answers:
            signals["cs_be_only"] = bool(answers.get("cs_be_only"))
            slots = signals.get("content_slots")
            untouched = not slots or all(s.get("state") == "empty" for s in slots)
            if untouched:
                rebuilt = content_slots.plan(cs_be_only=signals["cs_be_only"])
                signals["content_slots"] = rebuilt
                # a rebuilt, empty plan must clear any stale completion flag
                signals["content_done"] = content_slots.checklist_gate(
                    rebuilt)["complete"]

    # -- dossier-id guidance ------------------------------------------------
    def assess_dossier_id(self, data: dict) -> dict:
        return dossier_id.assess(data or {})

    def _sign_artifacts(self, signals: dict) -> list[dict]:
        """Checksummed eCTD leaves from the real dossier — what gets signed."""
        did = _s(signals.get("dossier_id"))
        if self.dossier is None or not did:
            return []
        content = self.dossier.content_state(did) or {}
        files = content.get("files_view") or {}
        return [{"id": _s(leaf.get("leaf_id")) or _s(leaf.get("href")),
                 "kind": "leaf", "checksum": _s(leaf.get("checksum"))}
                for node in (files.get("nodes") or [])
                for leaf in (node.get("leaves") or [])
                if _s(leaf.get("checksum"))]

    # -- advance the journey (perform a step's primary action) --------------
    def advance(self, session_id: str, step: str, data: dict,
                tenant_id: str | None = None) -> dict:
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
            # Provision the real dossier so the Module builder is ready to
            # fill — OWNED by the caller's tenant from birth (else it would be
            # created unscoped and leak across workspaces).
            if self.dossier is not None and _s(signals.get("dossier_id")):
                self.dossier.ensure_dossier(
                    _s(signals.get("dossier_id")), title=product,
                    submission_type=_s(signals.get("submission_type")) or "ANDS",
                    cs_be_only=bool(signals.get("cs_be_only", True)),
                    tenant_id=tenant_id,
                    # REP identity captured earlier in the journey: the sponsor
                    # company (applicant) + HC Company ID — so the REP RT XML
                    # and ca-regional carry the real sponsor, not the product
                    company_id=_s(signals.get("company_id")),
                    sponsor=applicant)
        elif step == "content":
            # Gate authoritatively against the LIVE plan so 'content_done' can
            # never stick true over an empty/incomplete eCTD — from the real
            # dossier when available, else the pure flat model.
            gate = self._content(signals)["gate"]
            if not gate.get("complete"):
                raise ProblemError(
                    422, "required documents are still missing",
                    detail="; ".join(m.get("title", "")
                                     for m in (gate.get("missing") or [])[:6]))
            signals["content_done"] = True
        elif step == "validate":
            did = _s(signals.get("dossier_id"))
            report = (self.dossier.validate(did)
                      if self.dossier is not None and did else None)
            if report is not None:
                # REAL eCTD technical validation (PDF conformance included)
                errs = report.get("errors") or []
                signals["validation"] = {
                    "ran": True, "errors": len(errs),
                    "warnings": len(report.get("warnings") or []),
                    "checked": report.get("checked", 0), "real": True}
                if errs:
                    raise ProblemError(
                        422, "validation found errors",
                        detail="; ".join(_s(e.get("message"))[:90]
                                         for e in errs[:5]))
            else:
                # no dossier service — guided simulation input
                errors = data.get("errors", 0)
                try:
                    errors = int(errors)
                except (TypeError, ValueError):
                    errors = 0
                signals["validation"] = {
                    "ran": True, "errors": errors,
                    "warnings": int(data.get("warnings", 0) or 0),
                    "real": False}
                if errors:
                    raise ProblemError(422, "validation still has errors",
                                       detail=f"{errors} error(s) must be fixed")
        elif step == "fees":
            did = _s(signals.get("dossier_id"))
            sme = bool(data.get("sb_granted"))
            synced = (self.dossier.set_fees(did, True, sme)
                      if self.dossier is not None and did else None)
            if synced is not None:
                # the dossier index is the single source of truth for fee state
                fb = synced.get("fees") or {}
                signals["fees"] = {
                    "paid": bool(fb.get("fee_paid")),
                    "sme_granted": bool(fb.get("sme_granted")),
                    "fiscal_year": (fb.get("review_fee") or {}).get("fiscal_year"),
                    "amount": (fb.get("review_fee") or {}).get("amount"),
                    "payable": (fb.get("mitigation") or {}).get("payable"),
                    "real": True}
            else:
                signals["fees"] = {"paid": True, "sme_granted": sme,
                                   "real": False}
        elif step == "review":
            reviewer = (_s(data.get("reviewer"))
                        or _s(signals.get("applicant")) or "sponsor-qa")
            rec = (self.governance.qa_review(
                       reviewer=reviewer, comment=_s(data.get("comment")))
                   if self.governance is not None else None)
            if rec is not None and not rec.get("valid"):
                raise ProblemError(
                    422, "QA review was not accepted",
                    detail="; ".join(_s(e.get("rule") if isinstance(e, dict)
                                        else e) for e in rec.get("errors", [])[:4]))
            signals["reviews"] = {"approved": True, "reviewer": reviewer,
                                  "review": (rec or {}).get("review"),
                                  "real": rec is not None}
        elif step == "sign":
            signer = (_s(data.get("signer"))
                      or _s(signals.get("applicant")) or "authorized-signer")
            manifest = None
            if self.governance is not None:
                artifacts = self._sign_artifacts(signals)
                res = (self.governance.sign(signer=signer, artifacts=artifacts)
                       if artifacts else None)
                if res is not None and not res.get("valid"):
                    raise ProblemError(
                        422, "e-signature was rejected",
                        detail="; ".join(_s(e.get("rule") if isinstance(e, dict)
                                            else e)
                                         for e in res.get("errors", [])[:4]))
                manifest = (res or {}).get("manifest")
            signals["esign"] = {"signed": True, "signer": signer,
                                "manifest_id": (manifest or {}).get("manifest_id"),
                                "artifact_count": len((manifest or {})
                                                      .get("artifacts") or []),
                                "real": manifest is not None}
            if manifest:
                signals["esign_manifest"] = manifest
        elif step == "transmit":
            did = _s(signals.get("dossier_id"))
            seq = _s(signals.get("sequence")) or "0000"
            txn = (self.transmission.transmit(did, seq)
                   if self.transmission is not None and did else None)
            if txn is not None:
                signals["transmission"] = {
                    "state": _s(txn.get("state")) or "SENT",
                    "message_id": txn.get("message_id"),
                    "core_id": txn.get("core_id"),
                    "mdn_received": bool(txn.get("mdn_received")),
                    "fda_ack_received": bool(txn.get("fda_ack_received")),
                    "hc_ack_received": bool(txn.get("hc_ack_received")),
                    "real": True}
            else:
                signals["transmission"] = {
                    "state": _s(data.get("state")) or "SUBMITTED",
                    "real": False}
        # 'track' is ongoing — nothing to write.

        self.repo.update(session["id"], session)
        self._emit(f"journey.step.{step}", session)
        return self._view(session)

    # -- content slots (drag-drop document placement onto Module 1-5) -------
    def place_document(self, session_id: str, slot_key: str, doc,
                       languages=None) -> dict:
        session = self._load(session_id)
        signals = session.setdefault("signals", {})
        slots = signals.get("content_slots") or content_slots.plan(
            cs_be_only=bool(signals.get("cs_be_only")))
        try:
            slots = content_slots.place(slots, slot_key, doc, languages=languages)
        except ValueError as exc:
            raise ProblemError(422, "unknown content slot", detail=str(exc))
        signals["content_slots"] = slots
        signals["content_done"] = content_slots.checklist_gate(slots)["complete"]
        self.repo.update(session["id"], session)
        self._emit("journey.content.placed", session, slot=_s(slot_key))
        return self._view(session)

    # -- post-filing tracking (HC review + deadline timers) ----------------
    def _tracking(self, signals: dict) -> dict:
        return signals.setdefault("tracking", {"notices": [], "paused": []})

    def log_notice(self, session_id: str, notice: dict) -> dict:
        session = self._load(session_id)
        tr = self._tracking(session.setdefault("signals", {}))
        tr["notices"].append({"type": _s((notice or {}).get("type")),
                              "date": _s((notice or {}).get("date"))})
        self.repo.update(session["id"], session)
        self._emit("journey.track.notice", session,
                   notice_type=_s((notice or {}).get("type")))
        return self._view(session)

    def set_pause(self, session_id: str, ntype: str, paused: bool = True) -> dict:
        session = self._load(session_id)
        tr = self._tracking(session.setdefault("signals", {}))
        current = set(tr.get("paused") or [])
        current.add(_s(ntype)) if paused else current.discard(_s(ntype))
        tr["paused"] = sorted(current)
        self.repo.update(session["id"], session)
        return tr

    def track_view(self, session_id: str, as_of: str) -> dict:
        session = self._load(session_id)
        tr = (session.get("signals") or {}).get("tracking") \
            or {"notices": [], "paused": []}
        return tracking.summarize(tr.get("notices") or [], _s(as_of),
                                  paused=tr.get("paused") or [])
