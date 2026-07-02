"""eCTD technical validator (REQ-107) — over an assembled dossier model."""

import re
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


# ---------------------------------------------------------------------------
# HC v5.3-style rule ids (CA-E-nnnn / CA-W-nnnn) + ported backbone checks
# ---------------------------------------------------------------------------

RULE_ID_RE = re.compile(r"CA-[EW]-\d{4}")

# a structurally sound ca-regional payload for backbone-level tests
GOOD_CA = "<ca-regional><dossier-id>e123456</dossier-id></ca-regional>"


def test_every_finding_carries_a_stable_rule_id():
    d = _clean_dossier()
    d["sequences"][0]["leaves"][0]["href"] = "Bad Folder/File.PDF"
    d["sequences"][0]["leaves"][0]["checksum"] = ""
    res = ectd_validation.validate(
        d, documents={"x.pdf": b"nope /Encrypt"})
    findings = res["errors"] + res["warnings"]
    assert findings
    for f in findings:
        assert RULE_ID_RE.fullmatch(f["rule_id"]), f
    # severity is encoded in the id: errors are E, warnings are W
    assert all(e["rule_id"].startswith("CA-E-") for e in res["errors"])
    assert all(w["rule_id"].startswith("CA-W-") for w in res["warnings"])


def test_inventory_rule_ids_pinned():
    d = _clean_dossier()
    d["sequences"][0]["leaves"][0]["href"] = ""
    d["sequences"][0]["leaves"][0]["checksum"] = ""
    dup = dict(d["sequences"][0]["leaves"][0])
    d["sequences"][0]["leaves"].append(dup)
    res = ectd_validation.validate(d)
    by_rule = {e["rule"]: e["rule_id"] for e in res["errors"]}
    assert by_rule["href_required"] == "CA-E-1001"
    assert by_rule["checksum_required"] == "CA-E-1002"
    assert by_rule["duplicate_leaf_id"] == "CA-E-1003"


def test_checksum_not_md5_hex_fails():
    d = _clean_dossier()
    d["sequences"][0]["leaves"][0]["checksum"] = "not-a-digest"
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    err = next(e for e in res["errors"] if e["rule"] == "checksum_not_md5")
    assert err["rule_id"] == "CA-E-1004"
    assert err["leaf"] == "pm"


def test_new_operation_with_prior_reference_fails():
    d = _clean_dossier()
    src = d["sequences"][0]["leaves"][0]
    d["sequences"].append({"sequence": "0001", "leaves": [
        {**src, "leaf_id": "pm2", "operation": "new",
         "modified_leaf": "pm", "sequence": "0001"}]})
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    err = next(e for e in res["errors"] if e["rule"] == "new_has_prior")
    assert err["rule_id"] == "CA-E-2005"
    assert err["leaf"] == "pm2"


def test_lifecycle_rule_ids_pinned():
    d = _clean_dossier()
    src = d["sequences"][0]["leaves"][0]
    d["sequences"].append({"sequence": "0001", "leaves": [
        {**src, "leaf_id": "pm2", "operation": "replace",
         "modified_leaf": "ghost", "sequence": "0001"}]})
    res = ectd_validation.validate(d)
    err = next(e for e in res["errors"] if e["rule"] == "prior_leaf_unknown")
    assert err["rule_id"] == "CA-E-2004"


def test_href_naming_rule_ids_pinned():
    d = _clean_dossier()
    d["sequences"][0]["leaves"][0]["href"] = "M1/CA/Cover Letter.pdf"
    res = ectd_validation.validate(d)
    ids = {f["rule"]: f["rule_id"]
           for f in res["errors"] + res["warnings"]}
    assert ids["href_not_lowercase"] == "CA-E-3001"
    assert ids["href_has_space"] == "CA-E-3002"
    assert ids["href_module_folder"] == "CA-W-3003"


def test_non_numeric_sequence_fails():
    d = _clean_dossier()
    d["sequences"].append({"sequence": "00ab", "leaves": []})
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    err = next(e for e in res["errors"]
               if e["rule"] == "sequence_not_numeric")
    assert err["rule_id"] == "CA-E-4001"
    assert err["leaf"] == "00ab"


def test_sequence_wrong_width_fails():
    d = _clean_dossier()
    d["sequences"].append({"sequence": "00000", "leaves": []})
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    err = next(e for e in res["errors"]
               if e["rule"] == "sequence_wrong_width")
    assert err["rule_id"] == "CA-E-4002"


def test_duplicate_sequence_number_fails():
    d = _clean_dossier()
    d["sequences"].append({"sequence": "0000", "leaves": []})
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    err = next(e for e in res["errors"]
               if e["rule"] == "sequence_duplicate")
    assert err["rule_id"] == "CA-E-4003"
    assert err["leaf"] == "0000"


def test_sequence_gap_is_a_warning_only():
    d = _clean_dossier()
    assembly.add_leaf(d, "0002", {"leaf_id": "cl", "operation": "new",
                                  "heading": "1.0", "title": "Cover"})
    res = ectd_validation.validate(d)
    warn = next(w for w in res["warnings"]
                if w["rule"] == "sequence_not_contiguous")
    assert warn["rule_id"] == "CA-W-4004"
    assert res["passed"] is True


def test_first_sequence_not_0000_warns():
    d = assembly.new_dossier("e777777")
    assembly.add_leaf(d, "0001", {"leaf_id": "pm", "operation": "new",
                                  "heading": "1.3.1", "title": "PM"})
    res = ectd_validation.validate(d)
    warn = next(w for w in res["warnings"]
                if w["rule"] == "sequence_start_not_0000")
    assert warn["rule_id"] == "CA-W-4005"
    assert res["passed"] is True


def test_backbone_xml_clean_pair_has_no_findings():
    d = _clean_dossier()
    backbone = assembly.build_outline_view(d, "0000")["backbone"]
    findings = ectd_validation.validate_backbone_xml(
        backbone["index.xml"], backbone["ca-regional.xml"])
    assert findings == []


def test_backbone_xml_index_root_is_pinned():
    findings = ectd_validation.validate_backbone_xml("<wrong/>", GOOD_CA)
    err = next(f for f in findings if f["rule"] == "index_root_unexpected")
    assert err["rule_id"] == "CA-E-5002"


def test_backbone_xml_incomplete_leaf_flagged():
    index = ('<ectd-index dossier-id="e123456" sequence="0000">'
             '<leaf id="pm" href="m1/ca/pm.pdf"/></ectd-index>')
    findings = ectd_validation.validate_backbone_xml(index, GOOD_CA)
    err = next(f for f in findings if f["rule"] == "index_leaf_incomplete")
    assert err["rule_id"] == "CA-E-5003"
    assert err["leaf"] == "pm"


def test_backbone_xml_missing_admin_attrs_flagged():
    findings = ectd_validation.validate_backbone_xml("<ectd-index/>", GOOD_CA)
    admin = [f for f in findings if f["rule"] == "index_admin_missing"]
    # both the dossier-id and the sequence identification are required
    assert len(admin) == 2
    assert all(f["rule_id"] == "CA-E-5004" for f in admin)


def test_backbone_xml_ca_regional_structure():
    index = '<ectd-index dossier-id="e123456" sequence="0000"/>'
    bad_root = ectd_validation.validate_backbone_xml(index, "<hcsc/>")
    assert any(f["rule"] == "ca_root_unexpected" and
               f["rule_id"] == "CA-E-6001" for f in bad_root)
    no_id = ectd_validation.validate_backbone_xml(index, "<ca-regional/>")
    assert any(f["rule"] == "ca_dossier_id_missing" and
               f["rule_id"] == "CA-E-6002" for f in no_id)


def test_backbone_xml_malformed_is_flagged_per_document():
    findings = ectd_validation.validate_backbone_xml("<oops", "<ca-regional")
    mal = [f for f in findings if f["rule"] == "backbone_malformed"]
    assert len(mal) == 2
    assert all(f["rule_id"] == "CA-E-5001" for f in mal)


def test_pdf_findings_carry_rule_ids():
    d = _clean_dossier()
    res = ectd_validation.validate(
        d, documents={"a.pdf": b"not a pdf",
                      "b.pdf": b"%PDF-1.7 body /Encrypt 5 0 R"})
    ids = {e["rule"]: e["rule_id"] for e in res["errors"]}
    assert ids["pdf_header"] == "CA-E-7001"
    assert ids["pdf_encrypted"] == "CA-E-7002"


# ---------------------------------------------------------------------------
# Transmissible ICH eCTD 3.2.2 sequence backbone conformance (55xx / 6xxx)
# ---------------------------------------------------------------------------

# a conformant CA M1 v2.2 regional payload for the sequence-backbone checks
GOOD_CA_SEQ = (
    '<ca:ectd-ca xmlns:ca="http://www.hc-sc.gc.ca/dhpd/ectd/ca">'
    '<application-info><dossier-id>e1</dossier-id>'
    '<company-id>c1</company-id></application-info>'
    '<product>Drugazole</product></ca:ectd-ca>')


def _seq_index(leaves_xml):
    return ('<?xml version="1.0"?>'
            '<!DOCTYPE ectd:ectd SYSTEM "util/dtd/ich-ectd-3-2.dtd">'
            '<ectd:ectd xmlns:ectd="http://www.ich.org/ectd" '
            'xmlns:xlink="http://www.w3c.org/1999/xlink">'
            + leaves_xml + '</ectd:ectd>')


def test_sequence_backbone_clean_pair_has_no_findings():
    d = _clean_dossier()
    bb = assembly.build_sequence_backbone(d, "0000")
    present = {lf["href"] for lf in assembly.sequence_leaves(d, "0000")}
    findings = ectd_validation.validate_sequence_backbone(
        bb["index_xml"], bb["ca_regional_xml"], present)
    assert findings == []


def test_dangling_href_flagged():
    index = _seq_index(
        '<leaf ID="pm" operation="new" '
        'xlink:href="m1/ca/13-product-info/131-pm/pm.pdf"/>')
    findings = ectd_validation.validate_sequence_backbone(
        index, GOOD_CA_SEQ, present_paths=set())   # no file present
    err = next(f for f in findings if f["rule"] == "leaf_href_dangling")
    assert err["rule_id"] == "CA-E-5503"
    assert err["leaf"] == "pm"


def test_replace_without_modified_file_flagged():
    index = _seq_index(
        '<leaf ID="cl2" operation="replace" '
        'xlink:href="m1/ca/10-cover-letter/cl2.pdf"/>')
    findings = ectd_validation.validate_sequence_backbone(
        index, GOOD_CA_SEQ, {"m1/ca/10-cover-letter/cl2.pdf"})
    err = next(f for f in findings
               if f["rule"] == "leaf_modified_file_missing")
    assert err["rule_id"] == "CA-E-5502"
    assert err["leaf"] == "cl2"


def test_missing_operation_attribute_flagged():
    index = _seq_index(
        '<leaf ID="pm" xlink:href="m1/ca/pm.pdf"/>')
    findings = ectd_validation.validate_sequence_backbone(
        index, GOOD_CA_SEQ, {"m1/ca/pm.pdf"})
    err = next(f for f in findings if f["rule"] == "leaf_operation_missing")
    assert err["rule_id"] == "CA-E-5501"


def test_missing_doctype_flagged():
    index = ('<ectd:ectd xmlns:ectd="http://www.ich.org/ectd"'
             ' xmlns:xlink="http://www.w3c.org/1999/xlink"/>')
    findings = ectd_validation.validate_sequence_backbone(
        index, GOOD_CA_SEQ, set())
    err = next(f for f in findings if f["rule"] == "index_doctype_missing")
    assert err["rule_id"] == "CA-E-5504"


def test_delete_leaf_href_is_not_dangling():
    # a delete carries no file, so its href must NOT be flagged as dangling
    index = _seq_index(
        '<leaf ID="x" operation="delete" xlink:href="m1/ca/gone.pdf">'
        '<modified-file xlink:href="../0000/m1/ca/gone.pdf"/></leaf>')
    findings = ectd_validation.validate_sequence_backbone(
        index, GOOD_CA_SEQ, set())
    assert not any(f["rule"] == "leaf_href_dangling" for f in findings)


def test_ca_regional_missing_company_and_product_flagged():
    index = _seq_index("")
    bad_ca = ('<ca:ectd-ca xmlns:ca="http://www.hc-sc.gc.ca/dhpd/ectd/ca">'
              '<application-info><dossier-id>e1</dossier-id>'
              '</application-info></ca:ectd-ca>')
    findings = ectd_validation.validate_sequence_backbone(index, bad_ca, set())
    ids = {f["rule"]: f["rule_id"] for f in findings}
    assert ids["ca_company_id_missing"] == "CA-E-6003"
    assert ids["ca_product_missing"] == "CA-E-6004"


def test_ca_regional_wrong_root_flagged():
    findings = ectd_validation.validate_sequence_backbone(
        _seq_index(""), "<ca-regional><dossier-id/></ca-regional>", set())
    err = next(f for f in findings if f["rule"] == "ca_root_unexpected")
    assert err["rule_id"] == "CA-E-6001"


def test_validate_flags_bad_sequence_backbone_via_model():
    # inject a replace leaf with no modified_leaf pointer straight into the model
    d = _clean_dossier()
    src = d["sequences"][0]["leaves"][0]
    d["sequences"].append({"sequence": "0001", "leaves": [
        {**src, "leaf_id": "pm2", "operation": "replace",
         "modified_leaf": None, "sequence": "0001",
         "href": "m1/ca/13-product-info/131-pm/pm2.pdf"}]})
    res = ectd_validation.validate(d)
    assert res["passed"] is False
    assert "leaf_modified_file_missing" in {e["rule"] for e in res["errors"]}


def test_validate_clean_replace_lifecycle_backbone_conformant():
    d = _clean_dossier()
    assembly.add_leaf(d, "0001", {"leaf_id": "pm2", "operation": "replace",
                                  "modified_leaf": "pm", "heading": "1.3.1",
                                  "title": "PM v2"})
    res = ectd_validation.validate(d)
    # the real per-sequence backbone check adds no errors for a valid lifecycle
    seq_rules = {"leaf_operation_missing", "leaf_modified_file_missing",
                 "leaf_href_dangling", "ca_company_id_missing",
                 "ca_product_missing"}
    assert not (seq_rules & {e["rule"] for e in res["errors"]})
    assert res["passed"] is True
