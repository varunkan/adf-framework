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


def test_rep_form_carries_sponsor_identity_not_product():
    """The CRO rejected an earlier draft because the sponsor company fields
    fell through to the product title (empty COMPANY_ID, product in the
    sponsor name slot). company_id / sponsor / product must be distinct."""
    doc = generators.generate("rep_application_form", {
        "company_id": "61234",
        "sponsor": "Northline Regulatory Partners",
        "drug_product": "Apo-Zentrix 50 mg tablet",
        "dossier_id": "e900001", "din": ""})
    xml = doc["body"].decode("utf-8")
    assert doc["content_type"] == "application/xml"
    assert doc["filename"] == "rep-application-form.xml"
    assert "<COMPANY_ID>61234</COMPANY_ID>" in xml
    assert ("<COMPANY_NAME>Northline Regulatory Partners</COMPANY_NAME>"
            in xml)
    assert ("<PRODUCT_NAME>Apo-Zentrix 50 mg tablet</PRODUCT_NAME>" in xml)
    assert "<DOSSIER_ID>e900001</DOSSIER_ID>" in xml
    # DIN is empty until HC assigns it at NOC — but it still renders empty
    assert "<DIN></DIN>" in xml
    # the sponsor slot is NOT the product name (the original defect)
    assert ("<COMPANY_NAME>Apo-Zentrix 50 mg tablet</COMPANY_NAME>"
            not in xml)
    # status stays an attribute only, never a required id element
    assert 'status="draft"' in xml
    # the REP CO/RT fields are present
    for frag in ("<DOSSIER_TYPE>", "<ACTIVITY_TYPE>", "<SEQUENCE_NUMBER>",
                 "<SEQUENCE_DESCRIPTION>"):
        assert frag in xml


def test_rep_form_company_falls_back_to_applicant_not_title():
    # when a distinct 'sponsor' is absent, applicant/company are used — but
    # never the product 'title'.
    xml = generators.generate("rep_application_form", {
        "applicant": "Acme Regulatory", "title": "Drugazole 10 mg",
        "company_id": "50000"})["body"].decode("utf-8")
    assert "<COMPANY_NAME>Acme Regulatory</COMPANY_NAME>" in xml
    assert "<PRODUCT_NAME>Drugazole 10 mg</PRODUCT_NAME>" in xml
    assert "<COMPANY_NAME>Drugazole 10 mg</COMPANY_NAME>" not in xml


def test_rep_form_without_sponsor_leaves_company_empty_not_product():
    # the whole bug: with only a title, the company name must be EMPTY, never
    # the product title.
    xml = generators.generate("rep_application_form",
                              {"title": "Drugazole 10 mg"})["body"].decode()
    assert "<COMPANY_NAME></COMPANY_NAME>" in xml
    assert "<COMPANY_ID></COMPANY_ID>" in xml
    assert "<PRODUCT_NAME>Drugazole 10 mg</PRODUCT_NAME>" in xml


def test_cover_letter_sponsor_is_sponsor_not_product():
    # the PDF renderer collapses runs of spaces, so the field padding is one
    # space in the byte stream.
    body = generators.generate("cover_letter", {
        "sponsor": "Northline Regulatory Partners",
        "company_id": "61234",
        "drug_product": "Apo-Zentrix 50 mg tablet",
        "dossier_id": "e900001"})["body"]
    assert b"Sponsor: Northline Regulatory Partners" in body
    assert b"Company ID: 61234" in body
    assert b"Drug product: Apo-Zentrix 50 mg tablet" in body
    # sponsor line must not carry the product name
    assert b"Sponsor: Apo-Zentrix 50 mg tablet" not in body


def test_cover_letter_sponsor_omitted_does_not_fall_to_product():
    # with only a title (no sponsor/applicant/company), the sponsor field is
    # the display sentinel, never the drug title.
    body = generators.generate("cover_letter",
                               {"title": "Drugazole 10 mg"})["body"]
    assert b"Sponsor: Drugazole 10 mg" not in body


def test_unknown_generator_raises():
    import pytest
    with pytest.raises(KeyError):
        generators.generate("nope", {})


def test_form_v_declares_one_s5_statement_per_patent():
    doc = generators.generate("patent_form_v",
                              {"drug_product": "Drugazole 10 mg",
                               "crp_brand": "Refazole", "crp_din": "02345678",
                               "patents": "CA 2,222,333",
                               "patent_expiry": "2031-05-04",
                               "allegation": "alleges non-infringement"})
    assert doc["title"] == ("Form V — Declaration Re: Patent List "
                            "(PM(NOC) Regulations)")
    assert doc["filename"] == "form-v-declaration.pdf"
    assert doc["content_type"] == "application/pdf"
    body = doc["body"]
    assert b"declares" in body and b"s.5 statement" in body
    for frag in (b"CA 2,222,333", b"2031-05-04", b"alleges non-infringement",
                 b"Drugazole 10 mg", b"Refazole", b"02345678"):
        assert frag in body
    # the four s.5 statement options are spelled out
    for frag in (b"not addressed", b"accepts expiry", b"alleges invalidity",
                 b"alleges non-infringement"):
        assert frag in body


def test_form_v_without_patents_needs_no_s5_statement():
    body = generators.generate("patent_form_v", {})["body"]
    assert b"no patents/CSPs" in body and b"no s.5 statement" in body


def test_patent_form_iv_alias_still_produces_the_form_v_declaration():
    # Stored section states created before the Form IV -> Form V correction
    # keep resolving; both keys emit the identical Form V document.
    ctx = {"patents": "CA 2,222,333"}
    assert (generators.generate("patent_form_iv", ctx)
            == generators.generate("patent_form_v", ctx))
    assert (generators.LLM_DRAFTABLE["patent_form_iv"]
            == generators.LLM_DRAFTABLE["patent_form_v"])


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
    # 1.2.2 Fees is upload-only BY DESIGN (a fee receipt is uploaded, not
    # authored) — every content section now offers in-app generate, so this
    # uses the section that is intentionally not generatable.
    r = client.post(f"/api/dossier/ectd/{did}/section/1.2.2/generate", json={})
    assert r.status_code == 422


def test_upload_rejects_extension_not_in_section_formats(client):
    """The dropzone accept= filter is client-side only — the service must
    enforce the section's declared formats (HC requires PDF leaves)."""
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.5/upload",
                    files={"file": ("notes.txt", b"plain text", "text/plain")})
    assert r.status_code == 422
    assert r.json()["rule"] == "file_format_invalid"
    # a PDF is still accepted
    r = client.post(f"/api/dossier/ectd/{did}/section/1.5/upload",
                    files={"file": ("ok.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert r.status_code == 200


def test_delete_soft_archives_recoverably(client):
    # WS3 record-integrity: a delete on a regulated dossier is a RECOVERABLE
    # soft-archive, not a hard purge. It leaves the working catalog but its
    # documents survive (so a restore is lossless), and re-archiving an already
    # archived dossier is a 404 (nothing live to archive).
    did = _dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate", json={})
    doc_id = next(n for m in client.get(f"/api/dossier/dossiers/{did}").json()
                  ["content"]["modules"] for n in m["nodes"]
                  if n["section"] == "1.0")["document"]["doc_id"]
    r = client.request("DELETE", f"/api/dossier/dossiers/{did}",
                       json={"reason": "created in error", "confirm_id": did})
    assert r.status_code == 200 and r.json()["archived"] == did
    assert client.get("/api/dossier/dossiers").json()["count"] == 0
    # RECOVERABLE: the bytes are NOT purged — the document is still fetchable
    assert client.get(f"/api/dossier/documents/{doc_id}").status_code == 200
    # already archived => nothing live to re-archive
    assert client.request("DELETE", f"/api/dossier/dossiers/{did}",
                          json={"reason": "again",
                                "confirm_id": did}).status_code == 404
    # ...and it can be restored back into the working catalog
    assert client.post(f"/api/dossier/dossiers/{did}/restore",
                       json={}).status_code == 200
    assert client.get("/api/dossier/dossiers").json()["count"] == 1
