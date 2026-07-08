"""Product-class honest-scope model — 'is this even the right tool?' (Tier B).

ANDS Studio's guided authoring is built for a GENERIC small-molecule chemical
drug filed as an ANDS (with an NDS/SNDS/SANDS/DIN variant of the SAME chemical-
drug content model). Other product classes — biologics, biosimilars,
radiopharmaceuticals, veterinary drugs, disinfectants, natural health products —
are real Health Canada regimes with DIFFERENT directorates, filing instruments
and evidence. Pretending to support them, or offering a hollow menu option, is a
trust failure. This model states the boundary HONESTLY: for an out-of-core class
it names the directorate, the correct filing instrument, the evidence basis and a
real contact, so the filer is handed off, not misled.

Every fact below is web-verified against canada.ca (July 2026):
  * Biosimilars are authorized via a New Drug Submission (NDS/SNDS) — NOT an ANDS.
    "Guidance Document: Information and Submission Requirements for Biosimilar
    Biologic Drugs." Recombinant-DNA biologics go the biosimilar (NDS) route;
    short polypeptides MAY use the ANDS pathway.
  * Biologics are Schedule D drugs reviewed by the Biologic and Radiopharmaceutical
    Drugs Directorate (BRDD).
  * Radiopharmaceuticals are Schedule C drugs under Part C, Division 3.
  * Veterinary drugs are reviewed by the Veterinary Drugs Directorate (VDD).
  * Disinfectants are DIN drugs assessed by the Natural and Non-prescription
    Health Products Directorate (NNHPD); disinfectants/sanitizers are transitioning
    to the Biocides Regulations. Contact hc.nnhpd.consultation-dpsnso.sc@canada.ca.
  * Natural health products are NNHPD-regulated and carry an NPN (not a DIN).
"""

from __future__ import annotations

_NNHPD_CONTACT = "hc.nnhpd.consultation-dpsnso.sc@canada.ca"

# code -> full record. in_scope=True is ANDS Studio's core generic chemical-drug
# authoring. Out-of-scope classes carry an HONEST hand-off (directorate + filing
# instrument + evidence + advisory + citation [+ contact]).
_CLASSES: dict[str, dict] = {
    "small_molecule": {
        "label": "Small-molecule chemical drug",
        "in_scope": True,
        "directorate": "",
        "filing_instrument": "",
        "evidence": "",
        "advisory": None,
        "citation": "",
        "contact": "",
    },
    "biologic": {
        "label": "Biologic (Schedule D)",
        "in_scope": False,
        "directorate": "Biologic and Radiopharmaceutical Drugs Directorate (BRDD)",
        "filing_instrument": "New Drug Submission (NDS) / SNDS — not an ANDS",
        "evidence": "full quality/nonclinical/clinical package (comparability for "
                    "changes), not comparative bioequivalence",
        "advisory": "A biologic (Schedule D) is reviewed by the BRDD and filed as "
                    "an NDS/SNDS, not an ANDS. ANDS Studio still gives you the "
                    "correct eCTD structure, validation and fees, but the "
                    "scientific dossier is authored to the biologics guidance. "
                    "(Short polypeptides may instead follow the ANDS pathway.)",
        "citation": "HC Regulatory roadmap for biologic (Schedule D) drugs.",
        "contact": "",
    },
    "biosimilar": {
        "label": "Biosimilar (subsequent-entry biologic, Schedule D)",
        "in_scope": False,
        "directorate": "Biologic and Radiopharmaceutical Drugs Directorate (BRDD)",
        "filing_instrument": "New Drug Submission (NDS) — not an ANDS",
        "evidence": "a similarity / comparability package vs. the reference "
                    "biologic, not a bioequivalence study",
        "advisory": "A biosimilar is NOT a generic: Health Canada authorizes it "
                    "through a full New Drug Submission (NDS) with a similarity "
                    "package versus the reference biologic — the ANDS "
                    "bioequivalence pathway does not apply. ANDS Studio can shape "
                    "the eCTD, but the biosimilarity evidence is authored to the "
                    "biosimilars guidance.",
        "citation": "HC Guidance: Information and Submission Requirements for "
                    "Biosimilar Biologic Drugs.",
        "contact": "",
    },
    "radiopharmaceutical": {
        "label": "Radiopharmaceutical (Schedule C)",
        "in_scope": False,
        "directorate": "Biologic and Radiopharmaceutical Drugs Directorate (BRDD)",
        "filing_instrument": "NDS/ANDS with Schedule C / Part C, Division 3 "
                             "requirements",
        "evidence": "the additional radiopharmaceutical quality/safety "
                    "requirements of Part C, Division 3",
        "advisory": "A radiopharmaceutical is a Schedule C drug subject to the "
                    "extra requirements of Part C, Division 3 and BRDD review. "
                    "ANDS Studio does not model those Division 3 specifics — treat "
                    "its output as the eCTD shell only.",
        "citation": "Food and Drug Regulations, Part C, Division 3 (Schedule C).",
        "contact": "",
    },
    "veterinary": {
        "label": "Veterinary drug",
        "in_scope": False,
        "directorate": "Veterinary Drugs Directorate (VDD)",
        "filing_instrument": "veterinary drug submission (separate stream)",
        "evidence": "target-animal safety/efficacy + human food-safety where "
                    "applicable",
        "advisory": "A veterinary drug is reviewed by the Veterinary Drugs "
                    "Directorate through its own submission stream, not the human-"
                    "drug ANDS pathway. ANDS Studio is not tuned for VDD "
                    "requirements.",
        "citation": "HC Veterinary Drugs Directorate submission guidance.",
        "contact": "",
    },
    "disinfectant": {
        "label": "Surface disinfectant / biocide",
        "in_scope": False,
        "directorate": "Natural and Non-prescription Health Products Directorate "
                       "(NNHPD)",
        "filing_instrument": "DIN application / market authorization (NNHPD) — not "
                             "an ANDS/NDS eCTD review",
        "evidence": "safety, efficacy and quality per the Hard Surface "
                    "Disinfectants Monograph or a disinfectant drug application",
        "advisory": "A surface disinfectant is a drug assessed by the NNHPD and "
                    "granted a DIN through a disinfectant application — not an "
                    "ANDS/NDS eCTD review. (Disinfectants and sanitizers are "
                    "transitioning to the Biocides Regulations.) This is outside "
                    "ANDS Studio's authoring model.",
        "citation": "HC Guidance documents on disinfectants; Hard Surface "
                    "Disinfectants Monograph; Biocides Regulations transition.",
        "contact": _NNHPD_CONTACT,
    },
    "natural_health_product": {
        "label": "Natural health product (NHP)",
        "in_scope": False,
        "directorate": "Natural and Non-prescription Health Products Directorate "
                       "(NNHPD)",
        "filing_instrument": "Product Licence application → NPN (not a DIN)",
        "evidence": "the Natural Health Products Regulations evidence for safety "
                    "and efficacy (monograph or full assessment)",
        "advisory": "A natural health product is regulated under the Natural "
                    "Health Products Regulations and carries an NPN, not a DIN — "
                    "an entirely separate regime from drug submissions. ANDS "
                    "Studio does not cover it.",
        "citation": "Natural Health Products Regulations; NNHPD guidance.",
        "contact": _NNHPD_CONTACT,
    },
}

# Ordered for the UI select: (value, label)
PRODUCT_CLASSES = tuple((code, rec["label"]) for code, rec in _CLASSES.items())

# a conservative record for an unrecognised class — honest 'we don't model this'
_UNKNOWN = {
    "label": "Other / not listed",
    "in_scope": False,
    "directorate": "the appropriate Health Canada directorate",
    "filing_instrument": "the pathway for that product class",
    "evidence": "the evidence required by that regime",
    "advisory": "This product class is not one ANDS Studio models. Confirm the "
                "correct directorate, filing instrument and evidence with Health "
                "Canada before relying on any ANDS Studio output.",
    "citation": "HC Management of Drug Submissions and Applications guidance.",
    "contact": "",
}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def scope(product_class: str) -> dict:
    """The honest scope record for a product class. ``in_scope`` True is ANDS
    Studio's core generic chemical-drug authoring (advisory None); otherwise the
    record names the real directorate / filing instrument / evidence / contact."""
    code = _s(product_class).lower() or "small_molecule"
    rec = _CLASSES.get(code, _UNKNOWN)
    return {"product_class": code if code in _CLASSES else "other", **rec}


def is_in_scope(product_class: str) -> bool:
    return bool(scope(product_class)["in_scope"])


def list_product_classes() -> list:
    """Every product class + its scope record, for the UI select + banner.
    Each row carries ``value`` (the option value) alongside the scope fields."""
    return [{"value": code, **scope(code)} for code, _ in PRODUCT_CLASSES]
