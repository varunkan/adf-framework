"""dossier_index persists the REP sponsor identity (company_id + sponsor).

The generator draws COMPANY_ID / COMPANY_NAME from the ctx; the ctx is built
from get_dossier_index. These columns give a (sibling) service change a place to
thread the captured Company ID and sponsor so they survive to the REP XML.
"""

from ands_shared import SqliteDb

from app.repository_sqlite import SqliteDossierRepository


def _repo():
    return SqliteDossierRepository(SqliteDb(":memory:"))


def test_company_id_and_sponsor_persist_and_read_back():
    repo = _repo()
    rec = repo.create_dossier_index({
        "dossier_id": "e900001", "title": "Apo-Zentrix 50 mg tablet",
        "company_id": "61234", "sponsor": "Northline Regulatory Partners"})
    assert rec["company_id"] == "61234"
    assert rec["sponsor"] == "Northline Regulatory Partners"
    got = repo.get_dossier_index("e900001")
    assert got["company_id"] == "61234"
    assert got["sponsor"] == "Northline Regulatory Partners"


def test_absent_rep_identity_stores_null():
    repo = _repo()
    rec = repo.create_dossier_index({
        "dossier_id": "e900002", "title": "Drugazole 10 mg"})
    assert rec["company_id"] is None
    assert rec["sponsor"] is None


def test_upsert_preserves_rep_identity_when_omitted():
    # like tenant_id: an upsert that leaves company_id/sponsor out must keep
    # the previously captured values (COALESCE-preserve).
    repo = _repo()
    repo.create_dossier_index({
        "dossier_id": "e900003", "title": "Apo-Zentrix 50 mg tablet",
        "company_id": "61234", "sponsor": "Northline Regulatory Partners"})
    upd = repo.create_dossier_index({
        "dossier_id": "e900003", "title": "Apo-Zentrix 50 mg tablet (rev)"})
    assert upd["title"] == "Apo-Zentrix 50 mg tablet (rev)"
    assert upd["company_id"] == "61234"
    assert upd["sponsor"] == "Northline Regulatory Partners"


def test_upsert_can_update_rep_identity_when_provided():
    repo = _repo()
    repo.create_dossier_index({
        "dossier_id": "e900004", "title": "X", "company_id": "1",
        "sponsor": "Old Sponsor"})
    upd = repo.create_dossier_index({
        "dossier_id": "e900004", "title": "X", "company_id": "61234",
        "sponsor": "Northline Regulatory Partners"})
    assert upd["company_id"] == "61234"
    assert upd["sponsor"] == "Northline Regulatory Partners"
