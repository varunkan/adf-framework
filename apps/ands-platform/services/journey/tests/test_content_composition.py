"""The journey composes the dossier service for the content step (with fallback).

Uses a fake DossierClient double — the real in-process cross-service wiring is
exercised in the integration suite (which handles the app-package collision)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app.api import build_app
from app.repository_sqlite import SqliteSessionRepository
from app.service import JourneyService


class FakeDossier:
    def __init__(self):
        self.ensured = []
        self._complete = False

    def ensure_dossier(self, dossier_id, **k):
        self.ensured.append((dossier_id, k))

    def content_state(self, dossier_id):
        if self._complete:
            return {"gate": {"complete": True, "missing": []},
                    "tower": [{"module": "1", "state": "pass",
                               "required_total": 8, "required_filled": 8}]}
        return {"gate": {"complete": False,
                         "missing": [{"section": "1.0", "title": "Cover Letter"}]},
                "tower": [{"module": "1", "state": "todo",
                           "required_total": 8, "required_filled": 0}]}


def _ctx(dossier=None):
    repo = SqliteSessionRepository(SqliteDb(":memory:"))
    service = JourneyService(repo, InMemoryEventBus(), dossier=dossier)
    return SimpleNamespace(client=TestClient(build_app(service)), service=service)


def _walk_to_submission(client, fake_dossier=True):
    sid = client.post("/api/journey/start", json={}).json()["id"]

    def adv(step, **data):
        return client.post(f"/api/journey/{sid}/advance",
                           json={"step": step, "data": data})
    adv("orient")
    adv("company", company_id="12345")
    adv("dossier", dossier_id="e123456")
    adv("submission", applicant="Acme", drug_product="Drugazole")
    return sid, adv


def test_submission_step_provisions_the_dossier():
    fake = FakeDossier()
    ctx = _ctx(fake)
    _walk_to_submission(ctx.client)
    assert fake.ensured and fake.ensured[0][0] == "e123456"


def test_content_view_uses_dossier_state_and_gate_blocks_then_passes():
    fake = FakeDossier()
    ctx = _ctx(fake)
    sid, adv = _walk_to_submission(ctx.client)
    view = ctx.client.get(f"/api/journey/{sid}").json()
    assert view["content"]["source"] == "dossier"
    assert view["content"]["tower"][0]["module"] == "1"
    # gate incomplete → content step blocks
    assert adv("content").status_code == 422
    # once the dossier reports complete, the step advances
    fake._complete = True
    assert adv("content").status_code == 200


def test_falls_back_to_flat_model_without_a_dossier_client():
    ctx = _ctx(None)
    sid, _ = _walk_to_submission(ctx.client)
    view = ctx.client.get(f"/api/journey/{sid}").json()
    assert view["content"]["source"] == "slots"
