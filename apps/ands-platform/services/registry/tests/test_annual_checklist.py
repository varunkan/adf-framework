"""Server-tracked annual notification checklist.

Round-4: per-item sign-offs (who + when) on the registry service.
Round-9 (qa_manager BLOCKER): a tick is a CONTROLLED e-signature — credential
re-authentication at the moment of signing, a meaning-of-signature attestation
captured with the tick, and a viewable signing record. "A name + UTC stamp …
is just decoration."
"""

from app import registry

TENANT = {"X-Tenant-Id": "t-acme"}
SIGNER = {**TENANT, "X-User-Email": "ra@acme.example"}
# conftest wires a fake reauth port: password "signer-pass-1" for any email
SIGN = {"email": "ra@acme.example", "password": "signer-pass-1",
        "meaning": "I attest this obligation is completed for the year."}


def test_checklist_starts_undone_with_all_canonical_items(client):
    r = client.get("/api/registry/annual-checklist", headers=TENANT)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(registry.ANNUAL_CHECKLIST_ITEMS) == 4
    assert [i["item_key"] for i in body["items"]] == \
        list(registry.ANNUAL_CHECKLIST_KEYS)
    for item in body["items"]:
        assert item["done"] is False
        assert item["signed_by"] is None and item["signed_at"] is None
    assert body["year"] >= 2026  # defaults to the current year


def test_sign_requires_reauth_and_meaning(client):
    # no password → refused, nothing recorded
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "adn_filed", "done": True,
                          "email": "ra@acme.example",
                          "meaning": "I attest."},
                    headers=SIGNER)
    assert r.status_code == 401
    # wrong password → refused
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "adn_filed", "done": True, **SIGN,
                          "password": "wrong-pass-9"},
                    headers=SIGNER)
    assert r.status_code == 401
    # no meaning → refused (the attestation is part of the signature)
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "adn_filed", "done": True,
                          "email": "ra@acme.example",
                          "password": "signer-pass-1"},
                    headers=SIGNER)
    assert r.status_code == 422
    listed = client.get("/api/registry/annual-checklist",
                        headers=TENANT).json()
    assert all(not i["done"] for i in listed["items"])


def test_controlled_signature_records_who_when_meaning(client):
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "adn_filed", "done": True, **SIGN},
                    headers=SIGNER)
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["done"] is True
    # signed_by is the RE-AUTHENTICATED identity, not a spoofable header
    assert item["signed_by"] == "ra@acme.example"
    assert item["signed_at"]
    assert item["meaning"] == SIGN["meaning"]
    assert item["reauthenticated"] is True


def test_untick_clears_the_sign_off(client):
    client.post("/api/registry/annual-checklist/items",
                json={"item_key": "rts_fee", "done": True, **SIGN},
                headers=SIGNER)
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "rts_fee", "done": False},
                    headers=SIGNER)
    item = r.json()["item"]
    assert item["done"] is False
    assert item["signed_by"] is None and item["signed_at"] is None


def test_signing_log_is_viewable_and_append_only(client):
    client.post("/api/registry/annual-checklist/items",
                json={"item_key": "din_status", "done": True, **SIGN},
                headers=SIGNER)
    client.post("/api/registry/annual-checklist/items",
                json={"item_key": "din_status", "done": False},
                headers=SIGNER)
    log = client.get("/api/registry/annual-checklist/signing-log",
                     headers=TENANT).json()
    acts = [(e["action"], e["item_key"]) for e in log["entries"]]
    assert ("sign", "din_status") in acts and ("unsign", "din_status") in acts
    signed = next(e for e in log["entries"] if e["action"] == "sign")
    assert signed["signed_by"] == "ra@acme.example"
    assert signed["meaning"] == SIGN["meaning"]
    assert signed["reauthenticated"] is True
    assert signed["signed_at"]


def test_checklist_is_per_tenant_and_per_year(client):
    client.post("/api/registry/annual-checklist/items",
                json={"item_key": "din_status", "done": True, "year": 2026,
                      **SIGN},
                headers=SIGNER)
    other = client.get("/api/registry/annual-checklist?year=2026",
                       headers={"X-Tenant-Id": "t-other"}).json()
    assert all(not i["done"] for i in other["items"])
    y2027 = client.get("/api/registry/annual-checklist?year=2027",
                       headers=TENANT).json()
    assert y2027["year"] == 2027
    assert all(not i["done"] for i in y2027["items"])


def test_unknown_item_rejected(client):
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "not_a_thing", "done": True, **SIGN},
                    headers=SIGNER)
    assert r.status_code == 422


def test_sign_off_hits_the_event_stream(ctx):
    ctx.client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "discontinuation", "done": True, **SIGN},
                    headers=SIGNER)
    ev = next(e for e in ctx.bus.published
              if e.type == "registry.annual_checklist_signed")
    assert ev.data["signed_by"] == "ra@acme.example"
    assert ev.data["reauthenticated"] is True
    assert ev.tenant_id == "t-acme"
