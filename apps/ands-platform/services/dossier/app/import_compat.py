"""CAMP-INTEROP — import-compatibility self-check over the tool's OWN export.

The one repeated adoption ask from regulatory-ops buyers was: *"confirm the
exported package imports clean into our Vault RIM / docuBridge lifecycle."* The
export is already a genuine ICH eCTD 3.2.2 sequence + CA Module 1 v2.2 regional
backbone (see :mod:`export_pkg` / :mod:`assembly`). This module proves it by
running a STRUCTURAL self-check over the ACTUAL zip bytes the tool just produced
— the exact structural contract any compliant RIM importer (Veeva Vault RIM,
docuBridge, Lorenz / HC eValidator) relies on to load a sequence:

  1. ``zip_opens``               — the package is a readable zip;
  2. ``single_sequence_root``    — exactly one ``<dossier_id>/<seq>/`` folder;
  3. ``util_dtd_present``        — ``util/dtd/*.dtd`` ships (DOCTYPEs resolve);
  4. ``index_present``           — ``index.xml`` is present;
  5. ``index_md5_matches``       — ``index-md5.txt`` present AND its digest
                                   equals the md5 of ``index.xml``'s bytes
                                   (the 3.2.2 integrity convention importers
                                   verify on load);
  6. ``ca_regional_present``     — ``m1/ca/ca-regional.xml`` (CA M1 v2.2);
  7. ``module_folders_present``  — at least one ``m1``..``m5`` module folder;
  8. ``leaf_hrefs_resolve``      — every backbone ``<leaf xlink:href>`` resolves
                                   to a file actually in the sequence (a
                                   ``delete`` leaf carries no bytes and a
                                   cross-sequence ``modified-file`` back-pointer
                                   ``../<seq>/…`` are BOTH exempt — they are not
                                   dangling references);
  9. ``file_md5s_match``         — each shipped file's stored md5 equals the md5
                                   an importer recomputes over the bytes (the
                                   checksum contract eCTD lifecycle relies on);
 10. ``no_missing_leaves``       — no live leaf's bytes failed to resolve at
                                   build time (``pkg["missing"]`` is empty).

Emits a machine + human "import-compatibility report": ``compatible`` (bool),
the per-check list, an ``inventory`` (exactly the artefacts an importer will
find), the resolved leaf list, and an explicit vendor-NEUTRAL honesty
disclaimer. It verifies the STANDARD structural contract; it does NOT certify
import into any specific commercial system.

Pure + stdlib. Input is the :func:`export_pkg.build_package` result dict
(``body`` zip bytes + ``files`` + ``missing``) — the tool checks its own output.
"""

from __future__ import annotations

import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

from . import assembly

# The standards the package is built to — surfaced verbatim so the report states
# exactly what a compliant importer is being handed (never a vendor claim).
ECTD_STANDARD = "ICH eCTD 3.2.2"
REGIONAL_STANDARD = "CA Module 1 v2.2"

XLINK_HREF = f"{{{assembly.XLINK_NS}}}href"
_MD5_LINE_RE = re.compile(r"[0-9a-fA-F]{32}")
_MODULE_RE = re.compile(r"^m[1-5]$")

DISCLAIMER = (
    "This import-compatibility report verifies the STANDARD structural contract "
    "of an " + ECTD_STANDARD + " sequence with a " + REGIONAL_STANDARD + " "
    "regional backbone — the same contract any compliant RIM importer (e.g. "
    "Veeva Vault RIM, docuBridge, Lorenz / Health Canada eValidator) relies on "
    "to load a sequence. It confirms what a compliant importer will find in the "
    "package. It does NOT certify import into any specific commercial system, "
    "and it is not Health Canada's official eValidator — run your publisher's "
    "validator before you transmit."
)


def _check(cid: str, label: str, passed: bool, detail: str = "") -> dict:
    return {"id": cid, "label": label, "passed": bool(passed), "detail": detail}


def _leaf_hrefs(index_xml: bytes) -> list[dict]:
    """Backbone leaves as ``{leaf_id, operation, href}`` (namespace-agnostic)."""
    out: list[dict] = []
    try:
        root = ET.fromstring(index_xml)
    except ET.ParseError:
        return out
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "leaf":
            continue
        href = (el.get(XLINK_HREF) or el.get("xlink:href")
                or el.get("href") or "").strip()
        out.append({"leaf_id": (el.get("ID") or el.get("id") or "").strip(),
                    "operation": (el.get("operation") or "").strip(),
                    "href": href})
    return out


def import_compatibility_report(pkg: dict) -> dict:
    """Run the structural import-compatibility self-check over ``pkg``'s zip.

    ``pkg`` is the :func:`export_pkg.build_package` result. Returns a machine +
    human report: ``compatible`` (bool), ``checks`` (each check with pass/fail),
    ``errors`` (the failing checks), ``inventory`` (what an importer will find),
    ``leaves`` (each backbone leaf + whether its href resolved in-package),
    ``standard`` and ``disclaimer``. Never raises on a malformed package — a
    corrupt zip is reported as ``zip_opens`` failed, not an exception.
    """
    checks: list[dict] = []
    body = pkg.get("body") or b""
    declared_missing = list(pkg.get("missing") or [])

    inventory: dict = {"root": "", "index_xml": "", "index_md5": "",
                       "ca_regional": "", "util_dtds": [], "modules": [],
                       "files": []}
    leaves_out: list[dict] = []

    # 1. zip_opens ---------------------------------------------------------
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
        names = [n for n in z.namelist() if not n.endswith("/")]
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        checks.append(_check("zip_opens", "Package is a readable zip archive",
                             False, f"the package could not be opened: {exc}"))
        return _finalize(pkg, checks, inventory, leaves_out)
    checks.append(_check("zip_opens", "Package is a readable zip archive",
                         True, f"{len(names)} files"))
    inventory["files"] = sorted(names)

    # 2. single_sequence_root — exactly one <dossier>/<seq>/ top folder -----
    roots = {n.split("/", 2)[0] + "/" + n.split("/", 2)[1]
             for n in names if n.count("/") >= 1
             and len(n.split("/")) >= 2 and n.split("/")[1]}
    single_root = len(roots) == 1
    root = next(iter(roots)) if single_root else ""
    inventory["root"] = root
    dossier_id, _, sequence = root.partition("/")
    checks.append(_check(
        "single_sequence_root",
        "Exactly one <dossier_id>/<sequence>/ sequence folder", single_root,
        f"root: {root}" if single_root
        else f"expected one sequence root, found {sorted(roots) or 'none'}"))

    def under(rel: str) -> str:
        return f"{root}/{rel}" if root else rel

    present = set(names)

    # 3. util_dtd_present ---------------------------------------------------
    util_dtds = sorted(n for n in names
                       if "/util/dtd/" in n and n.endswith(".dtd"))
    inventory["util_dtds"] = util_dtds
    checks.append(_check(
        "util_dtd_present", "util/dtd DTDs ship so DOCTYPEs resolve offline",
        bool(util_dtds),
        ", ".join(posixpath.basename(p) for p in util_dtds) or
        "no util/dtd/*.dtd found — the index/ca-regional DOCTYPEs will not "
        "resolve offline"))

    # 4. index_present + 5. index_md5_matches ------------------------------
    index_path = under("index.xml")
    md5_path = under("index-md5.txt")
    index_present = index_path in present
    inventory["index_xml"] = index_path if index_present else ""
    checks.append(_check("index_present", "index.xml backbone is present",
                         index_present,
                         index_path if index_present else "index.xml missing"))

    index_bytes = z.read(index_path) if index_present else b""
    md5_present = md5_path in present
    inventory["index_md5"] = md5_path if md5_present else ""
    if not index_present or not md5_present:
        checks.append(_check(
            "index_md5_matches", "index-md5.txt matches index.xml", False,
            "index-md5.txt is missing" if not md5_present
            else "index.xml is missing, so its md5 cannot be verified"))
    else:
        recorded = ""
        m = _MD5_LINE_RE.search(z.read(md5_path).decode("ascii", "replace"))
        recorded = m.group(0).lower() if m else ""
        actual = assembly.md5_hex(index_bytes)
        matches = recorded == actual
        checks.append(_check(
            "index_md5_matches",
            "index-md5.txt matches the md5 of index.xml's bytes", matches,
            f"index-md5.txt={recorded or '(none)'} · md5(index.xml)={actual}"))

    # 6. ca_regional_present ------------------------------------------------
    ca_path = under("m1/ca/ca-regional.xml")
    ca_present = ca_path in present
    inventory["ca_regional"] = ca_path if ca_present else ""
    checks.append(_check(
        "ca_regional_present",
        f"{REGIONAL_STANDARD} regional backbone (m1/ca/ca-regional.xml)",
        ca_present, ca_path if ca_present else "ca-regional.xml missing"))

    # 7. module_folders_present --------------------------------------------
    modules = sorted({seg for n in names
                      for seg in [n[len(root) + 1:].split("/", 1)[0]] if root
                      and n.startswith(root + "/") and _MODULE_RE.match(seg)})
    inventory["modules"] = modules
    checks.append(_check(
        "module_folders_present", "At least one m1..m5 module folder",
        bool(modules), ", ".join(modules) or "no m1..m5 module folder found"))

    # 8. leaf_hrefs_resolve — every backbone leaf href is a real file -------
    leaves = _leaf_hrefs(index_bytes) if index_present else []
    dangling: list[str] = []
    for lf in leaves:
        href = lf["href"]
        op = lf["operation"]
        # a delete carries no payload; an absent href is not a file reference
        exempt = (op == "delete") or (not href)
        # a cross-sequence back-pointer (../<seq>/…) is a lifecycle reference to
        # a prior sequence's file, NOT a file this sequence must ship.
        cross_seq = href.startswith("../")
        resolved = exempt or cross_seq or (under(href) in present)
        leaves_out.append({"leaf_id": lf["leaf_id"], "operation": op,
                           "href": href, "resolved": bool(resolved),
                           "cross_sequence": bool(cross_seq)})
        if not resolved:
            dangling.append(f"{lf['leaf_id'] or '?'} -> {href}")
    checks.append(_check(
        "leaf_hrefs_resolve",
        "Every backbone <leaf> href resolves to a file in the sequence",
        index_present and not dangling,
        "no dangling references" if index_present and not dangling
        else ("index.xml missing" if not index_present
              else "dangling: " + "; ".join(dangling))))

    # 9. file_md5s_match — stored md5 == recomputed md5 over the bytes ------
    md5_mismatches: list[str] = []
    for f in (pkg.get("files") or []):
        path = f.get("path")
        stored = (f.get("md5") or "").lower()
        if not path or path not in present or not stored:
            continue
        actual = assembly.md5_hex(z.read(path))
        if actual != stored:
            md5_mismatches.append(posixpath.basename(path))
    checks.append(_check(
        "file_md5s_match",
        "Each shipped file's md5 matches the md5 recomputed over its bytes",
        not md5_mismatches,
        "all file checksums verified" if not md5_mismatches
        else "checksum mismatch: " + ", ".join(md5_mismatches)))

    # 10. no_missing_leaves — build reported no unresolved leaf bytes -------
    checks.append(_check(
        "no_missing_leaves",
        "No live leaf's document bytes failed to resolve at build time",
        not declared_missing,
        "all leaf bytes resolved" if not declared_missing
        else "missing bytes for: " + ", ".join(
            m.get("href") or m.get("leaf_id") or "?" for m in declared_missing)))

    return _finalize(pkg, checks, inventory, leaves_out,
                     dossier_id=dossier_id, sequence=sequence)


def _finalize(pkg: dict, checks: list, inventory: dict, leaves: list,
              *, dossier_id: str = "", sequence: str = "") -> dict:
    errors = [{"id": c["id"], "label": c["label"], "detail": c["detail"]}
              for c in checks if not c["passed"]]
    return {
        "compatible": not errors,
        "checks": checks,
        "errors": errors,
        "passed_count": sum(1 for c in checks if c["passed"]),
        "check_count": len(checks),
        "inventory": inventory,
        "leaves": leaves,
        "file_count": len(inventory.get("files") or []),
        "dossier_id": dossier_id,
        "sequence": sequence,
        "filename": pkg.get("filename", ""),
        "standard": {"ectd": ECTD_STANDARD, "regional": REGIONAL_STANDARD},
        "disclaimer": DISCLAIMER,
    }
