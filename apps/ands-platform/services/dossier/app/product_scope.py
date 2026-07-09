"""Product-class honest scope note for the dossier builder (Tier B).

A lightweight, self-contained note map (mirrors the journey service's richer
``product_class`` model — each service owns its copy of the HC boundary). Given
the product class recorded on a dossier, ``note`` returns a plain-language
scope caveat when the class is OUTSIDE ANDS Studio's core generic small-molecule
chemical-drug authoring, or None for the in-core case. Pure, stdlib-only.

Facts web-verified vs canada.ca (Jul 2026): a biosimilar files a full NDS (not an
ANDS); biologics/radiopharmaceuticals are BRDD; veterinary is VDD; disinfectants
are NNHPD-assessed DINs (transitioning to the Biocides Regulations); NHPs carry
an NPN under the NNHPD.
"""

from __future__ import annotations

_NOTES: dict[str, str] = {
    "small_molecule": "",   # the in-core generic chemical drug — no caveat
    "biologic":
        "This dossier is marked as a biologic (Schedule D). Health Canada reviews "
        "it through the BRDD as an NDS/SNDS, not an ANDS — the eCTD structure, "
        "validation and fees here are correct, but the scientific dossier is "
        "authored to the biologics guidance, not the generic model.",
    "biosimilar":
        "This dossier is marked as a biosimilar. A biosimilar is authorized "
        "through a full New Drug Submission (NDS) — or, on a case-by-case basis, "
        "an SNDS relying on the previously demonstrated similarity (generally a "
        "labelling-only supplement) — with a similarity package versus the "
        "reference biologic, NOT the ANDS bioequivalence pathway. Use ANDS Studio "
        "for the eCTD shell only.",
    "radiopharmaceutical":
        "This dossier is marked as a radiopharmaceutical (Schedule C). It carries "
        "the additional Part C, Division 3 requirements under BRDD review, which "
        "ANDS Studio does not model — treat its output as the eCTD shell only.",
    "veterinary":
        "This dossier is marked as a veterinary drug. It is reviewed by the "
        "Veterinary Drugs Directorate through its own submission stream, not the "
        "human-drug ANDS pathway ANDS Studio is tuned for.",
    "disinfectant":
        "This dossier is marked as a surface disinfectant. A disinfectant is an "
        "NNHPD-assessed DIN (transitioning to the Biocides Regulations), not an "
        "ANDS/NDS eCTD review — this is outside ANDS Studio's authoring model.",
    "natural_health_product":
        "This dossier is marked as a natural health product. NHPs are regulated "
        "under the Natural Health Products Regulations (NPN, not a DIN) by the "
        "NNHPD — an entirely separate regime from drug submissions.",
}

_UNKNOWN_NOTE = (
    "This product class is not one ANDS Studio models. Confirm the correct "
    "directorate, filing instrument and evidence with Health Canada before "
    "relying on any output here.")


def note(product_class) -> str | None:
    """The honest scope note for a dossier's product class, or None for the
    in-core generic small-molecule chemical drug (the default)."""
    code = str(product_class or "").strip().lower() or "small_molecule"
    if code in _NOTES:
        return _NOTES[code] or None
    return _UNKNOWN_NOTE
