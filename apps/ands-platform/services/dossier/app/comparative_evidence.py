"""Dosage-form-aware comparative-evidence routing for a generic (Tier A).

Health Canada does NOT require a comparative bioequivalence (PK) study for every
generic dosage form. This module maps a dosage form to the comparative-evidence
ROUTE Health Canada expects, and to whether the in-vivo BE study (eCTD 5.3.1) /
CS-BE summary (1.6) is required, conditional (a biowaiver may apply — the filer
confirms), or not the applicable evidence type. Pure, stdlib-only, versioned.

Sources (canada.ca):
  * "Submissions for Generic Parenteral Drugs" — in-vivo BE waiver for
    qualitatively/quantitatively equivalent parenteral aqueous solutions.
  * "Comparative Bioavailability Standards: Formulations Used for Systemic
    Effects" — aqueous-solution biowaivers (oral, ophthalmic, otic, dermal)
    when non-medicinal ingredients are qualitatively identical.
  * "Comparative Pharmacokinetic Studies for Orally Inhaled Products" (2020).
  * ICH M9 — BCS-based biowaivers (in-vitro dissolution replaces the study).
"""

from __future__ import annotations

IR_SOLID_ORAL = "ir_solid_oral"
MR_SOLID_ORAL = "mr_solid_oral"
ORAL_SOLUTION = "oral_solution"
PARENTERAL_SOLUTION = "parenteral_solution"
OPHTHALMIC_OTIC_SOLUTION = "ophthalmic_otic_solution"
ORALLY_INHALED = "orally_inhaled"
TOPICAL_LOCAL = "topical_local"
COMPLEX_PARENTERAL = "complex_parenteral"
OTHER = "other"

# Ordered for UI selects: (value, label)
DOSAGE_FORMS = (
    (IR_SOLID_ORAL, "Immediate-release solid oral (tablet/capsule)"),
    (MR_SOLID_ORAL, "Modified-release solid oral"),
    (ORAL_SOLUTION, "Oral solution / aqueous liquid"),
    (PARENTERAL_SOLUTION, "Parenteral (injectable) aqueous solution"),
    (COMPLEX_PARENTERAL,
     "Complex parenteral (long-acting injectable / microsphere / liposome / suspension)"),
    (OPHTHALMIC_OTIC_SOLUTION, "Ophthalmic / otic solution"),
    (ORALLY_INHALED, "Orally inhaled product"),
    (TOPICAL_LOCAL, "Topical / locally-acting (dermal)"),
    (OTHER, "Other / not sure"),
)
_VALID = {v for v, _ in DOSAGE_FORMS}

_APPS = ("https://www.canada.ca/en/health-canada/services/drugs-health-products"
         "/drug-products/applications-submissions")

# route -> (requires_be_study, label, evidence, citation)
_ROUTES = {
    "pk_be_study": (
        True, "Comparative bioequivalence (PK) study",
        "A pivotal comparative PK study vs. the Canadian Reference Product "
        "(AUC/Cmax 90% CI within 80.00–125.00%) is required.",
        "HC Comparative Bioavailability Standards; ICH M13A (IR solid oral)."),
    "mr_pk_be_study": (
        True, "Comparative bioequivalence (PK) study — fed & fasting",
        "A modified-release generic requires comparative PK studies under BOTH "
        "fed and fasting conditions, with a dose-dumping assessment.",
        "HC Conduct and Analysis of Comparative Bioavailability Studies (MR)."),
    "oip_studies": (
        True, "Orally-inhaled comparative studies",
        "An orally-inhaled generic follows the dedicated OIP guidance: "
        "comparative PK (Cmax/AUC) plus in-vitro characterisation and, "
        "typically, comparative clinical/pharmacodynamic evidence.",
        "HC Comparative Pharmacokinetic Studies for Orally Inhaled Products (2020)."),
    "parenteral_biowaiver": (
        False, "Parenteral biowaiver (confirm)",
        "For a parenteral aqueous solution that is qualitatively and "
        "quantitatively the same as the reference, the in-vivo BE study may be "
        "WAIVED — provide the biowaiver justification instead of a PK study.",
        "HC Submissions for Generic Parenteral Drugs."),
    "aqueous_solution_biowaiver": (
        False, "Aqueous-solution biowaiver (confirm)",
        "For an aqueous solution (oral, ophthalmic, otic) whose non-medicinal "
        "ingredients are qualitatively identical to the reference, the in-vivo "
        "BE study may be WAIVED — provide the biowaiver justification.",
        "HC Comparative Bioavailability Standards (aqueous solutions)."),
    "topical_clinical_invitro": (
        False, "Topical comparative evidence (not PK BE)",
        "A locally-acting topical generic demonstrates equivalence by "
        "comparative CLINICAL endpoint or in-vitro release/permeation — not a "
        "systemic PK bioequivalence study.",
        "HC guidance for topical / locally-acting products."),
    "complex_generic_pk": (
        True, "Complex-generic comparative evidence (NOT a biowaiver)",
        "A complex parenteral (long-acting injectable / microsphere / liposome / "
        "suspension / depot) is NOT a simple aqueous-solution biowaiver: it "
        "requires product-specific comparative evidence — comparative PK PLUS "
        "physicochemical / in-vitro characterisation, and often comparative "
        "clinical data — per the product-specific guidance.",
        "HC product-specific comparative bioavailability guidance (complex generics)."),
}

_FORM_TO_ROUTE = {
    IR_SOLID_ORAL: "pk_be_study",
    MR_SOLID_ORAL: "mr_pk_be_study",
    ORALLY_INHALED: "oip_studies",
    PARENTERAL_SOLUTION: "parenteral_biowaiver",
    COMPLEX_PARENTERAL: "complex_generic_pk",
    ORAL_SOLUTION: "aqueous_solution_biowaiver",
    OPHTHALMIC_OTIC_SOLUTION: "aqueous_solution_biowaiver",
    TOPICAL_LOCAL: "topical_clinical_invitro",
    OTHER: "pk_be_study",           # conservative default
}


def _norm(dosage_form_class: str) -> str:
    df = str(dosage_form_class or "").strip()
    return df if df in _VALID else OTHER


# A SANDS is a POST-NOC supplement, not a fresh generic filing. Health Canada's
# Post-NOC Changes: Quality guidance supports a manufacturing/formulation change
# with comparative IN-VITRO dissolution (f2 similarity) in the general case; a
# fresh in-vivo comparative bioequivalence study is only triggered by specific
# higher-risk changes. So for a SANDS the BE study is CHANGE-DEPENDENT
# (conditional), never unconditionally "required".
_SUPPLEMENT_ROUTE = (
    False, "Post-NOC change — comparative evidence is change-dependent",
    "For a post-NOC supplement the comparative evidence depends on the change: "
    "many changes are supported by comparative in-vitro dissolution (f2 "
    "similarity 50-100) against the previously-approved product; a fresh in-vivo "
    "comparative bioequivalence study is required only for specific higher-risk "
    "changes. Scope the evidence to your change.",
    "HC Post-NOC Changes: Quality guidance.")


def route(dosage_form_class: str, submission_type: str = "ANDS") -> dict:
    """The comparative-evidence route for a dosage form + submission type: a
    plain-language plan + HC citation + whether an in-vivo BE study (5.3.1) is
    required. A SANDS (post-NOC supplement) is change-dependent, not required."""
    df = _norm(dosage_form_class)
    if str(submission_type or "").upper() == "SANDS":
        requires, label, evidence, citation = _SUPPLEMENT_ROUTE
        return {"dosage_form_class": df, "route": "post_noc_supplement",
                "requires_be_study": requires, "label": label,
                "evidence": evidence, "citation": citation}
    key = _FORM_TO_ROUTE[df]
    requires, label, evidence, citation = _ROUTES[key]
    return {"dosage_form_class": df, "route": key, "requires_be_study": requires,
            "label": label, "evidence": evidence, "citation": citation}


def be_study_applicability(dosage_form_class: str) -> str:
    """Applicability of the comparative-BE study (5.3.1) + CS-BE summary (1.6)
    for a GENERIC of this dosage form: 'required' when a PK study is needed,
    'conditional' when a biowaiver or non-PK evidence route applies."""
    return "required" if route(dosage_form_class)["requires_be_study"] \
        else "conditional"
