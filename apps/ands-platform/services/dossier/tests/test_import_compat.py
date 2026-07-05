"""CAMP-INTEROP — import-compatibility self-check over the tool's OWN export.

The tool builds the transmissible eCTD package, then runs :mod:`import_compat`
over the ACTUAL zip bytes it just produced, verifying the structural contract a
compliant RIM importer (Vault RIM / docuBridge / eValidator) relies on:

  - the zip opens and is a single ICH eCTD sequence folder (<dossier>/<seq>/);
  - util/dtd present (both DOCTYPEs resolve offline);
  - index.xml + index-md5.txt present, and the md5 matches index.xml's bytes;
  - ca-regional.xml (CA Module 1 v2.2) present under m1/ca/;
  - at least one m1..m5 module folder;
  - every backbone <leaf> xlink:href resolves to a file actually in the zip
    (no dangling reference — a delete carries no bytes and is exempt);
  - each shipped file's stored md5 matches the md5 an importer recomputes over
    the bytes (the checksum contract eCTD lifecycle importers rely on).

Honest scope: this verifies the STANDARD structural contract. It does NOT
certify import into a specific commercial system.
"""

import hashlib
import io
import zipfile

from app import assembly, export_pkg, import_compat


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def _model_0000(did="e123456"):
    d = assembly.new_dossier(did)
    assembly.add_leaf(d, "0000", {"leaf_id": "pm", "operation": "new",
                                  "heading": "1.3.1", "title": "Drugazole PM"})
    assembly.add_leaf(d, "0000", {"leaf_id": "cl", "operation": "new",
                                  "heading": "1.0", "title": "Cover"})
    return d


def _pkg(model, seq):
    return export_pkg.build_package(
        model, seq, lambda lid: b"%PDF-1.7 body", b"<rt/>")


def _md5(b):
    return hashlib.md5(b).hexdigest()


# ---------------------------------------------------------------------------
# happy path: the tool's own valid export is import-compatible
# ---------------------------------------------------------------------------

def test_own_valid_export_is_import_compatible():
    pkg = _pkg(_model_0000(), "0000")
    rep = import_compat.import_compatibility_report(pkg)
    assert rep["compatible"] is True
    assert rep["errors"] == []
    assert rep["standard"]["ectd"] == "ICH eCTD 3.2.2"
    assert rep["standard"]["regional"] == "CA Module 1 v2.2"
    # the report lists exactly what a compliant importer will find
    assert rep["dossier_id"] == "e123456"
    assert rep["sequence"] == "0000"
    assert rep["file_count"] >= 4


def test_report_enumerates_the_backbone_contract_checks():
    rep = import_compat.import_compatibility_report(_pkg(_model_0000(), "0000"))
    passed = {c["id"]: c for c in rep["checks"] if c["passed"]}
    for cid in ("zip_opens", "single_sequence_root", "util_dtd_present",
                "index_present", "index_md5_matches", "ca_regional_present",
                "module_folders_present", "leaf_hrefs_resolve",
                "file_md5s_match"):
        assert cid in passed, f"expected passing check {cid}"


def test_report_records_what_an_importer_will_find():
    rep = import_compat.import_compatibility_report(_pkg(_model_0000(), "0000"))
    inv = rep["inventory"]
    assert inv["index_xml"].endswith("index.xml")
    assert inv["index_md5"].endswith("index-md5.txt")
    assert inv["ca_regional"].endswith("ca-regional.xml")
    assert any(p.endswith(".dtd") for p in inv["util_dtds"])
    assert set(inv["modules"]) >= {"m1"}
    # every backbone leaf is listed with its resolved-in-package flag
    assert rep["leaves"]
    assert all(l["resolved"] for l in rep["leaves"])


def test_honesty_disclaimer_is_present_and_vendor_neutral():
    rep = import_compat.import_compatibility_report(_pkg(_model_0000(), "0000"))
    disc = rep["disclaimer"].lower()
    assert "structural" in disc
    # names the standards, not a vendor certification
    assert "ich ectd 3.2.2" in disc or "ich ectd 3.2.2" in disc
    assert "does not certify" in disc or "not certify" in disc


# ---------------------------------------------------------------------------
# lifecycle: a 0001 replace with a modified-file back-pointer stays compatible
# ---------------------------------------------------------------------------

def test_replace_sequence_is_import_compatible():
    d = _model_0000()
    assembly.add_leaf(d, "0001", {"leaf_id": "cl2", "operation": "replace",
                                  "modified_leaf": "cl", "heading": "1.0",
                                  "title": "Cover v2"})
    rep = import_compat.import_compatibility_report(_pkg(d, "0001"))
    assert rep["compatible"] is True
    assert rep["sequence"] == "0001"
    # the modified-file back-pointer (../0000/...) is NOT required to be in this
    # sequence's zip — it is a cross-sequence reference, not a dangling href.
    assert rep["errors"] == []


# ---------------------------------------------------------------------------
# the check actually FAILS on a broken package (proves it is not a rubber stamp)
# ---------------------------------------------------------------------------

def _rezip(pkg, mutate):
    """Rebuild the pkg dict with a mutated zip (name->bytes)."""
    z = zipfile.ZipFile(io.BytesIO(pkg["body"]))
    entries = {n: z.read(n) for n in z.namelist()}
    mutate(entries)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for n, b in entries.items():
            out.writestr(n, b)
    return {**pkg, "body": buf.getvalue()}


def test_missing_index_md5_is_incompatible():
    pkg = _pkg(_model_0000(), "0000")

    def drop(entries):
        for n in list(entries):
            if n.endswith("index-md5.txt"):
                del entries[n]
    bad = _rezip(pkg, drop)
    rep = import_compat.import_compatibility_report(bad)
    assert rep["compatible"] is False
    assert any(e["id"] == "index_present" or e["id"] == "index_md5_matches"
               for e in rep["errors"])


def test_tampered_index_md5_is_incompatible():
    pkg = _pkg(_model_0000(), "0000")

    def tamper(entries):
        for n in list(entries):
            if n.endswith("index-md5.txt"):
                entries[n] = b"0" * 32 + b"\n"
    bad = _rezip(pkg, tamper)
    rep = import_compat.import_compatibility_report(bad)
    assert rep["compatible"] is False
    assert any(e["id"] == "index_md5_matches" for e in rep["errors"])


def test_missing_util_dtd_is_incompatible():
    pkg = _pkg(_model_0000(), "0000")

    def drop(entries):
        for n in list(entries):
            if "/util/dtd/" in n:
                del entries[n]
    bad = _rezip(pkg, drop)
    rep = import_compat.import_compatibility_report(bad)
    assert rep["compatible"] is False
    assert any(e["id"] == "util_dtd_present" for e in rep["errors"])


def test_dangling_leaf_href_is_incompatible():
    pkg = _pkg(_model_0000(), "0000")

    def drop_a_leaf_pdf(entries):
        for n in list(entries):
            if n.endswith(".pdf") and "/m1/" not in n:
                del entries[n]
                break
        else:  # no non-m1 pdf — drop any leaf pdf
            for n in list(entries):
                if n.endswith(".pdf"):
                    del entries[n]
                    break
    bad = _rezip(pkg, drop_a_leaf_pdf)
    rep = import_compat.import_compatibility_report(bad)
    assert rep["compatible"] is False
    assert any(e["id"] == "leaf_hrefs_resolve" for e in rep["errors"])


def test_corrupt_zip_is_incompatible_not_crash():
    pkg = {"body": b"not a zip", "files": [], "missing": []}
    rep = import_compat.import_compatibility_report(pkg)
    assert rep["compatible"] is False
    assert any(e["id"] == "zip_opens" for e in rep["errors"])


# ---------------------------------------------------------------------------
# missing leaf bytes (resolver returned None) surface as an incompatibility
# ---------------------------------------------------------------------------

def test_missing_leaf_bytes_reported_as_incompatible():
    model = _model_0000()
    # a resolver that yields nothing -> every leaf missing
    pkg = export_pkg.build_package(model, "0000", lambda lid: None, b"<rt/>")
    rep = import_compat.import_compatibility_report(pkg)
    assert rep["compatible"] is False
    assert any(e["id"] in ("leaf_hrefs_resolve", "no_missing_leaves")
               for e in rep["errors"])


# ---------------------------------------------------------------------------
# end-to-end over the real service/API — the tool self-checks its own export
# ---------------------------------------------------------------------------

def _build_via_api(client, did="e123456"):
    client.post("/api/dossier/dossiers",
                json={"dossier_id": did, "title": "Drugazole 10 mg"})
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate", json={})
    client.post(f"/api/dossier/ectd/{did}/section/3.2.S.1/upload",
                files={"file": ("ds.pdf", b"%PDF-1.4 uploaded bytes",
                                "application/pdf")})
    return did


def test_api_import_compat_over_own_export(client):
    did = _build_via_api(client)
    r = client.get(f"/api/dossier/ectd/{did}/import-compat/0000")
    assert r.status_code == 200
    rep = r.json()
    assert rep["compatible"] is True
    assert rep["dossier_id"] == did and rep["sequence"] == "0000"
    assert rep["standard"] == {"ectd": "ICH eCTD 3.2.2",
                               "regional": "CA Module 1 v2.2"}
    # every structural contract check passed
    assert rep["errors"] == []
    ids = {c["id"] for c in rep["checks"] if c["passed"]}
    assert {"index_md5_matches", "leaf_hrefs_resolve",
            "file_md5s_match"} <= ids


def test_api_import_compat_unknown_dossier_404(client):
    assert client.get(
        "/api/dossier/ectd/nope/import-compat/0000").status_code == 404


def test_api_import_compat_respects_tenancy(client):
    did = _build_via_api(client)
    client.post("/api/dossier/dossiers",
                json={"dossier_id": did, "title": "Drugazole"},
                headers={"X-Tenant-Id": "tenant-a"})
    r = client.get(f"/api/dossier/ectd/{did}/import-compat/0000",
                   headers={"X-Tenant-Id": "tenant-b"})
    assert r.status_code == 404
