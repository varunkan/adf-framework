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
