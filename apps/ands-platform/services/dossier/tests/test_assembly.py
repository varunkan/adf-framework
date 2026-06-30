"""REQ-107 — eCTD assembly engine + Application Viewer (Files + Outline)."""

from app import assembly


def _dossier_with_leaves():
    d = assembly.new_dossier("e123456")
    assembly.add_leaf(d, "0000", {"leaf_id": "pm", "operation": "new",
                                  "heading": "1.3.1", "title": "PM"})
    assembly.add_leaf(d, "0000", {"leaf_id": "cl", "operation": "new",
                                  "heading": "1.0", "title": "Cover"})
    return d


def test_add_leaf_resolves_placement_href_and_checksum():
    d = assembly.new_dossier("e1")
    rec = assembly.add_leaf(d, "0000", {"leaf_id": "pm", "operation": "new",
                                        "heading": "1.3.1", "title": "PM"})
    assert rec["href"].startswith("m1/ca/13-product-info/131-pm")
    assert rec["checksum"] and rec["uuid"]


def test_replace_supersedes_prior_in_current_view():
    d = _dossier_with_leaves()
    assembly.add_leaf(d, "0001", {"leaf_id": "pm2", "operation": "replace",
                                  "modified_leaf": "pm", "heading": "1.3.1",
                                  "title": "PM v2"})
    live = {lf["leaf_id"] for lf in assembly.current_view(d)["live"]}
    assert "pm2" in live and "pm" not in live   # superseded


def test_delete_removes_from_live():
    d = _dossier_with_leaves()
    assembly.add_leaf(d, "0001", {"leaf_id": "cl-del", "operation": "delete",
                                  "modified_leaf": "cl", "heading": "1.0"})
    live = {lf["leaf_id"] for lf in assembly.current_view(d)["live"]}
    assert "cl" not in live


def test_replace_without_prior_raises():
    d = assembly.new_dossier("e1")
    try:
        assembly.add_leaf(d, "0000", {"leaf_id": "x", "operation": "replace",
                                      "heading": "1.0"})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_files_view_places_leaves_under_headings():
    fv = assembly.build_files_view(_dossier_with_leaves())
    pm_node = next(n for n in fv["nodes"] if n["heading"] == "1.3.1")
    assert any(lf["leaf_id"] == "pm" for lf in pm_node["leaves"])
    assert fv["live_leaf_count"] == 2


def test_outline_view_has_backbone_and_ops():
    ov = assembly.build_outline_view(_dossier_with_leaves(), "0000")
    assert "e123456" in ov["backbone"]["index.xml"]
    assert "ca-regional" in ov["backbone"]["ca-regional.xml"]
    assert len(ov["lifecycle_operations"]) == 2


def test_viewer_api_roundtrip(client):
    client.post("/api/dossier/ectd/leaf",
                json={"dossier_id": "e1", "sequence": "0000", "leaf_id": "pm",
                      "operation": "new", "heading": "1.3.1", "title": "PM"})
    files = client.get("/api/dossier/ectd/e1/viewer/files").json()
    assert files["live_leaf_count"] == 1
    outline = client.get("/api/dossier/ectd/e1/viewer/outline/0000").json()
    assert "e1" in outline["backbone"]["index.xml"]
    # unknown dossier → 404
    assert client.get("/api/dossier/ectd/nope/viewer/files").status_code == 404


def test_add_leaf_bad_op_422(client):
    r = client.post("/api/dossier/ectd/leaf",
                    json={"dossier_id": "e1", "leaf_id": "x",
                          "operation": "zap", "heading": "1.0"})
    assert r.status_code == 422
