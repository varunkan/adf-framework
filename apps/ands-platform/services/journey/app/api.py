"""FastAPI surface for the journey BFF — the single API the guided UI calls."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Query

from ands_shared import create_app

from .models import (AdvanceIn, DossierAssessIn, IntakeIn, NoticeIn, PauseIn,
                     PlaceDocIn, StartIn)
from .service import JourneyService


def build_app(service: JourneyService) -> FastAPI:
    app = create_app(
        title="journey",
        description="Guided drug-filing journey BFF (JOURNEY-REQ) — the story "
                    "spine + 'tell me about your drug' decision support")
    router = APIRouter(prefix="/api/journey", tags=["journey"])

    @router.get("/catalog")
    def catalog():
        """The static journey spine + reference data for the UI to render."""
        return service.catalog()

    @router.post("/start")
    def start(body: StartIn):
        return service.start(body.model_dump())

    @router.get("/sessions")
    def sessions():
        return service.list_sessions()

    @router.get("/{session_id}")
    def get(session_id: str):
        return service.get(session_id)

    @router.post("/{session_id}/advance")
    def advance(session_id: str, body: AdvanceIn):
        return service.advance(session_id, body.step, body.data)

    @router.post("/intake")
    def intake(body: IntakeIn):
        answers = body.model_dump()
        session_id = answers.pop("session_id", "")
        return service.intake(answers, session_id)

    @router.post("/dossier-id/assess")
    def dossier_id_assess(body: DossierAssessIn):
        return service.assess_dossier_id(body.model_dump())

    @router.post("/{session_id}/content/place")
    def content_place(session_id: str, body: PlaceDocIn):
        """Drop a document onto an eCTD Module slot (lights up the tower)."""
        return service.place_document(session_id, body.slot_key, body.doc,
                                      body.languages)

    @router.post("/{session_id}/track/notice")
    def track_notice(session_id: str, body: NoticeIn):
        """Log a Health Canada notice (SDN/SAL/clarifax/NOD/NON/NOC)."""
        return service.log_notice(session_id, body.model_dump())

    @router.post("/{session_id}/track/pause")
    def track_pause(session_id: str, body: PauseIn):
        """Pause / resume the clock on a clarifax response timer."""
        return service.set_pause(session_id, body.type, body.paused)

    @router.get("/{session_id}/track")
    def track(session_id: str, as_of: str = Query(...)):
        """The live review phase + deadline timers (as_of = the caller's today)."""
        return service.track_view(session_id, as_of)

    app.include_router(router)
    return app
