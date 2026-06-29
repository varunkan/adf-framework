"""eCTD Module-1 placement substrate (ported from the monolith ``ectd``).

The CA Module-1 placement table as data: each heading → its prescribed leaf.
The content-plan and monograph domains map their items/leaves through here, so an
updated HC table stays a data change. Pure, stdlib-only.
"""

from __future__ import annotations

PLACEMENT_TABLE_VERSION = "2024-04-02"   # HC 'Organization & document placement'
CA_M1_SCHEMA_VERSION = "2.2"

# Heading of the Product Monograph leaf (REQ-098 anchors EN/FR pairing here).
PM_HEADING = "1.3.1"

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
     "leaf_id": "m1-2-1-application-form",
     "folder": "m1/ca/12-admin-info/121-form",
     "docx_required": False, "sponsor_authored": False},
    {"heading": "1.3.1", "title": "Product Monograph",
     "leaf_id": "m1-3-1-product-monograph",
     "folder": "m1/ca/13-product-info/131-pm",
     "docx_required": True, "sponsor_authored": False},
    {"heading": "1.6", "title": "Comparative Studies — Bioequivalence (CS-BE)",
     "leaf_id": "m1-6-cs-be", "folder": "m1/ca/16-cs-be",
     "docx_required": False, "sponsor_authored": False},
]


def placement_for_heading(heading: str) -> dict | None:
    """The placement entry for a CA Module-1 heading, or ``None``."""
    heading = str(heading or "").strip()
    for e in CA_MODULE1_PLACEMENT:
        if e["heading"] == heading:
            return dict(e)
    return None


def module1_placement_table() -> dict:
    return {"version": PLACEMENT_TABLE_VERSION,
            "entries": [dict(e) for e in CA_MODULE1_PLACEMENT]}


def leaf_id_for(heading: str) -> str | None:
    entry = placement_for_heading(heading)
    return entry["leaf_id"] if entry else None
