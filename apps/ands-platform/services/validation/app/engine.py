"""Validation engine — run / inline-gutter / one-click-fix (ported, pure).

The SAME engine drives the terminal gate (:func:`run_validation`) and the
assembly-time inline gutter (:func:`inline_findings`) — REQ-104's "validate
continuously during assembly". Findings carry severity, colour and, where
remediable, a ``fix_id`` for one-click remediation.
"""

from __future__ import annotations

from . import rules
from .rules import (ACTIVE_RULESET_VERSION, CATEGORIES, SEVERITY_COLOUR,
                    SEVERITY_ERROR, SEVERITY_WARNING)


def run_validation(ctx: dict, version: str = ACTIVE_RULESET_VERSION,
                   profile: str = rules.PROFILE_ECTD) -> dict:
    """Run the versioned ruleset under a profile; split into errors/warnings;
    blocking iff any Error. Warnings never block (HC's two-tier model)."""
    rs = rules.get_ruleset(version, profile)
    findings = []
    for rule in rs["rules"]:
        for partial in (rule["check"](ctx) or []):
            findings.append({
                "rule_id": rule["rule_id"], "category": rule["category"],
                "severity": rule["severity"],
                "ruleset_version": rule["ruleset_version"],
                "description": rule["description"],
                "colour": SEVERITY_COLOUR.get(rule["severity"], "#444"),
                **partial})
    errors = [f for f in findings if f["severity"] == SEVERITY_ERROR]
    warnings = [f for f in findings if f["severity"] == SEVERITY_WARNING]
    by_category = {c: [] for c in CATEGORIES}
    for f in findings:
        by_category.setdefault(f["category"], []).append(f)
    return {
        "ruleset_version": rs["version"], "profile": rs["profile"],
        "ruleset_effective": rs["effective"],
        "findings": findings, "errors": errors, "warnings": warnings,
        "error_count": len(errors), "warning_count": len(warnings),
        "blocking": bool(errors), "by_category": by_category}


def inline_findings(ctx: dict, version: str = ACTIVE_RULESET_VERSION,
                    profile: str = rules.PROFILE_ECTD) -> dict:
    """REQ-104: defects keyed to file/node for the inline authoring gutter."""
    result = run_validation(ctx, version, profile)
    gutter: dict = {}
    for f in result["findings"]:
        gutter.setdefault(f["file"] or f["node"], []).append({
            "rule_id": f["rule_id"], "node": f["node"],
            "severity": f["severity"], "colour": f["colour"],
            "message": f["message"], "remediable": f.get("remediable", False),
            "fix_id": f.get("fix_id", "")})
    return {"ruleset_version": result["ruleset_version"],
            "blocking": result["blocking"], "gutter": gutter,
            "error_count": result["error_count"],
            "warning_count": result["warning_count"]}


def run_batch(contexts: list, version: str = ACTIVE_RULESET_VERSION,
              profile: str = rules.PROFILE_ECTD) -> dict:
    """REQ-116: validate many transactions and aggregate the outcome."""
    items, total_e, total_w, blocking = [], 0, 0, 0
    for ctx in (contexts or []):
        r = run_validation(ctx or {}, version, profile)
        items.append({"dossier_id": (ctx or {}).get("dossier_id", ""),
                      "sequence": (ctx or {}).get("sequence", "0000"),
                      "blocking": r["blocking"], "error_count": r["error_count"],
                      "warning_count": r["warning_count"]})
        total_e += r["error_count"]
        total_w += r["warning_count"]
        blocking += 1 if r["blocking"] else 0
    return {"profile": profile, "ruleset_version": version, "items": items,
            "count": len(items), "total_errors": total_e,
            "total_warnings": total_w, "blocking_count": blocking,
            "all_clear": blocking == 0}


def apply_fix(ctx: dict, fix_id: str, file: str) -> dict:
    """REQ-104: apply a one-click fix; returns an updated copy of ``ctx``.

    Non-destructive — only the targeted file's defect is cleared. Raises
    ``ValueError`` for an unknown fix.
    """
    fix_id = rules._norm(fix_id)
    file = rules._norm(file)
    if fix_id not in rules.REMEDIATIONS:
        raise ValueError(f"unknown fix '{fix_id}'")
    new_ctx = dict(ctx)
    new_files = []
    for f in rules._files(ctx):
        f = dict(f)
        if rules._norm(f.get("path")) == file:
            if fix_id == "grant-read":
                f["readable"] = True
            elif fix_id == "decrypt-pdf":
                f["encrypted"] = False
        new_files.append(f)
    new_ctx["files"] = new_files
    return new_ctx
