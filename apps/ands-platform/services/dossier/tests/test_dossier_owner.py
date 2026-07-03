"""dossier_index persists a per-dossier OWNER (PM/assignee).

WS6 portfolio: PMs want a single accountable owner per dossier — distinct from
the per-plan-item assignees (which are many) and the REP sponsor (the client
company). A dedicated ``owner`` column on the dossier index is the simplest
correct source of truth: one value per dossier, no aggregation ambiguity, and
it mirrors the existing COALESCE-preserve semantics of company_id/sponsor.
"""

from ands_shared import SqliteDb

from app.repository_sqlite import SqliteDossierRepository


def _repo():
    return SqliteDossierRepository(SqliteDb(":memory:"))


def test_owner_persists_and_reads_back():
    repo = _repo()
    rec = repo.create_dossier_index({
        "dossier_id": "e910001", "title": "Apo-Zentrix 50 mg tablet",
        "owner": "Priya Nair"})
    assert rec["owner"] == "Priya Nair"
    assert repo.get_dossier_index("e910001")["owner"] == "Priya Nair"


def test_absent_owner_stores_null():
    repo = _repo()
    rec = repo.create_dossier_index({
        "dossier_id": "e910002", "title": "Drugazole 10 mg"})
    assert rec["owner"] is None


def test_upsert_preserves_owner_when_omitted():
    # like sponsor/company_id: an upsert that leaves owner out keeps the
    # previously captured value (COALESCE-preserve).
    repo = _repo()
    repo.create_dossier_index({
        "dossier_id": "e910003", "title": "X", "owner": "Priya Nair"})
    upd = repo.create_dossier_index({
        "dossier_id": "e910003", "title": "X (rev)"})
    assert upd["title"] == "X (rev)"
    assert upd["owner"] == "Priya Nair"


def test_upsert_can_update_owner_when_provided():
    repo = _repo()
    repo.create_dossier_index({
        "dossier_id": "e910004", "title": "X", "owner": "Old PM"})
    upd = repo.create_dossier_index({
        "dossier_id": "e910004", "title": "X", "owner": "Priya Nair"})
    assert upd["owner"] == "Priya Nair"
