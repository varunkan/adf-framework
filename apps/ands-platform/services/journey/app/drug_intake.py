"""'Tell me about your drug' decision support — pure (ported from monolith).

Submission-type routing + advisories (steer a wrong-pathway filer off ANDS), the
Canadian Reference Product + pharmaceutical-equivalence check, and the
bioequivalence ruleset (ICH M13A vs legacy). ``assess`` ties them together into
the branching guidance the conversational intake renders.
"""

from __future__ import annotations

# -- submission-type router (from content_model) -----------------------------
SUBMISSION_TYPES = {
    "NDS": {"label": "New Drug Submission", "ands_content_model": False,
            "advice": "Full innovator submission — complete Modules 2-5 "
                      "(safety/efficacy required)."},
    "ANDS": {"label": "Abbreviated New Drug Submission", "ands_content_model": True,
             "advice": "Generic relying on a Canadian Reference Product — Module 4 "
                       "not required; Module 3 (CMC) and Module 5 bioequivalence "
                       "reports required."},
    "SNDS": {"label": "Supplement to a New Drug Submission",
             "ands_content_model": False,
             "advice": "Post-NOC change to an NDS — scope the supplement to the "
                       "changed modules."},
    "SANDS": {"label": "Supplement to an Abbreviated New Drug Submission",
              "ands_content_model": True,
              "advice": "Post-NOC change to an ANDS — ANDS content rules apply to "
                        "the changed modules."},
    "DIN": {"label": "DIN Application", "ands_content_model": False,
            "advice": "Drug Identification Number application (no NDS/ANDS review "
                      "pathway)."},
}

_ANDS_MODULES = [
    {"module": "1", "title": "Administrative & regional (Canada)", "required": True,
     "cs_be_suppressed": False},
    {"module": "2.3", "title": "Quality Overall Summary (QOS-CE)", "required": True,
     "cs_be_suppressed": False},
    {"module": "2.4", "title": "Nonclinical Overview", "required": False,
     "cs_be_suppressed": True},
    {"module": "2.5", "title": "Clinical Overview", "required": False,
     "cs_be_suppressed": True},
    {"module": "2.6", "title": "Nonclinical Written & Tabulated Summaries",
     "required": False, "cs_be_suppressed": True},
    {"module": "2.7", "title": "Clinical Summary (incl. 2.7.1)", "required": False,
     "cs_be_suppressed": True},
    {"module": "3", "title": "Quality (CMC)", "required": True,
     "cs_be_suppressed": False},
    {"module": "4", "title": "Nonclinical Study Reports", "required": False,
     "cs_be_suppressed": False},
    {"module": "5", "title": "Clinical Study Reports (BE reports)", "required": True,
     "cs_be_suppressed": False},
]


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def is_valid_submission_type(value) -> bool:
    return _s(value).upper() in SUBMISSION_TYPES


def ands_content_model(cs_be_only: bool = False) -> dict:
    cs_be_only = bool(cs_be_only)
    modules = []
    for spec in _ANDS_MODULES:
        suppressed = cs_be_only and spec["cs_be_suppressed"]
        required = False if (suppressed or spec["cs_be_suppressed"]) \
            else spec["required"]
        modules.append({"module": spec["module"], "title": spec["title"],
                        "required": required, "suppressed": suppressed,
                        "applicable": not suppressed})
    return {"submission_type": "ANDS", "cs_be_only": cs_be_only,
            "module4_required": False, "modules": modules}


def route_submission_type(data: dict) -> dict:
    """Route a submission type + decision support (steer ANDS-ineligible filers)."""
    data = data or {}
    raw = _s(data.get("submission_type"))
    code = raw.upper()
    if code not in SUBMISSION_TYPES:
        return {"valid": False, "submission_type": raw,
                "error": f"'{raw}' is not a recognised submission type "
                         f"(expected one of {', '.join(SUBMISSION_TYPES)})"}
    meta = SUBMISSION_TYPES[code]
    advisories = []
    if meta["ands_content_model"] and bool(data.get("new_indication")):
        advisories.append({
            "rule": "ands_not_for_new_indication",
            "message": "A generic seeking a new indication beyond the Canadian "
                       "Reference Product is generally NOT eligible for the ANDS "
                       "pathway — an NDS/SNDS is typically required."})
    result = {"valid": True, "submission_type": code, "label": meta["label"],
              "advice": meta["advice"],
              "ands_content_model": meta["ands_content_model"],
              "advisories": advisories}
    if meta["ands_content_model"]:
        result["content_model"] = ands_content_model(
            cs_be_only=bool(data.get("cs_be_only")))
    return result


# -- Canadian Reference Product + pharmaceutical equivalence ------------------
CRP_FIELDS = {"brand_name": "Brand name", "din": "DIN", "strength": "Strength",
              "dosage_form": "Dosage form", "innovator": "Innovator / manufacturer"}

_COMPARABLE_FORMS = (
    {"tablet", "caplet", "film-coated tablet", "coated tablet"},
    {"capsule", "hard capsule", "soft capsule", "softgel"},
    {"oral solution", "solution", "syrup", "oral liquid"},
    {"suspension", "oral suspension"})


def _form_group(form: str):
    f = _s(form).lower()
    return next((grp for grp in _COMPARABLE_FORMS if f in grp), None)


def is_comparable_dosage_form(a: str, b: str) -> bool:
    a_n, b_n = _s(a).lower(), _s(b).lower()
    if not a_n or not b_n:
        return False
    if a_n == b_n:
        return True
    ga, gb = _form_group(a_n), _form_group(b_n)
    return ga is not None and ga is gb


def _ingredients(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
    else:
        parts = [str(p).strip() for p in value]
    return sorted({p.lower() for p in parts if p})


def validate_crp(data: dict) -> list:
    out = []
    for field, label in CRP_FIELDS.items():
        if not _s((data or {}).get(field)):
            out.append({"rule": f"crp_{field}_required",
                        "message": f"{label} is required for the CRP"})
    if (data or {}).get("foreign") and not _s((data or {}).get("foreign_justification")):
        out.append({"rule": "foreign_crp_justification_required",
                    "message": "A foreign Canadian Reference Product requires a "
                               "justification record per the foreign-CRP path"})
    return out


def check_pharmaceutical_equivalence(crp: dict, generic: dict) -> list:
    out = []
    crp, generic = crp or {}, generic or {}
    crp_ing = _ingredients(crp.get("medicinal_ingredients"))
    gen_ing = _ingredients(generic.get("medicinal_ingredients"))
    if crp_ing and gen_ing and crp_ing != gen_ing:
        out.append({"rule": "pharmaceutical_equivalence_ingredient",
                    "message": f"Medicinal ingredient(s) differ — CRP has "
                               f"{', '.join(crp_ing)}; generic has "
                               f"{', '.join(gen_ing)}"})
    if _s(crp.get("dosage_form")) and _s(generic.get("dosage_form")) and \
            not is_comparable_dosage_form(crp.get("dosage_form"),
                                          generic.get("dosage_form")):
        out.append({"rule": "pharmaceutical_equivalence_dosage_form",
                    "message": f"Dosage form '{_s(generic.get('dosage_form'))}' is "
                               f"not comparable to the CRP dosage form "
                               f"'{_s(crp.get('dosage_form'))}'"})
    return out


# -- bioequivalence ruleset (ICH M13A vs legacy) -----------------------------
M13A_EFFECTIVE_DATE = "2025-12-27"
IR_SOLID_ORAL = "ir_solid_oral"
DOSAGE_FORM_CLASSES = {IR_SOLID_ORAL: "Immediate-release solid oral",
                       "mr_solid_oral": "Modified-release solid oral",
                       "non_ir": "Non-immediate-release / other",
                       "other": "Other dosage form"}
BE_RULESETS = {
    "legacy": {"version": "legacy", "cmax_rule": "point_estimate", "lower": 80.0,
               "upper": 125.0, "decimals": 1,
               "label": "Pre-ICH-M13A / non-IR (point-estimate Cmax)"},
    "M13A": {"version": "M13A", "cmax_rule": "ci90", "lower": 80.00, "upper": 125.00,
             "decimals": 2, "effective": M13A_EFFECTIVE_DATE,
             "label": "ICH M13A (IR solid oral, full 90% CI Cmax)"}}


def resolve_be_ruleset(submission_date: str, dosage_form_class: str) -> dict:
    submission_date = _s(submission_date)
    if (_s(dosage_form_class) == IR_SOLID_ORAL and submission_date
            and submission_date >= M13A_EFFECTIVE_DATE):
        rs = dict(BE_RULESETS["M13A"])
    else:
        rs = dict(BE_RULESETS["legacy"])
    rs["submission_date"] = submission_date
    rs["dosage_form_class"] = _s(dosage_form_class)
    return rs


def list_be_rulesets() -> list:
    return [dict(BE_RULESETS[v]) for v in ("M13A", "legacy")]


# -- comparative-evidence route by dosage form (biowaivers) ------------------
# Health Canada does NOT require an in-vivo comparative bioequivalence (PK) study
# for every generic dosage form. This maps a dosage form to the comparative-
# evidence ROUTE and to whether a PK BE study (eCTD 5.3.1) is REQUIRED or a
# biowaiver / non-PK evidence route may apply. Mirrors the dossier service's
# ``comparative_evidence`` model (each service owns its copy of the HC rule).
CE_PARENTERAL_SOLUTION = "parenteral_solution"
CE_ORAL_SOLUTION = "oral_solution"
CE_OPHTHALMIC_OTIC_SOLUTION = "ophthalmic_otic_solution"
CE_ORALLY_INHALED = "orally_inhaled"
CE_TOPICAL_LOCAL = "topical_local"
CE_MR_SOLID_ORAL = "mr_solid_oral"

# route -> (requires_be_study, label, evidence, citation)
_CE_ROUTES = {
    "pk_be_study": (
        True, "Comparative bioequivalence (PK) study",
        "A pivotal comparative PK study vs. the Canadian Reference Product "
        "(AUC/Cmax 90% CI within 80.00-125.00%) is required.",
        "HC Comparative Bioavailability Standards; ICH M13A (IR solid oral)."),
    "mr_pk_be_study": (
        True, "Comparative bioequivalence (PK) study - fed & fasting",
        "A modified-release generic requires comparative PK studies under BOTH "
        "fed and fasting conditions, plus a dose-dumping assessment.",
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
        "WAIVED - provide the biowaiver justification instead of a PK study.",
        "HC Submissions for Generic Parenteral Drugs."),
    "aqueous_solution_biowaiver": (
        False, "Aqueous-solution biowaiver (confirm)",
        "For an aqueous solution (oral, ophthalmic, otic) whose non-medicinal "
        "ingredients are qualitatively identical to the reference, the in-vivo "
        "BE study may be WAIVED - provide the biowaiver justification.",
        "HC Comparative Bioavailability Standards (aqueous solutions)."),
    "topical_clinical_invitro": (
        False, "Topical comparative evidence (not PK BE)",
        "A locally-acting topical generic demonstrates equivalence by "
        "comparative CLINICAL endpoint or in-vitro release/permeation - not a "
        "systemic PK bioequivalence study.",
        "HC guidance for topical / locally-acting products."),
}

_CE_FORM_TO_ROUTE = {
    IR_SOLID_ORAL: "pk_be_study",
    CE_MR_SOLID_ORAL: "mr_pk_be_study",
    "non_ir": "pk_be_study",
    CE_ORALLY_INHALED: "oip_studies",
    CE_PARENTERAL_SOLUTION: "parenteral_biowaiver",
    CE_ORAL_SOLUTION: "aqueous_solution_biowaiver",
    CE_OPHTHALMIC_OTIC_SOLUTION: "aqueous_solution_biowaiver",
    CE_TOPICAL_LOCAL: "topical_clinical_invitro",
}


def comparative_evidence_route(dosage_form_class: str) -> dict:
    """The comparative-evidence route for a dosage form: a plain-language plan +
    HC citation + whether an in-vivo BE study (5.3.1) is required. Unknown forms
    default conservatively to the PK-study route."""
    df = _s(dosage_form_class)
    key = _CE_FORM_TO_ROUTE.get(df, "pk_be_study")   # conservative default
    requires, label, evidence, citation = _CE_ROUTES[key]
    return {"dosage_form_class": df or "other", "route": key,
            "requires_be_study": requires, "label": label,
            "evidence": evidence, "citation": citation}


# Ordered for the intake dosage-form select: (value, human label)
DOSAGE_FORMS = (
    (IR_SOLID_ORAL, "Immediate-release solid oral (tablet/capsule)"),
    (CE_MR_SOLID_ORAL, "Modified-release solid oral"),
    (CE_ORAL_SOLUTION, "Oral solution / aqueous liquid"),
    (CE_PARENTERAL_SOLUTION, "Parenteral (injectable) aqueous solution"),
    (CE_OPHTHALMIC_OTIC_SOLUTION, "Ophthalmic / otic solution"),
    (CE_ORALLY_INHALED, "Orally inhaled product"),
    (CE_TOPICAL_LOCAL, "Topical / locally-acting (dermal)"),
    ("other", "Other / not sure"),
)


def list_dosage_forms() -> list:
    """Every intake dosage form + its comparative-evidence route, so the UI can
    render the select and preview whether a PK BE study is required or a
    biowaiver may apply — before the filer commits to a study."""
    out = []
    for value, label in DOSAGE_FORMS:
        r = comparative_evidence_route(value)
        out.append({"value": value, "label": label,
                    "requires_be_study": r["requires_be_study"],
                    "route": r["route"], "evidence": r["evidence"],
                    "citation": r["citation"]})
    return out


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _within(v, lo, hi) -> bool:
    return v is not None and lo <= v <= hi


def evaluate_bioequivalence(study: dict, submission_date: str,
                            dosage_form_class: str) -> dict:
    ruleset = resolve_be_ruleset(submission_date, dosage_form_class)
    study = study or {}
    lo, hi = ruleset["lower"], ruleset["upper"]
    findings = []
    auc = study.get("auc") or {}
    cl, cu = _to_float(auc.get("ci_lower")), _to_float(auc.get("ci_upper"))
    if cl is None or cu is None:
        findings.append({"rule": "auc_ci_required",
                         "message": "AUC 90% confidence interval is required"})
    elif not (_within(cl, lo, hi) and _within(cu, lo, hi)):
        findings.append({"rule": "auc_ci_out_of_range",
                         "message": f"AUC 90% CI {cl:g}-{cu:g}% is outside the "
                                    f"acceptance limits {lo:g}-{hi:g}%"})
    cmax = study.get("cmax") or {}
    if ruleset["cmax_rule"] == "ci90":
        cl, cu = _to_float(cmax.get("ci_lower")), _to_float(cmax.get("ci_upper"))
        if cl is None or cu is None:
            findings.append({"rule": "cmax_ci_required",
                             "message": "ICH M13A requires the full Cmax 90% CI"})
        elif not (_within(cl, lo, hi) and _within(cu, lo, hi)):
            findings.append({"rule": "cmax_ci_out_of_range",
                             "message": f"Cmax 90% CI {cl:g}-{cu:g}% is outside the "
                                        f"ICH M13A limits {lo:.2f}-{hi:.2f}%"})
    else:
        pe = _to_float(cmax.get("point_estimate"))
        if pe is None:
            findings.append({"rule": "cmax_point_estimate_required",
                             "message": "The Cmax point estimate is required"})
        elif not _within(pe, lo, hi):
            findings.append({"rule": "cmax_point_estimate_out_of_range",
                             "message": f"Cmax point estimate {pe:g}% is outside "
                                        f"the limits {lo:g}-{hi:g}%"})
    return {"ruleset": ruleset, "findings": findings,
            "bioequivalent": not findings, "cmax_rule": ruleset["cmax_rule"]}


# -- the unified 'assess my drug' engine -------------------------------------
def assess(answers: dict) -> dict:
    """The 'Tell me about your drug' engine: route the submission type, run the
    CRP pharmaceutical-equivalence + bioequivalence checks when supplied, and
    return combined plain-language guidance + advisories + the content model."""
    answers = answers or {}
    route = route_submission_type(answers)
    result = {"route": route, "advisories": list(route.get("advisories") or []),
              "eligible_ands": bool(route.get("ands_content_model")),
              "checks": {}}
    if not route.get("valid"):
        result["eligible_ands"] = False
        return result

    crp = answers.get("crp")
    if crp:
        crp_errors = validate_crp(crp)
        equiv = check_pharmaceutical_equivalence(crp, answers.get("generic"))
        result["checks"]["crp"] = {"errors": crp_errors,
                                   "pharmaceutical_equivalence": equiv,
                                   "ok": not crp_errors and not equiv}
        if equiv:
            result["advisories"].append({
                "rule": "not_pharmaceutically_equivalent",
                "message": "The proposed generic is not pharmaceutically "
                           "equivalent to the Canadian Reference Product — an "
                           "ANDS requires the same medicinal ingredient(s) in a "
                           "comparable dosage form."})
            result["eligible_ands"] = False

    study = answers.get("be_study")
    dosage_form_class = _s(answers.get("dosage_form_class"))
    if dosage_form_class:
        ce = comparative_evidence_route(dosage_form_class)
        result["checks"]["comparative_evidence"] = ce
        if not ce["requires_be_study"]:
            # steer the filer to the biowaiver / non-PK evidence route so they do
            # NOT needlessly run an in-vivo study Health Canada may waive
            result["advisories"].append({
                "rule": "comparative_evidence_biowaiver",
                "message": f"{ce['label']}: {ce['evidence']} ({ce['citation']})"})

    if study is not None or dosage_form_class:
        be = evaluate_bioequivalence(
            study or {}, _s(answers.get("submission_date")), dosage_form_class)
        result["checks"]["bioequivalence"] = be
        if study is not None and not be["bioequivalent"]:
            result["advisories"].append({
                "rule": "bioequivalence_failed",
                "message": f"The bioequivalence study does not meet the "
                           f"{be['ruleset']['label']} acceptance limits — the "
                           "ANDS cannot rely on it as filed."})
    return result
