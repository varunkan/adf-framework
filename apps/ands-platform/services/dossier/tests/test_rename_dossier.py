"""Placeholder Dossier-ID lifecycle: start without an HC ID, rename to the
real one later, and validation blocks filing while the placeholder remains
(usability-panel fix F1)."""


def _create(client, did="d431509", title="Placeholderol 10 mg tablet"):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title})
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_placeholder_id_blocks_validation(client):
    _create(client)
    v = client.get("/api/dossier/dossiers/d431509/validate").json()
    assert v["passed"] is False
    rules = [e["rule"] for e in v["errors"]]
    assert "placeholder_dossier_id" in rules
    first = v["errors"][0]
    assert first["rule_id"] == "CA-REP-0001"
    assert "REP" in first["message"]


def test_rename_rekeys_everything(client):
    _create(client)
    # author a section so there is real content + model state to migrate
    g = client.post("/api/dossier/ectd/d431509/section/1.2.1/generate", json={})
    assert g.status_code == 200, g.text

    r = client.post("/api/dossier/dossiers/d431509/rename",
                    json={"new_id": "e765001"})
    assert r.status_code == 200, r.text
    assert r.json() == {"renamed": "d431509", "dossier_id": "e765001"}

    # the catalog lists only the new id (deep-link GETs intentionally
    # self-heal missing indexes, so the old URL still resolves to an
    # empty shell — the catalog is the source of truth)
    listed = [d["dossier_id"] for d in
              client.get("/api/dossier/dossiers").json()["dossiers"]]
    assert "e765001" in listed and "d431509" not in listed
    full = client.get("/api/dossier/dossiers/e765001")
    assert full.status_code == 200
    content = client.get("/api/dossier/dossiers/e765001/content").json()
    assert content["dossier_id"] == "e765001"

    # the authored section survived the rename
    def flat(x, acc):
        if isinstance(x, dict):
            if x.get("status") == "complete":
                acc.append(x.get("section"))
            for v in x.values():
                flat(v, acc)
        elif isinstance(x, list):
            for v in x:
                flat(v, acc)
        return acc
    assert "1.2.1" in flat(content["modules"], [])

    # eCTD model paths were rewritten — no stale placeholder id anywhere
    outline = client.get("/api/dossier/ectd/e765001/viewer/outline/0000")
    assert outline.status_code == 200
    assert "d431509" not in outline.text

    # validation no longer carries the placeholder error
    v = client.get("/api/dossier/dossiers/e765001/validate").json()
    assert "placeholder_dossier_id" not in [e["rule"] for e in v["errors"]]


def test_rename_guards(client):
    _create(client)
    _create(client, did="e999888", title="Occupied")
    bad = client.post("/api/dossier/dossiers/d431509/rename",
                      json={"new_id": "BAD-FORMAT"})
    assert bad.status_code == 422
    taken = client.post("/api/dossier/dossiers/d431509/rename",
                        json={"new_id": "e999888"})
    assert taken.status_code == 409
    same = client.post("/api/dossier/dossiers/d431509/rename",
                       json={"new_id": "d431509"})
    assert same.status_code == 422
    missing = client.post("/api/dossier/dossiers/d000000/rename",
                          json={"new_id": "e111222"})
    assert missing.status_code == 404
