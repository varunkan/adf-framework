"""Health Canada content review for each authorable eCTD form (pure).

Distinct from :mod:`ectd_validation` (which checks the eCTD *package* —
backbone, checksums, PDF conformance). This checks the *content* of a Module-1
form against HC's documented required elements, and for every gap returns the
specific canada.ca guidance link and a concrete suggested edit — the
"review mechanism" a filer would otherwise get back from HC screening.

Rules are derived from HC guidance (Organization of Module 1, PM(NOC)
Regulations, Comparative Bioavailability, QOS-CE templates). Each finding:
{severity: error|warning, rule, message, hc_url, suggested_edit}.
"""

from __future__ import annotations

_APPS = ("https://www.canada.ca/en/health-canada/services/drugs-health-products"
         "/drug-products/applications-submissions")
URLS = {
    "m1": f"{_APPS}/guidance-documents/organization-document-placement-canadian-module-1.html",
    "rep": "https://health-products.canada.ca/rep-pir/index.html",
    "patent": "https://laws-lois.justice.gc.ca/eng/regulations/SOR-93-133/",  # PM(NOC)
    "babe": f"{_APPS}/guidance-documents/bioavailability-bioequivalence/conduct-analysis-comparative.html",
    "qos": f"{_APPS}/templates.html",
    "forms": f"{_APPS}/forms.html",
}


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _has(fields: dict, *keys) -> bool:
    return any(_s(fields.get(k)) and _s(fields.get(k)) != "—" for k in keys)


def _finding(sev, rule, message, url, suggested_edit) -> dict:
    return {"severity": sev, "rule": rule, "message": message,
            "hc_url": url, "suggested_edit": suggested_edit}


def _review_cover_letter(f: dict) -> list:
    out = []
    if not _has(f, "sponsor", "applicant", "company"):
        out.append(_finding("error", "cover_sponsor_required",
            "The cover letter must identify the sponsor company.", URLS["m1"],
            "Add the sponsor's legal name (e.g. 'Sponsor Pharma Inc.')."))
    if not _has(f, "company_id"):
        out.append(_finding("warning", "cover_company_id",
            "Health Canada Company ID is expected so the transaction is "
            "routed to your company file.", URLS["rep"],
            "Add your 5-digit HC Company ID (from the REP CO template)."))
    if not _has(f, "contact_email", "contact"):
        out.append(_finding("warning", "cover_contact",
            "A regulatory contact should be named for correspondence.",
            URLS["m1"], "Add a contact name + email for this submission."))
    return out


def _review_rep(f: dict) -> list:
    out = []
    if not _has(f, "company_id"):
        out.append(_finding("error", "rep_company_id_required",
            "The REP Regulatory Transaction requires the sponsor's HC "
            "Company ID.", URLS["rep"],
            "Enter your 5-digit Company ID; obtain one via the REP CO "
            "template if you don't have it."))
    if not _has(f, "sponsor", "applicant"):
        out.append(_finding("error", "rep_company_name_required",
            "The REP transaction must carry the sponsor company NAME "
            "(distinct from the product).", URLS["rep"],
            "Set the company name to the sponsor, not the drug product."))
    if not _has(f, "dossier_id"):
        out.append(_finding("error", "rep_dossier_id_required",
            "A Dossier ID is mandatory on every regulatory transaction.",
            URLS["rep"], "Add the Dossier ID (e + 6–7 digits)."))
    return out


def _review_form_v(f: dict) -> list:
    out = []
    patents = _s(f.get("patents"))
    if patents and patents != "—":
        if not _has(f, "allegation"):
            out.append(_finding("error", "formv_allegation_required",
                "Each listed patent/CSP needs one section-5 statement.",
                URLS["patent"],
                "State, per patent: not addressed / accepts expiry / alleges "
                "invalidity / alleges non-infringement."))
        alleg = _s(f.get("allegation")).lower()
        if ("invalid" in alleg or "non-infring" in alleg or
                "not infring" in alleg):
            out.append(_finding("warning", "formv_noa_service",
                "An invalidity/non-infringement allegation triggers service "
                "of a Notice of Allegation on the innovator (starts the "
                "45-day action window).", URLS["patent"],
                "Confirm the NOA is served and track the 45-day / 24-month "
                "clocks in Correspondence → NOA register."))
        if not _has(f, "crp_din"):
            out.append(_finding("warning", "formv_crp_din",
                "Identify the Canadian Reference Product DIN the patents are "
                "listed against.", URLS["patent"],
                "Add the CRP's 8-digit DIN."))
    return out


def _review_attestation(f: dict) -> list:
    out = []
    if not _has(f, "signer"):
        out.append(_finding("error", "attest_signer_required",
            "The ANDS Sponsor Attestation must name an authorised signer.",
            URLS["forms"],
            "Add the authorised signer's name and title."))
    return out


def _review_cs_be(f: dict) -> list:
    out = []
    if not _has(f, "crp_brand", "reference_product"):
        out.append(_finding("error", "csbe_crp_required",
            "The CS-BE must identify the Canadian Reference Product.",
            URLS["babe"], "Add the CRP brand name."))
    if not _has(f, "auc_ci"):
        out.append(_finding("error", "csbe_auc_required",
            "The comparative BE summary must report the AUC 90% confidence "
            "interval against the 80.00–125.00% limits.", URLS["babe"],
            "Add the AUC 90% CI (e.g. 94.2–106.8%)."))
    if not _has(f, "cmax"):
        out.append(_finding("error", "csbe_cmax_required",
            "The CS-BE must report the Cmax 90% CI / point estimate.",
            URLS["babe"], "Add the Cmax 90% CI (ICH M13A requires the full "
            "CI for IR solid oral products)."))
    return out


def _review_qos(f: dict) -> list:
    out = []
    if not _has(f, "drug_product", "product", "title"):
        out.append(_finding("warning", "qos_product",
            "Name the drug product the QOS-CE(BE) summarises.", URLS["qos"],
            "Add the product name + strength."))
    return out


_REVIEWERS = {
    "cover_letter": _review_cover_letter,
    "rep_application_form": _review_rep,
    "patent_form_v": _review_form_v,
    "patent_form_iv": _review_form_v,
    "ands_attestation": _review_attestation,
    "cs_be": _review_cs_be,
    "qos_ce_scaffold": _review_qos,
}


def review(generator_key: str, fields: dict) -> dict:
    """Run HC content review for one form. Returns {passed, findings[]}."""
    fn = _REVIEWERS.get(_s(generator_key))
    findings = fn(fields or {}) if fn else []
    errors = [x for x in findings if x["severity"] == "error"]
    return {"passed": not errors, "findings": findings,
            "error_count": len(errors),
            "warning_count": len(findings) - len(errors)}
