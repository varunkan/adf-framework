"""Per-tenant dossier scoping via the X-Tenant-Id header (CRO isolation)."""


def _mk(client, did, tenant):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": f"{did} product"},
                    headers={"X-Tenant-Id": tenant})
    assert r.status_code == 201
    return r.json()


def test_list_scoped_to_tenant(client):
    _mk(client, "e111111", "tenant-a")
    _mk(client, "e222222", "tenant-b")
    a = client.get("/api/dossier/dossiers",
                   headers={"X-Tenant-Id": "tenant-a"}).json()
    assert [d["dossier_id"] for d in a["dossiers"]] == ["e111111"]
    b = client.get("/api/dossier/dossiers",
                   headers={"X-Tenant-Id": "tenant-b"}).json()
    assert [d["dossier_id"] for d in b["dossiers"]] == ["e222222"]


def test_cross_tenant_get_and_delete_are_404(client):
    _mk(client, "e111111", "tenant-a")
    r = client.get("/api/dossier/dossiers/e111111",
                   headers={"X-Tenant-Id": "tenant-b"})
    assert r.status_code == 404
    r = client.delete("/api/dossier/dossiers/e111111",
                      headers={"X-Tenant-Id": "tenant-b"})
    assert r.status_code == 404
    # the owner still sees and can delete it
    assert client.get("/api/dossier/dossiers/e111111",
                      headers={"X-Tenant-Id": "tenant-a"}).status_code == 200


def test_upsert_never_rehomes_a_dossier(client):
    _mk(client, "e111111", "tenant-a")
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": "e111111", "title": "steal"},
                    headers={"X-Tenant-Id": "tenant-b"})
    assert r.status_code == 404   # invisible to the other tenant
    rec = client.get("/api/dossier/dossiers/e111111",
                     headers={"X-Tenant-Id": "tenant-a"}).json()["index"]
    assert rec["tenant_id"] == "tenant-a"


def test_unowned_dossiers_hidden_from_tenants(client):
    # strict isolation: an unowned (pre-tenancy) dossier is invisible to any
    # tenant context — the CRO guarantee. It only shows with no scoping.
    client.post("/api/dossier/dossiers",
                json={"dossier_id": "e999999", "title": "pre-tenancy"})
    a = client.get("/api/dossier/dossiers",
                   headers={"X-Tenant-Id": "tenant-a"}).json()
    assert "e999999" not in [d["dossier_id"] for d in a["dossiers"]]
    assert client.get("/api/dossier/dossiers/e999999",
                      headers={"X-Tenant-Id": "tenant-a"}).status_code == 404
    # visible when unscoped (mesh/tests)
    allv = client.get("/api/dossier/dossiers").json()
    assert "e999999" in [d["dossier_id"] for d in allv["dossiers"]]


def test_cross_tenant_scoped_routes_all_404(client):
    # every dossier-scoped route must reject a foreign tenant, not just get/list
    _mk(client, "e111111", "tenant-a")
    hb = {"X-Tenant-Id": "tenant-b"}
    for path in ("/api/dossier/dossiers/e111111/content",
                 "/api/dossier/dossiers/e111111/validate",
                 "/api/dossier/dossiers/e111111/sequences",
                 "/api/dossier/ectd/e111111/viewer/files",
                 "/api/dossier/ectd/e111111/current-view",
                 "/api/dossier/ectd/e111111/export/0000"):
        assert client.get(path, headers=hb).status_code == 404, path
    # the owner still reaches them
    assert client.get("/api/dossier/dossiers/e111111/content",
                      headers={"X-Tenant-Id": "tenant-a"}).status_code == 200


def test_no_header_remains_unscoped(client):
    _mk(client, "e111111", "tenant-a")
    allv = client.get("/api/dossier/dossiers").json()
    assert allv["count"] == 1


def test_cross_tenant_document_download_404(client):
    # a doc_id is disclosed in the owner's content response; a rival tenant
    # must not be able to fetch the bytes directly
    did = _mk(client, "e111111", "tenant-a")["dossier_id"] if False else "e111111"
    client.post("/api/dossier/dossiers", json={"dossier_id": "e111111",
                "title": "A drug"}, headers={"X-Tenant-Id": "tenant-a"})
    r = client.post("/api/dossier/ectd/e111111/section/1.0/generate", json={},
                    headers={"X-Tenant-Id": "tenant-a"})
    doc_id = next(n for m in r.json()["modules"] for n in m["nodes"]
                  if n["section"] == "1.0")["document"]["doc_id"]
    assert client.get(f"/api/dossier/documents/{doc_id}",
                      headers={"X-Tenant-Id": "tenant-a"}).status_code == 200
    assert client.get(f"/api/dossier/documents/{doc_id}",
                      headers={"X-Tenant-Id": "tenant-b"}).status_code == 404


def test_cross_tenant_binder_leak_and_tamper_404(client):
    client.post("/api/dossier/dossiers", json={"dossier_id": "e111111",
                "title": "A drug"}, headers={"X-Tenant-Id": "tenant-a"})
    b = client.post("/api/dossier/archive",
                    json={"dossier_id": "e111111", "sequence": "0000"},
                    headers={"X-Tenant-Id": "tenant-a"})
    assert b.status_code == 201
    binder_id = b.json()["id"]
    hb = {"X-Tenant-Id": "tenant-b"}
    assert client.get("/api/dossier/archive?dossier_id=e111111",
                      headers=hb).status_code == 404          # enumerate
    assert client.get(f"/api/dossier/archive/{binder_id}",
                      headers=hb).status_code == 404          # read
    assert client.post(f"/api/dossier/archive/{binder_id}/share",
                       headers=hb).status_code == 404         # tamper (write)
    # owner keeps full access
    assert client.get(f"/api/dossier/archive/{binder_id}",
                      headers={"X-Tenant-Id": "tenant-a"}).status_code == 200


def test_audit_hook_stamps_tenant_from_request(monkeypatch):
    """Regression: audit events must carry the request's tenant so the
    tenant-scoped audit read isn't permanently blank (round-4 finding)."""
    from app import audit_hook
    captured = {}
    monkeypatch.setattr(audit_hook, "_post",
                        lambda url, payload: captured.update(payload))
    audit_hook.set_tenant("tenant-a")
    audit_hook.set_actor("ra@a.example")
    # fire synchronously by calling _post via a stubbed thread-less path
    import threading
    real = threading.Thread
    monkeypatch.setattr(threading, "Thread",
                        lambda target, args, daemon: type("T", (), {
                            "start": lambda self: target(*args)})())
    audit_hook.record("dossier.document_generated", "e111111",
                      {"section": "1.0"})
    assert captured["tenant_id"] == "tenant-a"
    assert captured["actor"] == "ra@a.example"
    audit_hook.set_tenant(""); audit_hook.set_actor("")
