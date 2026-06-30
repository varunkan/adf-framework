"""Annotated PM cross-reference assistant (REQ-101) — pure.

Builds/annotates cross-references from the Product Monograph to Module 2 sections
and the Module 1.4.2 Bioequivalence Summary, and resolves them against the
targets actually present in the dossier — flagging dangling (invalid target) and
missing (valid target absent from the dossier) refs before validation.
"""

from __future__ import annotations

# Valid cross-reference targets: Module 2 summaries + the Module 1.4.2 BE Summary
# (which the flat eCTD content model does not otherwise define).
VALID_XREF_TARGETS = {
    "1.4.2": "Bioequivalence Summary (Module 1.4.2)",
    "2.3": "Quality Overall Summary (QOS-CE)",
    "2.4": "Nonclinical Overview",
    "2.5": "Clinical Overview",
    "2.6": "Nonclinical Written & Tabulated Summaries",
    "2.7": "Clinical Summary",
    "2.7.1": "Summary of Biopharmaceutic Studies",
}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def valid_targets() -> dict:
    return dict(VALID_XREF_TARGETS)


def build_pm_xrefs(pm_doc: dict) -> list:
    """Flatten a PM document into ref records ``{source, target}``.

    Accepts ``{"sections": [{"code", "refs": [target, ...]}]}`` and/or a
    top-level ``{"refs": [target | {"target", "source"}]}``.
    """
    pm_doc = pm_doc or {}
    out = []
    for section in (pm_doc.get("sections") or []):
        if not isinstance(section, dict):
            continue
        src = _s(section.get("code") or section.get("heading"))
        for ref in (section.get("refs") or []):
            out.append({"source": src, "target": _s(
                ref.get("target") if isinstance(ref, dict) else ref)})
    for ref in (pm_doc.get("refs") or []):
        if isinstance(ref, dict):
            out.append({"source": _s(ref.get("source")),
                        "target": _s(ref.get("target"))})
        else:
            out.append({"source": "", "target": _s(ref)})
    return out


def resolve_pm_xrefs(refs: list, present_targets=None) -> dict:
    """Resolve cross-references. ``present_targets`` (optional) is the set of
    targets actually present in the dossier; when given, a valid-but-absent
    target is flagged ``missing``. Returns ``{resolved, findings, all_resolved}``.
    """
    present = ({_s(t) for t in present_targets}
               if present_targets is not None else None)
    resolved, findings = [], []
    for ref in (refs or []):
        target = _s(ref.get("target"))
        source = _s(ref.get("source"))
        if target not in VALID_XREF_TARGETS:
            findings.append({
                "rule": "xref_target_invalid", "severity": "blocking",
                "source": source, "target": target,
                "message": f"cross-reference target '{target}' is not a valid "
                           "Module 2 / 1.4.2 section"})
        elif present is not None and target not in present:
            findings.append({
                "rule": "xref_target_missing", "severity": "blocking",
                "source": source, "target": target,
                "message": f"cross-reference to '{target}' "
                           f"({VALID_XREF_TARGETS[target]}) but that section is "
                           "not present in the dossier"})
        else:
            resolved.append({"source": source, "target": target,
                             "label": VALID_XREF_TARGETS[target]})
    return {"resolved": resolved, "findings": findings,
            "all_resolved": not findings}
