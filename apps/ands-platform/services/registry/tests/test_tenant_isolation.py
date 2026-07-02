"""Cross-tenant isolation contract (CRO blocker): a tenant's registration must
be invisible to every other tenant on list + get + right-to-sell + set_status,
while the in-process mesh (no header) stays unscoped."""

_A = {"X-Tenant-Id": "tenant-A"}
_B = {"X-Tenant-Id": "tenant-B"}


def _create(client, headers=None, product="Metformin", dossier="e1",
            din="02431234"):
    return client.post("/api/registry/registrations",
                       json={"product": product, "dossier_id": dossier,
                             "din": din, "drug_type": "prescription"},
                       headers=headers or {})


def test_row_invisible_to_other_tenant_list(client):
    _create(client, headers=_A)
    # A sees its own row
    a_view = client.get("/api/registry/registrations", headers=_A).json()
    assert a_view["count"] == 1
    # B sees nothing — A's DIN/product must not leak
    b_view = client.get("/api/registry/registrations", headers=_B).json()
    assert b_view["count"] == 0


def test_get_by_id_404s_for_other_tenant(client):
    rid = _create(client, headers=_A).json()["id"]
    assert client.get(f"/api/registry/registrations/{rid}",
                      headers=_A).status_code == 200
    # never 403 — do not confirm existence
    assert client.get(f"/api/registry/registrations/{rid}",
                      headers=_B).status_code == 404


def test_right_to_sell_404s_for_other_tenant(client):
    rid = _create(client, headers=_A).json()["id"]
    r = client.get(f"/api/registry/registrations/{rid}/right-to-sell",
                   params={"as_of": "2025-09-15"}, headers=_B)
    assert r.status_code == 404


def test_set_status_404s_for_other_tenant(client):
    rid = _create(client, headers=_A).json()["id"]
    r = client.post("/api/registry/registrations/status",
                    json={"id": rid, "status": "NOC-Issued"}, headers=_B)
    assert r.status_code == 404
    # A can still mutate its own row
    ok = client.post("/api/registry/registrations/status",
                     json={"id": rid, "status": "NOC-Issued"}, headers=_A)
    assert ok.status_code == 200 and ok.json()["status"] == "NOC-Issued"


def test_no_header_stays_unscoped(client):
    _create(client, headers=_A, dossier="e1", din="02431234")
    _create(client, headers=_B, product="Atorvastatin", dossier="e2",
            din="02430000")
    # in-process mesh / existing tests: no header => see everything
    allv = client.get("/api/registry/registrations").json()
    assert allv["count"] == 2
