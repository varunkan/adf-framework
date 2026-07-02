"""Focused eCTD assembly engine + Application Viewer (REQ-107) — pure, stdlib.

Ported from the monolith ``ectd``: a dossier is sequences of leaf operations;
``current_view`` reconstructs the live set (new/replace/append/delete), and the
viewer composes a Files view (Module-1 placement tree + live leaf properties) and
an Outline view (backbone index.xml/ca-regional.xml + lifecycle ops + metadata).
"""

from __future__ import annotations

import hashlib
import uuid
import xml.etree.ElementTree as ET

from . import ectd

VALID_OPERATIONS = ("new", "replace", "append", "delete")
OPERATIONS_REQUIRING_PRIOR = ("replace", "append", "delete")


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def md5_hex(content) -> str:
    data = content if isinstance(content, bytes) else _s(content).encode("utf-8")
    return hashlib.md5(data).hexdigest()


def _seq_key(sequence: str) -> str:
    s = _s(sequence)
    return s.zfill(4) if s.isdigit() else s


def new_dossier(dossier_id: str) -> dict:
    return {"dossier_id": _s(dossier_id), "sequences": []}


def _get_sequence(dossier: dict, sequence: str):
    key = _seq_key(sequence)
    return next((s for s in dossier["sequences"] if s["sequence"] == key), None)


def _find_leaf(dossier: dict, leaf_id: str):
    leaf_id = _s(leaf_id)
    for s in dossier["sequences"]:
        for lf in s["leaves"]:
            if lf["leaf_id"] == leaf_id:
                return lf
    return None


def leaves_in_order(dossier: dict) -> list:
    out = []
    for s in sorted(dossier["sequences"], key=lambda x: x["sequence"]):
        out.extend(s["leaves"])
    return out


def compute_current_view(leaves) -> dict:
    """Reconstruct the live leaf set from operations in order (REQ-018)."""
    live: dict = {}
    history: list = []
    for leaf in leaves:
        op = _s(leaf.get("operation"))
        target = _s(leaf.get("modified_leaf")) or None
        if op in ("new", "append"):
            live[leaf["leaf_id"]] = leaf
        elif op == "replace":
            if target and target in live:
                history.append(live.pop(target))
            live[leaf["leaf_id"]] = leaf
        elif op == "delete":
            if target and target in live:
                history.append(live.pop(target))
            history.append(leaf)
    return {"live": list(live.values()), "history": history}


def validate_leaf_operation(leaf: dict, live_leaf_ids) -> list:
    """Errors that would block a single leaf operation (REQ-017)."""
    errors = []
    op = _s(leaf.get("operation"))
    target = _s(leaf.get("modified_leaf")) or None
    leaf_id = _s(leaf.get("leaf_id"))
    if not leaf_id:
        errors.append({"rule": "leaf_id_required", "message": "a leaf ID is required"})
    if op not in VALID_OPERATIONS:
        errors.append({"rule": "operation_invalid",
                       "message": "operation must be one of "
                                  + ", ".join(VALID_OPERATIONS)})
        return errors
    if op in OPERATIONS_REQUIRING_PRIOR:
        if not target:
            errors.append({"rule": "prior_leaf_required",
                           "message": f"a '{op}' operation must reference a prior "
                                      "leaf (modified_leaf)"})
        elif target not in set(live_leaf_ids):
            errors.append({"rule": "prior_leaf_unknown",
                           "message": f"prior leaf '{target}' is not in the "
                                      "current live view"})
    return errors


def add_leaf(dossier: dict, sequence: str, leaf: dict) -> dict:
    """Validate + append a leaf operation. Raises ``ValueError`` on violation."""
    seq = _get_sequence(dossier, sequence)
    if seq is None:
        seq = {"sequence": _seq_key(sequence), "leaves": []}
        dossier["sequences"].append(seq)
    leaf_id = _s(leaf.get("leaf_id"))
    if _find_leaf(dossier, leaf_id):
        raise ValueError(f"leaf ID '{leaf_id}' already exists")
    live_ids = {lf["leaf_id"] for lf in
                compute_current_view(leaves_in_order(dossier))["live"]}
    errors = validate_leaf_operation(leaf, live_ids)
    if errors:
        raise ValueError(errors[0]["message"])
    heading = _s(leaf.get("heading"))
    placement = ectd.placement_for_heading(heading)
    href = _s(leaf.get("href"))
    if not href and placement:
        href = f"{placement['folder']}/{leaf_id or placement['leaf_id']}.pdf"
    op = _s(leaf.get("operation"))
    checksum = "" if op == "delete" else md5_hex(leaf.get("content") or href)
    record = {"leaf_id": leaf_id, "operation": op, "heading": heading,
              "title": _s(leaf.get("title")), "href": href, "checksum": checksum,
              "modified_leaf": _s(leaf.get("modified_leaf")) or None,
              "sequence": seq["sequence"], "uuid": uuid.uuid4().hex}
    seq["leaves"].append(record)
    return record


def set_leaf(dossier: dict, sequence: str, leaf: dict) -> dict:
    """Build-time upsert: idempotently place a leaf in a sequence (remove any
    prior leaf with the same id, then add it fresh as ``new``). This is for
    building the working sequence before transmission; cross-sequence
    replace/append/delete lifecycle is handled separately (Phase 3)."""
    leaf_id = _s(leaf.get("leaf_id"))
    for s in dossier["sequences"]:
        s["leaves"] = [lf for lf in s["leaves"] if lf["leaf_id"] != leaf_id]
    payload = {k: v for k, v in leaf.items() if k != "operation"}
    payload["operation"] = "new"
    return add_leaf(dossier, sequence, payload)


def set_leaf_lifecycle(dossier: dict, sequence: str, leaf: dict) -> dict:
    """Lifecycle-aware build-time placement for working sequences 0001+.

    Within the target sequence this keeps ``set_leaf``'s idempotent upsert
    semantics (re-placing the same document just refreshes it). When the
    document is already live from an EARLIER sequence, the placement is
    recorded as a ``replace`` operation whose ``modified_leaf`` points at
    that prior leaf — the lifecycle a response/supplement transaction must
    carry. The replacement leaf id is suffixed with the sequence number so
    leaf ids stay unique across the dossier."""
    seq_key = _seq_key(sequence)
    base = _s(leaf.get("leaf_id"))
    seq = _get_sequence(dossier, seq_key)
    if seq is not None:   # drop any working copy from the TARGET sequence only
        seq["leaves"] = [lf for lf in seq["leaves"]
                         if (lf.get("base_id") or lf["leaf_id"]) != base]
    prior = next(
        (lf for lf in compute_current_view(leaves_in_order(dossier))["live"]
         if (lf.get("base_id") or lf["leaf_id"]) == base
         and lf["sequence"] != seq_key), None)
    payload = {k: v for k, v in leaf.items() if k != "operation"}
    if prior is None:
        payload["operation"] = "new"
        payload["modified_leaf"] = None
    else:
        payload["operation"] = "replace"
        payload["modified_leaf"] = prior["leaf_id"]
        payload["leaf_id"] = f"{base}-{seq_key}"
    record = add_leaf(dossier, seq_key, payload)
    record["base_id"] = base
    return record


def add_sequence(dossier: dict, sequence: str, *, purpose: str = "",
                 note: str = "") -> dict:
    """Open a new (empty) sequence on the dossier if absent; return the dossier.

    ``purpose``/``note`` (regulatory activity metadata) are recorded on the
    sequence dict when given; existing callers passing neither are unchanged."""
    seq = _get_sequence(dossier, sequence)
    if seq is None:
        seq = {"sequence": _seq_key(sequence), "leaves": []}
        dossier["sequences"].append(seq)
    if purpose:
        seq["purpose"] = _s(purpose)
    if note:
        seq["note"] = _s(note)
    return dossier


def current_view(dossier: dict) -> dict:
    view = compute_current_view(leaves_in_order(dossier))
    keys = ("leaf_id", "title", "heading", "href", "operation", "sequence",
            "checksum", "modified_leaf")
    return {"live": [{k: lf.get(k, "") for k in keys} for lf in view["live"]],
            "history": [{k: lf.get(k, "") for k in keys}
                        for lf in view["history"]]}


def build_files_view(dossier: dict) -> dict:
    """REQ-107 Files view: Module-1 placement tree + the live leaves at each."""
    view = current_view(dossier)
    by_heading: dict = {}
    for lf in view["live"]:
        by_heading.setdefault(lf["heading"], []).append(lf)
    nodes = []
    seen = set()
    for entry in ectd.CA_MODULE1_PLACEMENT:
        nodes.append({"heading": entry["heading"], "title": entry["title"],
                      "folder": entry["folder"],
                      "leaves": by_heading.get(entry["heading"], [])})
        seen.add(entry["heading"])
    # any placed leaves at deeper M1 / Module 2-5 headings not in the M1 table
    for heading in sorted(by_heading):
        if heading in seen:
            continue
        leaves = by_heading[heading]
        folder = leaves[0].get("href", "").rsplit("/", 1)[0] if leaves else ""
        nodes.append({"heading": heading, "title": heading, "folder": folder,
                      "leaves": leaves})
    return {"dossier_id": dossier["dossier_id"],
            "placement_version": ectd.PLACEMENT_TABLE_VERSION, "nodes": nodes,
            "live_leaf_count": len(view["live"])}


def build_outline_view(dossier: dict, sequence: str) -> dict:
    """REQ-107 Outline view: backbone XML + lifecycle ops + admin metadata."""
    view = current_view(dossier)
    root = ET.Element("ectd-index", {"dossier-id": dossier["dossier_id"],
                                     "sequence": _seq_key(sequence)})
    for lf in view["live"]:
        ET.SubElement(root, "leaf", {"id": lf["leaf_id"], "href": lf["href"],
                                     "checksum": lf["checksum"]})
    index_xml = ET.tostring(root, encoding="unicode")
    ca = ET.Element("ca-regional")
    ET.SubElement(ca, "dossier-id").text = dossier["dossier_id"]
    ca_regional_xml = ET.tostring(ca, encoding="unicode")
    ops = [{"leaf_id": lf["leaf_id"], "operation": lf["operation"],
            "modified_leaf": lf.get("modified_leaf"), "sequence": lf["sequence"]}
           for lf in leaves_in_order(dossier)]
    return {"dossier_id": dossier["dossier_id"], "sequence": _seq_key(sequence),
            "backbone": {"index.xml": index_xml,
                         "ca-regional.xml": ca_regional_xml},
            "lifecycle_operations": ops,
            "document_uuids": [lf.get("uuid") for lf in leaves_in_order(dossier)]}
