"""Submission content-plan domain (REQ-103) — pure, deterministic.

A content plan instantiates an HA-compliant template (ANDS / SNDS / SANDS) into
an ordered list of checklist items, each mapped to an eCTD Module-1/CTD section
and (where one exists) its prescribed leaf. Items carry an assignee, a due date
and a status; ``plan_progress`` rolls them up for the readiness dashboard. The
application layer persists; this module decides the template and the maths.
"""

from __future__ import annotations

from datetime import date

from . import ectd

# -- submission types --------------------------------------------------------
SUBMISSION_TYPES = ("ANDS", "SNDS", "SANDS")

# -- item status -------------------------------------------------------------
ITEM_PENDING = "pending"
ITEM_IN_PROGRESS = "in_progress"
ITEM_COMPLETE = "complete"
ITEM_STATUSES = (ITEM_PENDING, ITEM_IN_PROGRESS, ITEM_COMPLETE)


def _i(key: str, title: str, section: str, *, required: bool = True) -> dict:
    """A template item; resolves its eCTD leaf from the placement table."""
    return {"key": key, "title": title, "section": section,
            "leaf_id": ectd.leaf_id_for(section), "required": required}


# Ordered, HA-compliant templates. ANDS is the full generic dossier; SANDS
# applies ANDS rules to the changed modules; SNDS is a supplement subset.
_TEMPLATES = {
    "ANDS": [
        _i("cover-letter", "Cover letter", "1.0"),
        _i("application-form", "Application / Submission Form", "1.2.1"),
        _i("product-monograph", "Product Monograph (EN + FR)", "1.3.1"),
        _i("qos-ce", "Quality Overall Summary (QOS-CE)", "2.3"),
        _i("cmc-body", "Module 3 Quality (CMC) body", "3.2"),
        _i("be-study-report", "Comparative bioequivalence study report",
           "5.3.1.2"),
    ],
    "SANDS": [
        _i("cover-letter", "Cover letter", "1.0"),
        _i("application-form", "Application / Submission Form", "1.2.1"),
        _i("product-monograph", "Product Monograph (EN + FR)", "1.3.1"),
        _i("qos-ce", "Quality Overall Summary (QOS-CE)", "2.3", required=False),
        _i("change-summary", "Summary of the post-NOC change", "1.2"),
    ],
    "SNDS": [
        _i("cover-letter", "Cover letter", "1.0"),
        _i("application-form", "Application / Submission Form", "1.2.1"),
        _i("change-summary", "Summary of the supplemental change", "1.2"),
        _i("product-monograph", "Updated Product Monograph (EN + FR)", "1.3.1",
           required=False),
    ],
}

# The BE electronic copy in Module 1.6 is required only on the CS-BE path (ANDS).
_CS_BE_ITEM = _i("cs-be-copy", "CS-BE electronic copy", "1.6")


def is_valid_submission_type(value: str) -> bool:
    return str(value or "").strip().upper() in SUBMISSION_TYPES


def build_plan_items(submission_type: str, *, cs_be_only: bool = False) -> list:
    """The ordered template items for a submission type (REQ-103).

    Each item is seeded ``pending`` with no assignee/due date. Raises
    ``ValueError`` on an unknown type.
    """
    code = str(submission_type or "").strip().upper()
    if code not in _TEMPLATES:
        raise ValueError(f"unknown submission type {submission_type!r}")
    items = [dict(i) for i in _TEMPLATES[code]]
    if code == "ANDS" and cs_be_only:
        items.insert(3, dict(_CS_BE_ITEM))  # after the PM
    for item in items:
        item.update(status=ITEM_PENDING, assignee=None, due_date=None)
    return items


def validate_item_status(status: str) -> bool:
    return str(status or "").strip() in ITEM_STATUSES


def validate_due_date(due_date: str) -> bool:
    due_date = str(due_date or "").strip()
    if not due_date:
        return True
    try:
        date.fromisoformat(due_date)
        return True
    except ValueError:
        return False


def plan_progress(items: list) -> dict:
    """Roll plan items up to {done,total,pct,by_module} for the dashboard.

    Only ``required`` items count toward completion; optional items are tracked
    but never block the percentage.
    """
    required = [i for i in items if i.get("required", True)]
    total = len(required)
    done = sum(1 for i in required if i.get("status") == ITEM_COMPLETE)
    pct = round(100 * done / total) if total else 100
    by_module: dict[str, dict] = {}
    for i in items:
        module = str(i.get("section") or "").split(".")[0] or "?"
        bucket = by_module.setdefault(module, {"total": 0, "done": 0})
        bucket["total"] += 1
        if i.get("status") == ITEM_COMPLETE:
            bucket["done"] += 1
    return {"done": done, "total": total, "pct": pct,
            "complete": done == total, "by_module": by_module}
