"""Realistic, editable sample field-sets for each authorable eCTD form (pure).

The module builder pre-fills a form with a worked example matched to the
dossier's submission type + product, so the filer edits a realistic draft
instead of a blank page full of '—'. Real dossier facts (product, sponsor,
company id, DIN) always win; the sample only supplies the fields the dossier
doesn't yet carry (study design, CI values, patent allegations, …).

Keyed by the section tree's ``generator_key``. Every value is clearly a
worked EXAMPLE the client is expected to replace — never invented regulatory
fact presented as truth.
"""

from __future__ import annotations


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _base(ctx: dict) -> dict:
    """The real, known facts from the dossier context (never overwritten)."""
    return {
        "drug_product": _s(ctx.get("drug_product") or ctx.get("title")),
        "dossier_id": _s(ctx.get("dossier_id")),
        "company_id": _s(ctx.get("company_id")),
        "sponsor": _s(ctx.get("sponsor") or ctx.get("applicant")),
        "din": _s(ctx.get("din")),
        "sequence": _s(ctx.get("sequence")) or "0000",
        "activity_type": _s(ctx.get("submission_type")
                            or ctx.get("activity_type")) or "ANDS",
    }


# Per-generator realistic sample values (the editable defaults). Values here are
# EXAMPLES — the UI labels them as sample text to review/replace.
def _samples_for(key: str, b: dict) -> dict:
    product = b["drug_product"] or "Drugazole 10 mg tablet"
    if key in ("cover_letter",):
        return {
            "contact_name": "Jane Doe, Regulatory Affairs Manager",
            "contact_email": "regulatory@sponsor.example",
            "sequence_description": "Original ANDS submission",
        }
    if key in ("rep_application_form",):
        return {
            "dossier_type": b["activity_type"],
            "sequence_description": "Original submission",
        }
    if key in ("patent_form_v", "patent_form_iv"):
        return {
            "crp_brand": "Brandozole",
            "crp_din": "02123456",
            "patents": "CA 2,845,123; CSP 155-00042",
            "patent_expiry": "2029-11-30",
            "allegation": "alleges non-infringement — no claim for the "
                          "medicinal ingredient, formulation, dosage form or "
                          "use would be infringed",
        }
    if key in ("ands_attestation",):
        return {
            "signer": "Dr. Sam Lee, VP Regulatory Affairs",
            "signer_title": "VP Regulatory Affairs",
        }
    if key in ("cs_be",):
        return {
            "crp_brand": "Brandozole",
            "crp_din": "02123456",
            "dosage_form": "immediate-release tablet",
            "strength": "10 mg",
            "study_design": "single-dose, fasting, randomized, two-way "
                            "crossover",
            "auc_ci": "94.2 – 106.8%",
            "cmax": "91.5 – 109.3%",
            "ruleset": "ICH M13A (single-dose, IR solid oral)",
        }
    if key in ("qos_ce_scaffold",):
        return {
            "manufacturer": "Sponsor Pharma Manufacturing Inc.",
            "shelf_life": "24 months",
            "storage": "Store at 15–30°C",
        }
    return {}


def sample_fields(generator_key: str, ctx: dict) -> dict:
    """The pre-fill for a form: real dossier facts + a realistic sample for the
    rest. Returns {fields: {..}, sample_keys: [..]} so the UI can badge which
    values are worked-example defaults vs. the dossier's own facts."""
    b = _base(ctx)
    sample = _samples_for(_s(generator_key), b)
    fields = {k: v for k, v in b.items() if v}   # known facts first
    for k, v in sample.items():
        fields.setdefault(k, v)                   # sample fills the gaps
    return {"fields": fields, "sample_keys": sorted(sample.keys())}
