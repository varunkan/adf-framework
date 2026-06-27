"""
ANDS Submission Portal — bundled, version-tracked REP XML stylesheet package
(REQ-065).

Health Canada ships an XSL stylesheet package — ``pharmabio_stylesheets``,
published ``2025-09-10`` — that renders REP CO/RT/PI XML into the human-readable
view a HC reviewer actually sees. Without a *version-matched* stylesheet the
portal cannot reliably preview what HC will display, so a sponsor cannot review
a transaction before filing (this also backs the REQ-024 pre-submission report).

This module BUNDLES and VERSION-TRACKS that package and renders generated REP
XML through the matching stylesheet for human review BEFORE filing:

  * The package is held as VERSIONED REFERENCE DATA keyed by its publish date,
    exactly like the controlled vocabularies in ``cv.py`` — a drop-in newer
    package can be registered without touching any call site (REQ-040). Each
    package declares which REP template versions it covers, so the stylesheet
    version is selected to MATCH the template that produced the XML.
  * The stylesheet "view" for each REP artifact kind is expressed as DATA (an
    ordered list of field rules), and a single deterministic, stdlib-only
    renderer interprets it. The Python standard library ships no XSLT engine, so
    rather than a partial/unsafe XSLT interpreter we model HC's stylesheet as the
    field-by-field presentation it produces — updatable as data, never code.

Stdlib only; caller-supplied XML is parsed through the shared ``xmlsafe``
hardening (billion-laughs / XXE safe). Deterministic, no I/O at import. The
HTTP/API/UI layer in server.py is a thin shell over these functions.

Requirement traceability (specs/ands-submission-portal/{requirements,spec}.md):
  REQ-065  Bundle + version-track the HC REP XML stylesheet package
           (pharmabio_stylesheets, 2025-09-10) matched to REP template
           generation; render generated REP XML through it for human review
           before filing.
  REQ-040  The package is configuration data, updatable without a code release.
  REQ-024  Supports the pre-submission report's version-matched REP XML preview.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from html import escape as _h

import rep
import xmlsafe


# ---------------------------------------------------------------------------
# The bundled package identity (REQ-065)
# ---------------------------------------------------------------------------

# HC's published REP XML stylesheet package name and the bundled edition's
# publish date. The version-matched edition is selected per-template below.
STYLESHEET_PACKAGE = "pharmabio_stylesheets"
BUNDLED_PACKAGE_VERSION = "2025-09-10"

# REP XML must be rendered for HUMAN REVIEW *before* it is filed with HC.
REVIEW_STAGE = "pre-file"


# ---------------------------------------------------------------------------
# Stylesheet "views" as DATA (REQ-040 — updatable without a code release)
# ---------------------------------------------------------------------------
#
# Each REP artifact kind maps its root element to an ordered list of field
# rules. A field rule is a plain dict the renderer interprets generically:
#   path  : dotted ElementTree path from the root to the element to display
#   label : the human-readable caption HC's stylesheet shows
#   attr  : (optional) render this attribute's value instead of element text
#   code  : (optional) also surface this attribute alongside the text (e.g. the
#           regulatory-activity-type CV code next to its label)
#   repeat: (optional) the element repeats; `fields` describes each occurrence
# Adding, renaming or reordering a field is a DATA edit — no renderer change.

_PHARMABIO_2025_09_10 = {
    "package": STYLESHEET_PACKAGE,
    "published": "2025-09-10",
    "title": "Health Canada REP XML stylesheet (pharmabio_stylesheets)",
    # Which REP template versions this stylesheet edition is matched to. The
    # values mirror rep.{CO,RT,PI}_TEMPLATE_VERSION so the match stays in lock-
    # step with template generation.
    "covers_templates": {
        "co": [rep.CO_TEMPLATE_VERSION],            # 5.0.0
        "rt": [rep.RT_TEMPLATE_VERSION],            # 5.1.0
        "pi": [rep.PI_TEMPLATE_VERSION],            # 2024-02-12
        "ca_regional": [rep.CA_MODULE1_SCHEMA_VERSION],  # 2.2
    },
    "views": {
        "co": {
            "root_tag": "rep-company",
            "title": "REP Company (CO)",
            "version_attr": "template-version",
            "fields": [
                {"path": "company-id", "label": "Company ID"},
                {"path": "company-name", "label": "Company name"},
                {"path": "contact", "label": "Contacts", "repeat": True,
                 "fields": [
                     {"path": "name", "label": "Name"},
                     {"path": "email", "label": "Email"},
                     {"path": "hc-contact-id", "label": "HC contact ID"},
                 ]},
            ],
        },
        "rt": {
            "root_tag": "rep-transaction",
            "title": "REP Regulatory Transaction (RT)",
            "version_attr": "template-version",
            "fields": [
                {"path": "dossier-id", "label": "Dossier ID"},
                {"path": "company-id", "label": "Company ID"},
                {"path": "regulatory-activity-type",
                 "label": "Regulatory activity type", "code": "code"},
                {"path": "regulatory-activity-lead",
                 "label": "Regulatory activity lead"},
                {"path": "sequence", "label": "Sequence"},
            ],
        },
        "pi": {
            "root_tag": "rep-product-information",
            "title": "REP Product Information (PI)",
            "version_attr": "template-version",
            "fields": [
                {"path": "dossier-id", "label": "Dossier ID"},
                {"path": "product-name", "label": "Product name"},
                {"path": "din", "label": "DIN"},
            ],
        },
        "ca_regional": {
            "root_tag": "hcsc_ectd",
            "title": "eCTD CA-regional transaction metadata",
            "version_attr": "schema-version",
            "fields": [
                {"path": "transaction-metadata/dossier-id",
                 "label": "Dossier ID"},
                {"path": "transaction-metadata/company-id",
                 "label": "Company ID"},
                {"path": "transaction-metadata/regulatory-activity-type",
                 "label": "Regulatory activity type", "code": "code"},
                {"path": "transaction-metadata/sequence", "label": "Sequence"},
            ],
        },
    },
}

# The version registry. Keyed by package version (publish date). A newer HC
# package is added with ``register_stylesheet_package`` — no call site changes.
_STYLESHEET_PACKAGES = {
    BUNDLED_PACKAGE_VERSION: _PHARMABIO_2025_09_10,
}

# Map an artifact root tag back to its kind, so a raw REP XML blob can be
# rendered without the caller naming the kind.
_ROOT_TAG_TO_KIND = {
    view["root_tag"]: kind
    for kind, view in _PHARMABIO_2025_09_10["views"].items()
}


class StylesheetVersionError(KeyError):
    """Raised when no bundled stylesheet matches the requested version/template."""


class StylesheetRenderError(ValueError):
    """Raised when REP XML cannot be rendered (unknown kind / not well-formed)."""


# ---------------------------------------------------------------------------
# Package registry (REQ-040 — updatable as data)
# ---------------------------------------------------------------------------

def available_versions() -> list:
    """Every bundled stylesheet package version, newest publish date last."""
    return sorted(_STYLESHEET_PACKAGES)


def active_version() -> str:
    """The most recent bundled package version (latest publish date)."""
    return available_versions()[-1]


def load_stylesheet(version: str = BUNDLED_PACKAGE_VERSION) -> dict:
    """REQ-065: load a bundled stylesheet package edition by version.

    Returns a deep-ish copy so callers can never mutate the canonical store.
    """
    ver = str(version or BUNDLED_PACKAGE_VERSION).strip()
    pkg = _STYLESHEET_PACKAGES.get(ver)
    if pkg is None:
        raise StylesheetVersionError(
            f"no REP XML stylesheet bundled for version {ver!r} "
            f"(have: {', '.join(available_versions())})")
    return _copy_package(pkg)


def _copy_package(pkg: dict) -> dict:
    """A defensive copy of a package (nested dicts/lists duplicated)."""
    import copy
    return copy.deepcopy(pkg)


def register_stylesheet_package(version: str, package: dict) -> None:
    """REQ-040: load a newer HC stylesheet package AS DATA (no code change).

    Demonstrates that a stylesheet update from HC is reflected by the renderer
    without touching renderer code: the new edition's ``views``/``covers_templates``
    drive rendering and template matching as soon as it is registered.
    """
    ver = str(version or "").strip()
    if not ver:
        raise ValueError("a stylesheet package version is required")
    if not isinstance(package, dict) or "views" not in package:
        raise ValueError("a stylesheet package must be a dict carrying 'views'")
    _STYLESHEET_PACKAGES[ver] = package


# ---------------------------------------------------------------------------
# Version matching — stylesheet matched to the REP template that produced it
# ---------------------------------------------------------------------------

def stylesheet_for_template(kind: str, template_version: str) -> dict:
    """REQ-065: pick the stylesheet edition MATCHED to a REP template version.

    Searches bundled packages (newest first) for one whose ``covers_templates``
    for ``kind`` includes ``template_version``. Returns
    ``{"version", "package", "view", "title"}``. Raises
    :class:`StylesheetVersionError` when no bundled edition matches — the portal
    refuses to preview with a mismatched stylesheet.
    """
    kind = str(kind or "").strip()
    template_version = str(template_version or "").strip()
    for ver in reversed(available_versions()):
        pkg = _STYLESHEET_PACKAGES[ver]
        covers = pkg.get("covers_templates", {}).get(kind, [])
        view = pkg.get("views", {}).get(kind)
        if view is not None and template_version in covers:
            return {"version": ver, "package": pkg.get("package",
                                                        STYLESHEET_PACKAGE),
                    "view": _copy_package(view), "title": pkg.get("title", "")}
    raise StylesheetVersionError(
        f"no bundled REP XML stylesheet matches {kind!r} template version "
        f"{template_version!r}")


def template_version_for_kind(kind: str) -> str:
    """The REP template version this app currently generates for ``kind``."""
    return {
        "co": rep.CO_TEMPLATE_VERSION,
        "rt": rep.RT_TEMPLATE_VERSION,
        "pi": rep.PI_TEMPLATE_VERSION,
        "ca_regional": rep.CA_MODULE1_SCHEMA_VERSION,
    }.get(str(kind or "").strip(), "")


# ---------------------------------------------------------------------------
# Rendering — what HC will actually display
# ---------------------------------------------------------------------------

def _detect_kind(root_tag: str) -> str:
    """Map a parsed root tag to a REP artifact kind, or '' when unknown."""
    return _ROOT_TAG_TO_KIND.get(str(root_tag or "").strip(), "")


def _parse(xml_text: str) -> "ET.Element":
    """Hardened parse of caller-supplied REP XML into an ElementTree root."""
    xmlsafe.assert_xml_entity_safe(xml_text)
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise StylesheetRenderError(f"REP XML is not well-formed: {exc}")


def _render_rows(parent: "ET.Element", fields: list) -> list:
    """Turn a list of field rules into structured ``rows`` for one element.

    Each row is ``{"label", "value", "code"(opt), "rows"(opt for repeats)}``.
    """
    rows: list = []
    for rule in fields:
        label = rule.get("label", rule.get("path", ""))
        if rule.get("repeat"):
            occurrences = parent.findall(rule["path"])
            sub = [_render_rows(occ, rule.get("fields", []))
                   for occ in occurrences]
            rows.append({"label": label, "value": "", "rows": sub})
            continue
        el = parent.find(rule["path"])
        if rule.get("attr"):
            value = "" if el is None else (el.get(rule["attr"], "") or "")
        else:
            value = "" if el is None else (el.text or "")
        row = {"label": label, "value": value.strip()}
        if rule.get("code") and el is not None:
            row["code"] = (el.get(rule["code"], "") or "").strip()
        rows.append(row)
    return rows


def _rows_to_html(rows: list, depth: int = 0) -> str:
    """Render structured rows into an HC-style definition table (escaped)."""
    html = ['<table class="rep-render">']
    for row in rows:
        if "rows" in row:
            html.append(
                f'<tr><th colspan="2" class="rep-group">{_h(row["label"])}'
                "</th></tr>")
            if not row["rows"]:
                html.append('<tr><td colspan="2" class="rep-empty">'
                            "(none)</td></tr>")
            for i, occ in enumerate(row["rows"], 1):
                html.append(
                    f'<tr><td colspan="2" class="rep-occ">#{i}'
                    f"{_rows_to_html(occ, depth + 1)}</td></tr>")
            continue
        value = _h(row["value"]) if row["value"] else \
            '<span class="rep-blank">—</span>'
        if row.get("code"):
            value = f'<span class="rep-code">{_h(row["code"])}</span> {value}'
        html.append(
            f'<tr><th>{_h(row["label"])}</th><td>{value}</td></tr>')
    html.append("</table>")
    return "".join(html)


def render_rep_xml(xml_text: str, kind: str | None = None,
                   template_version: str | None = None) -> dict:
    """REQ-065: render generated REP XML through the version-matched stylesheet.

    Parses ``xml_text`` (kind auto-detected from the root element when not
    given), selects the stylesheet edition matched to the REP template version,
    and produces the human-review HTML — *what HC will display* — for pre-file
    review.

    Returns a dict:
      ``kind``, ``template_version``, ``stylesheet`` (package + version + title),
      ``review_stage`` (``"pre-file"``), ``rows`` (structured) and ``html``.

    Raises :class:`StylesheetRenderError` for malformed/unknown XML and
    :class:`StylesheetVersionError` when no stylesheet matches the template.
    """
    root = _parse(xml_text)
    detected = _detect_kind(root.tag)
    kind = str(kind or "").strip() or detected
    if not kind or kind not in _ROOT_TAG_TO_KIND.values():
        raise StylesheetRenderError(
            f"unrecognised REP XML root element {root.tag!r}; cannot render")
    if detected and kind != detected:
        raise StylesheetRenderError(
            f"REP XML root {root.tag!r} does not match requested kind {kind!r}")

    # Version matching: prefer an explicit template version, else read it off the
    # document's own version attribute, else fall back to the app's current one.
    active_view = _STYLESHEET_PACKAGES[active_version()]["views"].get(kind) or {}
    version_attr = active_view.get("version_attr")
    doc_version = root.get(version_attr, "") if version_attr else ""
    resolved_version = (str(template_version or "").strip()
                        or str(doc_version or "").strip()
                        or template_version_for_kind(kind))
    match = stylesheet_for_template(kind, resolved_version)

    rows = _render_rows(root, match["view"]["fields"])
    return {
        "kind": kind,
        "title": match["view"].get("title", kind),
        "template_version": resolved_version,
        "review_stage": REVIEW_STAGE,
        "matched": True,
        "stylesheet": {
            "package": match["package"],
            "version": match["version"],
            "title": match["title"],
        },
        "rows": rows,
        "html": _rows_to_html(rows),
    }


# Artifact kinds inside an assembled transaction, in display order.
_TRANSACTION_ARTIFACTS = [
    ("co", "co"), ("rt", "rt"), ("pi", "pi"), ("ca_regional", "ca_regional"),
]


def render_transaction(transaction: dict) -> dict:
    """REQ-065: render every REP artifact in an assembled transaction for review.

    Walks the ``assemble_transaction`` output, rendering each present REP XML
    artifact (CO, RT, optional PI, and the ca-regional backbone) through its
    version-matched stylesheet. Returns
    ``{"review_stage", "stylesheet", "artifacts": [...]}`` ready for the
    pre-file human-review panel.
    """
    transaction = transaction or {}
    artifacts: list = []
    pkg_versions = set()
    for key, kind in _TRANSACTION_ARTIFACTS:
        node = transaction.get(key)
        if not node or not node.get("xml"):
            continue
        tmpl = (node.get("template_version")
                or node.get("schema_version")
                or template_version_for_kind(kind))
        rendered = render_rep_xml(node["xml"], kind=kind, template_version=tmpl)
        rendered["filename"] = node.get("filename") or node.get("path", "")
        artifacts.append(rendered)
        pkg_versions.add(rendered["stylesheet"]["version"])
    return {
        "review_stage": REVIEW_STAGE,
        "stylesheet": {
            "package": STYLESHEET_PACKAGE,
            "versions": sorted(pkg_versions),
        },
        "artifacts": artifacts,
    }


def package_manifest() -> dict:
    """REQ-065/040: the bundled stylesheet package, version-tracked.

    The shape the ``/api/rep/stylesheet`` GET surfaces: package name, every
    bundled version, the active one, and per-version template coverage.
    """
    versions = []
    for ver in available_versions():
        pkg = _STYLESHEET_PACKAGES[ver]
        versions.append({
            "version": ver,
            "package": pkg.get("package", STYLESHEET_PACKAGE),
            "published": pkg.get("published", ver),
            "title": pkg.get("title", ""),
            "covers_templates": {k: list(v) for k, v in
                                 pkg.get("covers_templates", {}).items()},
            "kinds": sorted(pkg.get("views", {})),
        })
    return {
        "package": STYLESHEET_PACKAGE,
        "active_version": active_version(),
        "review_stage": REVIEW_STAGE,
        "versions": versions,
    }
