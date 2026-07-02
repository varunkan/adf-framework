"""Cross-tenant isolation for the transmission ledger.

The writes (configure/submit/ack) take dossier_id in the BODY, so the web
proxy's path/query ownership check misses them — a tenant could otherwise
submit against, ack, or read another tenant's ledger. This applies the same
X-Tenant-Id contract the dossier service uses: present => scoped (foreign /
unowned ledgers 404); absent => unscoped (in-process mesh / existing tests).
"""

import pytest

from ands_shared import ProblemError

H_A = {"X-Tenant-Id": "tenant-a"}
H_B = {"X-Tenant-Id": "tenant-b"}


def _submit(client, dossier_id, headers=None):
    return client.post("/api/transmission/submit",
                       json={"dossier_id": dossier_id, "sequence": "0000",
                             "size_gb": 1}, headers=headers or {})


# -- get / ledger read ------------------------------------------------------

def test_ledger_get_isolated_by_tenant(ctx):
    # tenant A opens a ledger for dossier "da"
    assert _submit(ctx.client, "da", H_A).status_code == 201
    # A sees it
    assert ctx.client.get("/api/transmission/ledger/da",
                          headers=H_A).status_code == 200
    # B cannot — 404, never 403 (don't confirm existence)
    r = ctx.client.get("/api/transmission/ledger/da", headers=H_B)
    assert r.status_code == 404
    # no header => unscoped (mesh / tests) still reads it
    assert ctx.client.get("/api/transmission/ledger/da").status_code == 200


def test_submit_against_foreign_ledger_404s(ctx):
    _submit(ctx.client, "da", H_A)          # owned by A
    # B cannot submit a follow-on sequence against A's ledger
    r = ctx.client.post("/api/transmission/submit",
                        json={"dossier_id": "da", "sequence": "0001",
                              "size_gb": 1}, headers=H_B)
    assert r.status_code == 404


def test_ack_against_foreign_ledger_404s(ctx):
    _submit(ctx.client, "da", H_A)
    r = ctx.client.post("/api/transmission/ack",
                        json={"dossier_id": "da", "kind": "fda",
                              "sequence": "0000", "core_id": "C1"},
                        headers=H_B)
    assert r.status_code == 404
    # A (the owner) can ack
    ok = ctx.client.post("/api/transmission/ack",
                         json={"dossier_id": "da", "kind": "fda",
                               "sequence": "0000", "core_id": "C1"},
                         headers=H_A)
    assert ok.status_code == 200


def test_configure_records_owning_tenant(ctx):
    # A configures; B may not then read the config
    ctx.client.post("/api/transmission/configure",
                    json={"dossier_id": "dc", "account_type": "WebTrader",
                          "x509_certificate": "PEM", "recipient_center": "HC"},
                    headers=H_A)
    assert ctx.client.get("/api/transmission/ledger/dc",
                          headers=H_B).status_code == 404
    assert ctx.client.get("/api/transmission/ledger/dc",
                          headers=H_A).status_code == 200


def test_no_header_stays_unscoped(ctx):
    # existing mesh/test behaviour: no X-Tenant-Id => full access
    _submit(ctx.client, "dn")
    assert ctx.client.get("/api/transmission/ledger/dn").status_code == 200
    # and an owned ledger is readable via the header-less mesh path too
    _submit(ctx.client, "da", H_A)
    assert ctx.client.get("/api/transmission/ledger/da").status_code == 200


def test_service_get_guard_raises_404_for_foreign(ctx):
    ctx.service.submit({"dossier_id": "da", "sequence": "0000", "size_gb": 1},
                       tenant_id="tenant-a")
    with pytest.raises(ProblemError):
        ctx.service.get("da", tenant_id="tenant-b")
    # owner + unscoped both succeed
    assert ctx.service.get("da", tenant_id="tenant-a")["dossier_id"] == "da"
    assert ctx.service.get("da")["dossier_id"] == "da"
