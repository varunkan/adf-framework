"""REQ-107 — eCTD assembly engine + Application Viewer (Files + Outline)."""

import xml.etree.ElementTree as ET

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


# ---------------------------------------------------------------------------
# Transmissible ICH eCTD 3.2.2 sequence backbone (build_sequence_backbone)
# ---------------------------------------------------------------------------

ECTD = "{http://www.ich.org/ectd}"
XLINK = "{http://www.w3c.org/1999/xlink}"
CA = "{http://www.hc-sc.gc.ca/dhpd/ectd/ca}"


def _replace_in_0001():
    d = _dossier_with_leaves()
    assembly.add_leaf(d, "0001", {"leaf_id": "cl2", "operation": "replace",
                                  "modified_leaf": "cl", "heading": "1.0",
                                  "title": "Cover v2"})
    return d


def test_sequence_backbone_0000_is_full_new_leaf_set():
    bb = assembly.build_sequence_backbone(_dossier_with_leaves(), "0000")
    root = ET.fromstring(bb["index_xml"])
    assert root.tag == f"{ECTD}ectd"
    assert root.get("xmlns:ectd") is None  # namespace is a real ns, not an attr
    leaves = list(root)
    assert len(leaves) == 2
    assert all(lf.tag == "leaf" for lf in leaves)
    assert all(lf.get("operation") == "new" for lf in leaves)
    # every new leaf carries an md5 checksum + checksum-type + an xlink href
    for lf in leaves:
        assert lf.get("checksum-type") == "md5" and lf.get("checksum")
        assert lf.get(f"{XLINK}href")
        # a 'new' leaf has NO modified-file back-pointer
        assert lf.find("modified-file") is None


def test_sequence_backbone_has_doctype_and_util_dtds():
    bb = assembly.build_sequence_backbone(_dossier_with_leaves(), "0000")
    assert '<!DOCTYPE ectd:ectd SYSTEM "util/dtd/ich-ectd-3-2.dtd">' \
        in bb["index_xml"]
    assert "util/dtd/ich-ectd-3-2.dtd" in bb["util_files"]
    assert "util/dtd/ca-regional.dtd" in bb["util_files"]
    assert "<!ELEMENT" in bb["util_files"]["util/dtd/ich-ectd-3-2.dtd"]


def test_sequence_backbone_0001_lists_only_replaced_leaf_with_backpointer():
    d = _replace_in_0001()
    bb = assembly.build_sequence_backbone(d, "0001")
    root = ET.fromstring(bb["index_xml"])
    leaves = list(root)
    assert len(leaves) == 1                       # ONLY 0001's own leaf
    lf = leaves[0]
    assert lf.get("ID") == "cl2"
    assert lf.get("operation") == "replace"
    mod = lf.find("modified-file")
    assert mod is not None
    # modified-file points back at the prior leaf's relative path in ../0000/
    assert mod.get(f"{XLINK}href") == "../0000/m1/ca/10-cover-letter/cl.pdf"


def test_sequence_backbone_ca_regional_has_company_and_product():
    bb = assembly.build_sequence_backbone(_dossier_with_leaves(), "0000")
    ca = ET.fromstring(bb["ca_regional_xml"])
    assert ca.tag == f"{CA}ectd-ca"
    assert ca.get("dtd-version") == "2.2"
    info = ca.find("application-info")
    assert info.find("dossier-id").text == "e123456"
    assert info.find("company-id").text                    # non-empty company
    products = [p.text for p in ca.findall("product")]
    assert "PM" in products                                # 1.3.1 monograph name


def test_sequence_backbone_ca_regional_extra_overrides():
    bb = assembly.build_sequence_backbone(
        _dossier_with_leaves(), "0000",
        extra={"company_id": "12345", "product_names": ["Drugazole 10 mg"]})
    ca = ET.fromstring(bb["ca_regional_xml"])
    assert ca.find("application-info/company-id").text == "12345"
    assert [p.text for p in ca.findall("product")] == ["Drugazole 10 mg"]


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
