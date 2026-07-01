"""The guided module builder end-to-end: dossiers, real upload, generate, N/A."""

from app import generators


def _dossier(client, cs_be_only=True):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": "e123456", "title": "Drugazole 10 mg",
                          "cs_be_only": cs_be_only})
    assert r.status_code == 201
    return "e123456"


# -- generators (pure) ------------------------------------------------------
def test_generators_produce_bytes_with_context():
    doc = generators.generate("cover_letter",
                              {"dossier_id": "e123456", "applicant": "Acme"})
    assert isinstance(doc["body"], bytes)
    assert b"e123456" in doc["body"] and b"Acme" in doc["body"]


def test_unknown_generator_raises():
    import pytest
    with pytest.raises(KeyError):
        generators.generate("nope", {})


# -- section tree + dossiers ------------------------------------------------
def test_section_tree_endpoint(client):
    body = client.get("/api/dossier/section-tree").json()
    assert [m["module"] for m in body["modules"]] == ["1", "2", "3", "4", "5"]


def test_create_and_list_and_get_dossier(client):
    _dossier(client)
    lst = client.get("/api/dossier/dossiers").json()
    assert lst["count"] == 1 and lst["dossiers"][0]["dossier_id"] == "e123456"
    full = client.get("/api/dossier/dossiers/e123456").json()
    assert full["index"]["title"] == "Drugazole 10 mg"
    assert full["content"]["gate"]["complete"] is False
    tower = {t["module"]: t["state"] for t in full["content"]["tower"]}
    assert tower["1"] == "todo" and tower["4"] == "na"


# -- real upload ------------------------------------------------------------
def test_upload_places_leaf_and_completes_section(client):
    did = _dossier(client)
    pdf = b"%PDF-1.4 fake cover letter bytes"
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/upload",
                    files={"file": ("cover.pdf", pdf, "application/pdf")})
    assert r.status_code == 200
    content = r.json()
    node = next(n for m in content["modules"] for n in m["nodes"]
                if n["section"] == "1.0")
    assert node["status"] == "complete" and node["action"] == "uploaded"
    # the eCTD leaf was placed with a checksum matching the bytes
    files = content["files_view"]
    leaves = [lf for nd in files["nodes"] for lf in nd["leaves"]]
    import hashlib
    assert any(lf["checksum"] == hashlib.md5(pdf).hexdigest() for lf in leaves)
    # and the doc is downloadable
    doc_id = node["document"]["doc_id"]
    dl = client.get(f"/api/dossier/documents/{doc_id}")
    assert dl.status_code == 200 and dl.content == pdf


def test_bilingual_pm_needs_en_and_fr(client):
    did = _dossier(client)
    up = lambda lang: client.post(  # noqa: E731
        f"/api/dossier/ectd/{did}/section/1.3.1/upload",
        files={"file": (f"pm-{lang}.pdf", b"pm", "application/pdf")},
        data={"lang": lang})
    c = up("en").json()
    pm = next(n for m in c["modules"] for n in m["nodes"] if n["section"] == "1.3.1")
    assert pm["status"] == "partial"
    c = up("fr").json()
    pm = next(n for m in c["modules"] for n in m["nodes"] if n["section"] == "1.3.1")
    assert pm["status"] == "complete" and set(pm["languages"]) == {"en", "fr"}


def test_generate_cover_letter(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/generate", json={})
    assert r.status_code == 200
    node = next(n for m in r.json()["modules"] for n in m["nodes"]
                if n["section"] == "1.0")
    assert node["status"] == "complete" and node["action"] == "generated"


def test_mark_na(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.2.2/mark-na",
                    json={"reason": "no prior applications"})
    node = next(n for m in r.json()["modules"] for n in m["nodes"]
                if n["section"] == "1.2.2")
    assert node["status"] == "na" and node["na_reason"] == "no prior applications"


def test_upload_to_unknown_section_404(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/9.9/upload",
                    files={"file": ("x.pdf", b"x", "application/pdf")})
    assert r.status_code == 404


def test_generate_on_upload_only_section_422(client):
    did = _dossier(client)
    # 5.3.1 is upload-only (no generator)
    r = client.post(f"/api/dossier/ectd/{did}/section/5.3.1/generate", json={})
    assert r.status_code == 422
