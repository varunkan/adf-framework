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
    # 1.2.5 Authorization & Regulatory Correspondence is optional (mark-N/A-able)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.2.5/mark-na",
                    json={"reason": "no authorizations required"})
    node = next(n for m in r.json()["modules"] for n in m["nodes"]
                if n["section"] == "1.2.5")
    assert node["status"] == "na" and node["na_reason"] == "no authorizations required"


def test_fees_block_and_gate_requires_fee_and_validation(client):
    did = _dossier(client)
    content = client.get(f"/api/dossier/dossiers/{did}/content").json()
    # a live current-fiscal-year ANDS review fee is surfaced
    assert content["fees"]["review_fee"]["amount"] > 0
    assert content["gate"]["fee_paid"] is False
    assert content["gate"]["complete"] is False       # fee not arranged
    # confirming the fee flips the fee gate
    c2 = client.post(f"/api/dossier/dossiers/{did}/fees",
                     json={"fee_paid": True, "sme_granted": True}).json()
    assert c2["gate"]["fee_paid"] is True
    assert c2["fees"]["mitigation"]["reduction"]      # SME reduction present


def test_ectd_validation_endpoint(client):
    did = _dossier(client)
    # a non-PDF file in a pdf slot is caught by the technical validator
    client.post(f"/api/dossier/ectd/{did}/section/1.0/upload",
                files={"file": ("cover.pdf", b"not a pdf", "application/pdf")})
    v = client.get(f"/api/dossier/dossiers/{did}/validate").json()
    assert v["passed"] is False
    assert any(e["rule"] == "pdf_header" for e in v["errors"])


def test_generated_rep_form_leaf_has_xml_href(client):
    # the REP application form is XML — its eCTD leaf must carry a .xml href
    did = _dossier(client)
    c = client.post(f"/api/dossier/ectd/{did}/section/1.2.1/generate",
                    json={}).json()
    leaves = [lf for nd in c["files_view"]["nodes"] for lf in nd["leaves"]]
    rep = next(lf for lf in leaves if "application-form" in lf["leaf_id"])
    assert rep["href"].endswith(".xml")
    # a validation over the model still passes (well-formed backbone)
    assert client.get(f"/api/dossier/dossiers/{did}/validate").json()["passed"]


def test_din_format_validated(client):
    ok = client.post("/api/dossier/dossiers",
                     json={"dossier_id": "e900001", "din": "02345678"})
    assert ok.status_code == 201
    bad = client.post("/api/dossier/dossiers",
                      json={"dossier_id": "e900002", "din": "123"})
    assert bad.status_code == 422


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
