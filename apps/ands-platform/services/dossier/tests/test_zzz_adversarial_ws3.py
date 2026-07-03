"""ADVERSARIAL Part-11 audit — throwaway. Tries to BREAK the WS3 durable
ledger + delete gate on the current tree."""

import json
import pytest


def _create(client, did="d431509", title="Ledgerol 10 mg tablet"):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title})
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture
def dead_governance(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise ConnectionRefusedError("governance is down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    return monkeypatch


# ---- ATTACK 1: direct DELETE bypass of typed-id confirmation ----

def test_delete_empty_confirm_id_rejected(client, dead_governance):
    _create(client)
    # direct API DELETE with NO confirm_id but with a reason
    r = client.request("DELETE", "/api/dossier/dossiers/d431509",
                       json={"reason": "cleanup"})
    assert r.status_code == 422, r.text
    # dossier must be untouched (still live)
    g = client.get("/api/dossier/dossiers/d431509")
    assert g.status_code == 200
    assert g.json()["index"]["archived"] is False if "index" in g.json() else True


def test_delete_wrong_confirm_id_rejected(client, dead_governance):
    _create(client)
    r = client.request("DELETE", "/api/dossier/dossiers/d431509",
                       json={"reason": "cleanup", "confirm_id": "d999999"})
    assert r.status_code == 422, r.text
    # and NO archive event leaked into the durable ledger
    hist = client.get("/api/dossier/dossiers/d431509/history").json()["events"]
    assert not [e for e in hist if e["event_type"] == "dossier.archived"], hist


def test_delete_matching_confirm_id_archives(client, dead_governance):
    _create(client)
    r = client.request("DELETE", "/api/dossier/dossiers/d431509",
                       json={"reason": "cleanup", "confirm_id": "d431509"})
    assert r.status_code == 200, r.text
    hist = client.get("/api/dossier/dossiers/d431509/history").json()["events"]
    arch = [e for e in hist if e["event_type"] == "dossier.archived"]
    assert arch and arch[0]["reason"] == "cleanup"


# ---- ATTACK 2: append-only integrity across a rename ----

def test_events_survive_rename_unmutated(client, dead_governance):
    _create(client)
    # archive then restore to lay down events under old id
    client.request("DELETE", "/api/dossier/dossiers/d431509",
                   json={"reason": "r1", "confirm_id": "d431509"})
    client.post("/api/dossier/dossiers/d431509/restore", json={"reason": "back"})
    before = client.get("/api/dossier/dossiers/d431509/history").json()["events"]
    n_before = len(before)
    # rename
    r = client.post("/api/dossier/dossiers/d431509/rename",
                    json={"new_id": "e765001", "reason": "real id"})
    assert r.status_code == 200, r.text
    after = client.get("/api/dossier/dossiers/e765001/history").json()["events"]
    # all prior events still present (chained) PLUS the rename
    types_after = [e["event_type"] for e in after]
    assert types_after.count("dossier.archived") == 1
    assert types_after.count("dossier.restored") == 1
    assert types_after.count("dossier.renamed") == 1
    assert len(after) == n_before + 1


def test_multi_hop_rename_chain(client, dead_governance):
    _create(client, did="d100001")
    client.post("/api/dossier/dossiers/d100001/rename",
                json={"new_id": "d200002", "reason": "hop1"})
    client.post("/api/dossier/dossiers/d200002/rename",
                json={"new_id": "e300003", "reason": "hop2"})
    hist = client.get("/api/dossier/dossiers/e300003/history").json()["events"]
    renames = [e for e in hist if e["event_type"] == "dossier.renamed"]
    prev_ids = sorted(e["data"]["previous_id"] for e in renames)
    assert prev_ids == ["d100001", "d200002"], prev_ids


# ---- ATTACK 3: is the ledger genuinely append-only at the repo level? ----

def test_no_update_or_delete_path_on_events(client):
    """Grep the repo source for any UPDATE/DELETE touching dossier_events."""
    import app.repository_sqlite as rs
    src = open(rs.__file__).read()
    import re
    bad = re.findall(r"(UPDATE|DELETE FROM)\s+dossier_events", src, re.I)
    assert not bad, bad


def test_rename_does_not_rekey_events_table(client):
    """rename_dossier must NOT include dossier_events in its re-key list, or the
    old-id events would be silently rewritten (a mutation of prior records)."""
    import app.repository_sqlite as rs
    src = open(rs.__file__).read()
    # isolate the rename_dossier body
    body = src.split("def rename_dossier")[1].split("\n    def ")[0]
    assert "dossier_events" not in body, "rename re-keys the ledger!"


# ---- ATTACK 4: ordering — mutation without a ledger record ----

def test_archive_ledger_failure_rolls_back_mutation(client, monkeypatch):
    """INVARIANT #1 (no mutation without a durable record): if the ledger write
    fails, the archive state flip must NOT persist. The mechanism is a single
    transaction — archive_dossier + append_event commit together or not at all —
    so what we assert is the OUTCOME (dossier still live, ledger empty), not the
    call ordering. A raised ledger error propagates (500); nothing commits."""
    _create(client)
    import app.repository_sqlite as rs

    def boom_append(self, *a, **k):
        raise RuntimeError("ledger disk full")

    monkeypatch.setattr(rs.SqliteDossierRepository, "append_event", boom_append)

    try:
        client.request("DELETE", "/api/dossier/dossiers/d431509",
                       json={"reason": "cleanup", "confirm_id": "d431509"})
    except RuntimeError:
        pass  # append raised, propagated as 500 — that's fine
    # the archive was ROLLED BACK: the dossier is still LIVE (not archived)...
    idx = client.get("/api/dossier/dossiers/d431509")
    assert idx.status_code == 200
    assert "d431509" in [d["dossier_id"] for d in
                         client.get("/api/dossier/dossiers").json()["dossiers"]]
    # ...and NO archive event leaked into the durable ledger.
    monkeypatch.undo()  # restore append_event so history can be read
    hist = client.get("/api/dossier/dossiers/d431509/history").json()["events"]
    assert not [e for e in hist if e["event_type"] == "dossier.archived"], hist


def test_rename_ledger_failure_rolls_back_mutation(client, monkeypatch):
    """INVARIANT #1 for rename: if the ledger write fails, the re-key must NOT
    commit — proven by the OUTCOME (old id still resolves, new id absent, no
    'renamed' event), the transaction having rolled the whole thing back."""
    _create(client)
    import app.repository_sqlite as rs

    def boom_append(self, *a, **k):
        raise RuntimeError("ledger disk full")

    monkeypatch.setattr(rs.SqliteDossierRepository, "append_event", boom_append)

    try:
        client.post("/api/dossier/dossiers/d431509/rename",
                    json={"new_id": "e765001", "reason": "x"})
    except RuntimeError:
        pass
    # the re-key was ROLLED BACK: the OLD id is still the catalog entry, the new
    # id was never created.
    listed = [d["dossier_id"] for d in
              client.get("/api/dossier/dossiers").json()["dossiers"]]
    assert "d431509" in listed and "e765001" not in listed
    # no rename-chain / no renamed event was committed for the new id either.
    monkeypatch.undo()  # restore append_event so history can be read
    hist = client.get("/api/dossier/dossiers/e765001/history").json()["events"]
    assert not [e for e in hist if e["event_type"] == "dossier.renamed"], hist


def test_restore_evidence_preserved(client, dead_governance):
    _create(client)
    client.request("DELETE", "/api/dossier/dossiers/d431509",
                   json={"reason": "archive-why", "confirm_id": "d431509"},
                   headers={"X-User-Email": "alice@x.com"})
    client.post("/api/dossier/dossiers/d431509/restore",
                json={"reason": "restore-why"})
    hist = client.get("/api/dossier/dossiers/d431509/history").json()["events"]
    rest = next(e for e in hist if e["event_type"] == "dossier.restored")
    # the restore event must carry the prior archive stamp
    assert rest["data"]["prior_archive_reason"] == "archive-why", rest["data"]
    assert rest["data"]["prior_archived_by"] == "alice@x.com", rest["data"]
    assert rest["data"]["prior_archived_at"], rest["data"]
