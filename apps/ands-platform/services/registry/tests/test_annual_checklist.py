"""Server-tracked annual notification checklist (round-4 panel fix).

The unanimous panel theme: a browser-local checklist is worthless to an MAH —
obligations need per-item sign-offs (who + when) that survive any browser and
are visible to the whole workspace.
"""

from app import registry

TENANT = {"X-Tenant-Id": "t-acme"}
SIGNER = {**TENANT, "X-User-Email": "ra@acme.example"}


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


def test_tick_records_who_and_when(client):
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "adn_filed", "done": True},
                    headers=SIGNER)
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["done"] is True
    assert item["signed_by"] == "ra@acme.example"
    assert item["signed_at"]  # ISO timestamp set server-side

    listed = client.get("/api/registry/annual-checklist",
                        headers=TENANT).json()
    adn = next(i for i in listed["items"] if i["item_key"] == "adn_filed")
    assert adn["done"] and adn["signed_by"] == "ra@acme.example"


def test_untick_clears_the_sign_off(client):
    client.post("/api/registry/annual-checklist/items",
                json={"item_key": "rts_fee", "done": True}, headers=SIGNER)
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "rts_fee", "done": False},
                    headers=SIGNER)
    item = r.json()["item"]
    assert item["done"] is False
    assert item["signed_by"] is None and item["signed_at"] is None


def test_checklist_is_per_tenant_and_per_year(client):
    client.post("/api/registry/annual-checklist/items",
                json={"item_key": "din_status", "done": True, "year": 2026},
                headers=SIGNER)
    # another workspace sees nothing
    other = client.get("/api/registry/annual-checklist?year=2026",
                       headers={"X-Tenant-Id": "t-other"}).json()
    assert all(not i["done"] for i in other["items"])
    # another year sees nothing
    y2027 = client.get("/api/registry/annual-checklist?year=2027",
                       headers=TENANT).json()
    assert y2027["year"] == 2027
    assert all(not i["done"] for i in y2027["items"])


def test_unknown_item_rejected(client):
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "not_a_thing", "done": True},
                    headers=SIGNER)
    assert r.status_code == 422


def test_sign_off_hits_the_event_stream(ctx):
    ctx.client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "discontinuation", "done": True},
                    headers=SIGNER)
    kinds = [e.type for e in ctx.bus.published]
    assert "registry.annual_checklist_signed" in kinds
    ev = next(e for e in ctx.bus.published
              if e.type == "registry.annual_checklist_signed")
    assert ev.data["signed_by"] == "ra@acme.example"
    assert ev.tenant_id == "t-acme"


def test_tick_without_user_header_still_records_a_signer(client):
    r = client.post("/api/registry/annual-checklist/items",
                    json={"item_key": "din_status", "done": True},
                    headers=TENANT)
    assert r.json()["item"]["signed_by"] == "unrecorded"
