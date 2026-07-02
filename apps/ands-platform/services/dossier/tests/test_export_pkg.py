"""eCTD sequence export — the transmissible zip package."""

import io
import xml.etree.ElementTree as ET
import zipfile

from app import assembly, ectd_validation, export_pkg


def _build(client, did="e123456"):
    client.post("/api/dossier/dossiers",
                json={"dossier_id": did, "title": "Drugazole 10 mg"})
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate", json={})
    pdf = b"%PDF-1.4 uploaded bytes"
    client.post(f"/api/dossier/ectd/{did}/section/3.2.S.1/upload",
                files={"file": ("ds.pdf", pdf, "application/pdf")})
    return did, pdf


def test_export_zip_structure_and_bytes(client):
    did, pdf = _build(client)
    r = client.get(f"/api/dossier/ectd/{did}/export/0000")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    root = f"{did}/0000"
    assert f"{root}/index.xml" in names
    assert f"{root}/index-md5.txt" in names
    assert f"{root}/rt.xml" in names                    # REP RT XML inside
    assert f"{root}/m1/ca/ca-regional.xml" in names
    # the uploaded leaf rides at its real href with verbatim bytes
    leaf_paths = [n for n in names if "/m3/" in n or "32s1" in n.replace("-", "")]
    assert any(z.read(n) == pdf for n in names if n.endswith(".pdf")
               and "m1" not in n)
    # index-md5 matches index.xml
    idx = z.read(f"{root}/index.xml")
    assert z.read(f"{root}/index-md5.txt").decode().strip() == \
        assembly.md5_hex(idx)
    # RT XML names the dossier + sequence
    rt = z.read(f"{root}/rt.xml").decode()
    assert did in rt and "0000" in rt
    assert r.headers["X-Export-Missing"] == "0"


def test_export_bilingual_leaves_resolve(client):
    did = "e123456"
    client.post("/api/dossier/dossiers",
                json={"dossier_id": did, "title": "Drugazole"})
    for lang in ("en", "fr"):
        client.post(f"/api/dossier/ectd/{did}/section/1.3.1/upload",
                    files={"file": (f"pm-{lang}.pdf", b"%PDF-1.4 " + lang.encode(),
                                    "application/pdf")},
                    data={"lang": lang})
    r = client.get(f"/api/dossier/ectd/{did}/export/0000")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    pm = [n for n in z.namelist() if "product-monograph" in n]
    assert len(pm) == 2 and r.headers["X-Export-Missing"] == "0"


# ---------------------------------------------------------------------------
# Genuine ICH eCTD 3.2.2 / CA M1 v2.2 backbone via the pure builder
# ---------------------------------------------------------------------------

ECTD = "{http://www.ich.org/ectd}"
XLINK = "{http://www.w3c.org/1999/xlink}"


def _model_0000():
    d = assembly.new_dossier("e123456")
    assembly.add_leaf(d, "0000", {"leaf_id": "pm", "operation": "new",
                                  "heading": "1.3.1", "title": "Drugazole PM"})
    assembly.add_leaf(d, "0000", {"leaf_id": "cl", "operation": "new",
                                  "heading": "1.0", "title": "Cover"})
    return d


def _pkg(model, seq):
    return export_pkg.build_package(
        model, seq, lambda lid: b"%PDF-1.7 body", b"<rt/>")


def test_build_package_return_shape_preserved():
    pkg = _pkg(_model_0000(), "0000")
    assert set(pkg) == {"filename", "content_type", "body", "files", "missing"}
    assert pkg["content_type"] == "application/zip"
    assert pkg["filename"] == "e123456-seq-0000-ectd.zip"
    assert pkg["missing"] == []                    # every leaf's bytes resolved


def test_0000_export_is_full_new_leaf_set():
    pkg = _pkg(_model_0000(), "0000")
    z = zipfile.ZipFile(io.BytesIO(pkg["body"]))
    root = "e123456/0000"
    # util DTDs are shipped so both DOCTYPEs resolve inside the sequence
    assert f"{root}/util/dtd/ich-ectd-3-2.dtd" in z.namelist()
    assert f"{root}/util/dtd/ca-regional.dtd" in z.namelist()
    index = ET.fromstring(z.read(f"{root}/index.xml"))
    leaves = list(index)
    assert len(leaves) == 2 and all(l.get("operation") == "new" for l in leaves)
    # zero dangling: every referenced href is a real file in the zip
    names = set(z.namelist())
    for lf in leaves:
        href = lf.get(f"{XLINK}href")
        assert f"{root}/{href}" in names


def test_0001_export_contains_only_replaced_leaf_with_backpointer():
    d = _model_0000()
    assembly.add_leaf(d, "0001", {"leaf_id": "cl2", "operation": "replace",
                                  "modified_leaf": "cl", "heading": "1.0",
                                  "title": "Cover v2"})
    pkg = _pkg(d, "0001")
    z = zipfile.ZipFile(io.BytesIO(pkg["body"]))
    root = "e123456/0001"
    index = ET.fromstring(z.read(f"{root}/index.xml"))
    leaves = list(index)
    assert len(leaves) == 1                        # ONLY 0001's own leaf
    lf = leaves[0]
    assert lf.get("operation") == "replace"
    mod = lf.find("modified-file")
    assert mod.get(f"{XLINK}href") == "../0000/m1/ca/10-cover-letter/cl.pdf"
    # the prior leaf (cl) is NOT in this sequence's package — no dangle
    names = z.namelist()
    assert not any("cl.pdf" in n for n in names)
    assert any("cl2.pdf" in n for n in names)
    assert pkg["missing"] == []


def test_exported_backbone_is_conformant():
    d = _model_0000()
    assembly.add_leaf(d, "0001", {"leaf_id": "cl2", "operation": "replace",
                                  "modified_leaf": "cl", "heading": "1.0",
                                  "title": "Cover v2"})
    pkg = _pkg(d, "0001")
    z = zipfile.ZipFile(io.BytesIO(pkg["body"]))
    root = "e123456/0001"
    index = z.read(f"{root}/index.xml").decode()
    ca = z.read(f"{root}/m1/ca/ca-regional.xml").decode()
    present = {n[len(root) + 1:] for n in z.namelist()
              if n.startswith(root + "/m")}
    findings = ectd_validation.validate_sequence_backbone(index, ca, present)
    assert findings == []


def test_delete_operation_ships_no_bytes_but_lists_leaf():
    d = _model_0000()
    assembly.add_leaf(d, "0001", {"leaf_id": "cl-del", "operation": "delete",
                                  "modified_leaf": "cl", "heading": "1.0"})
    pkg = _pkg(d, "0001")
    z = zipfile.ZipFile(io.BytesIO(pkg["body"]))
    index = ET.fromstring(z.read("e123456/0001/index.xml"))
    leaf = list(index)[0]
    assert leaf.get("operation") == "delete"
    assert leaf.find("modified-file") is not None
    # a delete carries no payload file, and is not reported missing
    assert pkg["missing"] == []


def test_export_unknown_dossier_404(client):
    assert client.get("/api/dossier/ectd/nope/export/0000").status_code == 404


def test_export_respects_tenancy(client):
    did, _ = _build(client)
    # dossier is unowned (no header at create) -> visible; now re-home it
    client.post("/api/dossier/dossiers",
                json={"dossier_id": did, "title": "Drugazole"},
                headers={"X-Tenant-Id": "tenant-a"})
    r = client.get(f"/api/dossier/ectd/{did}/export/0000",
                   headers={"X-Tenant-Id": "tenant-b"})
    assert r.status_code == 404
