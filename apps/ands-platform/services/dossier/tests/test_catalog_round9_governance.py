"""Round-9 usability backlog — Dossier Catalog (`catalog`) governance items.

Covers the SERVICE side of:
- catalog/"No user roles, permissions, or e-signatures on workspace actions"
  (n=6): typed-name e-signature CAPTURE recorded verbatim on the durable
  archive/restore ledger events, and the Owner (PM) reassignment endpoint
  (owner is an accountability label — the old/new values land on the ledger).
- catalog/"No bilingual/French support surfaced anywhere on the page" (n=2):
  the governed French product name (title_fr) + labelling owner captured at
  creation and carried on the catalog list payload.
"""


def _mk(client, did="e123456", **kw):
    body = {"dossier_id": did, "title": kw.pop("title", "Drugazole 10 mg")}
    body.update(kw)
    return client.post("/api/dossier/dossiers", json=body)


def _events(client, did):
    return client.get(f"/api/dossier/dossiers/{did}/history").json()["events"]


# ── typed-name e-signature capture on archive / restore ─────────────────────

def test_archive_records_typed_name_esignature(client):
    _mk(client)
    r = client.request("DELETE", "/api/dossier/dossiers/e123456",
                       json={"reason": "duplicate created in error",
                             "confirm_id": "e123456",
                             "esign": {"signed_name": "Priya Nair",
                                       "meaning": "I authorize archiving "
                                                  "this dossier"}})
    assert r.status_code == 200
    ev = [e for e in _events(client, "e123456")
          if e["event_type"] == "dossier.archived"][0]
    sig = ev["data"]["esign"]
    assert sig["signed_name"] == "Priya Nair"                 # verbatim
    assert sig["meaning"] == "I authorize archiving this dossier"
    assert sig["method"] == "typed-name"     # honest: typed-name capture,
    #                                          not a cryptographic certificate


def test_archive_without_esign_still_works_and_carries_none(client):
    # back-compat: the typed-confirm + reason gate is unchanged; esign is an
    # ADDITIONAL capture, absent when the caller sent none.
    _mk(client)
    r = client.request("DELETE", "/api/dossier/dossiers/e123456",
                       json={"reason": "duplicate created in error",
                             "confirm_id": "e123456"})
    assert r.status_code == 200
    ev = [e for e in _events(client, "e123456")
          if e["event_type"] == "dossier.archived"][0]
    assert "esign" not in ev["data"]


def test_restore_records_typed_name_esignature(client):
    _mk(client)
    client.request("DELETE", "/api/dossier/dossiers/e123456",
                   json={"reason": "duplicate created in error",
                         "confirm_id": "e123456"})
    r = client.post("/api/dossier/dossiers/e123456/restore",
                    json={"reason": "archived in error",
                          "esign": {"signed_name": "Priya Nair",
                                    "meaning": "I authorize restoring "
                                               "this dossier"}})
    assert r.status_code == 200
    ev = [e for e in _events(client, "e123456")
          if e["event_type"] == "dossier.restored"][0]
    assert ev["data"]["esign"]["signed_name"] == "Priya Nair"
    assert ev["data"]["esign"]["method"] == "typed-name"


# ── Owner (PM) reassignment — an accountability label, on the ledger ────────

def test_owner_reassignment_updates_index_and_ledger(client):
    _mk(client, owner="j.smith@cro.example")
    r = client.post("/api/dossier/dossiers/e123456/owner",
                    json={"owner": "p.nair@cro.example",
                          "reason": "PM handover at sponsor request"})
    assert r.status_code == 200
    assert r.json()["owner"] == "p.nair@cro.example"
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["owner"] == "p.nair@cro.example"
    ev = [e for e in _events(client, "e123456")
          if e["event_type"] == "dossier.owner_changed"][0]
    assert ev["data"]["old_owner"] == "j.smith@cro.example"
    assert ev["data"]["new_owner"] == "p.nair@cro.example"
    assert ev["reason"] == "PM handover at sponsor request"


def test_owner_can_be_unassigned(client):
    _mk(client, owner="j.smith@cro.example")
    r = client.post("/api/dossier/dossiers/e123456/owner",
                    json={"owner": "", "reason": "PM left the project"})
    assert r.status_code == 200
    assert r.json()["owner"] is None


def test_owner_change_requires_reason(client):
    _mk(client, owner="j.smith@cro.example")
    r = client.post("/api/dossier/dossiers/e123456/owner",
                    json={"owner": "p.nair@cro.example"})
    assert r.status_code == 422
    assert r.json()["rule"] == "owner_reason_required"


def test_owner_change_on_missing_dossier_404s(client):
    r = client.post("/api/dossier/dossiers/e999999/owner",
                    json={"owner": "x@y.example", "reason": "n/a"})
    assert r.status_code == 404


# ── governed French product name + labelling owner at creation ──────────────

def test_create_captures_title_fr_and_labelling_owner(client):
    r = _mk(client, title="Drugazole 10 mg tablet",
            title_fr="Drugazole comprimé de 10 mg",
            labelling_owner="m.tremblay@cro.example")
    assert r.status_code == 201
    assert r.json()["title_fr"] == "Drugazole comprimé de 10 mg"
    assert r.json()["labelling_owner"] == "m.tremblay@cro.example"
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["title_fr"] == "Drugazole comprimé de 10 mg"
    assert row["labelling_owner"] == "m.tremblay@cro.example"


def test_create_without_french_fields_stores_null(client):
    assert _mk(client).status_code == 201
    row = client.get("/api/dossier/dossiers").json()["dossiers"][0]
    assert row["title_fr"] is None
    assert row["labelling_owner"] is None
