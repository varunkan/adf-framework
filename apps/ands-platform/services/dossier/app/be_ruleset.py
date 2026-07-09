"""Bioequivalence ruleset resolution (ICH M13A vs legacy) — dossier-side copy.

swarm r7 (e970001): the dossier CS-BE scaffold guidance hedged "ICH-M13A or
legacy" with no date resolution, so a post-cutover IR-solid-oral ANDS was left to
guess. ICH M13A is in force in Canada (effective 2025-12-27): a BE study for an
immediate-release solid oral dosage form filed on/after that date must comply with
M13A (full 90% CI on Cmax, 80.00-125.00%). Before the cutover, or for other
dosage forms, the legacy standard applies. Mirrors journey.drug_intake.resolve_be_ruleset
(each service owns its copy of the HC boundary). Pure, stdlib-only.

Web-verified vs canada.ca: "Notice — Implementation of ICH M13A bioequivalence for
immediate-release solid oral dosage forms" (effective 2025-12-27).
"""

from __future__ import annotations

M13A_EFFECTIVE_DATE = "2025-12-27"
IR_SOLID_ORAL = "ir_solid_oral"

_RULESETS = {
    "legacy": {"version": "legacy", "cmax_rule": "point_estimate",
               "lower": 80.0, "upper": 125.0, "decimals": 1,
               "label": "Pre-ICH-M13A / non-IR (point-estimate Cmax)",
               "effective": M13A_EFFECTIVE_DATE},
    "M13A": {"version": "M13A", "cmax_rule": "ci90",
             "lower": 80.00, "upper": 125.00, "decimals": 2,
             "effective": M13A_EFFECTIVE_DATE,
             "label": "ICH M13A (IR solid oral, full 90% CI Cmax)"},
}


def resolve(as_of: str, dosage_form_class: str) -> dict:
    """The BE ruleset for a filing prepared ``as_of`` (ISO date) for the given
    dosage form. M13A for an IR solid oral filed on/after the 2025-12-27 cutover;
    legacy otherwise. ``legacy_excluded`` is True when M13A unambiguously governs."""
    as_of = str(as_of or "").strip()
    is_m13a = (str(dosage_form_class or "") == IR_SOLID_ORAL
               and as_of and as_of >= M13A_EFFECTIVE_DATE)
    rs = dict(_RULESETS["M13A"] if is_m13a else _RULESETS["legacy"])
    rs["as_of"] = as_of
    rs["dosage_form_class"] = str(dosage_form_class or "")
    rs["legacy_excluded"] = bool(is_m13a)
    return rs
