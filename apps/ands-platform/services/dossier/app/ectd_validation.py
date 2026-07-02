"""eCTD technical validator over an assembled dossier model (REQ-107 gap).

Pure + stdlib. Given an assembled dossier (:mod:`assembly` model — sequences of
leaf operations), replays the lifecycle in order and reports the technical
defects Health Canada's eCTD validation would flag *before* transmission:

  - every LIVE leaf carries a non-empty ``href`` AND ``checksum``, and the
    checksum is a well-formed 32-hex-digit MD5 digest;
  - no ``leaf_id`` is duplicated across the whole dossier;
  - each operation is legal at the point it is applied (new/replace/append/
    delete), reusing :func:`assembly.validate_leaf_operation` semantics against
    the live set reconstructed *up to that leaf*, plus the monolith's
    ``new_has_prior`` rule (a ``new`` leaf must not reference a prior leaf);
  - sequence numbering: every sequence number is a unique four-digit number;
    numbering that does not start at 0000 or has gaps is warned about;
  - ``href`` naming hygiene: lowercase, no spaces (errors), and a ``m1``..``m5``
    module-folder prefix (a warning if it does not match);
  - backbone element structure (ported from the monolith's
    ``ectd.validate_backbone``): index.xml and ca-regional.xml must parse, the
    root element of each must match its pinned schema descriptor (the CA
    Module 1 v2.2 regional backbone + the ICH index), index.xml must carry its
    dossier-id/sequence identification, every ``<leaf>`` must be complete
    (id + href + checksum) and ca-regional.xml must identify the dossier;
  - optional document bytes: a ``.pdf`` whose bytes do not start with ``%PDF``
    is a ``pdf_header`` error; bytes containing ``/Encrypt`` are ``pdf_encrypted``
    (HC rejects secured PDFs).

Every finding carries a stable Health-Canada-v5.3-style rule id (``rule_id``)
alongside its machine ``rule`` name, human ``message`` and offending subject
(``leaf`` — a leaf id, sequence number or document key). The scheme:

    CA-<severity>-<block><nn>
      severity   E = error (blocks transmission), W = warning (advisory)
      block 1xxx leaf inventory integrity (href/checksum presence, duplicate
                 leaf ids, MD5 checksum format)
            2xxx lifecycle operation legality, replayed across sequences
            3xxx file/folder naming hygiene
            4xxx sequence numbering (four-digit, unique, contiguous from 0000)
            5xxx index.xml backbone element structure (ICH eCTD)
            6xxx ca-regional.xml element structure (CA Module 1 v2.2)
            7xxx document payload checks (PDF header / encryption)

Rule ids are stable API: never renumber or reuse an id — retire it instead.

``passed`` is true iff there are zero errors.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from . import assembly, ectd

# a leaf href must live under a module folder m1..m5, e.g. "m1/ca/13-.../131-pm.pdf"
MODULE_FOLDER_RE = re.compile(r"^m[1-5]/")
# an MD5 checksum is exactly 32 hex digits
MD5_HEX_RE = re.compile(r"[0-9a-fA-F]{32}")
PDF_MAGIC = b"%PDF"
PDF_ENCRYPT_MARKER = b"/Encrypt"

# Pinned backbone descriptors (ported from the monolith's descriptor-driven
# ``ectd.validate_backbone``): the expected root element is resolved from the
# descriptor, never asserted in prose. These pin the element structure the
# assembly builder emits for the ICH index + CA Module 1 v2.2 regional file.
INDEX_BACKBONE = {
    "root_element": "ectd-index",
    "admin_attrs": ("dossier-id", "sequence"),
    "leaf_attrs": ("id", "href", "checksum"),
}
CA_REGIONAL_BACKBONE = {
    "root_element": "ca-regional",
    "schema_version": ectd.CA_M1_SCHEMA_VERSION,   # CA Module 1 v2.2
    "dossier_id_element": "dossier-id",
}

# rule name -> stable HC-style rule id (see module docstring for the scheme)
RULE_IDS = {
    # 1xxx — leaf inventory integrity
    "href_required": "CA-E-1001",
    "checksum_required": "CA-E-1002",
    "duplicate_leaf_id": "CA-E-1003",
    "checksum_not_md5": "CA-E-1004",
    # 2xxx — lifecycle operation legality
    "leaf_id_required": "CA-E-2001",
    "operation_invalid": "CA-E-2002",
    "prior_leaf_required": "CA-E-2003",
    "prior_leaf_unknown": "CA-E-2004",
    "new_has_prior": "CA-E-2005",
    # 3xxx — file/folder naming hygiene
    "href_not_lowercase": "CA-E-3001",
    "href_has_space": "CA-E-3002",
    "href_module_folder": "CA-W-3003",
    # 4xxx — sequence numbering
    "sequence_not_numeric": "CA-E-4001",
    "sequence_wrong_width": "CA-E-4002",
    "sequence_duplicate": "CA-E-4003",
    "sequence_not_contiguous": "CA-W-4004",
    "sequence_start_not_0000": "CA-W-4005",
    # 5xxx — index.xml backbone structure
    "backbone_malformed": "CA-E-5001",
    "index_root_unexpected": "CA-E-5002",
    "index_leaf_incomplete": "CA-E-5003",
    "index_admin_missing": "CA-E-5004",
    # 6xxx — ca-regional.xml structure (CA Module 1 v2.2)
    "ca_root_unexpected": "CA-E-6001",
    "ca_dossier_id_missing": "CA-E-6002",
    # 7xxx — document payloads
    "pdf_header": "CA-E-7001",
    "pdf_encrypted": "CA-E-7002",
}
# defensive fallback for a rule the table does not know (e.g. a new rule added
# to assembly.validate_leaf_operation before this table learns its id)
UNMAPPED_RULE_ID = "CA-E-0000"


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _err(rule: str, message: str, leaf) -> dict:
    return {"rule": rule, "rule_id": RULE_IDS.get(rule, UNMAPPED_RULE_ID),
            "message": message, "leaf": leaf}


def _live_leaf_check(dossier: dict, errors: list) -> None:
    """Every live leaf needs an href AND a well-formed MD5 checksum."""
    for lf in assembly.current_view(dossier)["live"]:
        leaf_id = _s(lf.get("leaf_id"))
        if not _s(lf.get("href")):
            errors.append(_err("href_required",
                               "a live leaf must have a non-empty href", leaf_id))
        checksum = _s(lf.get("checksum"))
        if not checksum:
            errors.append(_err("checksum_required",
                               "a live leaf must have a non-empty checksum",
                               leaf_id))
        elif not MD5_HEX_RE.fullmatch(checksum):
            errors.append(_err("checksum_not_md5",
                               f"checksum '{checksum}' is not a 32-hex-digit "
                               "MD5 digest", leaf_id))


def _duplicate_leaf_check(dossier: dict, errors: list) -> None:
    seen: set = set()
    for lf in assembly.leaves_in_order(dossier):
        leaf_id = _s(lf.get("leaf_id"))
        if leaf_id and leaf_id in seen:
            errors.append(_err("duplicate_leaf_id",
                               f"leaf ID '{leaf_id}' appears more than once",
                               leaf_id))
        seen.add(leaf_id)


def _operation_check(dossier: dict, errors: list) -> None:
    """Replay operations in order; each must be legal against the live set so far."""
    live: dict = {}
    for lf in assembly.leaves_in_order(dossier):
        leaf_id = _s(lf.get("leaf_id"))
        op = _s(lf.get("operation"))
        target = _s(lf.get("modified_leaf")) or None
        for e in assembly.validate_leaf_operation(lf, set(live.keys())):
            errors.append(_err(e["rule"], e["message"], leaf_id))
        # ported monolith rule: a 'new' leaf must not point at a prior leaf
        if op == "new" and target:
            errors.append(_err("new_has_prior",
                               "a 'new' operation must not reference a prior "
                               "leaf", leaf_id))
        # advance the live set exactly as compute_current_view would
        if op in ("new", "append"):
            live[leaf_id] = lf
        elif op == "replace":
            if target and target in live:
                live.pop(target)
            live[leaf_id] = lf
        elif op == "delete":
            if target and target in live:
                live.pop(target)


def _sequence_numbering_check(dossier: dict, errors: list,
                              warnings: list) -> None:
    """Sequence numbers are unique four-digit numbers, contiguous from 0000."""
    seen: set = set()
    numeric: list = []
    for s in dossier.get("sequences", []):
        seq = _s(s.get("sequence"))
        if not seq.isdigit():
            errors.append(_err("sequence_not_numeric",
                               f"sequence '{seq}' is not a numeric sequence "
                               "number", seq))
            continue
        if len(seq) != 4:
            errors.append(_err("sequence_wrong_width",
                               f"sequence '{seq}' must be exactly four digits "
                               "(e.g. '0000')", seq))
        if seq in seen:
            errors.append(_err("sequence_duplicate",
                               f"sequence '{seq}' appears more than once", seq))
        seen.add(seq)
        numeric.append(int(seq))
    if not numeric:
        return
    ordered = sorted(set(numeric))
    if ordered[0] != 0:
        warnings.append(_err("sequence_start_not_0000",
                             f"the first sequence is '{ordered[0]:04d}', not "
                             "'0000'", f"{ordered[0]:04d}"))
    if ordered != list(range(ordered[0], ordered[0] + len(ordered))):
        gaps = sorted(set(range(ordered[0], ordered[-1])) - set(ordered))
        warnings.append(_err("sequence_not_contiguous",
                             "sequence numbering has gaps (missing: "
                             + ", ".join(f"{g:04d}" for g in gaps) + ")",
                             None))


def _href_naming_check(dossier: dict, errors: list, warnings: list) -> None:
    for lf in assembly.current_view(dossier)["live"]:
        leaf_id = _s(lf.get("leaf_id"))
        href = _s(lf.get("href"))
        if not href:
            continue
        if href != href.lower():
            errors.append(_err("href_not_lowercase",
                               f"href '{href}' must be lowercase", leaf_id))
        if " " in href:
            errors.append(_err("href_has_space",
                               f"href '{href}' must not contain spaces", leaf_id))
        if not MODULE_FOLDER_RE.match(href):
            warnings.append(_err("href_module_folder",
                                 f"href '{href}' does not match the m1..m5 "
                                 "module-folder pattern", leaf_id))


def _parse_backbone(xml_text: str, name: str, findings: list):
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        findings.append(_err("backbone_malformed",
                             f"{name} failed to parse: {exc}", None))
        return None


def validate_backbone_xml(index_xml: str, ca_regional_xml: str) -> list:
    """Structural findings for a built backbone pair (empty list = clean).

    Port of the monolith's ``ectd.validate_backbone``: each document must be
    well-formed, its root element must match the pinned schema descriptor
    (never a prose assertion), index.xml must carry its dossier-id/sequence
    identification and complete ``<leaf>`` elements (id + href + checksum),
    and the CA Module 1 v2.2 regional file must identify the dossier.
    """
    findings: list = []

    root = _parse_backbone(index_xml, "index.xml", findings)
    if root is not None:
        expected = INDEX_BACKBONE["root_element"]
        if root.tag != expected:
            findings.append(_err("index_root_unexpected",
                                 f"index.xml root element '{root.tag}' does "
                                 "not match the pinned schema root "
                                 f"'{expected}'", None))
        else:
            for attr in INDEX_BACKBONE["admin_attrs"]:
                if not _s(root.get(attr)):
                    findings.append(_err("index_admin_missing",
                                         "index.xml is missing its "
                                         f"'{attr}' identification", None))
            for leaf in root.iter("leaf"):
                leaf_id = _s(leaf.get("id")) or None
                for attr in INDEX_BACKBONE["leaf_attrs"]:
                    if not _s(leaf.get(attr)):
                        findings.append(_err("index_leaf_incomplete",
                                             "a <leaf> in index.xml is "
                                             f"missing its '{attr}'", leaf_id))

    ca = _parse_backbone(ca_regional_xml, "ca-regional.xml", findings)
    if ca is not None:
        expected = CA_REGIONAL_BACKBONE["root_element"]
        version = CA_REGIONAL_BACKBONE["schema_version"]
        if ca.tag != expected:
            findings.append(_err("ca_root_unexpected",
                                 f"ca-regional.xml root element '{ca.tag}' "
                                 "does not match the pinned CA Module 1 "
                                 f"v{version} root '{expected}'", None))
        else:
            node = ca.find(CA_REGIONAL_BACKBONE["dossier_id_element"])
            if node is None or not _s(node.text):
                findings.append(_err("ca_dossier_id_missing",
                                     f"ca-regional.xml (CA Module 1 v{version})"
                                     " must identify the dossier via "
                                     "<dossier-id>", None))
    return findings


def _backbone_check(dossier: dict, errors: list) -> None:
    seqs = [s["sequence"] for s in dossier.get("sequences", [])]
    sequence = seqs[-1] if seqs else "0000"
    try:
        backbone = assembly.build_outline_view(dossier, sequence)["backbone"]
        index_xml = backbone["index.xml"]
        ca_xml = backbone["ca-regional.xml"]
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(_err("backbone_malformed",
                           f"backbone build failed: {exc}", None))
        return
    errors.extend(validate_backbone_xml(index_xml, ca_xml))


def _document_check(documents: dict, errors: list) -> None:
    for key, data in documents.items():
        name = _s(key).lower()
        raw = data if isinstance(data, (bytes, bytearray)) else _s(data).encode()
        raw = bytes(raw)
        # only .pdf-named payloads get header/encryption scrutiny
        if not name.endswith(".pdf"):
            continue
        if not raw.startswith(PDF_MAGIC):
            errors.append(_err("pdf_header",
                               f"document '{key}' is named .pdf but its bytes do "
                               "not start with %PDF", key))
        if PDF_ENCRYPT_MARKER in raw:
            errors.append(_err("pdf_encrypted",
                               f"document '{key}' is an encrypted/secured PDF "
                               "(HC rejects /Encrypt)", key))


def validate(dossier: dict, *, documents: dict | None = None) -> dict:
    """Run the full eCTD technical validation over an assembled ``dossier``.

    ``documents`` optionally maps a doc id / leaf id / filename -> raw bytes; any
    key ending ``.pdf`` is checked for the %PDF magic and for /Encrypt.
    Returns ``{passed, errors, warnings, checked}`` where ``checked`` is the live
    leaf count. Every error/warning carries a stable ``rule_id`` (see the
    module docstring for the CA-E/CA-W scheme). ``passed`` is true iff
    ``errors`` is empty.
    """
    errors: list = []
    warnings: list = []

    _sequence_numbering_check(dossier, errors, warnings)
    _duplicate_leaf_check(dossier, errors)
    _operation_check(dossier, errors)
    _live_leaf_check(dossier, errors)
    _href_naming_check(dossier, errors, warnings)
    _backbone_check(dossier, errors)
    if documents:
        _document_check(documents, errors)

    checked = len(assembly.current_view(dossier)["live"])
    return {"passed": not errors, "errors": errors, "warnings": warnings,
            "checked": checked}
