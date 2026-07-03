"""WS3 durable-ledger hardening proofs, stated as INVARIANTS:

  #1  atomicity — a ledger-write failure rolls the state mutation back (proved
      directly at the SqliteDb.transaction() layer), and
  #3  no cross-dossier audit leak — a new dossier reusing a dossier_id freed by
      a rename-away inherits NONE of the prior dossier's ledger (uid-keyed).
"""

import pytest

from ands_shared import InMemoryEventBus, SqliteDb

from app.repository_sqlite import SqliteDossierRepository


def _mk(client, did, title="x"):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title})
    assert r.status_code in (200, 201), r.text


# ── INVARIANT #1: atomicity via a real transaction rollback ──────────────────

def test_transaction_rolls_back_every_statement_on_failure():
    """SqliteDb.transaction() commits all-or-nothing: a body that writes several
    rows then raises leaves ZERO of them (and does not leak the open txn state)."""
    db = SqliteDb(":memory:")
    db.execute("CREATE TABLE t (v TEXT)")
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute("INSERT INTO t (v) VALUES ('a')")
            db.execute("INSERT INTO t (v) VALUES ('b')")
            raise RuntimeError("boom before commit")
    assert db.fetchall("SELECT v FROM t") == []          # nothing committed
    # the scope cleaned up — a subsequent normal write still commits per-stmt
    db.execute("INSERT INTO t (v) VALUES ('c')")
    assert [r["v"] for r in db.fetchall("SELECT v FROM t")] == ["c"]


def test_archive_with_event_atomic_rollback_on_ledger_failure(monkeypatch):
    """The repo pairing: if append_event raises, the archive state flip is rolled
    back — no mutation without a durable record (INVARIANT #1)."""
    repo = SqliteDossierRepository(SqliteDb(":memory:"))
    repo.create_dossier_index({"dossier_id": "d431509", "title": "X"})

    def boom(self, *a, **k):
        raise RuntimeError("ledger disk full")

    monkeypatch.setattr(SqliteDossierRepository, "append_event", boom)
    with pytest.raises(RuntimeError):
        repo.archive_with_event("d431509", actor="a", reason="r",
                                event_type="dossier.archived",
                                tenant_id="", data={})
    monkeypatch.undo()
    # the archive was rolled back — still live, and the ledger is empty
    assert repo.get_dossier_index("d431509")["archived"] is False
    assert repo.list_events("d431509") == []


def test_no_op_mutation_commits_no_phantom_event():
    """The other half of atomicity (INVARIANT #2): when the mutation is a no-op
    (dossier already archived -> archive_dossier False), the transaction commits
    NOTHING — no phantom ledger event."""
    repo = SqliteDossierRepository(SqliteDb(":memory:"))
    repo.create_dossier_index({"dossier_id": "d222001", "title": "X"})
    assert repo.archive_with_event("d222001", actor="a", reason="r1",
                                   event_type="dossier.archived",
                                   tenant_id="", data={}) is not None
    n = len(repo.list_events("d222001"))
    # second archive is a no-op (already archived) -> None, no new event
    assert repo.archive_with_event("d222001", actor="a", reason="r2",
                                   event_type="dossier.archived",
                                   tenant_id="", data={}) is None
    assert len(repo.list_events("d222001")) == n


# ── INVARIANT #3: rename-away + id-reuse must not leak the prior ledger ───────

def test_reused_id_after_rename_away_gets_fresh_uid_no_leak(client):
    """Full happy-path: A (a111111) accrues a distinctive event, is renamed away
    to b222222 (a111111 now free), then a BRAND-NEW dossier reuses a111111. The
    new dossier's history is empty of A's events — it has its own fresh uid — and
    A's whole history still resolves under b222222."""
    _mk(client, "a111111")
    client.request("DELETE", "/api/dossier/dossiers/a111111",
                   json={"reason": "PATIENT-SAFETY-RECALL", "confirm_id": "a111111"})
    client.post("/api/dossier/dossiers/a111111/restore", json={"reason": "ok"})
    assert client.post("/api/dossier/dossiers/a111111/rename",
                       json={"new_id": "b222222"}).status_code == 200

    _mk(client, "a111111", title="Unrelated New Product")

    # the NEW a111111 inherits nothing
    new_hist = client.get("/api/dossier/dossiers/a111111/history").json()["events"]
    assert new_hist == [] or not [e for e in new_hist
                                  if e.get("reason") == "PATIENT-SAFETY-RECALL"], new_hist
    # A's full history still resolves under its current id b222222
    b_hist = client.get("/api/dossier/dossiers/b222222/history").json()["events"]
    types = [e["event_type"] for e in b_hist]
    assert types.count("dossier.archived") == 1
    assert types.count("dossier.restored") == 1
    assert types.count("dossier.renamed") == 1
    assert any(e.get("reason") == "PATIENT-SAFETY-RECALL" for e in b_hist)
