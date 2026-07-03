"""WS3 Part-11 audit-integrity: destructive re-keys/deletes/restores MUST leave
a DURABLE local append-only record even if the governance forward is dead.

The prior design coupled the ONLY record of previous_id/actor/reason to
audit_hook.record() — a fire-and-forget daemon POST whose _post() swallows all
exceptions. Governance down => a destructive mutation with zero durable audit.

These tests monkeypatch the governance forward to HARD-FAIL and prove the local
ledger still captures the event (incl. previous_id / archive evidence), that a
server-side typed-id confirmation gate rejects a mismatched delete (422), and
that GET /dossiers/{id}/history reads the durable ledger (chained across a
rename so the previous_id still resolves).
"""

import pytest


def _create(client, did="d431509", title="Ledgerol 10 mg tablet"):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title})
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture
def dead_governance(monkeypatch):
    """Governance forward is unreachable — the underlying HTTP call raises,
    which audit_hook._post swallows by contract (best-effort). We then assert
    the mutation STILL leaves a durable local ledger entry despite the forward
    silently dropping the event. Patching urlopen (not _post) exercises the
    real swallow-all path exactly as a governance outage would."""
    import urllib.request

    def boom(*a, **k):
        raise ConnectionRefusedError("governance is down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    return monkeypatch


def test_rename_leaves_durable_ledger_with_previous_id(client, dead_governance):
    _create(client)
    r = client.post("/api/dossier/dossiers/d431509/rename",
                    json={"new_id": "e765001", "reason": "HC issued real ID"},
                    headers={"X-User-Email": "regops@sponsor.example"})
    assert r.status_code == 200, r.text

    # the durable local ledger — NOT the governance forward — has the event
    hist = client.get("/api/dossier/dossiers/e765001/history")
    assert hist.status_code == 200, hist.text
    events = hist.json()["events"]
    ren = next(e for e in events if e["event_type"] == "dossier.renamed")
    assert ren["data"]["previous_id"] == "d431509"
    assert ren["data"]["new_id"] == "e765001"
    assert ren["reason"] == "HC issued real ID"
    assert ren["actor"] == "regops@sponsor.example"
    assert ren["timestamp"]


def test_history_chains_across_rename(client):
    _create(client)
    # author + record an event under the OLD id, then re-key
    client.post("/api/dossier/ectd/d431509/section/1.2.1/generate", json={})
    client.post("/api/dossier/dossiers/d431509/rename",
                json={"new_id": "e765001"})
    # history for the NEW id resolves events recorded under the OLD id too
    events = client.get("/api/dossier/dossiers/e765001/history").json()["events"]
    types = [e["event_type"] for e in events]
    assert "dossier.renamed" in types
    # the chain resolves: at least the rename event carries the previous id
    assert any(e.get("dossier_id") == "d431509"
               or e["data"].get("previous_id") == "d431509" for e in events)


def test_delete_leaves_durable_archive_evidence(client, dead_governance):
    _create(client)
    r = client.request(
        "DELETE", "/api/dossier/dossiers/d431509",
        json={"reason": "duplicate created in error", "confirm_id": "d431509"},
        headers={"X-User-Email": "regops@sponsor.example"})
    assert r.status_code == 200, r.text
    events = client.get("/api/dossier/dossiers/d431509/history").json()["events"]
    arch = next(e for e in events if e["event_type"] == "dossier.archived")
    assert arch["reason"] == "duplicate created in error"
    assert arch["actor"] == "regops@sponsor.example"
    assert arch["timestamp"]


def test_restore_preserves_archive_evidence_durably(client, dead_governance):
    _create(client)
    client.request("DELETE", "/api/dossier/dossiers/d431509",
                   json={"reason": "filed in wrong workspace",
                         "confirm_id": "d431509"},
                   headers={"X-User-Email": "alice@sponsor.example"})
    r = client.post("/api/dossier/dossiers/d431509/restore",
                    json={"reason": "belongs here after all"},
                    headers={"X-User-Email": "bob@sponsor.example"})
    assert r.status_code == 200, r.text
    events = client.get("/api/dossier/dossiers/d431509/history").json()["events"]
    et = {e["event_type"]: e for e in events}
    # BOTH the archive and the restore survive in the durable ledger — the
    # evidence the dossier was ever archived (who/when/why) is NOT erased.
    assert "dossier.archived" in et
    assert et["dossier.archived"]["actor"] == "alice@sponsor.example"
    assert et["dossier.archived"]["reason"] == "filed in wrong workspace"
    assert "dossier.restored" in et
    assert et["dossier.restored"]["actor"] == "bob@sponsor.example"
    # the restore event carries the prior archive stamp it undid
    assert et["dossier.restored"]["data"].get("prior_archived_at")


def test_delete_requires_matching_confirm_id(client):
    _create(client)
    # server-side typed-id gate: a mismatched confirm_id is rejected 422 even
    # though a direct API DELETE bypasses the client-side "type the ID" gate.
    bad = client.request("DELETE", "/api/dossier/dossiers/d431509",
                         json={"reason": "x", "confirm_id": "e999999"})
    assert bad.status_code == 422, bad.text
    assert "confirm" in bad.text.lower() or "match" in bad.text.lower()
    # missing confirm_id entirely -> also 422
    none = client.request("DELETE", "/api/dossier/dossiers/d431509",
                          json={"reason": "x"})
    assert none.status_code == 422, none.text
    # the dossier is UNTOUCHED — still in the working catalog
    listed = [d["dossier_id"] for d in
              client.get("/api/dossier/dossiers").json()["dossiers"]]
    assert "d431509" in listed


def test_delete_with_matching_confirm_id_succeeds(client):
    _create(client)
    ok = client.request("DELETE", "/api/dossier/dossiers/d431509",
                        json={"reason": "duplicate", "confirm_id": "d431509"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["archived"] == "d431509"


def test_history_endpoint_returns_events(client):
    _create(client)
    client.request("DELETE", "/api/dossier/dossiers/d431509",
                   json={"reason": "r", "confirm_id": "d431509"})
    client.post("/api/dossier/dossiers/d431509/restore", json={})
    hist = client.get("/api/dossier/dossiers/d431509/history")
    assert hist.status_code == 200
    events = hist.json()["events"]
    types = {e["event_type"] for e in events}
    assert {"dossier.archived", "dossier.restored"} <= types
    # append-only, newest-first, monotonically-sequenced
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs, reverse=True)


# ── WS3 re-review hardening: no phantom audit on a failed/raced mutation, and
#    the server-side typed-ID gate is EXACT (no whitespace looseness). ────────

def test_padded_confirm_id_is_rejected(client):
    did = "d431509"
    client.post("/api/dossier/dossiers", json={"dossier_id": did, "title": "X"})
    r = client.request("DELETE", f"/api/dossier/dossiers/{did}",
                       json={"reason": "cleanup", "confirm_id": " d431509"})
    assert r.status_code == 422
    assert r.json()["rule"] == "delete_confirm_id_mismatch"


def test_failed_rename_leaves_no_phantom_history(ctx, monkeypatch):
    """A rename that fails at the repo (TOCTOU / DB error) must leave NO durable
    'renamed' event or chain — else a later dossier reusing the id inherits a
    phantom history (cross-dossier audit contamination)."""
    c, old, new = ctx.client, "d431509", "e9876543"
    c.post("/api/dossier/dossiers", json={"dossier_id": old, "title": "X"})
    monkeypatch.setattr(ctx.repo, "rename_dossier", lambda *a, **k: False)
    r = c.post(f"/api/dossier/dossiers/{old}/rename",
               json={"new_id": new, "reason": "real HC id"})
    assert r.status_code == 404
    assert ctx.repo.list_events(new) == []          # no phantom event/chain


def test_failed_archive_leaves_no_phantom_event(ctx, monkeypatch):
    c, did = ctx.client, "d222001"
    c.post("/api/dossier/dossiers", json={"dossier_id": did, "title": "X"})
    monkeypatch.setattr(ctx.repo, "archive_dossier", lambda *a, **k: False)
    r = c.request("DELETE", f"/api/dossier/dossiers/{did}",
                  json={"reason": "cleanup", "confirm_id": did})
    assert r.status_code == 404
    assert not any(e.get("event_type") == "dossier.archived"
                   for e in ctx.repo.list_events(did))
