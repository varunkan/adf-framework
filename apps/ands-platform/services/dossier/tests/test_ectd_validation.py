"""eCTD technical validator (REQ-107) — over an assembled dossier model."""

import xml.etree.ElementTree as ET

from app import assembly, ectd_validation


def _clean_dossier():
    d = assembly.new_dossier("e123456")
    assembly.add_leaf(d, "0000", {"leaf_id": "pm", "operation": "new",
                                  "heading": "1.3.1", "title": "PM"})
    return d


def test_clean_single_leaf_dossier_passes():
    d = _clean_dossier()
    res = ectd_validation.validate(d)
    assert res["passed"] is True
    assert res["errors"] == []
    assert res["checked"] == 1


def test_leaf_missing_checksum_fails():
    d = _clean_dossier()
    # scrub the checksum off the persisted live leaf
    d["sequences"][0]["leaves"][0]["checksum"] = ""
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    rules = {e["rule"] for e in res["errors"]}
    assert "checksum_required" in rules
    assert any(e["leaf"] == "pm" for e in res["errors"])


def test_leaf_missing_href_fails():
    d = _clean_dossier()
    d["sequences"][0]["leaves"][0]["href"] = ""
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    assert "href_required" in {e["rule"] for e in res["errors"]}


def test_duplicate_leaf_id_fails():
    d = _clean_dossier()
    # inject a second leaf with the same id directly (add_leaf would refuse it)
    dup = dict(d["sequences"][0]["leaves"][0])
    d["sequences"][0]["leaves"].append(dup)
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    dup_errs = [e for e in res["errors"] if e["rule"] == "duplicate_leaf_id"]
    assert dup_errs and dup_errs[0]["leaf"] == "pm"


def test_replace_with_unknown_modified_leaf_fails():
    d = _clean_dossier()
    # add_leaf refuses this at insert time; the validator's job is to catch a
    # dossier that reached a bad state another way, so inject the leaf directly.
    src = d["sequences"][0]["leaves"][0]
    d["sequences"].append({"sequence": "0001", "leaves": [
        {**src, "leaf_id": "pm2", "operation": "replace",
         "modified_leaf": "does-not-exist", "sequence": "0001"}]})
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    assert "prior_leaf_unknown" in {e["rule"] for e in res["errors"]}


def test_valid_replace_lifecycle_passes():
    d = _clean_dossier()
    assembly.add_leaf(d, "0001", {"leaf_id": "pm2", "operation": "replace",
                                  "modified_leaf": "pm", "heading": "1.3.1",
                                  "title": "PM v2"})
    res = ectd_validation.validate(d)
    assert res["passed"] is True
    # only pm2 is live after the replace
    assert res["checked"] == 1


def test_href_uppercase_and_space_flagged():
    d = _clean_dossier()
    d["sequences"][0]["leaves"][0]["href"] = "M1/CA/Cover Letter.pdf"
    res = ectd_validation.validate(d)
    rules = {e["rule"] for e in res["errors"]}
    assert "href_not_lowercase" in rules
    assert "href_has_space" in rules
    assert res["passed"] is False


def test_non_module_href_is_a_warning_not_error():
    d = _clean_dossier()
    d["sequences"][0]["leaves"][0]["href"] = "misc/floating.pdf"
    res = ectd_validation.validate(d)
    warn_rules = {w["rule"] for w in res["warnings"]}
    assert "href_module_folder" in warn_rules
    # a stray folder is only a warning — nothing else is wrong, so it passes
    assert res["passed"] is True


def test_backbone_parses_on_clean_dossier():
    d = _clean_dossier()
    seq = d["sequences"][-1]["sequence"]
    backbone = assembly.build_outline_view(d, seq)["backbone"]
    # the validator's own assertion: both documents are well-formed XML
    assert ET.fromstring(backbone["index.xml"]) is not None
    assert ET.fromstring(backbone["ca-regional.xml"]) is not None
    res = ectd_validation.validate(d)
    assert "backbone_malformed" not in {e["rule"] for e in res["errors"]}


def test_non_pdf_bytes_named_pdf_fails_pdf_header():
    d = _clean_dossier()
    res = ectd_validation.validate(
        d, documents={"cover.pdf": b"this is not a pdf at all"})
    assert res["passed"] is False
    assert "pdf_header" in {e["rule"] for e in res["errors"]}


def test_encrypted_pdf_fails_pdf_encrypted():
    d = _clean_dossier()
    res = ectd_validation.validate(
        d, documents={"secured.pdf": b"%PDF-1.7\n...stuff.../Encrypt 5 0 R"})
    assert res["passed"] is False
    assert "pdf_encrypted" in {e["rule"] for e in res["errors"]}


def test_valid_pdf_document_passes():
    d = _clean_dossier()
    res = ectd_validation.validate(
        d, documents={"pm.pdf": b"%PDF-1.7\nplain unencrypted body\n%%EOF"})
    assert res["passed"] is True


def test_non_pdf_named_documents_are_ignored():
    d = _clean_dossier()
    # a .xml payload without %PDF should not trip pdf_header
    res = ectd_validation.validate(
        d, documents={"index.xml": b"<root/>"})
    assert res["passed"] is True
    assert "pdf_header" not in {e["rule"] for e in res["errors"]}
