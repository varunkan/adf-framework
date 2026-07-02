"""F2 / SAAS-REQ-002 — subscription billing access gating."""

from app import billing

from tests.conftest import auth, owner_token


def test_active_allows_everything():
    a = billing.effective_access("active")
    assert a["state"] == "ok"
    assert billing.is_allowed(a, "transmit")


def test_past_due_in_grace_then_blocked():
    grace = billing.effective_access("past_due", "2026-12-31", as_of="2026-06-30")
    assert grace["state"] == "grace" and billing.is_allowed(grace, "transmit")
    over = billing.effective_access("past_due", "2026-06-01", as_of="2026-06-30")
    assert over["state"] == "blocked" and not billing.is_allowed(over, "transmit")
    assert billing.is_allowed(over, "export")   # read/export still allowed


def test_canceled_is_read_export_only():
    a = billing.effective_access("canceled")
    assert a["state"] == "blocked"
    assert billing.is_allowed(a, "export") and not billing.is_allowed(a, "new_sequence")


def test_owner_sets_billing_and_tenant_reads_it(ctx):
    tok = owner_token(ctx)
    tenant = ctx.client.post("/api/identity/owner/tenants",
                             json={"name": "T", "admin_email": "t@t.io",
                                   "admin_password": "pw12345-2026"},
                             headers=auth(tok)).json()["tenant"]
    # owner moves the tenant to canceled
    r = ctx.client.post("/api/identity/owner/billing",
                        json={"tenant_id": tenant["id"],
                              "billing_status": "canceled"}, headers=auth(tok))
    assert r.status_code == 200
    access = ctx.client.get("/api/identity/billing",
                            params={"tenant_id": tenant["id"]},
                            headers=auth(tok)).json()
    assert access["state"] == "blocked" and "transmit" in access["blocked"]


def test_set_billing_invalid_status_422(ctx):
    tok = owner_token(ctx)
    tenant = ctx.client.post("/api/identity/owner/tenants",
                             json={"name": "T", "admin_email": "t@t.io",
                                   "admin_password": "pw12345-2026"},
                             headers=auth(tok)).json()["tenant"]
    r = ctx.client.post("/api/identity/owner/billing",
                        json={"tenant_id": tenant["id"],
                              "billing_status": "freemium"}, headers=auth(tok))
    assert r.status_code == 422
