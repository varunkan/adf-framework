"""ADVERSARIAL round 2 — orphan rename-chain + id-reuse poisoning."""

import pytest


def _create(client, did, title="X 10 mg"):
    r = client.post("/api/dossier/dossiers", json={"dossier_id": did, "title": title})
    assert r.status_code in (200, 201), r.text


@pytest.fixture
def dead_governance(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError()))
    return monkeypatch


def test_rename_repo_false_leaves_orphan_chain_then_id_reuse_leaks(client, monkeypatch):
    """rename_dossier() returns False AFTER the ledger event + rename_chain are
    already committed (they run first, each auto-commits). The service then
    404s, but the chain new_id->old_id and the 'renamed' event persist. If a
    DIFFERENT dossier is later legitimately created with that new_id, its
    history read walks the stale chain and surfaces the UNRELATED old dossier's
    events — a Part-11 cross-contamination / phantom-provenance leak."""
    _create(client, "d100001")
    _create(client, "d900009")  # unrelated dossier we lay events on
    # put a distinctive archive event on d900009's ledger
    client.request("DELETE", "/api/dossier/dossiers/d900009",
                   json={"reason": "SECRET-OTHER-DOSSIER", "confirm_id": "d900009"})

    import app.repository_sqlite as rs
    # force the actual re-key to fail, AFTER ledger+chain are written
    monkeypatch.setattr(rs.SqliteDossierRepository, "rename_dossier",
                        lambda self, o, n: False)

    r = client.post("/api/dossier/dossiers/d100001/rename",
                    json={"new_id": "d900009_x", "reason": "attempt"})
    # service 404s because repo said False
    # (new_id here is fresh; pick it so it doesn't collide with the taken check)

    # Now: was an orphan chain committed for the fresh new_id?
    hist = client.get("/api/dossier/dossiers/d900009_x/history").json()["events"]
    chained_prev = [e for e in hist if e.get("data", {}).get("previous_id")]
    print("ORPHAN CHAIN EVENTS:", chained_prev, "status", r.status_code)
    # If the chain leaked, d900009_x history now shows d100001's rename event
    # even though d900009_x was never actually created.
    assert True  # informational — inspect output


def test_id_reuse_after_failed_rename_surfaces_prior_events(client, dead_governance, monkeypatch):
    """The concrete exploit: A is renamed to B but the re-key fails (orphan
    chain B->A committed). Later B is created fresh as an unrelated dossier.
    Reading B's history now leaks A's ledger events."""
    _create(client, "a111111")
    # lay a distinctive event on A
    client.request("DELETE", "/api/dossier/dossiers/a111111",
                   json={"reason": "A-PRIVATE-REASON", "confirm_id": "a111111"})
    client.post("/api/dossier/dossiers/a111111/restore", json={"reason": "x"})

    import app.repository_sqlite as rs
    real = rs.SqliteDossierRepository.rename_dossier
    # make rename write the chain+event but then FAIL the actual re-key
    monkeypatch.setattr(rs.SqliteDossierRepository, "rename_dossier",
                        lambda self, o, n: False)
    r = client.post("/api/dossier/dossiers/a111111/rename",
                    json={"new_id": "b222222", "reason": "attempt"})
    monkeypatch.setattr(rs.SqliteDossierRepository, "rename_dossier", real)

    # b222222 was NEVER really created. Now a legitimate, unrelated b222222:
    _create(client, "b222222", title="Totally Unrelated Drug")
    hist = client.get("/api/dossier/dossiers/b222222/history").json()["events"]
    leaked = [e for e in hist if e.get("reason") == "A-PRIVATE-REASON"
              or e.get("data", {}).get("previous_id") == "a111111"]
    assert not leaked, f"LEAK: unrelated b222222 history shows A's events: {leaked}"
