#!/usr/bin/env python3
"""
ANDS Submission Portal — rejection / eCTD Validation Report ingestion (REQ-029).

WHEN a transaction is rejected, Health Canada emails an **eCTD Validation
Report** (a PDF). This module ingests that report (its extracted text — no
third-party PDF library, stdlib only), correlates it to the originating
transaction **via the Core ID**, and maps **each reported error back to the
exact file / node in the dossier tree** so it can be corrected in the next
sequence.

Pure, deterministic and dependency-free: callers (server.py) supply the
transaction views from the transmission ledger and the leaves from the eCTD
dossier; everything here is unit-testable in isolation.

Parsing is deliberately tolerant. The report is treated as text with:
  * a header block of ``Key: value`` lines (Core ID, Dossier ID, Sequence,
    Validation Result), and
  * one error row per finding, prefixed by a bracketed severity tag and
    pipe-delimited::

        [ERROR]   <rule_id> | <file> | <node> | <message>
        [WARNING] <rule_id> | <file> | <node> | <message>

    where ``<node>`` may be ``leaf:<leaf_id>`` (an eCTD leaf), ``node:<xpath>``
    (a backbone node) or empty. Missing trailing fields are tolerated.
"""

from __future__ import annotations

import re

# Severity tags HC uses on the validation report.
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
_SEVERITY_ALIASES = {
    "ERROR": SEVERITY_ERROR, "FAIL": SEVERITY_ERROR, "FAILURE": SEVERITY_ERROR,
    "WARNING": SEVERITY_WARNING, "WARN": SEVERITY_WARNING,
}

# A finding row: [SEVERITY] field | field | field | field
_ROW_RE = re.compile(r"^\s*\[(?P<sev>[A-Za-z]+)\]\s*(?P<body>.*)$")
# A header "Key: value" line (only before/around the findings).
_HEADER_RE = re.compile(r"^\s*(?P<key>[A-Za-z][A-Za-z /]+?)\s*:\s*(?P<val>.+?)\s*$")

# Canonical header keys we care about, mapped from their many spellings.
_HEADER_KEYS = {
    "core id": "core_id",
    "coreid": "core_id",
    "dossier id": "dossier_id",
    "dossier": "dossier_id",
    "sequence": "sequence",
    "validation result": "result",
    "result": "result",
}


class ReportParseError(ValueError):
    """Raised when the validation-report text carries no usable content."""


def _norm(value) -> str:
    return str(value or "").strip()


def _split_node(node: str):
    """Split a reported node into ``(leaf_id, xpath)``.

    ``leaf:cover-001`` -> ("cover-001", ""); ``node:/ectd/...`` -> ("", "/ectd/...");
    a bare value is treated as a leaf id (HC commonly quotes the leaf).
    """
    node = _norm(node)
    if not node:
        return "", ""
    low = node.lower()
    if low.startswith("leaf:"):
        return node[5:].strip(), ""
    if low.startswith("node:"):
        return "", node[5:].strip()
    if low.startswith("xpath:"):
        return "", node[6:].strip()
    # Bare token: a slash means an xpath, otherwise a leaf id.
    if node.startswith("/"):
        return "", node
    return node, ""


def parse_validation_report(text: str) -> dict:
    """Parse the emailed eCTD Validation Report text (REQ-029).

    Returns ``{core_id, dossier_id, sequence, result, errors:[...]}`` where each
    error is ``{severity, rule_id, file, node, leaf_id, xpath, message}``. Raises
    :class:`ReportParseError` when there is nothing parseable at all.
    """
    text = str(text or "")
    if not text.strip():
        raise ReportParseError("validation report is empty")

    header = {"core_id": "", "dossier_id": "", "sequence": "", "result": ""}
    errors: list = []

    for raw in text.splitlines():
        row = _ROW_RE.match(raw)
        if row:
            sev = _SEVERITY_ALIASES.get(row.group("sev").upper())
            if sev is None:
                continue
            parts = [p.strip() for p in row.group("body").split("|")]
            rule_id = parts[0] if len(parts) > 0 else ""
            file_ = parts[1] if len(parts) > 1 else ""
            node = parts[2] if len(parts) > 2 else ""
            message = parts[3] if len(parts) > 3 else ""
            # A 2-field row is "rule | message"; a 3-field row is "rule|file|msg".
            if len(parts) == 2:
                rule_id, message, file_, node = parts[0], parts[1], "", ""
            elif len(parts) == 3:
                rule_id, file_, message, node = parts[0], parts[1], parts[2], ""
            leaf_id, xpath = _split_node(node)
            errors.append({
                "severity": sev,
                "rule_id": rule_id,
                "file": file_,
                "node": node,
                "leaf_id": leaf_id,
                "xpath": xpath,
                "message": message,
            })
            continue
        h = _HEADER_RE.match(raw)
        if h:
            key = _HEADER_KEYS.get(h.group("key").strip().lower())
            if key and not header[key]:
                header[key] = h.group("val").strip()

    return {
        "core_id": header["core_id"],
        "dossier_id": header["dossier_id"],
        "sequence": header["sequence"],
        "result": header["result"],
        "errors": errors,
    }


def _next_sequence(existing_sequences) -> str:
    """Next 4-digit eCTD sequence after the dossier's accepted set (REQ-016)."""
    nums = []
    for s in existing_sequences or ():
        try:
            nums.append(int(str(s).strip()))
        except (TypeError, ValueError):
            continue
    return "0000" if not nums else f"{max(nums) + 1:04d}"


def _index_leaves(leaves):
    """Build ``(by_leaf_id, by_file)`` lookup maps over the dossier's leaves."""
    by_leaf_id, by_file = {}, {}
    for lf in leaves or ():
        lid = _norm(lf.get("leaf_id"))
        href = _norm(lf.get("href"))
        if lid:
            by_leaf_id[lid] = lf
        if href:
            by_file[href] = lf
    return by_leaf_id, by_file


def _map_error_to_leaf(error: dict, by_leaf_id: dict, by_file: dict):
    """Map one reported error back to the exact dossier leaf (REQ-029).

    Priority: an explicit ``leaf:<id>`` node, then the reported file (href),
    then a file basename match. Returns the leaf dict or ``None``.
    """
    leaf_id = error.get("leaf_id")
    if leaf_id and leaf_id in by_leaf_id:
        return by_leaf_id[leaf_id]
    file_ = _norm(error.get("file"))
    if file_ and file_ in by_file:
        return by_file[file_]
    # Fall back to a basename match (the report may quote a relative path).
    if file_:
        base = file_.rsplit("/", 1)[-1]
        for href, lf in by_file.items():
            if href.rsplit("/", 1)[-1] == base:
                return lf
    return None


def correlate_rejection(report_text: str, transactions=(), leaves=(),
                        existing_sequences=()) -> dict:
    """Ingest a rejection report and correlate it end-to-end (REQ-029).

    * Parses the emailed eCTD Validation Report text.
    * Correlates it to the originating transaction **via the Core ID**.
    * Maps **each reported error** back to the exact file / node in the dossier
      tree, flagging the ones that cannot be located.
    * Produces a remediation plan targeting the **next sequence**.

    ``transactions`` are the ledger's transaction views (each carries
    ``core_id``/``sequence``/``state``); ``leaves`` are the dossier's live leaves
    (``leaf_id``/``href``/``heading``/``title``); ``existing_sequences`` are the
    dossier's accepted sequence numbers (for the next-sequence computation).
    """
    report = parse_validation_report(report_text)
    core_id = report["core_id"]

    # 1. Correlate to the originating transaction by Core ID (REQ-029).
    txn = None
    for t in transactions or ():
        if _norm(t.get("core_id")) and _norm(t.get("core_id")) == core_id:
            txn = t
            break
    correlated = txn is not None

    # 2. Map every reported error back to a leaf in the dossier tree.
    by_leaf_id, by_file = _index_leaves(leaves)
    next_seq = _next_sequence(existing_sequences)

    mapped_errors, unmatched = [], []
    for err in report["errors"]:
        leaf = _map_error_to_leaf(err, by_leaf_id, by_file)
        item = {
            "severity": err["severity"],
            "rule_id": err["rule_id"],
            "message": err["message"],
            "reported_file": err["file"],
            "reported_node": err["node"],
            "mapped": leaf is not None,
        }
        if leaf is not None:
            item.update({
                "leaf_id": _norm(leaf.get("leaf_id")),
                "heading": _norm(leaf.get("heading")),
                "title": _norm(leaf.get("title")),
                "href": _norm(leaf.get("href")),
                "action": (f"Correct leaf '{_norm(leaf.get('leaf_id'))}' "
                           f"({_norm(leaf.get('href')) or _norm(leaf.get('heading'))}) "
                           f"and re-file in sequence {next_seq}"),
            })
        else:
            target = err["file"] or err["node"] or err["rule_id"]
            item["action"] = (
                f"Locate '{target}' — not found in the current dossier tree; "
                f"add or correct it in sequence {next_seq}")
            unmatched.append(item)
        mapped_errors.append(item)

    error_items = [e for e in mapped_errors if e["severity"] == SEVERITY_ERROR]
    return {
        "correlated": correlated,
        "core_id": core_id,
        "report_dossier_id": report["dossier_id"],
        "report_sequence": report["sequence"],
        "result": report["result"],
        "transaction": txn,
        "error_count": len(error_items),
        "warning_count": len(mapped_errors) - len(error_items),
        "mapped_count": sum(1 for e in mapped_errors if e["mapped"]),
        "unmatched_count": len(unmatched),
        "errors": mapped_errors,
        "unmatched": unmatched,
        "remediation": {
            "next_sequence": next_seq,
            "items": [e for e in mapped_errors
                      if e["severity"] == SEVERITY_ERROR],
        },
    }
