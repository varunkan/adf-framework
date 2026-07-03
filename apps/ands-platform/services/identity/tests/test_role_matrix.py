"""WS4.2 — role permission matrix, sourced from rbac.capabilities_for so the
UI can never drift from what authorize() actually enforces."""

from app import rbac

from tests.conftest import auth, owner_token


def test_role_matrix_is_sourced_from_rbac(ctx):
    client = ctx.client
    tok = owner_token(ctx)
    r = client.get("/api/identity/rbac/matrix", headers=auth(tok))
    assert r.status_code == 200
    matrix = r.json()["roles"]
    by_id = {row["role"]: row for row in matrix}
    assert set(by_id) == set(rbac.ROLES)
    # owner is the platform-wide wildcard
    assert by_id[rbac.OWNER_ROLE]["capabilities"] == ["*"]
    # user + tenant-admin cap lists match rbac exactly (can't drift)
    assert set(by_id[rbac.USER_ROLE]["capabilities"]) == \
        rbac.capabilities_for(rbac.USER_ROLE)
    assert set(by_id[rbac.TENANT_ADMIN_ROLE]["capabilities"]) == \
        rbac.capabilities_for(rbac.TENANT_ADMIN_ROLE)
    # each row states who can assign that role
    for row in matrix:
        assert row["assignable_by"]


def test_role_matrix_requires_auth(client):
    assert client.get("/api/identity/rbac/matrix").status_code == 401
