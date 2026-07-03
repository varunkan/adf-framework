"""WS3 record-integrity: a destructive delete on a regulated dossier is
RECOVERABLE — it soft-archives (actor + timestamp + reason), drops out of the
working catalog but stays restorable, and both delete and restore land on the
append-only audit trail with a reason-for-change field. No hard purge.
"""


def _create(client, did="d431509", title="Recoverablol 10 mg tablet"):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title})
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_delete_soft_archives_and_excludes_from_list(client):
    _create(client)
    # author a section so there is real content that must survive an archive
    g = client.post("/api/dossier/ectd/d431509/section/1.2.1/generate", json={})
    assert g.status_code == 200, g.text

    r = client.request("DELETE", "/api/dossier/dossiers/d431509",
                       json={"reason": "duplicate submission created in error",
                             "confirm_id": "d431509"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["archived"] == "d431509"
    assert body["reason"] == "duplicate submission created in error"

    # working catalog no longer shows it
    listed = [d["dossier_id"] for d in
              client.get("/api/dossier/dossiers").json()["dossiers"]]
    assert "d431509" not in listed

    # but the archived view does — with actor/timestamp/reason
    arch = client.get("/api/dossier/dossiers/archived").json()
    ids = {d["dossier_id"] for d in arch["dossiers"]}
    assert "d431509" in ids
    rec = next(d for d in arch["dossiers"] if d["dossier_id"] == "d431509")
    assert rec["archived_at"]
    assert rec["archive_reason"] == "duplicate submission created in error"


def test_restore_brings_it_back_to_the_working_catalog(client):
    _create(client)
    client.post("/api/dossier/ectd/d431509/section/1.2.1/generate", json={})
    client.request("DELETE", "/api/dossier/dossiers/d431509",
                   json={"reason": "filed under wrong workspace",
                         "confirm_id": "d431509"})

    r = client.post("/api/dossier/dossiers/d431509/restore",
                    json={"reason": "recovered — belongs here after all"})
    assert r.status_code == 200, r.text
    assert r.json()["restored"] == "d431509"

    listed = [d["dossier_id"] for d in
              client.get("/api/dossier/dossiers").json()["dossiers"]]
    assert "d431509" in listed

    # the authored content survived the archive->restore round trip
    content = client.get("/api/dossier/dossiers/d431509/content").json()

    def flat(x, acc):
        if isinstance(x, dict):
            if x.get("status") == "complete":
                acc.append(x.get("section"))
            for v in x.values():
                flat(v, acc)
        elif isinstance(x, list):
            for v in x:
                flat(v, acc)
        return acc
    assert "1.2.1" in flat(content["modules"], [])


def test_delete_and_restore_are_audited_with_reason(client, monkeypatch):
    """Both destructive actions land on the append-only audit trail carrying
    the reason-for-change field (Part-11 who/when/why)."""
    from app import audit_hook
    events = []
    monkeypatch.setattr(audit_hook, "record",
                        lambda et, did, data=None, **kw:
                        events.append((et, did, dict(data or {}))))
    _create(client)
    client.request("DELETE", "/api/dossier/dossiers/d431509",
                   json={"reason": "created in error", "confirm_id": "d431509"})
    client.post("/api/dossier/dossiers/d431509/restore",
                json={"reason": "un-delete requested by sponsor"})

    by_type = {et: data for et, did, data in events}
    assert "dossier.archived" in by_type
    assert by_type["dossier.archived"]["reason"] == "created in error"
    assert "dossier.restored" in by_type
    assert by_type["dossier.restored"]["reason"] == "un-delete requested by sponsor"


def test_delete_requires_a_reason(client):
    _create(client)
    r = client.request("DELETE", "/api/dossier/dossiers/d431509",
                       json={"reason": "   "})
    assert r.status_code == 422, r.text
    assert "reason" in r.text.lower()


def test_delete_unknown_dossier_is_404(client):
    r = client.request("DELETE", "/api/dossier/dossiers/d000000",
                       json={"reason": "whatever", "confirm_id": "d000000"})
    assert r.status_code == 404
