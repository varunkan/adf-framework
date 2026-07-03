"""WS6 portfolio PM columns: list_dossiers surfaces owner + sponsor + the
soonest content-plan due date, so a PM sees ownership, client and deadline
per dossier without opening it.

- owner/sponsor: pass through from the dossier index (stored columns).
- soonest_due: DERIVED (not stored) from the dossier's content-plan items —
  the earliest ISO due_date across open (non-complete) items. No new storage.
"""

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app import content_plan
from app.api import build_app
from app.repository_sqlite import SqliteDossierRepository
from app.service import DossierService


@pytest.fixture
def svc():
    repo = SqliteDossierRepository(SqliteDb(":memory:"))
    service = DossierService(repo, InMemoryEventBus()).register()
    return service


def test_list_exposes_owner_and_sponsor(svc):
    svc.repo.create_dossier_index({
        "dossier_id": "e920001", "title": "Apo-Zentrix",
        "owner": "Priya Nair", "sponsor": "Northline Regulatory Partners"})
    row = next(d for d in svc.list_dossiers()["dossiers"]
               if d["dossier_id"] == "e920001")
    assert row["owner"] == "Priya Nair"
    assert row["sponsor"] == "Northline Regulatory Partners"


def test_list_derives_soonest_due_from_plan_items(svc):
    svc.repo.create_dossier_index({"dossier_id": "e920002", "title": "X"})
    plan = svc.repo.create_plan("e920002", "ANDS",
                                content_plan.build_plan_items("ANDS"))
    items = plan["items"]
    # two open items with due dates + one earlier date on a COMPLETE item that
    # must be ignored (a shipped item is not an upcoming deadline).
    svc.assign_item(items[0]["id"], "bob", "2026-09-15")
    svc.assign_item(items[1]["id"], "sue", "2026-08-01")
    svc.repo.update_item(items[2]["id"], {"due_date": "2026-01-01",
                                          "status": content_plan.ITEM_COMPLETE})
    row = next(d for d in svc.list_dossiers()["dossiers"]
               if d["dossier_id"] == "e920002")
    assert row["soonest_due"] == "2026-08-01"


def test_list_soonest_due_null_when_no_dates(svc):
    svc.repo.create_dossier_index({"dossier_id": "e920003", "title": "X"})
    svc.repo.create_plan("e920003", "ANDS",
                         content_plan.build_plan_items("ANDS"))
    row = next(d for d in svc.list_dossiers()["dossiers"]
               if d["dossier_id"] == "e920003")
    assert row["soonest_due"] is None


def test_list_soonest_due_null_when_no_plan(svc):
    svc.repo.create_dossier_index({"dossier_id": "e920004", "title": "X"})
    row = next(d for d in svc.list_dossiers()["dossiers"]
               if d["dossier_id"] == "e920004")
    assert row["soonest_due"] is None


def test_owner_accepted_on_create_dossier_api(svc):
    client = TestClient(build_app(svc))
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": "e920005", "title": "X",
                          "owner": "Priya Nair", "sponsor": "Acme"})
    assert r.status_code == 201
    assert r.json()["owner"] == "Priya Nair"
