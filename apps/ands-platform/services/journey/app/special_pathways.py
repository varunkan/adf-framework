"""Special submission pathways & attributes — honest, cited, ADVISORY-ONLY (Tier C).

Real Health Canada pathways/attributes a filer weighs when PLANNING a submission.
ANDS Studio recognises and explains each with an authoritative citation, but does
NOT automate its mechanics (it does not run the Priority Review clock, track NOC/c
conditions, manage OCS licences, etc.) — every entry is marked ``advisory_only``.
This is the honest 'here is what applies and where to look', not a claim of
automated support. Pure, stdlib-only, versioned.

Every fact is web-verified against canada.ca (July 2026):
  * Priority Review: a 180-CALENDAR-day review target (vs. 300 for a standard
    submission) for an NDS/SNDS for a serious, life-threatening or severely
    debilitating condition with substantial evidence of clinical effectiveness.
    "Priority Review of Drug Submissions Policy / Guidance."
  * Notice of Compliance with conditions (NOC/c): market authorisation on
    PROMISING clinical evidence (a surrogate or clinical endpoint reasonably
    likely to predict benefit), conditional on the sponsor's undertaking to run
    CONFIRMATORY trials plus increased monitoring/labelling. "Guidance Document:
    Notice of Compliance with Conditions (NOC/c)."
  * Controlled substances: additional Office of Controlled Substances (OCS)
    obligations under the CDSA (dealer's licence, security, reporting) BEYOND the
    drug submission.
  * Clinical Trial Application (CTA): a PRE-market authorisation (Food and Drug
    Regulations, Part C, Division 5) to conduct a trial — a different track from
    a market submission.
"""

from __future__ import annotations

# ordered for the UI. Each: id, label, kind, summary, eligibility, citation.
_PATHWAYS: tuple[dict, ...] = (
    {
        "id": "priority_review",
        "label": "Priority Review",
        "kind": "expedited",
        "summary": "An accepted Priority Review shortens the review target to "
                   "180 calendar days (vs. 300 for a standard submission).",
        "eligibility": "An NDS/SNDS for a serious, life-threatening or severely "
                       "debilitating disease with substantial evidence of "
                       "clinical effectiveness (unmet need or a significant "
                       "improvement in benefit/risk). Requires a Priority Review "
                       "request that Health Canada accepts before filing.",
        "citation": "HC Priority Review of Drug Submissions Policy & Guidance.",
    },
    {
        "id": "noc_c",
        "label": "Notice of Compliance with conditions (NOC/c)",
        "kind": "conditional_authorization",
        "summary": "Market authorisation granted on PROMISING clinical evidence "
                   "(a surrogate or clinical endpoint reasonably likely to "
                   "predict clinical benefit), with conditions.",
        "eligibility": "A serious/life-threatening condition where the sponsor "
                       "undertakes to complete CONFIRMATORY trials to verify "
                       "benefit, plus increased monitoring, defined labelling and "
                       "advertising restrictions until the conditions are met.",
        "citation": "HC Guidance Document: Notice of Compliance with Conditions "
                    "(NOC/c).",
    },
    {
        "id": "pediatric",
        "label": "Pediatric submission / data",
        "kind": "attribute",
        "summary": "A submission with a pediatric indication or pediatric data "
                   "carries specific data expectations and may qualify for a "
                   "data-protection extension.",
        "eligibility": "Any submission proposing pediatric use or containing the "
                       "results of pediatric studies designed to support a "
                       "pediatric indication.",
        "citation": "HC data-protection provisions (Food and Drug Regulations "
                    "C.08.004.1) and pediatric submission guidance.",
    },
    {
        "id": "controlled_substance",
        "label": "Controlled substance",
        "kind": "attribute",
        "summary": "A scheduled drug triggers additional Office of Controlled "
                   "Substances (OCS) obligations UNDER THE CDSA, on top of the "
                   "drug submission.",
        "eligibility": "A product whose medicinal ingredient is scheduled under "
                       "the Controlled Drugs and Substances Act — requires the "
                       "applicable dealer's licence, security and reporting "
                       "controls administered by the OCS.",
        "citation": "Controlled Drugs and Substances Act; HC Office of Controlled "
                    "Substances requirements.",
    },
    {
        "id": "cta",
        "label": "Clinical Trial Application (CTA)",
        "kind": "pre_market",
        "summary": "A PRE-market authorisation to conduct a clinical trial in "
                   "Canada — a different track from a market (NDS/ANDS) "
                   "submission.",
        "eligibility": "Sponsors conducting a phase I-III trial of a drug not yet "
                       "authorised for the studied use. Filed and reviewed under "
                       "Part C, Division 5 of the Food and Drug Regulations.",
        "citation": "Food and Drug Regulations, Part C, Division 5 (CTA).",
    },
    {
        "id": "fixed_dose_combination",
        "label": "Fixed-dose combination (FDC)",
        "kind": "attribute",
        "summary": "A product combining two or more medicinal ingredients in one "
                   "dosage form must justify the combination.",
        "eligibility": "Requires a combination rationale (contribution of each "
                       "component, dosing justification) and, for a generic FDC, "
                       "comparative evidence appropriate to the combination.",
        "citation": "HC guidance on fixed-dose combination drug products.",
    },
    {
        "id": "complex_generic",
        "label": "Complex generic",
        "kind": "attribute",
        "summary": "A generic of a complex product (e.g. long-acting injectable, "
                   "orally-inhaled, topical, drug-device) often needs product-"
                   "specific comparative evidence beyond a simple PK study.",
        "eligibility": "A generic whose dosage form / route makes standard "
                       "bioequivalence insufficient — follow the product-specific "
                       "HC comparative-evidence guidance (see the dossier's "
                       "dosage-form comparative-evidence route).",
        "citation": "HC product-specific comparative bioavailability guidance.",
    },
)

# every entry is advisory-only: recognised + cited, not automated by ANDS Studio.
_BY_ID = {p["id"]: {**p, "advisory_only": True} for p in _PATHWAYS}


def pathway(pathway_id) -> dict | None:
    """The honest advisory record for a special pathway, or None if unknown."""
    return _BY_ID.get(str(pathway_id or "").strip().lower())


def list_pathways() -> list:
    """Every special pathway/attribute, in UI order — advisory-only + cited."""
    return [dict(_BY_ID[p["id"]]) for p in _PATHWAYS]
