"""Dossier-ID guidance — branches, 8-week MAX lead time, format check (pure).

Ported from the monolith ``rep.py``. A Dossier ID is the permanent file number
for one product (one lowercase letter + 6/7 digits, e.g. ``e123456``); it is
requested at most 8 weeks before the first filing (a MAXIMUM, warn-only — never a
hard gate) and reused forever. ``assess`` combines the branch, the format check
and the lead-time warning into the guidance the dossier step renders.
"""

from __future__ import annotations

import re
from datetime import datetime

DOSSIER_ID_MAX_LEAD_WEEKS = 8
DOSSIER_ID_MAX_LEAD_DAYS = DOSSIER_ID_MAX_LEAD_WEEKS * 7   # 56
DSTS_IA_LOOKUP_CONTACT = "client.information@hc-sc.gc.ca"

_REQUEST_FIELDS = ["company_id", "company_name", "product_name",
                   "activity_type", "intended_first_filing_date"]

# Product-type / activity branches for a Dossier ID request — HC prefix, accepted
# digit lengths, and the HC request form.
DOSSIER_REQUEST_BRANCHES = {
    "pharmaceutical": {
        "label": "Pharmaceutical / biologic (eCTD)", "prefix": "e",
        "digits": (6, 7),
        "form": "Dossier ID request form for pharmaceutical/biologic dossiers",
        "fields": list(_REQUEST_FIELDS)},
    "pharmaceutical-clinical-trial": {
        "label": "Pharmaceutical clinical trial (CTA)", "prefix": "e",
        "digits": (6, 7),
        "form": "Dossier ID request form for pharmaceutical/biologic dossiers",
        "fields": list(_REQUEST_FIELDS)},
    "biologic-clinical-trial": {
        "label": "Biologic clinical trial (CTA)", "prefix": "e", "digits": (6, 7),
        "form": "Dossier ID request form for pharmaceutical/biologic dossiers",
        "fields": list(_REQUEST_FIELDS)},
    "veterinary": {
        "label": "Veterinary drug", "prefix": "e", "digits": (6, 7),
        "form": "Dossier ID request form for veterinary drugs",
        "fields": list(_REQUEST_FIELDS)},
    "biocide": {
        "label": "Biocide", "prefix": "e", "digits": (6, 7),
        "form": "Dossier ID request form for biocides",
        "fields": list(_REQUEST_FIELDS)},
    "medical-device": {
        "label": "Medical device", "prefix": "m", "digits": (6, 7),
        "form": "Dossier ID request form for medical devices",
        "fields": list(_REQUEST_FIELDS)},
    "master-file-ectd": {
        "label": "Master File (eCTD)", "prefix": "e", "digits": (6,),
        "form": "Master File Dossier ID request form (eCTD)",
        "fields": list(_REQUEST_FIELDS)},
    "master-file-non-ectd": {
        "label": "Master File (non-eCTD)", "prefix": "f", "digits": (7,),
        "form": "Master File Dossier ID request form (non-eCTD)",
        "fields": list(_REQUEST_FIELDS)},
}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _parse_iso_date(value):
    text = _s(value)
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def is_valid_dossier_id(value: str, prefix: str = "e") -> bool:
    """One lowercase ``prefix`` letter followed by 6 or 7 digits (e.g. e123456)."""
    return bool(re.fullmatch(rf"{re.escape(prefix)}\d{{6,7}}", _s(value)))


def dossier_id_conforms(value, branch_key: str) -> bool:
    """Prefix + per-branch digit-count check (Master File e+6 vs f+7, etc.)."""
    branch = DOSSIER_REQUEST_BRANCHES.get(_s(branch_key)) or \
        DOSSIER_REQUEST_BRANCHES["pharmaceutical"]
    value = _s(value)
    if not is_valid_dossier_id(value, branch["prefix"]):
        return False
    return (len(value) - 1) in set(branch["digits"])


def list_branches() -> list:
    return [{"key": k, **{kk: vv for kk, vv in v.items() if kk != "fields"}}
            for k, v in DOSSIER_REQUEST_BRANCHES.items()]


def assess_lead_time(request_date, first_filing_date) -> dict:
    """HC's 8-week lead time is a MAXIMUM, not a minimum gate — warn ONLY when the
    request is placed MORE than 8 weeks ahead. Never gates."""
    req = _parse_iso_date(request_date)
    filing = _parse_iso_date(first_filing_date)
    basis = (f"HC {DOSSIER_ID_MAX_LEAD_WEEKS}-week MAXIMUM lead time "
             "(warn-only; never gates)")
    if req is None or filing is None:
        return {"assessable": False, "days_ahead": None, "weeks_ahead": None,
                "too_early": False, "warning": None,
                "max_lead_weeks": DOSSIER_ID_MAX_LEAD_WEEKS, "basis": basis}
    days_ahead = (filing - req).days
    weeks_ahead = round(days_ahead / 7, 1)
    too_early = days_ahead > DOSSIER_ID_MAX_LEAD_DAYS
    warning = None
    if too_early:
        warning = (f"Dossier ID requested {weeks_ahead} weeks before the intended "
                   f"first-filing date; HC asks that it be requested no more than "
                   f"{DOSSIER_ID_MAX_LEAD_WEEKS} weeks in advance (a MAXIMUM, not a "
                   "minimum lead time).")
    return {"assessable": True, "days_ahead": days_ahead, "weeks_ahead": weeks_ahead,
            "too_early": too_early, "warning": warning,
            "max_lead_weeks": DOSSIER_ID_MAX_LEAD_WEEKS, "basis": basis}


def assess(data: dict) -> dict:
    """Combined Dossier-ID guidance: branch resolution, format check (if an ID is
    supplied) and the warn-only lead-time assessment."""
    data = data or {}
    branch_key = _s(data.get("branch")) or "pharmaceutical"
    branch = DOSSIER_REQUEST_BRANCHES.get(branch_key)
    out: dict = {"branch": branch_key, "valid_branch": branch is not None}
    if branch is None:
        out["error"] = (f"'{branch_key}' is not a known request branch "
                        f"({', '.join(DOSSIER_REQUEST_BRANCHES)})")
        return out
    out["branch_info"] = {kk: vv for kk, vv in branch.items() if kk != "fields"}
    out["fields"] = list(branch["fields"])

    dossier_id = _s(data.get("dossier_id"))
    if dossier_id:
        conforms = dossier_id_conforms(dossier_id, branch_key)
        out["dossier_id"] = dossier_id
        out["format_ok"] = conforms
        if not conforms:
            digits = " or ".join(str(d) for d in branch["digits"])
            out["format_error"] = (
                f"'{dossier_id}' is not a valid {branch['label']} Dossier ID — "
                f"expected the prefix '{branch['prefix']}' followed by {digits} "
                "digits.")
    out["lead_time"] = assess_lead_time(
        data.get("request_date"), data.get("first_filing_date"))
    return out
