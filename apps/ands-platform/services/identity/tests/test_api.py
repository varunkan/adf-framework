"""End-to-end identity API via FastAPI TestClient."""

from ands_shared import EventType

from tests.conftest import auth, owner_token


# -- self-serve auth ---------------------------------------------------------
def test_signup_creates_tenant_admin_and_session(client):
    r = client.post("/api/identity/auth/signup",
                    json={"email": "ra@acme.io", "password": "pw12345",
                          "company_name": "Acme Generics"})
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["role"] == "tenant-admin"
    assert body["tenant"]["status"] == "trial"
    assert body["token"]
    me = client.get("/api/identity/auth/me", headers=auth(body["token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "ra@acme.io"


def test_signup_publishes_tenant_provisioned(ctx):
    ctx.service.signup({"email": "ra@acme.io", "password": "pw12345",
                        "company_name": "Acme"})
    assert len(ctx.bus.events_of(EventType.TENANT_PROVISIONED)) == 1


def test_login_wrong_password_401(client):
    client.post("/api/identity/auth/signup",
                json={"email": "ra@acme.io", "password": "pw12345",
                      "company_name": "Acme"})
    tid = client.post("/api/identity/auth/signup",
                      json={"email": "x@b.io", "password": "pw12345",
                            "company_name": "B"}).json()["tenant"]["id"]
    r = client.post("/api/identity/auth/login",
                    json={"email": "x@b.io", "password": "nope",
                          "tenant_id": tid})
    assert r.status_code == 401


def test_me_without_token_401(client):
    assert client.get("/api/identity/auth/me").status_code == 401


def test_logout_invalidates_session(client):
    token = client.post("/api/identity/auth/signup",
                        json={"email": "ra@acme.io", "password": "pw12345",
                              "company_name": "Acme"}).json()["token"]
    client.post("/api/identity/auth/logout", headers=auth(token))
    assert client.get("/api/identity/auth/me",
                      headers=auth(token)).status_code == 401


# -- entitlements ------------------------------------------------------------
def test_new_tenant_has_all_features(client):
    body = client.post("/api/identity/auth/signup",
                       json={"email": "ra@acme.io", "password": "pw12345",
                             "company_name": "Acme"}).json()
    ent = client.get("/api/identity/entitlements",
                     params={"tenant_id": body["tenant"]["id"]},
                     headers=auth(body["token"])).json()
    assert ent["effective"]["transmission"]["enabled"] is True
    assert "dashboard" in ent["features"]


def test_entitlements_cross_tenant_denied(client):
    a = client.post("/api/identity/auth/signup",
                    json={"email": "a@a.io", "password": "pw12345",
                          "company_name": "A"}).json()
    b = client.post("/api/identity/auth/signup",
                    json={"email": "b@b.io", "password": "pw12345",
                          "company_name": "B"}).json()
    r = client.get("/api/identity/entitlements",
                   params={"tenant_id": a["tenant"]["id"]},
                   headers=auth(b["token"]))
    assert r.status_code == 403


# -- owner control plane -----------------------------------------------------
def test_owner_provisions_tenant_and_lists(ctx):
    tok = owner_token(ctx)
    r = ctx.client.post("/api/identity/owner/tenants",
                        json={"name": "BigPharma",
                              "admin_email": "admin@big.io",
                              "admin_password": "pw12345"},
                        headers=auth(tok))
    assert r.status_code == 201
    tenants = ctx.client.get("/api/identity/owner/tenants",
                             headers=auth(tok)).json()["tenants"]
    assert any(t["name"] == "BigPharma" for t in tenants)


def test_owner_endpoints_forbidden_without_owner(client):
    # a tenant-admin token must not reach the owner console
    tok = client.post("/api/identity/auth/signup",
                      json={"email": "ra@acme.io", "password": "pw12345",
                            "company_name": "Acme"}).json()["token"]
    r = client.get("/api/identity/owner/tenants", headers=auth(tok))
    assert r.status_code == 403


def test_owner_creates_plan_assigns_and_overrides(ctx):
    tok = owner_token(ctx)
    # a restricted plan with only a couple features
    plan = ctx.client.post("/api/identity/owner/plans",
                           json={"name": "Starter",
                                 "features": ["dashboard", "dossiers"]},
                           headers=auth(tok)).json()
    assert plan["id"] == "starter"
    tenant = ctx.client.post("/api/identity/owner/tenants",
                             json={"name": "T", "admin_email": "t@t.io",
                                   "admin_password": "pw12345"},
                             headers=auth(tok)).json()["tenant"]
    ctx.client.post("/api/identity/owner/tenants/assign-plan",
                    json={"tenant_id": tenant["id"], "plan_id": "starter"},
                    headers=auth(tok))
    ent = ctx.service.entitlements(tenant["id"])
    assert ent["effective"]["transmission"]["enabled"] is False
    assert ent["effective"]["dashboard"]["enabled"] is True
    # override re-enables one feature
    ctx.client.post("/api/identity/owner/overrides",
                    json={"tenant_id": tenant["id"], "feature": "transmission",
                          "enabled": True}, headers=auth(tok))
    ent = ctx.service.entitlements(tenant["id"])
    assert ent["effective"]["transmission"] == {"enabled": True,
                                                "source": "override"}


# -- authorize ---------------------------------------------------------------
def test_authorize_endpoint(client):
    r = client.post("/api/identity/authorize",
                    json={"principal": {"role": "user", "tenant_id": "t1"},
                          "capability": "dossier.read",
                          "resource": {"tenant_id": "t1"}})
    assert r.json()["allowed"] is True
    r = client.post("/api/identity/authorize",
                    json={"principal": {"role": "user", "tenant_id": "t1"},
                          "capability": "transmit",
                          "resource": {"tenant_id": "t1"}})
    assert r.json()["allowed"] is False
