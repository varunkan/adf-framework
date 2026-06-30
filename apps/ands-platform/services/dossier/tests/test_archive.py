"""REQ-110 — submission archive / regulatory binder + read-only share links."""

from app import archive, assembly


def _seed(client, dossier="e1"):
    client.post("/api/dossier/ectd/leaf",
                json={"dossier_id": dossier, "sequence": "0000",
                      "leaf_id": "pm", "operation": "new", "heading": "1.3.1",
                      "title": "PM"})


def test_build_binder_aggregates_views():
    d = assembly.new_dossier("e1")
    assembly.add_leaf(d, "0000", {"leaf_id": "pm", "operation": "new",
                                  "heading": "1.3.1", "title": "PM"})
    binder = archive.build_binder(d, sequence="0000",
                                  validation_report={"error_count": 0},
                                  transmission={"state": "RECEIVED_BY_HC"})
    assert binder["layout"] == "regulatory-binder"
    assert binder["files_view"]["live_leaf_count"] == 1
    assert "index.xml" in binder["outline"]["backbone"]
    assert binder["validation_report"]["error_count"] == 0
    assert binder["transmission"]["state"] == "RECEIVED_BY_HC"


def test_create_list_and_get_binder(client):
    _seed(client)
    created = client.post("/api/dossier/archive",
                          json={"dossier_id": "e1", "sequence": "0000"})
    assert created.status_code == 201
    bid = created.json()["id"]
    listing = client.get("/api/dossier/archive",
                         params={"dossier_id": "e1"}).json()
    assert listing["count"] == 1
    got = client.get(f"/api/dossier/archive/{bid}").json()
    assert got["binder"]["dossier_id"] == "e1"


def test_share_link_read_only_access(client):
    _seed(client)
    bid = client.post("/api/dossier/archive",
                      json={"dossier_id": "e1"}).json()["id"]
    share = client.post(f"/api/dossier/archive/{bid}/share").json()
    token = share["share_token"]
    shared = client.get(f"/api/dossier/archive/share/{token}")
    assert shared.status_code == 200
    body = shared.json()
    assert body["read_only"] is True and body["dossier_id"] == "e1"


def test_create_binder_unknown_dossier_404(client):
    r = client.post("/api/dossier/archive", json={"dossier_id": "nope"})
    assert r.status_code == 404


def test_unknown_share_token_404(client):
    assert client.get("/api/dossier/archive/share/deadbeef").status_code == 404
