"""
ANDS Submission Portal — Canadian Reference Product, BE acceptance ruleset, and
the CS-BE (Comparative Studies — Bioequivalence) builder.

This ADDITIVE slice sits alongside the intake (``domain.py``), REP (``rep.py``),
eCTD-assembly (``ectd.py``) and validation (``validation.py``) modules. It is the
"CRP & Bioequivalence Builder" half of the portal:

  REQ-007  Capture the Canadian Reference Product with STRUCTURED CRP fields
           (brand name, DIN, strength, dosage form, innovator/manufacturer),
           provide a foreign-CRP justification path, and validate that the
           proposed generic is pharmaceutically equivalent (identical medicinal
           ingredient(s) in a comparable dosage form).
  REQ-008  A CS-BE builder for a BE-only ANDS that places the CS-BE electronic
           copy in Module 1.6, links full pivotal study reports into Module
           5.3.1.2, and does NOT generate a Module 2.7.1 (2.4-2.7 suppressed);
           it captures AUC and Cmax results, branches Cmax acceptance by the
           applicable BE ruleset version, and carries a DRAFT-status flag (the
           CS-BE template + comparative-BA CTD guidance are DRAFT, 2004-05-18).
  REQ-063  VERSION the bioequivalence acceptance ruleset by submission date and
           dosage-form class and branch Cmax validation: point-estimate
           (relative mean) within 80.0-125.0% for legacy/pre-ICH-M13A or non-IR
           products, versus the full 90% confidence interval within
           80.00-125.00% under ICH M13A (effective 2025-12-27, IR solid oral).
           It does NOT hardcode a single Cmax rule.

Pure, dependency-free (Python 3 standard library only) and deterministic.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _xml_escape


# ---------------------------------------------------------------------------
# REQ-008 — CTD placement constants for the CS-BE path
# ---------------------------------------------------------------------------

CS_BE_MODULE = "1.6"                      # CS-BE electronic copy lives in M1.6
CS_BE_LEAF = "m1-6-cs-be"                 # heading 1.6 (see ectd placement table)
PIVOTAL_REPORT_MODULE = "5.3.1.2"        # full pivotal BE study reports
# A BE-only ANDS suppresses Modules 2.4-2.7 (the CS-BE replaces them); emitting a
# 2.7.1 while suppressing 2.4-2.7 is non-conformant, so it is NEVER generated.
SUPPRESSED_MODULES = ("2.4", "2.5", "2.6", "2.7", "2.7.1")

# CS-BE template + comparative-BA CTD guidance are DRAFT, dated 2004-05-18.
CS_BE_DRAFT = True
CS_BE_DRAFT_DATE = "2004-05-18"


# ---------------------------------------------------------------------------
# REQ-063 — versioned BE acceptance ruleset (Cmax branch)
# ---------------------------------------------------------------------------

# ICH M13A becomes effective at HC for IR solid-oral generics on this date.
M13A_EFFECTIVE_DATE = "2025-12-27"

# Dosage-form classes the BE ruleset branches on. Only IR solid-oral products
# filed on/after the M13A effective date take the M13A (90% CI) Cmax rule; every
# other class (and any pre-M13A filing) takes the legacy point-estimate rule.
IR_SOLID_ORAL = "ir_solid_oral"
DOSAGE_FORM_CLASSES = {
    IR_SOLID_ORAL: "Immediate-release solid oral",
    "mr_solid_oral": "Modified-release solid oral",
    "non_ir": "Non-immediate-release / other",
    "other": "Other dosage form",
}

# The two published BE acceptance rulesets. ``cmax_rule`` is the BRANCH point:
#   point_estimate -> Cmax relative-mean point estimate within 80.0-125.0%
#                     (NO 90% CI required for Cmax)
#   ci90           -> Cmax full 90% confidence interval within 80.00-125.00%
# AUC is always assessed by its 90% CI within the ruleset bounds.
BE_RULESETS = {
    "legacy": {
        "version": "legacy",
        "label": "Pre-ICH-M13A / non-IR (point-estimate Cmax)",
        "cmax_rule": "point_estimate",
        "lower": 80.0,
        "upper": 125.0,
        "decimals": 1,
    },
    "M13A": {
        "version": "M13A",
        "label": "ICH M13A (IR solid oral, full 90% CI Cmax)",
        "cmax_rule": "ci90",
        "lower": 80.00,
        "upper": 125.00,
        "decimals": 2,
        "effective": M13A_EFFECTIVE_DATE,
    },
}


def _norm(value) -> str:
    return str(value if value is not None else "").strip()


def is_ir_solid_oral(dosage_form_class: str) -> bool:
    """REQ-063: only IR solid-oral products take the M13A Cmax branch."""
    return _norm(dosage_form_class) == IR_SOLID_ORAL


def resolve_be_ruleset(submission_date: str, dosage_form_class: str) -> dict:
    """REQ-063: select the Cmax ruleset by submission date AND dosage-form class.

    Returns the ruleset descriptor (a copy of ``BE_RULESETS[...]``). The M13A
    (full 90% CI) rule applies ONLY to an IR solid-oral product filed on/after
    ``M13A_EFFECTIVE_DATE``; every legacy/pre-M13A or non-IR product takes the
    point-estimate rule. The single Cmax rule is never hardcoded.
    """
    submission_date = _norm(submission_date)
    if (is_ir_solid_oral(dosage_form_class)
            and submission_date
            and submission_date >= M13A_EFFECTIVE_DATE):
        rs = dict(BE_RULESETS["M13A"])
    else:
        rs = dict(BE_RULESETS["legacy"])
    rs["submission_date"] = submission_date
    rs["dosage_form_class"] = _norm(dosage_form_class)
    return rs


def list_be_rulesets() -> list:
    """REQ-063: every published BE acceptance ruleset (for the UI / API)."""
    return [dict(BE_RULESETS[v]) for v in ("M13A", "legacy")]


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _within(value, lower, upper) -> bool:
    return value is not None and lower <= value <= upper


def validate_auc(auc: dict, ruleset: dict) -> list:
    """AUC is always assessed by its 90% CI within the ruleset bounds.

    ``auc`` carries ``ci_lower`` / ``ci_upper`` (percent of reference). Returns a
    list of ``{"rule","message"}`` (empty == within limits).
    """
    out = []
    lower, upper = ruleset["lower"], ruleset["upper"]
    cl = _to_float((auc or {}).get("ci_lower"))
    cu = _to_float((auc or {}).get("ci_upper"))
    if cl is None or cu is None:
        out.append({"rule": "auc_ci_required",
                    "message": "AUC 90% confidence interval (ci_lower/ci_upper) "
                               "is required"})
        return out
    if not (_within(cl, lower, upper) and _within(cu, lower, upper)):
        out.append({"rule": "auc_ci_out_of_range",
                    "message": (f"AUC 90% CI {cl:g}-{cu:g}% is outside the "
                                f"acceptance limits {lower:g}-{upper:g}%")})
    return out


def validate_cmax(cmax: dict, ruleset: dict) -> list:
    """REQ-008/063: branch Cmax acceptance by the resolved ruleset.

    Under the legacy/non-IR rule the Cmax POINT ESTIMATE (relative mean) must be
    within 80.0-125.0% and no 90% CI is required. Under ICH M13A the full 90% CI
    must be within 80.00-125.00%. Returns ``{"rule","message"}`` findings.
    """
    out = []
    lower, upper = ruleset["lower"], ruleset["upper"]
    cmax = cmax or {}
    if ruleset["cmax_rule"] == "ci90":
        cl = _to_float(cmax.get("ci_lower"))
        cu = _to_float(cmax.get("ci_upper"))
        if cl is None or cu is None:
            out.append({"rule": "cmax_ci_required",
                        "message": "ICH M13A requires the full Cmax 90% CI "
                                   "(ci_lower/ci_upper) for an IR solid-oral "
                                   "product filed on/after " + M13A_EFFECTIVE_DATE})
            return out
        if not (_within(cl, lower, upper) and _within(cu, lower, upper)):
            out.append({"rule": "cmax_ci_out_of_range",
                        "message": (f"Cmax 90% CI {cl:g}-{cu:g}% is outside the "
                                    f"ICH M13A acceptance limits "
                                    f"{lower:.2f}-{upper:.2f}%")})
    else:  # point_estimate
        pe = _to_float(cmax.get("point_estimate"))
        if pe is None:
            out.append({"rule": "cmax_point_estimate_required",
                        "message": "The Cmax point estimate (relative mean) is "
                                   "required for a legacy/non-IR product"})
            return out
        if not _within(pe, lower, upper):
            out.append({"rule": "cmax_point_estimate_out_of_range",
                        "message": (f"Cmax point estimate {pe:g}% is outside the "
                                    f"acceptance limits {lower:g}-{upper:g}%")})
    return out


def evaluate_bioequivalence(study: dict, submission_date: str,
                            dosage_form_class: str) -> dict:
    """REQ-008/063: evaluate a BE study's AUC + Cmax against the resolved ruleset.

    Returns ``{ruleset, findings, bioequivalent}`` where ``bioequivalent`` is
    True only when both AUC and Cmax pass the applicable limits.
    """
    ruleset = resolve_be_ruleset(submission_date, dosage_form_class)
    study = study or {}
    findings = []
    findings.extend(validate_auc(study.get("auc"), ruleset))
    findings.extend(validate_cmax(study.get("cmax"), ruleset))
    return {
        "ruleset": ruleset,
        "findings": findings,
        "bioequivalent": not findings,
        "cmax_rule": ruleset["cmax_rule"],
    }


# ---------------------------------------------------------------------------
# REQ-007 — Canadian Reference Product + pharmaceutical equivalence
# ---------------------------------------------------------------------------

# Structured CRP fields HC requires (C.08.001.1 / C.08.002.1).
CRP_FIELDS = {
    "brand_name": "Brand name",
    "din": "DIN",
    "strength": "Strength",
    "dosage_form": "Dosage form",
    "innovator": "Innovator / manufacturer",
}

# Dosage forms treated as COMPARABLE for pharmaceutical equivalence. Each group
# is a set of interchangeable presentations (e.g. tablet ~ caplet); a generic in
# the same group as the CRP is "comparable dosage form".
_COMPARABLE_FORMS = (
    {"tablet", "caplet", "film-coated tablet", "coated tablet"},
    {"capsule", "hard capsule", "soft capsule", "softgel"},
    {"oral solution", "solution", "syrup", "oral liquid"},
    {"suspension", "oral suspension"},
)


def _form_group(form: str):
    f = _norm(form).lower()
    for grp in _COMPARABLE_FORMS:
        if f in grp:
            return grp
    return None


def is_comparable_dosage_form(a: str, b: str) -> bool:
    """REQ-007: two dosage forms are comparable if identical or in one group."""
    a_n, b_n = _norm(a).lower(), _norm(b).lower()
    if not a_n or not b_n:
        return False
    if a_n == b_n:
        return True
    ga, gb = _form_group(a_n), _form_group(b_n)
    return ga is not None and ga is gb


def _ingredients(value) -> list:
    """Normalise a medicinal-ingredient list/string into a comparable set."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
    else:
        parts = [str(p).strip() for p in value]
    return sorted({p.lower() for p in parts if p})


def validate_crp(data: dict) -> list:
    """REQ-007: required structured CRP fields + the foreign-CRP justification.

    Returns ``{"rule","message"}`` per failure (empty == complete). A foreign
    reference product (``foreign`` truthy) additionally requires a
    ``foreign_justification`` record.
    """
    out = []

    def add(rule, message):
        out.append({"rule": rule, "message": message})

    for field, label in CRP_FIELDS.items():
        if not _norm((data or {}).get(field)):
            add(f"crp_{field}_required", f"{label} is required for the CRP")

    if (data or {}).get("foreign"):
        if not _norm(data.get("foreign_justification")):
            add("foreign_crp_justification_required",
                "A foreign Canadian Reference Product requires a justification "
                "record per the foreign-CRP path")
    return out


def check_pharmaceutical_equivalence(crp: dict, generic: dict) -> list:
    """REQ-007: the proposed generic must be pharmaceutically equivalent to the
    CRP — identical medicinal ingredient(s) in a comparable dosage form.

    Returns ``{"rule","message"}`` defects (empty == equivalent).
    """
    out = []
    crp = crp or {}
    generic = generic or {}

    crp_ing = _ingredients(crp.get("medicinal_ingredients"))
    gen_ing = _ingredients(generic.get("medicinal_ingredients"))
    if crp_ing and gen_ing and crp_ing != gen_ing:
        out.append({
            "rule": "pharmaceutical_equivalence_ingredient",
            "message": (f"Medicinal ingredient(s) differ — CRP has "
                        f"{', '.join(crp_ing)}; generic has "
                        f"{', '.join(gen_ing)}"),
        })

    crp_form = crp.get("dosage_form")
    gen_form = generic.get("dosage_form")
    if _norm(crp_form) and _norm(gen_form) and \
            not is_comparable_dosage_form(crp_form, gen_form):
        out.append({
            "rule": "pharmaceutical_equivalence_dosage_form",
            "message": (f"Dosage form '{_norm(gen_form)}' is not comparable to "
                        f"the CRP dosage form '{_norm(crp_form)}'"),
        })
    return out


def assemble_crp(data: dict) -> dict:
    """REQ-007: validate + record a CRP entry with its equivalence verdict.

    ``data`` carries the structured CRP fields, an optional ``foreign`` flag +
    ``foreign_justification``, the CRP ``medicinal_ingredients``, and a nested
    ``generic`` (with its own ``medicinal_ingredients`` / ``dosage_form``).
    Returns ``{"valid", "errors", "crp"}``. ``valid`` is False when required
    fields are missing OR a pharmaceutical-equivalence defect is found.
    """
    errors = validate_crp(data)
    equivalence = check_pharmaceutical_equivalence(data, (data or {}).get("generic"))
    errors = errors + equivalence
    if errors:
        return {"valid": False, "errors": errors, "crp": None}

    crp = {field: _norm(data.get(field)) for field in CRP_FIELDS}
    crp["foreign"] = bool(data.get("foreign"))
    crp["foreign_justification"] = _norm(data.get("foreign_justification"))
    crp["medicinal_ingredients"] = _ingredients(data.get("medicinal_ingredients"))
    crp["pharmaceutically_equivalent"] = True
    return {"valid": True, "errors": [], "crp": crp}


# ---------------------------------------------------------------------------
# REQ-008 — the CS-BE builder
# ---------------------------------------------------------------------------

def build_cs_be(data: dict) -> dict:
    """REQ-008: build the CS-BE evidence for a BE-only ANDS.

    Places the CS-BE electronic copy in Module 1.6, links the full pivotal study
    reports into Module 5.3.1.2, and explicitly does NOT generate a Module 2.7.1
    (Modules 2.4-2.7 suppressed). Captures AUC + Cmax and branches the Cmax
    acceptance rule by the resolved BE ruleset version. Carries the DRAFT-status
    flag.

    Returns ``{"valid", "errors", "cs_be"}``. ``valid`` is False on any BE
    acceptance-limit failure.
    """
    data = data or {}
    submission_date = _norm(data.get("submission_date"))
    dosage_form_class = _norm(data.get("dosage_form_class"))
    study = {"auc": data.get("auc"), "cmax": data.get("cmax")}

    evaluation = evaluate_bioequivalence(study, submission_date, dosage_form_class)

    pivotal_reports = []
    for rep_report in (data.get("pivotal_reports") or []):
        title = _norm(rep_report.get("title") if isinstance(rep_report, dict)
                      else rep_report)
        report_id = _norm(rep_report.get("id") if isinstance(rep_report, dict)
                          else "")
        pivotal_reports.append({
            "id": report_id,
            "title": title,
            "module": PIVOTAL_REPORT_MODULE,
            "leaf_id": f"m5-3-1-2-{report_id or 'be-study'}",
        })

    cs_be = {
        "draft": CS_BE_DRAFT,
        "draft_date": CS_BE_DRAFT_DATE,
        "draft_notice": ("CS-BE template and comparative-BA CTD guidance are "
                         f"DRAFT (dated {CS_BE_DRAFT_DATE}); this path adapts "
                         "when the guidance is finalized"),
        "electronic_copy": {
            "module": CS_BE_MODULE,
            "leaf_id": CS_BE_LEAF,
            "title": "Comparative Studies — Bioequivalence (CS-BE)",
        },
        "pivotal_reports": pivotal_reports,
        # 2.7.1 is NEVER produced on the CS-BE path; 2.4-2.7 are suppressed.
        "generates_2_7_1": False,
        "suppressed_modules": list(SUPPRESSED_MODULES),
        "auc": data.get("auc"),
        "cmax": data.get("cmax"),
        "ruleset": evaluation["ruleset"],
        "cmax_rule": evaluation["cmax_rule"],
        "bioequivalent": evaluation["bioequivalent"],
    }
    errors = list(evaluation["findings"])
    return {"valid": not errors, "errors": errors, "cs_be": cs_be}


def build_cs_be_leaf_xml(cs_be: dict) -> str:
    """REQ-008: a small CS-BE descriptor XML for the Module 1.6 electronic copy."""
    rs = cs_be.get("ruleset") or {}
    reports = "".join(
        f"    <pivotal-report module=\"{_xml_escape(r['module'])}\" "
        f"leaf=\"{_xml_escape(r['leaf_id'])}\">{_xml_escape(r['title'])}"
        "</pivotal-report>\n"
        for r in (cs_be.get("pivotal_reports") or [])
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<cs-be module="{CS_BE_MODULE}" draft="{str(CS_BE_DRAFT).lower()}" '
        f'draft-date="{CS_BE_DRAFT_DATE}">\n'
        f'  <generates-2-7-1>false</generates-2-7-1>\n'
        f'  <be-ruleset version="{_xml_escape(rs.get("version", ""))}" '
        f'cmax-rule="{_xml_escape(rs.get("cmax_rule", ""))}"/>\n'
        '  <pivotal-reports>\n'
        f"{reports}"
        '  </pivotal-reports>\n'
        '</cs-be>\n'
    )
