"""Tenant partitioning — a tenant may neither list nor mutate another
tenant's NOA / shortage / DEL / correspondence rows (CRO isolation guarantee).

The web proxy injects X-Tenant-Id on every authenticated request; the write
paths carry dossier_id / noa_id in the body/path the proxy cannot guard, so
the service enforces ownership here. Absent the header the mesh stays UNSCOPED.
"""

A = {"X-Tenant-Id": "tenant-A"}
B = {"X-Tenant-Id": "tenant-B"}


def _noa(client, headers, **over):
    body = {"dossier_id": "dA", "patent_number": "CA2500000",
            "allegation": "not_infringed", "form_v_date": "2025-02-01"}
    body.update(over)
    return client.post("/api/lifecycle/noa", json=body, headers=headers)


def _shortage(client, headers, **over):
    body = {"dossier_id": "dA", "din": "02531234", "kind": "shortage",
            "tier": 3, "reason": "API supply interruption",
            "anticipated_start": "2026-02-01", "became_aware": "2026-01-01",
            "reported_at": "2026-01-04"}
    body.update(over)
    return client.post("/api/lifecycle/shortage", json=body, headers=headers)


# -- NOA: cross-tenant list is invisible, mutate is 404 -----------------------
def test_tenant_b_cannot_see_or_mutate_tenant_a_noa(client):
    nid = _noa(client, A).json()["id"]

    # A sees its own allegation; B sees nothing for the same dossier_id
    a_list = client.get("/api/lifecycle/noa",
                        params={"dossier_id": "dA"}, headers=A).json()
    assert a_list["count"] == 1
    b_list = client.get("/api/lifecycle/noa",
                        params={"dossier_id": "dA"}, headers=B).json()
    assert b_list["count"] == 0

    # B guessing A's noa_id gets 404 (never 403) on serve AND action
    served_b = client.post(f"/api/lifecycle/noa/{nid}/serve",
                           json={"served_date": "2025-03-01"}, headers=B)
    assert served_b.status_code == 404
    action_b = client.post(f"/api/lifecycle/noa/{nid}/action",
                           json={"action_date": "2025-04-01"}, headers=B)
    assert action_b.status_code == 404

    # A still succeeds on its own NOA
    served_a = client.post(f"/api/lifecycle/noa/{nid}/serve",
                           json={"served_date": "2025-03-01"}, headers=A)
    assert served_a.status_code == 200
    assert served_a.json()["action_window_end"] == "2025-04-15"


# -- shortage + DEL + correspondence lists are tenant-scoped ------------------
def test_tenant_b_cannot_see_tenant_a_shortage_del_correspondence(client):
    _shortage(client, A)
    client.post("/api/lifecycle/del",
                json={"dossier_id": "dA", "del_number": "DEL-1", "sites": []},
                headers=A)
    client.post("/api/lifecycle/correspondence",
                json={"kind": "NOD", "dossier_id": "dA", "subject": "x"},
                headers=A)

    for path in ("shortage", "del", "correspondence"):
        b = client.get(f"/api/lifecycle/{path}",
                       params={"dossier_id": "dA"}, headers=B).json()
        assert b["count"] == 0, f"tenant B saw A's {path}"
        a = client.get(f"/api/lifecycle/{path}",
                       params={"dossier_id": "dA"}, headers=A).json()
        assert a["count"] == 1, f"tenant A lost its own {path}"


# -- no header stays unscoped (in-process mesh / existing tests) --------------
def test_no_header_is_unscoped(client):
    _noa(client, A)              # created under tenant A
    _shortage(client, {})       # created with no tenant
    # an unauthenticated (no-header) list sees everything for the dossier
    noa_all = client.get("/api/lifecycle/noa",
                         params={"dossier_id": "dA"}).json()
    assert noa_all["count"] == 1
    sh_all = client.get("/api/lifecycle/shortage",
                        params={"dossier_id": "dA"}).json()
    assert sh_all["count"] == 1


# -- foreign / unowned NOA is invisible to a scoped list ----------------------
def test_scoped_list_hides_unowned_rows(client):
    _noa(client, {})            # created with NO tenant (unowned)
    scoped = client.get("/api/lifecycle/noa",
                        params={"dossier_id": "dA"}, headers=A).json()
    assert scoped["count"] == 0   # unowned row invisible to tenant A


# -- response shape stays identical (no tenant_id leaked) ---------------------
def test_response_shape_has_no_tenant_id(client):
    corr = client.post(
        "/api/lifecycle/correspondence",
        json={"kind": "NOD", "dossier_id": "dA", "subject": "x"},
        headers=A).json()
    assert "tenant_id" not in corr
    listed = client.get("/api/lifecycle/correspondence",
                        params={"dossier_id": "dA"}, headers=A).json()
    assert "tenant_id" not in listed["correspondence"][0]
