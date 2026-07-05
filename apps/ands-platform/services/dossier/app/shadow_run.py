"""CAMP-SHADOW — shadow / parallel-run comparison over a known-good sequence.

The one thing 16/24 task-eval personas named before trusting the tool live:

    "Before I trust it live I would run it in parallel against a filing we KNOW
     passed eValidator and diff the tool's output against our validated
     publisher's output."

This module makes that a first-class, structured affordance. Given the tool's
own view of a prior / known-good sequence — the structural validation result
(:mod:`ectd_validation`), the transmissible package it just built
(:mod:`export_pkg`) and its import-compatibility self-check (:mod:`import_compat`)
— it assembles a DIFF-FRIENDLY *shadow-run comparison record*:

  - ``validation``           the tool's structural verdict (errors/warnings),
                             with the honest criteria/disclaimer;
  - ``import_compat``        the structural import-compatibility report over the
                             REAL package bytes (what any compliant importer
                             finds), incl. the package ``inventory``;
  - ``leaf_inventory``       every live/shipped leaf as
                             ``{leaf_id, href, md5, operation, title, heading}``
                             — the granular list a filer lines up against their
                             publisher's leaf list;
  - ``lifecycle_operations`` the new/replace/append/delete ops in order.

When the filer supplies a known-good REFERENCE (the leaves their publisher's
validated output enumerated — ``{leaf_id, href, checksum}``), the module
computes a leaf-level DIFF: ``matched`` / ``checksum_mismatch`` /
``only_in_tool`` / ``only_in_reference``, plus an ``identical`` flag.

Honest scope: this is a CONFIDENCE-BUILDING comparison of the tool's own
structural output against a known-good reference — it is NOT a guarantee the
sequence will pass Health Canada's official eValidator, and it never drives the
filing gate. Run eValidator (or your publisher's validator) before you transmit.

Pure + stdlib. The service layer resolves the model/package/validation and the
optional reference; this module does the assembly + diff so it is trivially
unit-testable (mirroring :mod:`import_compat`).
"""

from __future__ import annotations

from . import assembly, import_compat

MODE = "shadow"

DISCLAIMER = (
    "This is a shadow / parallel-run comparison. It runs ANDS Studio's own "
    "STRUCTURAL validator and import-compatibility self-check over this "
    "sequence and lays the result out so you can diff it against a filing you "
    "already KNOW passed your validated publisher / Health Canada's eValidator. "
    "It is a confidence-building comparison of structural output — NOT a "
    "guarantee this sequence will pass HC's official eValidator, and it does "
    "not drive the filing gate. Run eValidator (or your publisher's validator) "
    "before you transmit."
)


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def leaf_inventory(model: dict, sequence: str) -> list[dict]:
    """Every leaf this sequence ships, as a diff-friendly inventory row.

    A ``delete`` leaf carries no bytes (its md5 is empty by construction) but is
    still enumerated so a lifecycle retirement is visible in the diff. Each row
    is ``{leaf_id, href, md5, operation, title, heading}``.
    """
    rows: list[dict] = []
    for lf in assembly.sequence_leaves(model, sequence):
        rows.append({
            "leaf_id": _s(lf.get("leaf_id")),
            "href": _s(lf.get("href")),
            "md5": _s(lf.get("checksum")),
            "operation": _s(lf.get("operation")),
            "title": _s(lf.get("title")),
            "heading": _s(lf.get("heading")),
        })
    return rows


def lifecycle_operations(model: dict, sequence: str) -> list[dict]:
    """The new/replace/append/delete operations in this sequence, in order."""
    return [{"leaf_id": _s(lf.get("leaf_id")),
             "operation": _s(lf.get("operation")),
             "modified_leaf": _s(lf.get("modified_leaf")) or None}
            for lf in assembly.sequence_leaves(model, sequence)]


def diff_against_reference(inventory: list[dict],
                           reference: list[dict]) -> dict:
    """Leaf-level diff of the tool's ``inventory`` against a known-good
    ``reference`` (each ``{leaf_id, href, checksum}``).

    Matched by ``leaf_id``. For a matched pair, when BOTH sides carry a checksum
    a mismatch is flagged (bytes differ); when either side omits its checksum
    the row is still matched (by id) but the checksum comparison is recorded as
    ``unknown`` rather than a false mismatch. Buckets: ``matched`` (with a
    ``checksum_match`` tri-state), ``checksum_mismatch``, ``only_in_tool``,
    ``only_in_reference``; plus ``identical`` (true iff every leaf lines up with
    no mismatch and no side-only rows).
    """
    tool_by_id = {r["leaf_id"]: r for r in inventory if _s(r.get("leaf_id"))}
    ref_by_id: dict[str, dict] = {}
    for r in (reference or []):
        lid = _s(r.get("leaf_id"))
        if lid and lid not in ref_by_id:
            ref_by_id[lid] = r

    matched: list[dict] = []
    checksum_mismatch: list[dict] = []
    only_in_tool: list[dict] = []
    only_in_reference: list[dict] = []

    for lid, tool in tool_by_id.items():
        ref = ref_by_id.get(lid)
        if ref is None:
            only_in_tool.append({"leaf_id": lid, "href": tool.get("href"),
                                 "md5": tool.get("md5"),
                                 "operation": tool.get("operation")})
            continue
        tool_md5 = _s(tool.get("md5")).lower()
        ref_md5 = _s(ref.get("checksum")).lower()
        if tool_md5 and ref_md5:
            state = "match" if tool_md5 == ref_md5 else "mismatch"
        else:
            state = "unknown"
        row = {"leaf_id": lid,
               "tool_href": tool.get("href"),
               "reference_href": _s(ref.get("href")) or None,
               "tool_md5": tool_md5 or None,
               "reference_checksum": ref_md5 or None,
               "checksum_match": state,
               "operation": tool.get("operation")}
        matched.append(row)
        if state == "mismatch":
            checksum_mismatch.append(row)

    for lid, ref in ref_by_id.items():
        if lid not in tool_by_id:
            only_in_reference.append({"leaf_id": lid,
                                      "href": _s(ref.get("href")) or None,
                                      "checksum": _s(ref.get("checksum"))
                                      or None})

    identical = (not checksum_mismatch and not only_in_tool
                 and not only_in_reference)
    return {
        "identical": identical,
        "matched": matched,
        "checksum_mismatch": checksum_mismatch,
        "only_in_tool": only_in_tool,
        "only_in_reference": only_in_reference,
        "matched_count": len(matched),
        "tool_leaf_count": len(tool_by_id),
        "reference_leaf_count": len(ref_by_id),
    }


def build_shadow_report(model: dict, sequence: str, pkg: dict,
                        validation: dict,
                        *, reference: list[dict] | None = None) -> dict:
    """Assemble the structured shadow-run comparison record.

    ``pkg`` is the :func:`export_pkg.build_package` result for ``sequence``;
    ``validation`` is the :func:`ectd_validation.validate` result (scoped to the
    sequence). ``reference`` optionally supplies the known-good leaf list to
    diff against. The import-compatibility self-check runs over the real package
    bytes here, so the record is a single, archivable parallel-run artefact.
    """
    seq = assembly._seq_key(sequence)
    inventory = leaf_inventory(model, seq)
    ic = import_compat.import_compatibility_report(pkg)
    diff = (diff_against_reference(inventory, reference)
            if reference is not None else None)
    return {
        "mode": MODE,
        "dossier_id": _s(model.get("dossier_id")),
        "sequence": seq,
        "validation": {
            "passed": bool(validation.get("passed")),
            "errors": validation.get("errors", []),
            "warnings": validation.get("warnings", []),
            "criteria": validation.get("criteria") or {},
        },
        "import_compat": ic,
        "leaf_inventory": inventory,
        "leaf_count": len(inventory),
        "lifecycle_operations": lifecycle_operations(model, seq),
        "has_reference": reference is not None,
        "diff": diff,
        "disclaimer": DISCLAIMER,
    }
