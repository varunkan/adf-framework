"""Dosage-form-aware comparative evidence (Tier A gap fix).

The gap: the content model always forced the comparative-BE study (5.3.1) and
CS-BE summary (1.6) 'required' for a generic, regardless of dosage form — so it
told an injectable-solution or ophthalmic generic to run a bioequivalence study
Health Canada may WAIVE, and had no route for orally-inhaled or topical forms.

Health Canada comparative-evidence routes by dosage form:
  * IR/MR solid oral, orally inhaled  -> a comparative PK study IS required
  * parenteral / oral / ophthalmic-otic aqueous solutions -> a biowaiver may
    apply (no in-vivo BE study) — CONDITIONAL, the filer confirms the route
  * topical / locally-acting -> comparative clinical or in-vitro, not PK BE —
    CONDITIONAL (the 5.3.1 PK study is not the evidence type)
"""

from app import comparative_evidence as ce
from app import section_tree


# -- the pure route model ----------------------------------------------------
def test_solid_oral_and_inhaled_require_a_pk_study():
    for df in ("ir_solid_oral", "mr_solid_oral", "orally_inhaled", "other"):
        assert ce.be_study_applicability(df) == "required", df
        assert ce.route(df)["requires_be_study"] is True, df


def test_solutions_and_topical_do_not_force_a_pk_study():
    for df in ("parenteral_solution", "oral_solution",
               "ophthalmic_otic_solution", "topical_local"):
        assert ce.be_study_applicability(df) == "conditional", df
        assert ce.route(df)["requires_be_study"] is False, df


def test_route_carries_an_hc_citation_and_plain_evidence_note():
    r = ce.route("parenteral_solution")
    assert "biowaiver" in r["route"]
    assert r["citation"] and r["evidence"]
    assert "Generic Parenteral" in r["citation"] or "parenteral" in r["citation"].lower()
    oip = ce.route("orally_inhaled")
    assert "inhal" in oip["evidence"].lower() or "inhal" in oip["route"].lower()
    top = ce.route("topical_local")
    assert top["requires_be_study"] is False
    assert "clinical" in top["evidence"].lower() or "in-vitro" in top["evidence"].lower()


def test_unknown_dosage_form_is_conservative_required():
    assert ce.be_study_applicability("") == "required"
    assert ce.be_study_applicability("banana") == "required"


# -- the content model uses it (5.3.1 + 1.6 conditional on dosage form) -------
def _ap(section, *, sub="ANDS", cs=True, df="ir_solid_oral"):
    n = section_tree.node_for(section, cs_be_only=cs, submission_type=sub,
                              dosage_form_class=df)
    return n["applicability"] if n else None


def test_ir_solid_oral_ands_still_requires_be_study_and_csbe():
    assert _ap("5.3.1", df="ir_solid_oral") == "required"
    assert _ap("1.6", df="ir_solid_oral") == "required"


def test_parenteral_ands_marks_be_study_conditional_not_required():
    # the crux: an injectable-solution generic must NOT be forced to file a BE study
    assert _ap("5.3.1", df="parenteral_solution") == "conditional"
    assert _ap("1.6", df="parenteral_solution") == "conditional"


def test_topical_ands_does_not_force_the_pk_study():
    assert _ap("5.3.1", df="topical_local") == "conditional"


def test_dosage_form_never_makes_a_brand_file_generic_artifacts():
    # an NDS never files 5.3.1/1.6 regardless of dosage form (generic-only)
    for df in ("ir_solid_oral", "parenteral_solution", "topical_local"):
        assert _ap("5.3.1", sub="NDS", cs=False, df=df) == "na", df
        assert _ap("1.6", sub="NDS", cs=False, df=df) == "na", df
