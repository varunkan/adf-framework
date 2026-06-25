"""
ANDS Submission Portal — versioned validation-rules engine, cross-document
consistency, pre-submission report, and schema/service failure resume path.

This ADDITIVE slice sits on top of the intake (``domain.py``), REP
(``rep.py``) and eCTD-assembly (``ectd.py``) modules. It implements the
Health-Canada-style validation surface that turns an assembled transaction into
a "first-pass clean" package:

  REQ-022  A VERSIONED validation-rules engine (default v5.3, effective
           2025-05-31; the active version is selectable) that models each rule
           as {rule_id, category, severity, description, ruleset_version} across
           HC's General / PDF / Referenced / XML / ICH-Backbone / Regional /
           STF / REP categories, using the two-tier Error/Warning severity
           model — BLOCKING on any Error, surfacing Warnings non-blocking.
  REQ-023  Running those rules CONTINUOUSLY (inline) during authoring, surfacing
           each defect in a severity-colored gutter mapped to the exact
           file/node, with a one-click fix where remediable — not only as a
           terminal gate.
  REQ-024  A downloadable pre-submission validation report mirroring HC's output
           — a categorized Error/Warning list with rule IDs against the pinned
           ruleset version, plus a backbone preview (rendered index.xml and
           ca-regional.xml, and REP XML rendered via the version-matched HC REP
           XML stylesheet) with each leaf's MD5 verified against the actual
           bytes.
  REQ-045  WHEN a generated REP CO/RT/PI XML or backbone fails HC schema/DTD
           validation, or an external HC/FDA service (FDA ESG, REP ID return) is
           unavailable, surfacing the specific schema-validation error or
           service-outage condition, RETAINING the in-progress work without data
           loss, and providing a guided retry/resume path.
  REQ-059  Cross-document and metadata consistency across a transaction —
           DIN / Dossier ID / Company ID agreement among CO/RT/PI, cover letter
           and ca-regional.xml; product-name / strength / dosage-form
           consistency between PI metadata and content; and STF (Study Tagging
           File) presence & correctness where Module 5 study data (e.g. BE study
           reports) requires it — BLOCKING on inconsistencies before packaging.
  REQ-070  An A02 (file & folder security/readability) check that verifies every
           file and folder in the transaction is readable and free of
           access-permission restrictions, as a DISTINCT general-category check
           separate from PDF encryption (A09).

Pure, dependency-free (Python 3 standard library only) and deterministic. The
HTTP/API/UI layer in server.py is a thin shell over these functions.
"""

from __future__ import annotations

import re
import unicodedata
from xml.dom.minidom import parseString
from xml.parsers.expat import ParserCreate
from xml.sax.saxutils import escape as _xml_escape

import ectd
import rep


# ---------------------------------------------------------------------------
# Safe XML parsing (security: entity-expansion / external-entity hardening)
# ---------------------------------------------------------------------------
#
# Several validation endpoints parse caller-supplied XML (an ``index.xml`` /
# ``ca-regional.xml`` posted to ``/api/validation/run`` etc., or a generated REP
# artifact). Python's stdlib ``xml.dom.minidom``/expat does NOT defend against a
# maliciously crafted document: a tiny "billion laughs" payload of nested
# internal ``<!ENTITY>`` declarations expands to gigabytes (a CPU/memory DoS),
# and a ``SYSTEM`` entity can exfiltrate local files / hit the network (XXE).
#
# eCTD backbones legitimately carry a ``<!DOCTYPE ... SYSTEM "util/…dtd">`` that
# references an *external* DTD by name but NEVER declares internal entities, so
# we can neutralise both attack classes by refusing any ``<!ENTITY>`` declaration
# and never resolving an external entity, while leaving every well-formed,
# entity-free document (including the real eCTD index) parsing exactly as before.


class UnsafeXmlError(ValueError):
    """Raised when XML carries a DTD entity declaration or external entity
    reference — the building blocks of billion-laughs / XXE attacks."""


def _assert_xml_entity_safe(xml_text) -> None:
    """Reject entity-expansion (billion laughs) and external-entity (XXE) XML.

    Runs a fast, non-expanding expat pass that fires on the *declaration* of any
    entity (before it could ever be expanded) and on any external-entity
    reference, so a hostile payload is refused before it can do work. Raises
    :class:`UnsafeXmlError`; lets a genuinely malformed document fall through to
    the caller's own well-formedness handling.
    """
    parser = ParserCreate()
    # Never parse external parameter entities (closes the XXE vector outright).
    parser.SetParamEntityParsing(0)  # XML_PARAM_ENTITY_PARSING_NEVER

    def _reject_entity_decl(*_args):
        raise UnsafeXmlError("XML entity declarations are not permitted")

    def _reject_external_ref(*_args):
        raise UnsafeXmlError("external XML entities are not permitted")

    parser.EntityDeclHandler = _reject_entity_decl
    parser.ExternalEntityRefHandler = _reject_external_ref
    data = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    try:
        parser.Parse(data, True)
    except UnsafeXmlError:
        raise
    except Exception:
        # Malformed XML that is not an entity attack — defer to the caller, which
        # parses it again and surfaces its own "not well-formed" diagnostic.
        return


def safe_parse_xml(xml_text):
    """Parse caller-supplied XML into a minidom DOM, hardened against
    entity-expansion and external-entity attacks. Use this for any XML that did
    not originate inside the portal."""
    _assert_xml_entity_safe(xml_text)
    return parseString(xml_text)


# ---------------------------------------------------------------------------
# REQ-022 — versioned ruleset registry
# ---------------------------------------------------------------------------

SEVERITY_ERROR = "Error"
SEVERITY_WARNING = "Warning"

# HC's defect categories (mirrors the published validation-criteria grouping).
CATEGORIES = (
    "General", "PDF", "Referenced", "XML",
    "ICH-Backbone", "Regional", "STF", "REP",
)

# Severity → gutter colour for the inline authoring view (REQ-023).
SEVERITY_COLOUR = {SEVERITY_ERROR: "#b3261e", SEVERITY_WARNING: "#b26a00"}

# Published ruleset versions with their effective dates. The DEFAULT/ACTIVE
# version is selectable; v5.3 is current (effective 2025-05-31).
RULESETS = {
    "5.2": {"version": "5.2", "effective": "2024-04-01"},
    "5.3": {"version": "5.3", "effective": "2025-05-31"},
}
ACTIVE_RULESET_VERSION = "5.3"


def _vtuple(version: str) -> tuple:
    return tuple(int(p) for p in str(version).split("."))


def list_ruleset_versions() -> list:
    """REQ-022: every published ruleset version, newest first, active flagged."""
    out = []
    for v in sorted(RULESETS, key=_vtuple, reverse=True):
        rec = dict(RULESETS[v])
        rec["active"] = (v == ACTIVE_RULESET_VERSION)
        out.append(rec)
    return out


class UnknownRulesetError(ValueError):
    """REQ-022: a non-published ruleset version was requested."""


# ---------------------------------------------------------------------------
# Rule checks — each returns a list of partial findings
# {file, node, message, remediable, fix_id}; the engine stamps on the rule's
# {rule_id, category, severity, description, ruleset_version}.
# ---------------------------------------------------------------------------

def _files(ctx) -> list:
    return list(ctx.get("files") or [])


def _leaves(ctx) -> list:
    return list(ctx.get("leaves") or [])


def _norm(value) -> str:
    return str(value if value is not None else "").strip()


def _check_a02(ctx) -> list:
    """REQ-070 / rule A02 — file & folder security & readability.

    Every file AND folder in the transaction must be readable and free of
    access-permission restrictions. This is DISTINCT from PDF encryption (A09):
    A02 is about OS-level read/permission access on any node, file or folder.
    """
    out = []
    for f in _files(ctx):
        if not f.get("readable", True):
            kind = "folder" if f.get("is_dir") else "file"
            out.append({
                "file": _norm(f.get("path")),
                "node": _norm(f.get("path")),
                "message": (f"{kind} '{_norm(f.get('path'))}' is not readable or "
                            "has an access-permission restriction (A02)"),
                "remediable": True,
                "fix_id": "grant-read",
            })
    return out


def _check_a09(ctx) -> list:
    """Rule A09 — PDF encryption (kept DISTINCT from A02, REQ-070)."""
    out = []
    for f in _files(ctx):
        if f.get("kind") == "pdf" and f.get("encrypted"):
            out.append({
                "file": _norm(f.get("path")),
                "node": _norm(f.get("path")),
                "message": (f"PDF '{_norm(f.get('path'))}' is encrypted; HC "
                            "requires unencrypted PDFs (A09)"),
                "remediable": True,
                "fix_id": "decrypt-pdf",
            })
    return out


def _check_referenced(ctx) -> list:
    """Referenced category — every leaf href must resolve to a shipped file."""
    paths = {_norm(f.get("path")) for f in _files(ctx)}
    out = []
    for lf in _leaves(ctx):
        href = _norm(lf.get("href"))
        if href and paths and href not in paths:
            out.append({
                "file": href,
                "node": _norm(lf.get("leaf_id")),
                "message": (f"leaf '{_norm(lf.get('leaf_id'))}' references "
                            f"'{href}', which is not present in the transaction"),
                "remediable": False,
                "fix_id": "",
            })
    return out


def _check_xml_wellformed(ctx) -> list:
    """XML category — provided backbones must be well-formed."""
    out = []
    for key, label in (("index_xml", "index.xml"),
                       ("ca_regional_xml", "ca-regional.xml")):
        xml = ctx.get(key)
        if not xml:
            continue
        try:
            safe_parse_xml(xml)
        except UnsafeXmlError as exc:
            out.append({
                "file": label, "node": label,
                "message": f"{label} was rejected as unsafe XML: {exc}",
                "remediable": False, "fix_id": "",
            })
        except Exception as exc:  # malformed
            out.append({
                "file": label, "node": label,
                "message": f"{label} is not well-formed XML: {exc}",
                "remediable": False, "fix_id": "",
            })
    return out


def _check_backbone_checksums(ctx) -> list:
    """ICH-Backbone category — every leaf carries a MD5 checksum."""
    out = []
    for lf in _leaves(ctx):
        if _norm(lf.get("operation")) == "delete":
            continue
        if not _norm(lf.get("checksum")):
            out.append({
                "file": _norm(lf.get("href")),
                "node": _norm(lf.get("leaf_id")),
                "message": (f"leaf '{_norm(lf.get('leaf_id'))}' is missing its "
                            "MD5 checksum in the backbone"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_regional(ctx) -> list:
    """Regional category — ca-regional dossier-id must match the transaction."""
    out = []
    ca = ctx.get("ca_regional") or {}
    dossier = _norm(ctx.get("dossier_id"))
    ca_dossier = _norm(ca.get("dossier_id"))
    if dossier and ca_dossier and ca_dossier != dossier:
        out.append({
            "file": "m1/ca/ca-regional.xml", "node": "dossier-id",
            "message": (f"ca-regional.xml dossier-id '{ca_dossier}' does not "
                        f"match the transaction dossier-id '{dossier}'"),
            "remediable": False, "fix_id": "",
        })
    return out


def _check_stf(ctx) -> list:
    """STF category (REQ-059) — Module 5 study data that requires a Study
    Tagging File must have a present, valid STF (e.g. a BE study report)."""
    out = []
    for study in (ctx.get("module5_studies") or []):
        if not study.get("requires_stf", True):
            continue
        sid = _norm(study.get("id") or study.get("type"))
        if not study.get("stf_present"):
            out.append({
                "file": _norm(study.get("folder")),
                "node": sid,
                "message": (f"Module 5 study '{sid}' requires a Study Tagging "
                            "File (STF) but none is present"),
                "remediable": False, "fix_id": "",
            })
        elif not study.get("stf_valid", True):
            out.append({
                "file": _norm(study.get("folder")),
                "node": sid,
                "message": (f"the Study Tagging File for study '{sid}' is "
                            "present but malformed/incorrect"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_rep_identifier_agreement(ctx) -> list:
    """REP category (REQ-059) — DIN / Dossier ID / Company ID must agree across
    CO, RT, PI, the cover letter and ca-regional.xml."""
    out = []
    docs = {
        "REP CO": ctx.get("rep", {}).get("co") or {},
        "REP RT": ctx.get("rep", {}).get("rt") or {},
        "REP PI": ctx.get("rep", {}).get("pi") or {},
        "cover letter": ctx.get("cover_letter") or {},
        "ca-regional.xml": ctx.get("ca_regional") or {},
    }
    for field, label in (("dossier_id", "Dossier ID"),
                         ("company_id", "Company ID"),
                         ("din", "DIN")):
        seen = {}
        for doc_name, doc in docs.items():
            val = _norm(doc.get(field))
            if val:
                seen.setdefault(val, []).append(doc_name)
        if len(seen) > 1:
            detail = "; ".join(
                f"{v} in {', '.join(srcs)}" for v, srcs in seen.items())
            out.append({
                "file": "transaction", "node": field,
                "message": (f"{label} disagrees across documents: {detail}"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_rep_product_consistency(ctx) -> list:
    """REP category (REQ-059) — product name / strength / dosage-form in the PI
    metadata must match the transaction content."""
    out = []
    pi = ctx.get("rep", {}).get("pi")
    if not pi:
        return out
    for field, label, content_key in (
        ("product_name", "Product name", "drug_product"),
        ("strength", "Strength", "strength"),
        ("dosage_form", "Dosage form", "dosage_form"),
    ):
        pi_val = _norm(pi.get(field))
        content_val = _norm(ctx.get(content_key))
        if pi_val and content_val and pi_val.lower() != content_val.lower():
            out.append({
                "file": "REP PI", "node": field,
                "message": (f"{label} in PI metadata ('{pi_val}') does not match "
                            f"the product content ('{content_val}')"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_pdf_bookmarks(ctx) -> list:
    """PDF category — a non-blocking WARNING when a PDF carries no bookmarks
    (illustrates HC's two-tier model: surfaced, never blocking)."""
    out = []
    for f in _files(ctx):
        if f.get("kind") == "pdf" and f.get("bookmarks") is False:
            out.append({
                "file": _norm(f.get("path")), "node": _norm(f.get("path")),
                "message": (f"PDF '{_norm(f.get('path'))}' has no bookmarks; HC "
                            "recommends bookmarks for navigation"),
                "remediable": False, "fix_id": "",
            })
    return out


# ---------------------------------------------------------------------------
# Additional published HC rules (REQ-010/013/020/021/069). Each fires ONLY on
# an explicit defect signal so a clean transaction stays clean.
# ---------------------------------------------------------------------------

# REQ-013 — published per-file size band (A03a warn 150-200 MB, A03b block
# >=200 MB). The numbers are HC's real A03a/A03b thresholds, not tool config.
A03A_WARN_MB = 150
A03B_BLOCK_MB = 200

# REQ-010 — accepted PDF versions (1.4-1.7 inclusive).
ACCEPTED_PDF_VERSIONS = ("1.4", "1.5", "1.6", "1.7")

# REQ-020 — file/folder naming: lowercase a-z, digits, hyphen and the dot for a
# single extension only. No spaces, uppercase, accented/non-ASCII characters.
_NAME_SEGMENT_RE = re.compile(r"[a-z0-9.\-]+")

# REQ-020 — total path length ceiling from the sequence root (mirrors B08).
MAX_PATH_LENGTH = 200

# REQ-020 — reserved Windows device names that may not be used as a file/folder
# basename (mirrors the B47/B48 naming family).
_RESERVED_WIN_NAMES = (
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


def _path_segments(path: str) -> list:
    return [seg for seg in _norm(path).split("/") if seg]


def _check_a01_empty_folder(ctx) -> list:
    """REQ-021 / rule A01 — a sequence may contain no empty folder.

    Fires for any node explicitly modelled as a folder (``is_dir``) that is
    flagged ``empty`` (no leaf or required file beneath it)."""
    out = []
    for f in _files(ctx):
        if f.get("is_dir") and f.get("empty"):
            path = _norm(f.get("path"))
            out.append({
                "file": path, "node": path,
                "message": (f"folder '{path}' is empty; HC blocks packaging of "
                            "any sequence containing an empty folder (A01)"),
                "remediable": False, "fix_id": "",
            })
    return out


def _file_size_mb(f) -> float:
    try:
        return float(f.get("size_mb") or 0)
    except (TypeError, ValueError):
        return 0.0


def _check_a03a_size_warn(ctx) -> list:
    """REQ-013 / rule A03a — WARN when a single file is in the 150-200 MB band."""
    out = []
    for f in _files(ctx):
        size = _file_size_mb(f)
        if A03A_WARN_MB <= size < A03B_BLOCK_MB:
            path = _norm(f.get("path"))
            out.append({
                "file": path, "node": path,
                "message": (f"file '{path}' is {size:g} MB (150-200 MB band); HC "
                            "advises splitting before transmission (A03a)"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_a03b_size_block(ctx) -> list:
    """REQ-013 / rule A03b — BLOCK any single file at or above 200 MB."""
    out = []
    for f in _files(ctx):
        size = _file_size_mb(f)
        if size >= A03B_BLOCK_MB:
            path = _norm(f.get("path"))
            out.append({
                "file": path, "node": path,
                "message": (f"file '{path}' is {size:g} MB (>= 200 MB); HC blocks "
                            "it and an oversize-split is required (A03b)"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_b08_path_length(ctx) -> list:
    """REQ-020 / rule B08 — total path length within 200 characters."""
    out = []
    for f in _files(ctx):
        path = _norm(f.get("path"))
        if path and len(path) > MAX_PATH_LENGTH:
            out.append({
                "file": path, "node": path,
                "message": (f"path is {len(path)} characters, exceeding the "
                            f"{MAX_PATH_LENGTH}-character limit from the sequence "
                            "root (B08)"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_b32_naming(ctx) -> list:
    """REQ-020 / rule B32 — file/folder names use only lowercase a-z, digits and
    hyphens (a single dotted extension allowed); no spaces, uppercase, or
    accented/non-ASCII characters."""
    out = []
    for f in _files(ctx):
        path = _norm(f.get("path"))
        for seg in _path_segments(path):
            if not _NAME_SEGMENT_RE.fullmatch(seg):
                try:
                    seg.encode("ascii")
                    reason = "spaces, uppercase or disallowed punctuation"
                except UnicodeEncodeError:
                    reason = "accented/non-ASCII characters"
                out.append({
                    "file": path, "node": seg,
                    "message": (f"name segment '{seg}' in '{path}' is not "
                                f"compliant ({reason}); use lowercase a-z, digits "
                                "and hyphens only (B32)"),
                    "remediable": False, "fix_id": "",
                })
                break
    return out


def _check_b48_reserved_names(ctx) -> list:
    """REQ-020 / rule B48 — no reserved Windows device name as a basename."""
    out = []
    for f in _files(ctx):
        path = _norm(f.get("path"))
        segs = _path_segments(path)
        if not segs:
            continue
        base = segs[-1].split(".")[0].lower()
        if base in _RESERVED_WIN_NAMES:
            out.append({
                "file": path, "node": segs[-1],
                "message": (f"'{segs[-1]}' uses the reserved Windows device name "
                            f"'{base}', which is not a valid file/folder name "
                            "(B48)"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_b47_duplicate_leaf_ids(ctx) -> list:
    """REQ-020 / rule B47 — leaf IDs are unique across the transaction."""
    out = []
    seen = {}
    for lf in _leaves(ctx):
        if _norm(lf.get("operation")) == "delete":
            continue
        lid = _norm(lf.get("leaf_id"))
        if lid:
            seen.setdefault(lid, 0)
            seen[lid] += 1
    for lid, count in seen.items():
        if count > 1:
            out.append({
                "file": "transaction", "node": lid,
                "message": (f"leaf ID '{lid}' is used {count} times; leaf IDs "
                            "must be unique (B47)"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_b49_ocr(ctx) -> list:
    """REQ-010 / rules B49/D29 — a scanned PDF must be text-searchable (OCR)."""
    out = []
    for f in _files(ctx):
        if (f.get("kind") == "pdf" and f.get("scanned")
                and not f.get("searchable", True)):
            path = _norm(f.get("path"))
            out.append({
                "file": path, "node": path,
                "message": (f"scanned PDF '{path}' is not text-searchable; it must "
                            "be OCR'd before submission (B49/D29)"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_d03_pdf_version(ctx) -> list:
    """REQ-010 — content PDFs must be version 1.4-1.7."""
    out = []
    for f in _files(ctx):
        if f.get("kind") != "pdf":
            continue
        ver = _norm(f.get("pdf_version"))
        if ver and ver not in ACCEPTED_PDF_VERSIONS:
            path = _norm(f.get("path"))
            out.append({
                "file": path, "node": path,
                "message": (f"PDF '{path}' is version {ver}; HC accepts only PDF "
                            "1.4-1.7"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_d04_track_changes(ctx) -> list:
    """REQ-010 — content PDFs must not have Track Changes enabled."""
    out = []
    for f in _files(ctx):
        if f.get("kind") == "pdf" and f.get("track_changes"):
            path = _norm(f.get("path"))
            out.append({
                "file": path, "node": path,
                "message": (f"PDF '{path}' has Track Changes enabled; it must be "
                            "disabled before submission"),
                "remediable": False, "fix_id": "",
            })
    return out


def _check_a10_security_settings(ctx) -> list:
    """REQ-069 / rule A10 — block HC-prohibited non-password security settings
    (DRM, IRM, restricted access, rights management), DISTINCT from A09's
    password/encryption check."""
    out = []
    flags = ("drm", "irm", "restricted_access", "rights_management")
    for f in _files(ctx):
        if f.get("kind") != "pdf":
            continue
        offending = [name for name in flags if f.get(name)]
        if offending:
            path = _norm(f.get("path"))
            out.append({
                "file": path, "node": path,
                "message": (f"PDF '{path}' has prohibited security settings "
                            f"({', '.join(offending)}); HC blocks DRM/IRM/"
                            "restricted-access/rights-management beyond passwords "
                            "(A10, distinct from A09)"),
                "remediable": False, "fix_id": "",
            })
    return out


# REQ-012 — content-PDF hyperlinks must be relative and functional; an
# external/absolute web hyperlink (or a link explicitly marked broken) is a
# defect surfaced before export. Internal/relative links that resolve stay clean.
EXTERNAL_LINK_SCHEMES = ("http://", "https://", "ftp://", "ftps://", "file://",
                         "mailto:")


def _check_d12_hyperlinks(ctx) -> list:
    """REQ-012 / rule D12 — content PDF hyperlinks must be relative & functional.

    A content PDF may carry a ``links`` list of strings or
    ``{"target"/"href", "broken"}`` dicts. An absolute/external web hyperlink
    (http/https/ftp/file/mailto, or a leading '/') is flagged as a defect, and
    any relative link explicitly marked broken is surfaced before export. Files
    with no ``links`` key are left untouched, so a clean transaction stays clean.
    """
    out = []
    for f in _files(ctx):
        if f.get("kind") != "pdf":
            continue
        path = _norm(f.get("path"))
        for link in (f.get("links") or []):
            if isinstance(link, str):
                link = {"target": link}
            target = _norm(link.get("target") or link.get("href"))
            if not target:
                continue
            if target.lower().startswith(EXTERNAL_LINK_SCHEMES) \
                    or target.startswith("/"):
                out.append({
                    "file": path, "node": target,
                    "message": (f"PDF '{path}' contains an external/absolute "
                                f"hyperlink '{target}'; content PDFs must use "
                                "relative internal links only (D12)"),
                    "remediable": False, "fix_id": "",
                })
            elif link.get("broken"):
                out.append({
                    "file": path, "node": target,
                    "message": (f"PDF '{path}' has a broken relative hyperlink "
                                f"'{target}' that must be fixed before export "
                                "(D12)"),
                    "remediable": False, "fix_id": "",
                })
    return out


# ---------------------------------------------------------------------------
# REQ-022 — the rule catalog (data-driven; versioned by ``min_version``)
# ---------------------------------------------------------------------------
#
# Each rule declares the version in which it became effective. ``get_ruleset``
# includes a rule only when its ``min_version`` <= the requested version, so the
# selected ruleset version materially changes which rules run (A02 and STF were
# introduced in 5.3).

RULE_CATALOG = [
    {"rule_id": "A02", "category": "General", "severity": SEVERITY_ERROR,
     "description": "Every file and folder is readable and free of "
                    "access-permission restrictions",
     "min_version": "5.3", "check": _check_a02},
    {"rule_id": "A01", "category": "General", "severity": SEVERITY_ERROR,
     "description": "No empty folder in the sequence",
     "min_version": "5.2", "check": _check_a01_empty_folder},
    {"rule_id": "A03a", "category": "General", "severity": SEVERITY_WARNING,
     "description": "Single file in the 150-200 MB band (advise split)",
     "min_version": "5.2", "check": _check_a03a_size_warn},
    {"rule_id": "A03b", "category": "General", "severity": SEVERITY_ERROR,
     "description": "Single file at or above the 200 MB hard limit",
     "min_version": "5.2", "check": _check_a03b_size_block},
    {"rule_id": "B08", "category": "General", "severity": SEVERITY_ERROR,
     "description": "Path length within 200 characters from the sequence root",
     "min_version": "5.2", "check": _check_b08_path_length},
    {"rule_id": "B32", "category": "General", "severity": SEVERITY_ERROR,
     "description": "File/folder names use lowercase a-z, digits and hyphens only",
     "min_version": "5.2", "check": _check_b32_naming},
    {"rule_id": "B47", "category": "General", "severity": SEVERITY_ERROR,
     "description": "Leaf IDs are unique across the transaction",
     "min_version": "5.2", "check": _check_b47_duplicate_leaf_ids},
    {"rule_id": "B48", "category": "General", "severity": SEVERITY_ERROR,
     "description": "No reserved Windows device name as a basename",
     "min_version": "5.2", "check": _check_b48_reserved_names},
    {"rule_id": "A09", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "PDF documents are not encrypted",
     "min_version": "5.2", "check": _check_a09},
    {"rule_id": "A10", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "No DRM/IRM/restricted-access/rights-management settings",
     "min_version": "5.2", "check": _check_a10_security_settings},
    {"rule_id": "B49", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "Scanned PDFs are text-searchable (OCR)",
     "min_version": "5.2", "check": _check_b49_ocr},
    {"rule_id": "D03", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "PDF version is within 1.4-1.7",
     "min_version": "5.2", "check": _check_d03_pdf_version},
    {"rule_id": "D04", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "PDF Track Changes is not enabled",
     "min_version": "5.2", "check": _check_d04_track_changes},
    {"rule_id": "A11", "category": "PDF", "severity": SEVERITY_WARNING,
     "description": "PDF documents carry navigation bookmarks",
     "min_version": "5.2", "check": _check_pdf_bookmarks},
    {"rule_id": "D12", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "Content PDF hyperlinks are relative/functional (no "
                    "external/absolute web links)",
     "min_version": "5.2", "check": _check_d12_hyperlinks},
    {"rule_id": "R05", "category": "Referenced", "severity": SEVERITY_ERROR,
     "description": "Every referenced leaf file is present in the transaction",
     "min_version": "5.2", "check": _check_referenced},
    {"rule_id": "X01", "category": "XML", "severity": SEVERITY_ERROR,
     "description": "Backbone XML is well-formed",
     "min_version": "5.2", "check": _check_xml_wellformed},
    {"rule_id": "B07", "category": "ICH-Backbone", "severity": SEVERITY_ERROR,
     "description": "Every leaf carries an MD5 checksum in the backbone",
     "min_version": "5.2", "check": _check_backbone_checksums},
    {"rule_id": "G01", "category": "Regional", "severity": SEVERITY_ERROR,
     "description": "ca-regional.xml dossier-id matches the transaction",
     "min_version": "5.2", "check": _check_regional},
    {"rule_id": "S01", "category": "STF", "severity": SEVERITY_ERROR,
     "description": "Module 5 study data has a present, valid Study Tagging File",
     "min_version": "5.3", "check": _check_stf},
    {"rule_id": "P01", "category": "REP", "severity": SEVERITY_ERROR,
     "description": "DIN/Dossier ID/Company ID agree across CO/RT/PI, cover "
                    "letter and ca-regional.xml",
     "min_version": "5.2", "check": _check_rep_identifier_agreement},
    {"rule_id": "P02", "category": "REP", "severity": SEVERITY_ERROR,
     "description": "Product name/strength/dosage-form agree between PI metadata "
                    "and content",
     "min_version": "5.2", "check": _check_rep_product_consistency},
]


def get_ruleset(version: str = ACTIVE_RULESET_VERSION) -> dict:
    """REQ-022: the rule definitions effective at ``version``.

    Raises ``UnknownRulesetError`` for an unpublished version. Each returned
    rule descriptor carries {rule_id, category, severity, description,
    ruleset_version}.
    """
    version = _norm(version) or ACTIVE_RULESET_VERSION
    if version not in RULESETS:
        raise UnknownRulesetError(
            f"unknown ruleset version '{version}'; published versions are "
            f"{', '.join(sorted(RULESETS))}")
    target = _vtuple(version)
    rules = []
    for rule in RULE_CATALOG:
        if _vtuple(rule["min_version"]) <= target:
            rules.append({
                "rule_id": rule["rule_id"],
                "category": rule["category"],
                "severity": rule["severity"],
                "description": rule["description"],
                "ruleset_version": version,
                "check": rule["check"],
            })
    return {
        "version": version,
        "effective": RULESETS[version]["effective"],
        "rules": rules,
    }


def ruleset_catalog(version: str = ACTIVE_RULESET_VERSION) -> dict:
    """REQ-022: the ruleset as serialisable data (no ``check`` callables)."""
    rs = get_ruleset(version)
    return {
        "version": rs["version"],
        "effective": rs["effective"],
        "rules": [
            {k: r[k] for k in
             ("rule_id", "category", "severity", "description", "ruleset_version")}
            for r in rs["rules"]
        ],
    }


# ---------------------------------------------------------------------------
# REQ-022/023 — the engine
# ---------------------------------------------------------------------------

def run_validation(ctx: dict, version: str = ACTIVE_RULESET_VERSION) -> dict:
    """REQ-022: run the versioned ruleset over a transaction context.

    Returns a structured result: every finding stamped with its rule metadata,
    split into ``errors`` and ``warnings``, with ``blocking`` True iff there is
    at least one Error (Warnings never block). ``by_category`` groups findings
    by HC category for the report/UI.
    """
    rs = get_ruleset(version)
    findings = []
    for rule in rs["rules"]:
        for partial in (rule["check"](ctx) or []):
            finding = {
                "rule_id": rule["rule_id"],
                "category": rule["category"],
                "severity": rule["severity"],
                "ruleset_version": rule["ruleset_version"],
                "description": rule["description"],
                "colour": SEVERITY_COLOUR.get(rule["severity"], "#444"),
            }
            finding.update(partial)
            findings.append(finding)

    errors = [f for f in findings if f["severity"] == SEVERITY_ERROR]
    warnings = [f for f in findings if f["severity"] == SEVERITY_WARNING]
    by_category = {c: [] for c in CATEGORIES}
    for f in findings:
        by_category.setdefault(f["category"], []).append(f)

    return {
        "ruleset_version": rs["version"],
        "ruleset_effective": rs["effective"],
        "findings": findings,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "blocking": bool(errors),
        "by_category": by_category,
    }


def inline_findings(ctx: dict, version: str = ACTIVE_RULESET_VERSION) -> dict:
    """REQ-023: defects for the inline authoring gutter.

    Returns each defect keyed to its exact file/node with a severity colour and,
    where the rule is remediable, a ``fix_id`` the UI can offer as a one-click
    fix. This is the SAME engine as the terminal gate (``run_validation``) — run
    continuously rather than only at submission.
    """
    result = run_validation(ctx, version)
    gutter = {}
    for f in result["findings"]:
        gutter.setdefault(f["file"] or f["node"], []).append({
            "rule_id": f["rule_id"],
            "node": f["node"],
            "severity": f["severity"],
            "colour": f["colour"],
            "message": f["message"],
            "remediable": f.get("remediable", False),
            "fix_id": f.get("fix_id", ""),
        })
    return {
        "ruleset_version": result["ruleset_version"],
        "blocking": result["blocking"],
        "gutter": gutter,
        "error_count": result["error_count"],
        "warning_count": result["warning_count"],
    }


# Remediations the inline "one-click fix" can apply (REQ-023). Each takes the
# context + the target file path and returns a NEW context with the defect
# cleared — non-destructive (the rest of the transaction is preserved).
def apply_fix(ctx: dict, fix_id: str, file: str) -> dict:
    """REQ-023: apply a one-click fix for a remediable defect.

    Returns an updated copy of ``ctx`` with the targeted file's defect cleared.
    Raises ``ValueError`` for an unknown fix. Only ``grant-read`` (A02) and
    ``decrypt-pdf`` (A09) are remediable in-place.
    """
    fix_id = _norm(fix_id)
    file = _norm(file)
    new_ctx = dict(ctx)
    new_files = []
    touched = False
    for f in _files(ctx):
        f = dict(f)
        if _norm(f.get("path")) == file:
            if fix_id == "grant-read":
                f["readable"] = True
                touched = True
            elif fix_id == "decrypt-pdf":
                f["encrypted"] = False
                touched = True
            else:
                raise ValueError(f"unknown fix '{fix_id}'")
        new_files.append(f)
    if not touched and fix_id not in ("grant-read", "decrypt-pdf"):
        raise ValueError(f"unknown fix '{fix_id}'")
    new_ctx["files"] = new_files
    return new_ctx


# ---------------------------------------------------------------------------
# REQ-059 — cross-document consistency gate (packaging block)
# ---------------------------------------------------------------------------

def check_cross_document_consistency(ctx: dict) -> list:
    """REQ-059: the cross-document / metadata-consistency findings only.

    The DIN/Dossier/Company agreement (P01), PI ↔ content product consistency
    (P02) and STF presence/correctness (S01) checks, independent of ruleset
    version selection. Returns a list of findings (empty == consistent).
    """
    findings = []
    for rule_id, category, check in (
        ("P01", "REP", _check_rep_identifier_agreement),
        ("P02", "REP", _check_rep_product_consistency),
        ("S01", "STF", _check_stf),
    ):
        for partial in (check(ctx) or []):
            f = {"rule_id": rule_id, "category": category,
                 "severity": SEVERITY_ERROR}
            f.update(partial)
            findings.append(f)
    return findings


def validate_for_packaging(ctx: dict, version: str = ACTIVE_RULESET_VERSION) -> dict:
    """REQ-059: block packaging on any cross-document inconsistency or Error.

    Runs the full versioned ruleset; ``can_package`` is True only when there are
    no Errors. Cross-document findings are surfaced separately so the caller can
    point at the offending documents.
    """
    result = run_validation(ctx, version)
    consistency = check_cross_document_consistency(ctx)
    return {
        "ruleset_version": result["ruleset_version"],
        "can_package": not result["blocking"],
        "blocking": result["blocking"],
        "errors": result["errors"],
        "warnings": result["warnings"],
        "consistency_findings": consistency,
    }


# ---------------------------------------------------------------------------
# REQ-024 — version-matched REP XML stylesheet rendering + report
# ---------------------------------------------------------------------------

# The HC REP XML stylesheets are pinned to the REP template versions. Rendering
# a REP artifact uses the stylesheet that MATCHES its template version; a
# mismatch is an error (no silent best-effort rendering).
REP_STYLESHEETS = {
    rep.CO_TEMPLATE_VERSION: "rep-co-stylesheet-" + rep.CO_TEMPLATE_VERSION,
    rep.RT_TEMPLATE_VERSION: "rep-rt-stylesheet-" + rep.RT_TEMPLATE_VERSION,
    rep.PI_TEMPLATE_VERSION: "rep-pi-stylesheet-" + rep.PI_TEMPLATE_VERSION,
}


class StylesheetVersionError(ValueError):
    """REQ-024: no HC REP XML stylesheet matches the artifact's version."""


def render_rep_xml(xml: str, template_version: str) -> dict:
    """REQ-024: render a REP artifact via its version-matched HC stylesheet.

    Returns ``{"stylesheet", "template_version", "rendered"}`` where ``rendered``
    is a human-readable, label/value transform of the REP XML (the stylesheet
    stand-in). Raises ``StylesheetVersionError`` when no stylesheet matches the
    declared template version — rendering is never done with a mismatched sheet.
    """
    template_version = _norm(template_version)
    stylesheet = REP_STYLESHEETS.get(template_version)
    if not stylesheet:
        raise StylesheetVersionError(
            f"no HC REP XML stylesheet matches template version "
            f"'{template_version}'")
    try:
        dom = safe_parse_xml(xml)
    except UnsafeXmlError as exc:
        raise StylesheetVersionError(f"REP XML was rejected as unsafe: {exc}")
    except Exception as exc:
        raise StylesheetVersionError(f"REP XML is not well-formed: {exc}")

    lines = []

    def walk(node, depth=0):
        for child in node.childNodes:
            if child.nodeType == child.ELEMENT_NODE:
                text = "".join(
                    t.data for t in child.childNodes
                    if t.nodeType == t.TEXT_NODE).strip()
                indent = "  " * depth
                if text:
                    lines.append(f"{indent}{child.tagName}: {text}")
                else:
                    lines.append(f"{indent}{child.tagName}")
                walk(child, depth + 1)

    walk(dom.documentElement)
    return {
        "stylesheet": stylesheet,
        "template_version": template_version,
        "rendered": "\n".join(lines) + "\n",
    }


def verify_leaf_md5(ctx: dict) -> list:
    """REQ-024: re-verify each leaf's recorded MD5 against the actual bytes.

    Returns ``[{leaf_id, href, recorded, actual, verified}]``. ``verified`` is
    False on any mismatch — the report surfaces it explicitly.
    """
    out = []
    for lf in _leaves(ctx):
        if _norm(lf.get("operation")) == "delete":
            continue
        recorded = _norm(lf.get("checksum"))
        actual = ectd.md5_hex(lf.get("content") or "")
        out.append({
            "leaf_id": _norm(lf.get("leaf_id")),
            "href": _norm(lf.get("href")),
            "recorded": recorded,
            "actual": actual,
            "verified": bool(recorded) and recorded == actual,
        })
    return out


def build_validation_report(ctx: dict,
                            version: str = ACTIVE_RULESET_VERSION) -> dict:
    """REQ-024: the downloadable pre-submission validation report.

    Mirrors HC's output: a categorised Error/Warning list with rule IDs against
    the PINNED ruleset version, a backbone preview (index.xml + ca-regional.xml,
    plus any REP XML rendered via its version-matched stylesheet) and the
    per-leaf MD5 verification.
    """
    result = run_validation(ctx, version)

    categories = []
    for cat in CATEGORIES:
        items = result["by_category"].get(cat, [])
        if not items:
            continue
        categories.append({
            "category": cat,
            "errors": [_report_item(f) for f in items
                       if f["severity"] == SEVERITY_ERROR],
            "warnings": [_report_item(f) for f in items
                         if f["severity"] == SEVERITY_WARNING],
        })

    # Backbone preview — render any provided REP artifacts via their stylesheet.
    rep_rendered = []
    for art in (ctx.get("rep_artifacts") or []):
        try:
            rendered = render_rep_xml(art.get("xml", ""),
                                      art.get("template_version", ""))
            rep_rendered.append({"name": art.get("name", ""), **rendered})
        except StylesheetVersionError as exc:
            rep_rendered.append({"name": art.get("name", ""),
                                 "error": str(exc)})

    return {
        "ruleset_version": result["ruleset_version"],
        "ruleset_effective": result["ruleset_effective"],
        "dossier_id": _norm(ctx.get("dossier_id")),
        "sequence": _norm(ctx.get("sequence")),
        "blocking": result["blocking"],
        "error_count": result["error_count"],
        "warning_count": result["warning_count"],
        "categories": categories,
        "backbone_preview": {
            "index.xml": ctx.get("index_xml", ""),
            "m1/ca/ca-regional.xml": ctx.get("ca_regional_xml", ""),
            "rep_rendered": rep_rendered,
        },
        "leaf_md5": verify_leaf_md5(ctx),
    }


def _report_item(f: dict) -> dict:
    return {"rule_id": f["rule_id"], "message": f["message"],
            "file": f.get("file", ""), "node": f.get("node", "")}


def render_report_text(report: dict) -> str:
    """REQ-024: the report as downloadable plain text mirroring HC's layout."""
    lines = []
    lines.append("Health Canada — Pre-submission Validation Report")
    lines.append("=" * 52)
    lines.append(f"Ruleset version : {report['ruleset_version']} "
                 f"(effective {report['ruleset_effective']})")
    lines.append(f"Dossier ID      : {report['dossier_id']}")
    lines.append(f"Sequence        : {report['sequence']}")
    verdict = "BLOCKED — errors must be resolved" if report["blocking"] \
        else "PASS — no blocking errors"
    lines.append(f"Result          : {verdict}")
    lines.append(f"Errors          : {report['error_count']}")
    lines.append(f"Warnings        : {report['warning_count']}")
    lines.append("")
    for cat in report["categories"]:
        lines.append(f"[{cat['category']}]")
        for e in cat["errors"]:
            lines.append(f"  ERROR   {e['rule_id']}  {e['message']} "
                         f"({e['file']})")
        for w in cat["warnings"]:
            lines.append(f"  WARNING {w['rule_id']}  {w['message']} "
                         f"({w['file']})")
        lines.append("")
    lines.append("Leaf MD5 verification")
    lines.append("-" * 21)
    for lf in report["leaf_md5"]:
        status = "OK" if lf["verified"] else "MISMATCH"
        lines.append(f"  [{status}] {lf['leaf_id']}  {lf['href']}  "
                     f"{lf['actual']}")
    if not report["leaf_md5"]:
        lines.append("  (no leaves)")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# REQ-045 — schema/DTD failure & service outage with retained-state resume
# ---------------------------------------------------------------------------

class ServiceOutageError(RuntimeError):
    """REQ-045: an external HC/FDA service (FDA ESG, REP ID return) is down."""

    def __init__(self, service: str, message: str = ""):
        self.service = service
        super().__init__(message or f"external service '{service}' is unavailable")


class RepSchemaError(ectd.SchemaValidationError):
    """REQ-045: a generated REP CO/RT/PI XML failed HC schema validation."""


# The external services this transaction depends on, with the user-facing
# guidance shown when one is down.
EXTERNAL_SERVICES = {
    "fda_esg": "FDA Electronic Submissions Gateway (ESG)",
    "rep_id_return": "HC REP ID return service",
}


def validate_rep_artifact(name: str, xml: str) -> None:
    """REQ-045: validate one generated REP artifact against its HC schema.

    Checks well-formedness and that the expected root + the identifier elements
    HC requires are present and non-empty. Raises ``RepSchemaError`` on any
    violation (the specific, surfaceable schema error).
    """
    try:
        dom = safe_parse_xml(xml)
    except UnsafeXmlError as exc:
        raise RepSchemaError(f"{name}: rejected as unsafe XML: {exc}")
    except Exception as exc:
        raise RepSchemaError(f"{name}: not well-formed XML: {exc}")

    expected_roots = {
        "co": "rep-company",
        "rt": "rep-transaction",
        "pi": "rep-product-information",
    }
    root = expected_roots.get(name)
    actual_root = dom.documentElement.tagName
    if root and actual_root != root:
        raise RepSchemaError(
            f"{name}: root element '{actual_root}' does not match the HC schema "
            f"root '{root}'")

    required = {
        "co": ["company-id"],
        "rt": ["dossier-id", "company-id", "regulatory-activity-type"],
        "pi": ["dossier-id", "product-name"],
    }.get(name, [])
    for tag in required:
        nodes = dom.getElementsByTagName(tag)
        text = ""
        if nodes:
            text = "".join(t.data for t in nodes[0].childNodes
                           if t.nodeType == t.TEXT_NODE).strip()
        if not text:
            raise RepSchemaError(
                f"{name}: required element <{tag}> is missing or empty")


class ResumableTransaction:
    """REQ-045: a packaging attempt that RETAINS state across failures.

    Holds the in-progress transaction context. ``attempt(services)`` runs the
    generate → schema-validate → external-service steps; on a schema or
    service failure it records the specific blocking condition and the guided
    retry/resume path WITHOUT discarding any state, so a later ``attempt`` (after
    the operator fixes the schema or the service recovers) resumes cleanly.
    """

    def __init__(self, ctx: dict):
        self.ctx = dict(ctx)
        self.attempts = 0
        self.last_result = None

    def _result(self, **kw) -> dict:
        kw.setdefault("attempts", self.attempts)
        kw.setdefault("state_retained", True)
        self.last_result = kw
        return kw

    def attempt(self, services: dict | None = None) -> dict:
        """Run one packaging attempt; never raises, never loses state.

        ``services`` maps service key -> "up"/"down" (default: all up). Returns
        an envelope: on success ``{"ok": True, ...}``; on failure
        ``{"ok": False, "blocked_by": "schema"|"service", "error", "resume",
        "state_retained": True}``.
        """
        services = services or {}
        self.attempts += 1

        # 1. Schema/DTD validation of each generated REP artifact + backbones.
        for art in (self.ctx.get("rep_artifacts") or []):
            try:
                validate_rep_artifact(art.get("name", ""), art.get("xml", ""))
            except RepSchemaError as exc:
                return self._result(
                    ok=False, blocked_by="schema", error=str(exc),
                    artifact=art.get("name", ""),
                    resume=("Correct the flagged element, then resume — your "
                            "in-progress work has been retained."))

        for key, descriptor in (("index_xml", ectd.ICH_ECTD_DTD),
                               ("ca_regional_xml", ectd.CA_M1_XSD)):
            xml = self.ctx.get(key)
            if not xml:
                continue
            try:
                ectd.validate_backbone(xml, descriptor)
            except ectd.SchemaValidationError as exc:
                return self._result(
                    ok=False, blocked_by="schema", error=str(exc),
                    artifact=key,
                    resume=("Regenerate the backbone to fix the schema error, "
                            "then resume — no data was lost."))

        # 2. External HC/FDA services.
        for svc_key, label in EXTERNAL_SERVICES.items():
            if str(services.get(svc_key, "up")).lower() == "down":
                return self._result(
                    ok=False, blocked_by="service", service=svc_key,
                    error=f"{label} is currently unavailable",
                    resume=(f"{label} is down. Your transaction is saved; retry "
                            "when the service is restored."))

        return self._result(ok=True, error="", resume="",
                            message="packaged and transmitted")


def attempt_package(ctx: dict, services: dict | None = None) -> dict:
    """REQ-045: one-shot helper around ``ResumableTransaction.attempt``."""
    return ResumableTransaction(ctx).attempt(services)


# ---------------------------------------------------------------------------
# Context assembly — bridge an assembled REP transaction + dossier into the
# validation context the engine consumes. Keeps the server wiring thin.
# ---------------------------------------------------------------------------

def context_from_request(data: dict) -> dict:
    """Normalise a raw request body into a validation context.

    Accepts the explicit context shape (files / leaves / rep / cover_letter /
    ca_regional / module5_studies) and fills sensible defaults so partial
    payloads still validate. Pure and side-effect free.
    """
    ctx = dict(data or {})
    ctx.setdefault("files", [])
    ctx.setdefault("leaves", [])
    ctx.setdefault("module5_studies", [])
    ctx.setdefault("rep", {})
    return ctx
