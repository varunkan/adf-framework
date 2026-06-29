"""Bilingual Product Monograph domain (REQ-098) — pure, deterministic.

Health Canada requires a prescription ANDS to carry **paired EN + FR** Product
Monographs as first-class leaves under Module-1 heading 1.3.1. This module groups
the language pair and validates completeness/sync: a missing FR (or EN) is a
**blocking** defect; an EN newer than its FR pair is a non-blocking **warning**
(Plain-Language-Labelling sync). The application layer stores the leaves.
"""

from __future__ import annotations

from . import ectd

LANG_EN = "en"
LANG_FR = "fr"
LANGS = (LANG_EN, LANG_FR)

STATUS_COMPLETE = "complete"
STATUS_BLOCKED = "blocked"


def normalize_pm_leaf(data: dict) -> dict:
    """Validate + clean a PM leaf submission. ``{"valid","leaf"|"errors"}``."""
    data = data or {}
    errors = []
    lang = str(data.get("lang") or "").strip().lower()
    dossier_id = str(data.get("dossier_id") or "").strip()
    if lang not in LANGS:
        errors.append({"rule": "pm_lang_invalid",
                       "message": "lang must be 'en' or 'fr'"})
    if not dossier_id:
        errors.append({"rule": "pm_dossier_required",
                       "message": "dossier_id is required"})
    if not str(data.get("title") or "").strip():
        errors.append({"rule": "pm_title_required",
                       "message": "title is required"})
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "leaf": {
        "dossier_id": dossier_id, "lang": lang,
        "leaf_id": str(data.get("leaf_id")
                       or ectd.leaf_id_for(ectd.PM_HEADING)),
        "title": str(data.get("title")).strip(),
        "version": int(data.get("version") or 1),
        "heading": ectd.PM_HEADING}}


def pm_language_pair(leaves: list) -> dict:
    """Group PM leaves into ``{"en": leaf|None, "fr": leaf|None}`` (latest wins)."""
    pair: dict = {LANG_EN: None, LANG_FR: None}
    for leaf in leaves or []:
        lang = str(leaf.get("lang") or "").strip().lower()
        if lang in pair:
            cur = pair[lang]
            if cur is None or int(leaf.get("version") or 1) >= int(
                    cur.get("version") or 1):
                pair[lang] = leaf
    return pair


def validate_bilingual_monograph(leaves: list) -> dict:
    """Both languages present and in sync? (REQ-098)

    Returns ``{"status", "findings", "pair"}`` where status is ``blocked`` if
    either language leaf is absent (a transmission blocker), else ``complete``.
    An EN version greater than the FR version adds a non-blocking warning.
    """
    pair = pm_language_pair(leaves)
    findings = []
    if pair[LANG_EN] is None:
        findings.append({"rule": "pm_en_missing", "severity": "blocking",
                         "message": "English Product Monograph leaf is missing "
                                    "under heading 1.3.1"})
    if pair[LANG_FR] is None:
        findings.append({"rule": "pm_fr_missing", "severity": "blocking",
                         "message": "French Product Monograph leaf is missing "
                                    "under heading 1.3.1"})
    if pair[LANG_EN] and pair[LANG_FR]:
        if int(pair[LANG_EN].get("version") or 1) > int(
                pair[LANG_FR].get("version") or 1):
            findings.append({
                "rule": "pm_fr_out_of_sync", "severity": "warning",
                "message": "The English Product Monograph is newer than the "
                           "French — update the FR for Plain Language "
                           "Labelling timing."})
    blocked = any(f["severity"] == "blocking" for f in findings)
    return {"status": STATUS_BLOCKED if blocked else STATUS_COMPLETE,
            "blocking": blocked, "findings": findings, "pair": pair}
