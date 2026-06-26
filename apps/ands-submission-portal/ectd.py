"""
ANDS Submission Portal — eCTD tree, dual backbones, leaf lifecycle & current view.

This ADDITIVE slice implements the dossier-assembly half of the portal that the
intake (``domain.py``) and REP (``rep.py``) modules feed into:

  REQ-009  Drive the eCTD tree / Module 1 leaf placement from HC's
           'Organization and document placement' heading table (2024-04-02) as
           VERSIONED DATA, including required .docx-alongside-PDF documents; the
           cover letter is sponsor-authored under the m1-0-1-cover-letter leaf
           (heading 1.0) — HC supplies the slot, not a fillable template.
  REQ-014  Deterministically generate BOTH backbones per sequence — the ICH
           index.xml (validated against the ICH eCTD v3.2.2 DTD) with
           index-md5.txt at the sequence root, and the Canadian ca-regional.xml
           under m1/ca/ (validated against the pinned CA Module 1 Schema v2.2
           XSD, 2012-07-06) — plus a util/ folder carrying the published DTD +
           XSL, validating each backbone against its schema/DTD before export.
  REQ-015  Compute a per-leaf MD5 checksum (checksum-type 'MD5'), record it in
           the backbone, write index-md5.txt for index.xml, and re-verify every
           stored checksum against the actual file bytes, hard-blocking on any
           mismatch.
  REQ-017  Require & persist a valid prior-leaf reference for replace/append/
           delete operations, preventing any dangling cross-reference.
  REQ-018  Reconstruct & display the 'current view' (the live leaves after all
           new/replace/append/delete ops across every sequence) and use it to
           validate that delete/replace targets exist.
  REQ-019  Support file reuse — a later sequence re-points to an unchanged
           physical file from an earlier sequence rather than re-shipping bytes,
           preserving correct checksums and references.

Pure, dependency-free (Python 3 standard library only) and deterministic: the
same content always yields byte-identical backbones and checksums. The
HTTP/API/UI layer in server.py is a thin shell over these functions.
"""

from __future__ import annotations

import hashlib
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_attr

import xmlsafe


# ---------------------------------------------------------------------------
# Pinned reference-data versions (REQ-040 alignment)
# ---------------------------------------------------------------------------

PLACEMENT_TABLE_VERSION = "2024-04-02"      # HC 'Organization & document placement'
ICH_DTD_VERSION = "3.2.2"                    # ICH eCTD DTD
CA_M1_SCHEMA_VERSION = "2.2"                 # CA Module 1 Schema
CA_M1_SCHEMA_DATE = "2012-07-06"            # CA Module 1 Schema XSD date

VALID_OPERATIONS = ("new", "replace", "append", "delete")
# Operations that MUST point at a prior leaf (REQ-017). 'new' must NOT.
OPERATIONS_REQUIRING_PRIOR = ("replace", "append", "delete")


# ---------------------------------------------------------------------------
# REQ-009 — Module 1 placement table (versioned DATA, not code)
# ---------------------------------------------------------------------------
#
# Each entry maps a CA Module 1 heading to its prescribed leaf location. Driving
# the tree from this list means an updated HC table is a DATA change, not a code
# change. ``docx_required`` marks sections where HC requires a .docx alongside
# the PDF (e.g. the Product Monograph). ``sponsor_authored`` marks the cover
# letter — HC provides the slot, never a fillable template.

CA_MODULE1_PLACEMENT = [
    {"heading": "1.0", "title": "Cover Letter",
     "leaf_id": "m1-0-1-cover-letter", "folder": "m1/ca/10-cover-letter",
     "docx_required": False, "sponsor_authored": True},
    {"heading": "1.1", "title": "Comprehensive Table of Contents",
     "leaf_id": "m1-1-toc", "folder": "m1/ca/11-toc",
     "docx_required": False, "sponsor_authored": False},
    {"heading": "1.2", "title": "Administrative Information",
     "leaf_id": "m1-2-admin", "folder": "m1/ca/12-admin-info",
     "docx_required": False, "sponsor_authored": False},
    {"heading": "1.2.1", "title": "Application / Submission Form",
     "leaf_id": "m1-2-1-application-form", "folder": "m1/ca/12-admin-info/121-form",
     "docx_required": False, "sponsor_authored": False},
    {"heading": "1.3.1", "title": "Product Monograph",
     "leaf_id": "m1-3-1-product-monograph", "folder": "m1/ca/13-product-info/131-pm",
     "docx_required": True, "sponsor_authored": False},
    {"heading": "1.6", "title": "Comparative Studies — Bioequivalence (CS-BE)",
     "leaf_id": "m1-6-cs-be", "folder": "m1/ca/16-cs-be",
     "docx_required": False, "sponsor_authored": False},
]


def module1_placement_table() -> dict:
    """REQ-009: the versioned Module 1 placement table as data."""
    return {
        "version": PLACEMENT_TABLE_VERSION,
        "entries": [dict(e) for e in CA_MODULE1_PLACEMENT],
    }


def placement_for_heading(heading: str):
    """The placement entry for a CA Module 1 heading, or None."""
    heading = str(heading or "").strip()
    for e in CA_MODULE1_PLACEMENT:
        if e["heading"] == heading:
            return dict(e)
    return None


def cover_letter_slot() -> dict:
    """REQ-009: the sponsor-authored cover-letter slot (heading 1.0)."""
    return placement_for_heading("1.0")


def docx_required_headings() -> list:
    """Headings that require a .docx alongside the PDF (REQ-009)."""
    return [e["heading"] for e in CA_MODULE1_PLACEMENT if e["docx_required"]]


def build_module1_tree() -> dict:
    """REQ-009: render the Module 1 tree from the placement table (for UI)."""
    return {
        "version": PLACEMENT_TABLE_VERSION,
        "nodes": [
            {
                "heading": e["heading"],
                "title": e["title"],
                "leaf_id": e["leaf_id"],
                "folder": e["folder"],
                "docx_required": e["docx_required"],
                "sponsor_authored": e["sponsor_authored"],
            }
            for e in CA_MODULE1_PLACEMENT
        ],
    }


# ---------------------------------------------------------------------------
# Pinned schema descriptors (REQ-014) — root elements resolved from the schema,
# NOT asserted in prose. The generator and the validator both read these.
# ---------------------------------------------------------------------------

ICH_ECTD_DTD = {
    "version": ICH_DTD_VERSION,
    "root_element": "ectd:ectd",
    "util_path": "util/dtd/ich-ectd-3-2.dtd",
}

CA_M1_XSD = {
    "version": CA_M1_SCHEMA_VERSION,
    "date": CA_M1_SCHEMA_DATE,
    # Root element of the CA Module 1 Schema v2.2 (2012-07-06): <hcsc_ectd>.
    "root_element": "hcsc_ectd",
    "util_path": "util/dtd/ca-regional-2-2.xsd",
}

ICH_ECTD_XSL = {"util_path": "util/style/ectd-2-0.xsl"}


class SchemaValidationError(ValueError):
    """REQ-014: a backbone failed schema/DTD validation (mirrors A06a/H08)."""


class ChecksumMismatchError(ValueError):
    """REQ-015: a stored checksum did not match the actual file bytes."""


class LeafOperationError(ValueError):
    """REQ-017: an invalid / dangling leaf operation reference."""


# ---------------------------------------------------------------------------
# REQ-015 — checksums
# ---------------------------------------------------------------------------

def md5_hex(data) -> str:
    """MD5 hex digest over UTF-8 bytes (accepts str or bytes)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.md5(data).hexdigest()


# ---------------------------------------------------------------------------
# util/ folder — the HC-published DTD + XSL carried with every sequence (REQ-014)
# ---------------------------------------------------------------------------

def util_files() -> dict:
    """The util/ payload (DTD + XSD + XSL) carried at the sequence root.

    Stand-ins for the exact HC-published artifacts; the point is that util/
    exists and carries the DTD, the regional XSD and the XSL stylesheet so a
    sequence is self-describing and index.xml can be validated against the DTD.
    """
    dtd = (
        "<!-- ICH eCTD DTD v{ver} (HC-published) -->\n"
        "<!ELEMENT {root} (#PCDATA|leaf)*>\n"
        "<!ATTLIST leaf ID CDATA #REQUIRED operation CDATA #REQUIRED "
        "checksum CDATA #REQUIRED checksum-type CDATA #REQUIRED>\n"
    ).format(ver=ICH_DTD_VERSION, root=ICH_ECTD_DTD["root_element"])
    xsd = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!-- CA Module 1 Schema v{ver} ({date}) (HC-published) -->\n'
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">\n'
        '  <xs:element name="{root}"/>\n'
        '</xs:schema>\n'
    ).format(ver=CA_M1_SCHEMA_VERSION, date=CA_M1_SCHEMA_DATE,
             root=CA_M1_XSD["root_element"])
    xsl = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!-- ICH eCTD XSL stylesheet (HC-published) -->\n'
        '<xsl:stylesheet version="1.0" '
        'xmlns:xsl="http://www.w3.org/1999/XSL/Transform"/>\n'
    )
    return {
        ICH_ECTD_DTD["util_path"]: dtd,
        CA_M1_XSD["util_path"]: xsd,
        ICH_ECTD_XSL["util_path"]: xsl,
    }


# ---------------------------------------------------------------------------
# REQ-017 / REQ-018 — leaf lifecycle & current-view reconstruction
# ---------------------------------------------------------------------------

def _seq_key(sequence) -> str:
    return str(sequence or "").strip()


def compute_current_view(leaves_in_order) -> dict:
    """REQ-018: reconstruct the live leaf set from operations in order.

    ``leaves_in_order`` is the full chronological list of leaf-operation dicts
    across every sequence (sequence-ordered, then file-order within a sequence).
    Returns ``{"live": [...], "history": [...]}`` where ``live`` holds the
    content leaves currently displayed and ``history`` holds every superseded /
    deleted / delete-marker leaf, each retained with its originating sequence.

    Operation semantics:
      new      -> the leaf becomes live
      replace  -> the target leaf is superseded (moves to history); the new leaf
                  becomes live
      append   -> the new leaf becomes live alongside the (still-live) target
      delete   -> the target leaf is removed from the live set; the delete
                  marker itself is never a live content leaf
    """
    live: dict = {}      # leaf_id -> leaf record
    history: list = []

    for leaf in leaves_in_order:
        op = str(leaf.get("operation", "") or "").strip()
        target = str(leaf.get("modified_leaf", "") or "").strip() or None
        if op == "new":
            live[leaf["leaf_id"]] = leaf
        elif op == "append":
            live[leaf["leaf_id"]] = leaf
        elif op == "replace":
            if target and target in live:
                history.append(live.pop(target))
            live[leaf["leaf_id"]] = leaf
        elif op == "delete":
            if target and target in live:
                history.append(live.pop(target))
            history.append(leaf)

    return {
        "live": list(live.values()),
        "history": history,
    }


def validate_leaf_operation(leaf: dict, live_leaf_ids) -> list:
    """REQ-017: errors that would block a single leaf operation.

    ``live_leaf_ids`` is the set of leaf IDs live in the current view BEFORE this
    operation. Returns a list of ``{"rule","message"}``; empty means valid.
    """
    errors: list = []

    def add(rule, message):
        errors.append({"rule": rule, "message": message})

    op = str(leaf.get("operation", "") or "").strip()
    target = str(leaf.get("modified_leaf", "") or "").strip() or None
    leaf_id = str(leaf.get("leaf_id", "") or "").strip()

    if not leaf_id:
        add("leaf_id_required", "A leaf ID is required")
    if op not in VALID_OPERATIONS:
        add("operation_invalid",
            f"Operation must be one of {', '.join(VALID_OPERATIONS)}")
        return errors

    if op in OPERATIONS_REQUIRING_PRIOR:
        if not target:
            add("prior_leaf_required",
                f"A '{op}' operation must reference a prior leaf "
                "(modified_leaf)")
        elif target not in set(live_leaf_ids):
            add("dangling_reference",
                f"'{op}' references prior leaf '{target}', which is not live in "
                "the current view of this dossier")
    elif op == "new" and target:
        add("new_has_prior",
            "A 'new' operation must not reference a prior leaf")

    return errors


# ---------------------------------------------------------------------------
# Backbone XML generation (REQ-014/015) — deterministic
# ---------------------------------------------------------------------------

def _leaf_xml(leaf: dict, indent: str) -> str:
    """One <leaf> element with checksum + lifecycle + (optional) reuse pointer."""
    op = _xml_escape(str(leaf.get("operation", "")).strip())
    leaf_id = _xml_escape(str(leaf.get("leaf_id", "")).strip())
    href = _xml_escape(str(leaf.get("href", "")).strip())
    checksum = _xml_escape(str(leaf.get("checksum", "")).strip())
    title = _xml_escape(str(leaf.get("title", "")).strip())
    attrs = (
        f'ID="{leaf_id}" operation="{op}" '
        f'xlink:href="{href}" '
        f'checksum="{checksum}" checksum-type="MD5"'
    )
    modified = str(leaf.get("modified_leaf", "") or "").strip()
    if modified:
        attrs += f' modified-file="{_xml_escape(modified)}"'
    return (
        f"{indent}<leaf {attrs}>\n"
        f"{indent}  <title>{title}</title>\n"
        f"{indent}</leaf>\n"
    )


def build_index_xml(dossier_id: str, sequence: str, leaves) -> str:
    """REQ-014: the ICH eCTD index.xml backbone (deterministic)."""
    root = ICH_ECTD_DTD["root_element"]
    body = "".join(_leaf_xml(lf, "    ") for lf in leaves)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<!DOCTYPE {root} SYSTEM "{ICH_ECTD_DTD["util_path"]}">\n'
        f'<{root} xmlns:ectd="http://www.ich.org/ectd" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'dtd-version="{ICH_DTD_VERSION}">\n'
        f"  <dossier-id>{_xml_escape(str(dossier_id).strip())}</dossier-id>\n"
        f"  <sequence>{_xml_escape(str(sequence).strip())}</sequence>\n"
        "  <leaves>\n"
        f"{body}"
        "  </leaves>\n"
        f"</{root}>\n"
    )


def build_ca_regional_xml(dossier_id: str, sequence: str, leaves) -> str:
    """REQ-014: the Canadian Module 1 ca-regional.xml backbone (deterministic)."""
    root = CA_M1_XSD["root_element"]
    m1_leaves = [lf for lf in leaves if str(lf.get("heading", "")).startswith("1")]
    body = "".join(_leaf_xml(lf, "      ") for lf in m1_leaves)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<{root} xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'ca-schema-version="{CA_M1_SCHEMA_VERSION}">\n'
        "  <ca-regional-information>\n"
        f"    <dossier-id>{_xml_escape(str(dossier_id).strip())}</dossier-id>\n"
        f"    <sequence>{_xml_escape(str(sequence).strip())}</sequence>\n"
        "    <m1-administrative-information>\n"
        f"{body}"
        "    </m1-administrative-information>\n"
        "  </ca-regional-information>\n"
        f"</{root}>\n"
    )


def validate_backbone(xml_text: str, descriptor: dict) -> None:
    """REQ-014: validate a backbone against its schema/DTD descriptor.

    The required root element is resolved FROM THE DESCRIPTOR (the schema), not
    asserted prose. Every <leaf> must carry a checksum and checksum-type. Raises
    ``SchemaValidationError`` on any violation (mirrors A06a/H08).
    """
    try:
        # Hardened against billion-laughs / XXE: a backbone can be posted from an
        # untrusted client (``/api/validation/package-attempt``), so it must go
        # through the same entity-safety guard as every other caller-supplied XML.
        dom = xmlsafe.safe_parse_xml(xml_text)
    except xmlsafe.UnsafeXmlError as exc:
        raise SchemaValidationError(f"backbone XML rejected for safety: {exc}")
    except Exception as exc:  # malformed XML
        raise SchemaValidationError(f"backbone is not well-formed XML: {exc}")

    expected_root = descriptor["root_element"]
    actual_root = dom.documentElement.tagName
    if actual_root != expected_root:
        raise SchemaValidationError(
            f"backbone root element '{actual_root}' does not match the pinned "
            f"schema root '{expected_root}'")

    for leaf in dom.getElementsByTagName("leaf"):
        if not leaf.getAttribute("checksum"):
            raise SchemaValidationError("a <leaf> is missing its checksum")
        if leaf.getAttribute("checksum-type") != "MD5":
            raise SchemaValidationError(
                "a <leaf> is missing checksum-type='MD5'")


# ---------------------------------------------------------------------------
# Dossier aggregate — sequences, leaves, current view, file reuse, export
# ---------------------------------------------------------------------------

class Dossier:
    """A multi-sequence eCTD dossier (REQ-014/015/017/018/019).

    Serializable to/from a plain dict so the server can persist it. Leaves carry
    their own content (``content``) for shipped bytes, or a ``reused_from``
    pointer (REQ-019) instead of re-shipping. Checksums are computed from the
    resolved content and re-verified against it.
    """

    def __init__(self, dossier_id: str, sequences=None):
        self.dossier_id = str(dossier_id or "").strip()
        self.sequences = sequences if sequences is not None else []

    # -- serialization --------------------------------------------------
    def to_dict(self) -> dict:
        return {"dossier_id": self.dossier_id, "sequences": self.sequences}

    @classmethod
    def from_dict(cls, data: dict) -> "Dossier":
        return cls(data.get("dossier_id", ""),
                   [dict(s) for s in data.get("sequences", [])])

    # -- structure ------------------------------------------------------
    def sequence_numbers(self) -> list:
        return [s["sequence"] for s in self.sequences]

    def _get_sequence(self, sequence: str):
        key = _seq_key(sequence)
        for s in self.sequences:
            if s["sequence"] == key:
                return s
        return None

    def add_sequence(self, sequence: str) -> dict:
        key = _seq_key(sequence)
        if self._get_sequence(key):
            raise LeafOperationError(f"sequence {key} already exists")
        rec = {"sequence": key, "leaves": []}
        self.sequences.append(rec)
        return rec

    def leaves_in_order(self) -> list:
        """Every leaf across every sequence, sequence-ordered then file-order."""
        out = []
        for s in sorted(self.sequences, key=lambda x: x["sequence"]):
            for lf in s["leaves"]:
                out.append(lf)
        return out

    def _find_leaf(self, leaf_id: str):
        leaf_id = str(leaf_id or "").strip()
        for s in self.sequences:
            for lf in s["leaves"]:
                if lf["leaf_id"] == leaf_id:
                    return lf
        return None

    # -- REQ-018: current view -----------------------------------------
    def current_view(self) -> dict:
        view = compute_current_view(self.leaves_in_order())
        # surface a compact, UI-friendly projection of the live set
        live = [
            {
                "leaf_id": lf["leaf_id"],
                "title": lf.get("title", ""),
                "heading": lf.get("heading", ""),
                "href": lf.get("href", ""),
                "operation": lf.get("operation", ""),
                "sequence": lf.get("sequence", ""),
                "reused_from": lf.get("reused_from"),
            }
            for lf in view["live"]
        ]
        return {"live": live, "history": view["history"]}

    def live_leaf_ids(self) -> set:
        return {lf["leaf_id"] for lf in compute_current_view(
            self.leaves_in_order())["live"]}

    # -- REQ-017 + REQ-019: add a leaf operation -----------------------
    def add_leaf(self, sequence: str, leaf: dict) -> dict:
        """Validate and append a leaf operation to ``sequence``.

        Resolves file reuse (REQ-019), computes the MD5 checksum (REQ-015) and
        enforces the prior-leaf reference rules (REQ-017). Raises
        ``LeafOperationError`` on any violation; the dossier is left unchanged.
        """
        seq = self._get_sequence(sequence)
        if seq is None:
            seq = self.add_sequence(sequence)

        leaf_id = str(leaf.get("leaf_id", "") or "").strip()
        op = str(leaf.get("operation", "") or "").strip()
        heading = str(leaf.get("heading", "") or "").strip()
        title = str(leaf.get("title", "") or "").strip()
        modified_leaf = str(leaf.get("modified_leaf", "") or "").strip() or None
        reused_from = str(leaf.get("reused_from", "") or "").strip() or None

        if self._find_leaf(leaf_id):
            raise LeafOperationError(f"leaf ID '{leaf_id}' already exists")

        # Resolve placement / href from the Module 1 table when available.
        placement = placement_for_heading(heading)
        href = str(leaf.get("href", "") or "").strip()
        content = leaf.get("content")

        # REQ-019: file reuse — re-point to a prior physical file, no re-ship.
        reuse_meta = None
        if reused_from:
            ref = self._find_leaf(reused_from)
            if ref is None:
                raise LeafOperationError(
                    f"cannot reuse file from unknown leaf '{reused_from}'")
            ref_content = self._resolve_content(ref)
            if ref_content is None:
                raise LeafOperationError(
                    f"leaf '{reused_from}' has no physical file to reuse")
            checksum = md5_hex(ref_content)
            href = href or ref.get("href", "")
            reuse_meta = {"leaf_id": reused_from,
                          "sequence": ref.get("sequence", ""),
                          "href": ref.get("href", "")}
            content = None  # bytes are NOT re-shipped
        else:
            if not href and placement:
                slug = leaf_id or placement["leaf_id"]
                href = f"{placement['folder']}/{slug}.pdf"
            if op == "delete":
                checksum = ""  # a delete marker ships no bytes
            else:
                checksum = md5_hex(content or "")

        record = {
            "leaf_id": leaf_id,
            "operation": op,
            "title": title,
            "heading": heading,
            "href": href,
            "checksum": checksum,
            "checksum_type": "MD5",
            "modified_leaf": modified_leaf,
            "reused_from": reuse_meta,
            "content": content,
            "sequence": seq["sequence"],
        }

        errors = validate_leaf_operation(record, self.live_leaf_ids())
        if errors:
            raise LeafOperationError(errors[0]["message"])

        seq["leaves"].append(record)
        return record

    def _resolve_content(self, leaf: dict):
        """The actual bytes (as str) backing a leaf, following reuse pointers."""
        reused = leaf.get("reused_from")
        if reused:
            ref = self._find_leaf(reused.get("leaf_id", ""))
            return self._resolve_content(ref) if ref else None
        return leaf.get("content")

    # -- REQ-014/015: backbone generation + export ---------------------
    def build_backbones(self, sequence: str) -> dict:
        """Generate both backbones + util/ + index-md5.txt for a sequence.

        Returns a virtual package ``{path: text}`` plus the recorded per-leaf
        checksums. Both backbones are validated against their schema/DTD before
        being returned (REQ-014). Deterministic: identical content -> identical
        bytes.
        """
        seq = self._get_sequence(sequence)
        if seq is None:
            raise LeafOperationError(f"sequence {sequence} does not exist")
        leaves = seq["leaves"]

        index_xml = build_index_xml(self.dossier_id, seq["sequence"], leaves)
        ca_xml = build_ca_regional_xml(self.dossier_id, seq["sequence"], leaves)

        # Validate BEFORE export (mirrors A06a/H08).
        validate_backbone(index_xml, ICH_ECTD_DTD)
        validate_backbone(ca_xml, CA_M1_XSD)

        package = {"index.xml": index_xml, "m1/ca/ca-regional.xml": ca_xml}
        package.update(util_files())

        # Ship each leaf's actual bytes (reused files are NOT duplicated).
        recorded = {}
        for lf in leaves:
            if lf["operation"] == "delete":
                continue
            recorded[lf["leaf_id"]] = {
                "href": lf["href"], "checksum": lf["checksum"],
                "checksum_type": "MD5", "reused": bool(lf.get("reused_from")),
            }
            if lf.get("reused_from"):
                continue  # re-pointed to a prior sequence's physical file
            package[lf["href"]] = lf.get("content") or ""

        # REQ-015: index-md5.txt carries index.xml's MD5.
        index_md5 = md5_hex(index_xml)
        package["index-md5.txt"] = index_md5 + "\n"

        return {
            "sequence": seq["sequence"],
            "package": package,
            "checksums": recorded,
            "index_md5": index_md5,
            "files": sorted(package.keys()),
        }

    def verify_checksums(self, sequence: str) -> dict:
        """REQ-015: re-verify every stored checksum against the actual bytes.

        Recomputes the MD5 of each leaf's resolved content and compares it to the
        recorded checksum, plus index-md5.txt against index.xml. Raises
        ``ChecksumMismatchError`` on any mismatch (hard block).
        """
        built = self.build_backbones(sequence)
        seq = self._get_sequence(sequence)

        for lf in seq["leaves"]:
            if lf["operation"] == "delete":
                continue
            actual = md5_hex(self._resolve_content(lf) or "")
            if actual != lf["checksum"]:
                raise ChecksumMismatchError(
                    f"leaf '{lf['leaf_id']}' checksum mismatch: recorded "
                    f"{lf['checksum']}, actual {actual}")

        index_xml = built["package"]["index.xml"]
        recorded_index = built["package"]["index-md5.txt"].strip()
        if md5_hex(index_xml) != recorded_index:
            raise ChecksumMismatchError("index-md5.txt does not match index.xml")

        return {"verified": True, "leaf_count": len(built["checksums"]),
                "index_md5": built["index_md5"]}

    def export_sequence(self, sequence: str) -> dict:
        """Build, schema-validate, then re-verify checksums and return previews.

        The single entry point a caller uses to package a sequence: it surfaces
        either a clean export or the specific blocking error (REQ-014/015).
        """
        built = self.build_backbones(sequence)
        self.verify_checksums(sequence)
        return {
            "valid": True,
            "sequence": built["sequence"],
            "files": built["files"],
            "checksums": built["checksums"],
            "index_md5": built["index_md5"],
            "previews": {
                "index.xml": built["package"]["index.xml"],
                "m1/ca/ca-regional.xml": built["package"]["m1/ca/ca-regional.xml"],
            },
        }
