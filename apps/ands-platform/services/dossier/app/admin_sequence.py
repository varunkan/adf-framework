"""Administrative / corrective sequence builder (REQ-092) — pure.

Builds a valid next eCTD sequence for an administrative regulatory activity
(withdraw a leaf, relocate/reorganize, admin change) WITHOUT forcing the full
ANDS scientific content — the content gate for an admin activity requires only
the cover letter (the portal-generated one satisfies it).
"""

from __future__ import annotations

from . import ectd

ADMIN_ACTIVITIES = {
    "withdrawal": "Voluntary withdrawal of the submission or a leaf",
    "administrative-change": "Administrative change (contact, name, RT/MF)",
    "reorganization": "Sequence reorganization (relocate leaves)",
}

# eCTD leaf operations an administrative sequence may use — adds 'withdraw' and
# 'relocate' to the standard new/replace/delete set.
ADMIN_VALID_OPS = ("new", "replace", "delete", "withdraw", "relocate")

COVER_LETTER_KEY = "cover-letter"


def _s(v) -> str:
    return str(v or "").strip()


def admin_content_gate(data: dict) -> dict:
    """An admin activity needs only the 1.0 cover letter (REQ-092).

    The portal-generated sponsor cover letter satisfies it unless the caller
    explicitly sets ``cover_letter_generated`` False and supplies none.
    """
    data = data or {}
    cover_generated = data.get("cover_letter_generated", True)
    present = {_s(d.get("key") or d.get("section"))
               for d in (data.get("present_documents") or [])
               if isinstance(d, dict)}
    if cover_generated or COVER_LETTER_KEY in present:
        return {"can_pass": True, "missing": []}
    return {"can_pass": False, "missing": [
        {"rule": "missing_cover_letter", "key": COVER_LETTER_KEY,
         "section": "1.0", "message": "An administrative sequence still requires "
                                      "the 1.0 cover letter"}]}


def build_admin_sequence(data: dict) -> dict:
    """Build an administrative/corrective next sequence. ``{valid, sequence|errors}``."""
    data = data or {}
    errors = []
    activity = _s(data.get("activity")).lower()
    dossier_id = _s(data.get("dossier_id"))
    sequence = _s(data.get("sequence"))
    if activity not in ADMIN_ACTIVITIES:
        errors.append({"rule": "admin_activity_invalid",
                       "message": "activity must be one of "
                                  + ", ".join(ADMIN_ACTIVITIES)})
    if not dossier_id:
        errors.append({"rule": "dossier_id_required",
                       "message": "dossier_id is required"})
    if not sequence:
        errors.append({"rule": "sequence_required",
                       "message": "a 4-digit sequence is required"})
    operations = []
    for op in (data.get("operations") or []):
        if not isinstance(op, dict):
            errors.append({"rule": "operation_invalid",
                           "message": "each operation must be an object"})
            continue
        kind = _s(op.get("op")).lower()
        leaf_id = _s(op.get("leaf_id"))
        if kind not in ADMIN_VALID_OPS:
            errors.append({"rule": "operation_unknown",
                           "message": f"operation '{kind}' is not one of "
                                      + ", ".join(ADMIN_VALID_OPS)})
            continue
        if kind != "new" and not leaf_id:
            errors.append({"rule": "operation_target_required",
                           "message": f"a '{kind}' operation must target a leaf"})
            continue
        entry = {"op": kind, "leaf_id": leaf_id}
        if kind == "relocate":
            entry["to_heading"] = _s(op.get("to_heading"))
        operations.append(entry)
    gate = admin_content_gate(data)
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": gate["can_pass"], "sequence": {
        "dossier_id": dossier_id, "sequence": sequence, "activity": activity,
        "activity_label": ADMIN_ACTIVITIES[activity], "operations": operations,
        "cover_letter_leaf": ectd.leaf_id_for("1.0"), "content_gate": gate,
        "scientific_content_required": False}}
