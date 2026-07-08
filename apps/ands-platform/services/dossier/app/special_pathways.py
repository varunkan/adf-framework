"""Per-dossier special-pathway advisories (swarm round-2 ENHANCEMENT).

Special submission pathways (Priority Review, NOC/c, pediatric, CTA, fixed-dose
combination, complex generic) were recognised in the journey catalog but never
surfaced on the DOSSIER itself. A dossier can now flag the pathways that apply,
and content_state emits an honest, cited advisory for each — the tool explains
and cites the pathway, it does NOT automate its mechanics (advisory_only).

Facts web-verified vs canada.ca (Jul 2026); mirrors journey.special_pathways
(each service owns its copy of the HC boundary). Pure, stdlib-only.
"""

from __future__ import annotations

# id -> (label, summary, citation)
_PATHWAYS: dict[str, tuple[str, str, str]] = {
    "priority_review": (
        "Priority Review",
        "An accepted Priority Review shortens the review target to 180 calendar "
        "days (vs. 300) for a serious/life-threatening/severely-debilitating "
        "condition with substantial evidence of clinical effectiveness; it needs "
        "a request Health Canada accepts before filing.",
        "HC Priority Review of Drug Submissions Policy & Guidance."),
    "noc_c": (
        "Notice of Compliance with conditions (NOC/c)",
        "Authorisation on PROMISING clinical evidence (a surrogate/clinical "
        "endpoint reasonably likely to predict benefit), conditional on the "
        "sponsor's undertaking to run CONFIRMATORY trials plus increased "
        "monitoring and labelling/advertising restrictions.",
        "HC Guidance Document: Notice of Compliance with Conditions (NOC/c)."),
    "pediatric": (
        "Pediatric submission / data",
        "A pediatric indication or pediatric data carries specific data "
        "expectations and may qualify for a data-protection extension.",
        "HC data protection (Food and Drug Regulations C.08.004.1) + pediatric "
        "guidance."),
    "cta": (
        "Clinical Trial Application (CTA)",
        "A PRE-market authorisation to run a trial — a different track from a "
        "market (NDS/ANDS) submission, filed under Part C, Division 5.",
        "Food and Drug Regulations, Part C, Division 5 (CTA)."),
    "fixed_dose_combination": (
        "Fixed-dose combination (FDC)",
        "Two or more medicinal ingredients in one dosage form must justify the "
        "combination (each component's contribution, dosing) and, for a generic "
        "FDC, comparative evidence appropriate to the combination.",
        "HC guidance on fixed-dose combination drug products."),
    "complex_generic": (
        "Complex generic",
        "A generic of a complex product (long-acting injectable, inhaled, "
        "topical, drug-device) often needs product-specific comparative evidence "
        "beyond a simple PK study.",
        "HC product-specific comparative bioavailability guidance."),
}

VALID_PATHWAYS = tuple(_PATHWAYS)


def advisory(pathway_id: str) -> dict | None:
    """The honest advisory record for a special pathway id, or None if unknown."""
    rec = _PATHWAYS.get(str(pathway_id or "").strip().lower())
    if not rec:
        return None
    label, summary, citation = rec
    return {"id": str(pathway_id).strip().lower(), "label": label,
            "summary": summary, "citation": citation, "advisory_only": True}


def advisories(pathway_ids) -> list[dict]:
    """Advisory records for a dossier's flagged special pathways (unknown ids
    dropped, order preserved, deduped)."""
    out, seen = [], set()
    for pid in (pathway_ids or []):
        a = advisory(pid)
        if a and a["id"] not in seen:
            seen.add(a["id"])
            out.append(a)
    return out
