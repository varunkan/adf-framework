"""eCTD technical validator over an assembled dossier model (REQ-107 gap).

Pure + stdlib. Given an assembled dossier (:mod:`assembly` model — sequences of
leaf operations), replays the lifecycle in order and reports the technical
defects Health Canada's eCTD validation would flag *before* transmission:

  - every LIVE leaf carries a non-empty ``href`` AND ``checksum``;
  - no ``leaf_id`` is duplicated across the whole dossier;
  - each operation is legal at the point it is applied (new/replace/append/
    delete), reusing :func:`assembly.validate_leaf_operation` semantics against
    the live set reconstructed *up to that leaf*;
  - ``href`` naming hygiene: lowercase, no spaces (errors), and a ``m1``..``m5``
    module-folder prefix (a warning if it does not match);
  - backbone well-formedness: :func:`assembly.build_outline_view` then an
    ``xml.etree`` parse of index.xml + ca-regional.xml must succeed;
  - optional document bytes: a ``.pdf`` whose bytes do not start with ``%PDF``
    is a ``pdf_header`` error; bytes containing ``/Encrypt`` are ``pdf_encrypted``
    (HC rejects secured PDFs).

``passed`` is true iff there are zero errors.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from . import assembly

# a leaf href must live under a module folder m1..m5, e.g. "m1/ca/13-.../131-pm.pdf"
MODULE_FOLDER_RE = re.compile(r"^m[1-5]/")
PDF_MAGIC = b"%PDF"
PDF_ENCRYPT_MARKER = b"/Encrypt"


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _err(rule: str, message: str, leaf) -> dict:
    return {"rule": rule, "message": message, "leaf": leaf}


def _live_leaf_check(dossier: dict, errors: list) -> None:
    """Every leaf in the current live view needs an href AND a checksum."""
    for lf in assembly.current_view(dossier)["live"]:
        leaf_id = _s(lf.get("leaf_id"))
        if not _s(lf.get("href")):
            errors.append(_err("href_required",
                               "a live leaf must have a non-empty href", leaf_id))
        if not _s(lf.get("checksum")):
            errors.append(_err("checksum_required",
                               "a live leaf must have a non-empty checksum",
                               leaf_id))


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
        for e in assembly.validate_leaf_operation(lf, set(live.keys())):
            errors.append(_err(e["rule"], e["message"], leaf_id))
        # advance the live set exactly as compute_current_view would
        op = _s(lf.get("operation"))
        target = _s(lf.get("modified_leaf")) or None
        if op in ("new", "append"):
            live[leaf_id] = lf
        elif op == "replace":
            if target and target in live:
                live.pop(target)
            live[leaf_id] = lf
        elif op == "delete":
            if target and target in live:
                live.pop(target)


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


def _backbone_check(dossier: dict, errors: list) -> None:
    seqs = [s["sequence"] for s in dossier.get("sequences", [])]
    sequence = seqs[-1] if seqs else "0000"
    try:
        outline = assembly.build_outline_view(dossier, sequence)
        backbone = outline["backbone"]
        ET.fromstring(backbone["index.xml"])
        ET.fromstring(backbone["ca-regional.xml"])
    except (ET.ParseError, KeyError, TypeError) as exc:
        errors.append(_err("backbone_malformed",
                           f"backbone XML failed to parse: {exc}", None))


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
    leaf count. ``passed`` is true iff ``errors`` is empty.
    """
    errors: list = []
    warnings: list = []

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
