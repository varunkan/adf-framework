"""HC eCTD validation rule catalog — pure, versioned (ported from the monolith).

Each rule is a check function over a transaction ``context`` (``files``,
``leaves``, ``index_xml``, ``ca_regional``/``dossier_id``, …) returning partial
findings ``{file, node, message, remediable, fix_id}``. ``get_ruleset`` filters
the catalog by ``min_version`` so the selected version changes which rules run.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

SEVERITY_ERROR = "Error"
SEVERITY_WARNING = "Warning"
SEVERITY_COLOUR = {SEVERITY_ERROR: "#c0392b", SEVERITY_WARNING: "#d68910"}

CATEGORIES = ["General", "PDF", "Referenced", "XML", "ICH-Backbone", "Regional"]

RULESETS = {
    "5.2": {"effective": "2023-09-30"},
    "5.3": {"effective": "2025-05-31"},
}
ACTIVE_RULESET_VERSION = "5.3"


class UnknownRulesetError(ValueError):
    """An unpublished ruleset version was requested."""


def _vtuple(v: str) -> tuple:
    return tuple(int(p) for p in str(v).split(".") if p.isdigit())


def _norm(value) -> str:
    return str(value if value is not None else "").strip()


def _files(ctx) -> list:
    return list(ctx.get("files") or [])


def _leaves(ctx) -> list:
    return list(ctx.get("leaves") or [])


# -- thresholds / patterns (HC's real numbers) -------------------------------
A03A_WARN_MB = 150
A03B_BLOCK_MB = 200
ACCEPTED_PDF_VERSIONS = ("1.4", "1.5", "1.6", "1.7")
MAX_PATH_LENGTH = 200
_NAME_SEGMENT_RE = re.compile(r"[a-z0-9.\-]+")
_RESERVED_WIN_NAMES = ({"con", "prn", "aux", "nul"}
                       | {f"com{i}" for i in range(1, 10)}
                       | {f"lpt{i}" for i in range(1, 10)})
EXTERNAL_LINK_SCHEMES = ("http://", "https://", "ftp://", "ftps://", "file://",
                         "mailto:")


def _segs(path: str) -> list:
    return [s for s in _norm(path).split("/") if s]


def _size_mb(f) -> float:
    try:
        return float(f.get("size_mb") or 0)
    except (TypeError, ValueError):
        return 0.0


# -- checks (ported verbatim in intent) --------------------------------------
def _check_a02(ctx):
    out = []
    for f in _files(ctx):
        if not f.get("readable", True):
            kind = "folder" if f.get("is_dir") else "file"
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": True,
                        "fix_id": "grant-read",
                        "message": f"{kind} '{p}' is not readable or has an "
                                   "access-permission restriction (A02)"})
    return out


def _check_a01_empty_folder(ctx):
    out = []
    for f in _files(ctx):
        if f.get("is_dir") and f.get("empty"):
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"folder '{p}' is empty; HC blocks any "
                                   "sequence containing an empty folder (A01)"})
    return out


def _check_a03a(ctx):
    out = []
    for f in _files(ctx):
        size = _size_mb(f)
        if A03A_WARN_MB <= size < A03B_BLOCK_MB:
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"file '{p}' is {size:g} MB (150-200 MB band); "
                                   "HC advises splitting (A03a)"})
    return out


def _check_a03b(ctx):
    out = []
    for f in _files(ctx):
        size = _size_mb(f)
        if size >= A03B_BLOCK_MB:
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"file '{p}' is {size:g} MB (>= 200 MB); HC "
                                   "blocks it, oversize-split required (A03b)"})
    return out


def _check_b08(ctx):
    out = []
    for f in _files(ctx):
        p = _norm(f.get("path"))
        if p and len(p) > MAX_PATH_LENGTH:
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"path is {len(p)} characters, exceeding the "
                                   f"{MAX_PATH_LENGTH}-char limit (B08)"})
    return out


def _check_b32_naming(ctx):
    out = []
    for f in _files(ctx):
        p = _norm(f.get("path"))
        for seg in _segs(p):
            if not _NAME_SEGMENT_RE.fullmatch(seg):
                out.append({"file": p, "node": seg, "remediable": False,
                            "fix_id": "",
                            "message": f"name segment '{seg}' must use only "
                                       "lowercase a-z, digits and hyphens (B32)"})
    return out


def _check_b47_dupe_leaf_ids(ctx):
    seen = {}
    for lf in _leaves(ctx):
        if _norm(lf.get("operation")) == "delete":
            continue
        lid = _norm(lf.get("leaf_id"))
        if lid:
            seen[lid] = seen.get(lid, 0) + 1
    return [{"file": "transaction", "node": lid, "remediable": False,
             "fix_id": "",
             "message": f"leaf ID '{lid}' is used {n} times; leaf IDs must be "
                        "unique (B47)"}
            for lid, n in seen.items() if n > 1]


def _check_b48_reserved(ctx):
    out = []
    for f in _files(ctx):
        segs = _segs(_norm(f.get("path")))
        if not segs:
            continue
        base = segs[-1].split(".")[0].lower()
        if base in _RESERVED_WIN_NAMES:
            out.append({"file": _norm(f.get("path")), "node": segs[-1],
                        "remediable": False, "fix_id": "",
                        "message": f"'{segs[-1]}' uses reserved device name "
                                   f"'{base}' (B48)"})
    return out


def _check_a09_encrypted(ctx):
    out = []
    for f in _files(ctx):
        if f.get("kind") == "pdf" and f.get("encrypted"):
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": True,
                        "fix_id": "decrypt-pdf",
                        "message": f"PDF '{p}' is encrypted; HC requires "
                                   "unencrypted PDFs (A09)"})
    return out


def _check_a10_security(ctx):
    out = []
    flags = ("drm", "irm", "restricted_access", "rights_management")
    for f in _files(ctx):
        if f.get("kind") != "pdf":
            continue
        offending = [n for n in flags if f.get(n)]
        if offending:
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"PDF '{p}' has prohibited security settings "
                                   f"({', '.join(offending)}); HC blocks DRM/IRM "
                                   "(A10)"})
    return out


def _check_b49_ocr(ctx):
    out = []
    for f in _files(ctx):
        if (f.get("kind") == "pdf" and f.get("scanned")
                and not f.get("searchable", True)):
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"scanned PDF '{p}' is not text-searchable; "
                                   "must be OCR'd (B49/D29)"})
    return out


def _check_d03_pdf_version(ctx):
    out = []
    for f in _files(ctx):
        if f.get("kind") != "pdf":
            continue
        ver = _norm(f.get("pdf_version"))
        if ver and ver not in ACCEPTED_PDF_VERSIONS:
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"PDF '{p}' is version {ver}; HC accepts only "
                                   "PDF 1.4-1.7 (D03)"})
    return out


def _check_d04_track_changes(ctx):
    out = []
    for f in _files(ctx):
        if f.get("kind") == "pdf" and f.get("track_changes"):
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"PDF '{p}' has Track Changes enabled; disable "
                                   "before submission (D04)"})
    return out


def _check_a11_bookmarks(ctx):
    out = []
    for f in _files(ctx):
        if f.get("kind") == "pdf" and f.get("bookmarks") is False:
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"PDF '{p}' has no bookmarks; HC recommends "
                                   "bookmarks for navigation (A11)"})
    return out


def _check_d12_hyperlinks(ctx):
    out = []
    for f in _files(ctx):
        if f.get("kind") != "pdf":
            continue
        p = _norm(f.get("path"))
        for link in (f.get("links") or []):
            if isinstance(link, str):
                link = {"target": link}
            target = _norm(link.get("target") or link.get("href"))
            if not target:
                continue
            if target.lower().startswith(EXTERNAL_LINK_SCHEMES) \
                    or target.startswith("/"):
                out.append({"file": p, "node": target, "remediable": False,
                            "fix_id": "",
                            "message": f"PDF '{p}' has an external/absolute link "
                                       f"'{target}'; use relative links (D12)"})
            elif link.get("broken"):
                out.append({"file": p, "node": target, "remediable": False,
                            "fix_id": "",
                            "message": f"PDF '{p}' has a broken relative link "
                                       f"'{target}' (D12)"})
    return out


def _check_referenced(ctx):
    paths = {_norm(f.get("path")) for f in _files(ctx)}
    out = []
    for lf in _leaves(ctx):
        href = _norm(lf.get("href"))
        if href and paths and href not in paths:
            out.append({"file": href, "node": _norm(lf.get("leaf_id")),
                        "remediable": False, "fix_id": "",
                        "message": f"leaf '{_norm(lf.get('leaf_id'))}' references "
                                   f"'{href}', not present in the transaction "
                                   "(R05)"})
    return out


def _check_xml_wellformed(ctx):
    out = []
    for key, label in (("index_xml", "index.xml"),
                       ("ca_regional_xml", "ca-regional.xml")):
        xml = ctx.get(key)
        if not xml:
            continue
        try:
            ET.fromstring(xml)
        except Exception as exc:  # malformed
            out.append({"file": label, "node": label, "remediable": False,
                        "fix_id": "",
                        "message": f"{label} is not well-formed XML: {exc} (X01)"})
    return out


def _check_backbone_checksums(ctx):
    out = []
    for lf in _leaves(ctx):
        if _norm(lf.get("operation")) == "delete":
            continue
        if not _norm(lf.get("checksum")):
            out.append({"file": _norm(lf.get("href")),
                        "node": _norm(lf.get("leaf_id")), "remediable": False,
                        "fix_id": "",
                        "message": f"leaf '{_norm(lf.get('leaf_id'))}' is missing "
                                   "its MD5 checksum in the backbone (B07)"})
    return out


def _check_regional(ctx):
    dossier = _norm(ctx.get("dossier_id"))
    ca = _norm((ctx.get("ca_regional") or {}).get("dossier_id"))
    if dossier and ca and dossier != ca:
        return [{"file": "ca-regional.xml", "node": "dossier-id",
                 "remediable": False, "fix_id": "",
                 "message": f"ca-regional.xml dossier-id '{ca}' does not match the "
                            f"transaction dossier-id '{dossier}' (G01)"}]
    return []


RULE_CATALOG = [
    {"rule_id": "A02", "category": "General", "severity": SEVERITY_ERROR,
     "description": "Files & folders are readable (no access restriction)",
     "min_version": "5.3", "check": _check_a02},
    {"rule_id": "A01", "category": "General", "severity": SEVERITY_ERROR,
     "description": "No empty folder in the sequence",
     "min_version": "5.2", "check": _check_a01_empty_folder},
    {"rule_id": "A03a", "category": "General", "severity": SEVERITY_WARNING,
     "description": "Single file in the 150-200 MB band (advise split)",
     "min_version": "5.2", "check": _check_a03a},
    {"rule_id": "A03b", "category": "General", "severity": SEVERITY_ERROR,
     "description": "Single file at or above the 200 MB hard limit",
     "min_version": "5.2", "check": _check_a03b},
    {"rule_id": "B08", "category": "General", "severity": SEVERITY_ERROR,
     "description": "Path length within 200 characters",
     "min_version": "5.2", "check": _check_b08},
    {"rule_id": "B32", "category": "General", "severity": SEVERITY_ERROR,
     "description": "Names use lowercase a-z, digits and hyphens only",
     "min_version": "5.2", "check": _check_b32_naming},
    {"rule_id": "B47", "category": "General", "severity": SEVERITY_ERROR,
     "description": "Leaf IDs are unique across the transaction",
     "min_version": "5.2", "check": _check_b47_dupe_leaf_ids},
    {"rule_id": "B48", "category": "General", "severity": SEVERITY_ERROR,
     "description": "No reserved Windows device name as a basename",
     "min_version": "5.2", "check": _check_b48_reserved},
    {"rule_id": "A09", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "PDF documents are not encrypted",
     "min_version": "5.2", "check": _check_a09_encrypted},
    {"rule_id": "A10", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "No DRM/IRM/restricted-access settings",
     "min_version": "5.2", "check": _check_a10_security},
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
     "min_version": "5.2", "check": _check_a11_bookmarks},
    {"rule_id": "D12", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "Content PDF hyperlinks are relative/functional",
     "min_version": "5.2", "check": _check_d12_hyperlinks},
    {"rule_id": "R05", "category": "Referenced", "severity": SEVERITY_ERROR,
     "description": "Every referenced leaf file is present",
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
]

# remediable fixes (REQ-104 inline one-click fix)
REMEDIATIONS = {"grant-read": "readable", "decrypt-pdf": "encrypted"}

# REQ-102 — validation profiles. The non-eCTD (HC folder-structure zip) profile
# runs the same content rules but skips the checks that assume an eCTD XML
# backbone (index.xml well-formedness, backbone MD5, ca-regional dossier match).
PROFILE_ECTD = "eCTD"
PROFILE_NON_ECTD = "non-eCTD"
PROFILE_GRP = "GRP"
PROFILES = {PROFILE_ECTD: "Health Canada eCTD",
            PROFILE_NON_ECTD: "Health Canada non-eCTD (folder structure)",
            PROFILE_GRP: "Extended GRP (stricter than HC minimum)"}
_ECTD_ONLY_RULES = frozenset({"X01", "B07", "G01"})

GRP_MIN_DPI = 300


def _check_grp_bookmarks(ctx):
    # GRP elevates A11 (missing bookmarks) from a warning to a blocking error.
    out = []
    for f in _files(ctx):
        if f.get("kind") == "pdf" and f.get("bookmarks") is False:
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"PDF '{p}' has no bookmarks; the GRP profile "
                                   "requires navigation bookmarks (GRP01)"})
    return out


def _check_grp_dpi(ctx):
    out = []
    for f in _files(ctx):
        if f.get("kind") != "pdf" or not f.get("scanned"):
            continue
        try:
            dpi = int(f.get("dpi") or 0)
        except (TypeError, ValueError):
            dpi = 0
        if dpi and dpi < GRP_MIN_DPI:
            p = _norm(f.get("path"))
            out.append({"file": p, "node": p, "remediable": False, "fix_id": "",
                        "message": f"scanned PDF '{p}' is {dpi} DPI; the GRP "
                                   f"profile requires >= {GRP_MIN_DPI} DPI (GRP02)"})
    return out


# GRP-only rules — appended on top of the full eCTD catalog under the GRP profile.
_GRP_EXTRA_RULES = [
    {"rule_id": "GRP01", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "PDF documents must carry navigation bookmarks (GRP)",
     "min_version": "5.3", "check": _check_grp_bookmarks},
    {"rule_id": "GRP02", "category": "PDF", "severity": SEVERITY_ERROR,
     "description": "Scanned PDFs are at least 300 DPI (GRP)",
     "min_version": "5.3", "check": _check_grp_dpi},
]


class UnknownProfileError(ValueError):
    """An unpublished validation profile was requested."""


def list_validation_profiles() -> dict:
    return {"default": PROFILE_ECTD,
            "profiles": [{"key": k, "label": v} for k, v in PROFILES.items()]}


def get_ruleset(version: str = ACTIVE_RULESET_VERSION,
                profile: str = PROFILE_ECTD) -> dict:
    version = _norm(version) or ACTIVE_RULESET_VERSION
    if version not in RULESETS:
        raise UnknownRulesetError(
            f"unknown ruleset version '{version}'; published: "
            f"{', '.join(sorted(RULESETS))}")
    profile = _norm(profile) or PROFILE_ECTD
    if profile not in PROFILES:
        raise UnknownProfileError(
            f"unknown validation profile '{profile}'; available: "
            f"{', '.join(PROFILES)}")
    target = _vtuple(version)
    catalog = RULE_CATALOG + (_GRP_EXTRA_RULES if profile == PROFILE_GRP else [])
    rules = [{**r, "ruleset_version": version} for r in catalog
             if _vtuple(r["min_version"]) <= target
             and not (profile == PROFILE_NON_ECTD
                      and r["rule_id"] in _ECTD_ONLY_RULES)]
    return {"version": version, "profile": profile,
            "effective": RULESETS[version]["effective"], "rules": rules}


def ruleset_catalog(version: str = ACTIVE_RULESET_VERSION,
                    profile: str = PROFILE_ECTD) -> dict:
    rs = get_ruleset(version, profile)
    return {"version": rs["version"], "profile": rs["profile"],
            "effective": rs["effective"],
            "rules": [{k: r[k] for k in ("rule_id", "category", "severity",
                                         "description", "ruleset_version")}
                      for r in rs["rules"]]}
