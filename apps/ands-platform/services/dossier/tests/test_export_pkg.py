"""eCTD sequence export — the transmissible zip package."""

import io
import zipfile

from app import assembly


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
