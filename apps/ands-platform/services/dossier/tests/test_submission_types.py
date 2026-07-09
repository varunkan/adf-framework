"""Submission-type-aware content model (comprehensive drug-type testing).

The bug this locks down: every submission type (NDS, ANDS, SANDS, SNDS, DIN)
was emitting the IDENTICAL generic-ANDS content plan — Module 4 marked N/A,
plus the GENERIC-ONLY artifacts (Form V 1.2.4, CS-BE 1.6, comparative-BE study
report 5.3.1) forced 'required'. That is regulatorily wrong:

  * an innovator NDS MUST file Module 4 (nonclinical) + the full clinical /
    nonclinical summaries (2.4-2.7), and does NOT file a Form V or a
    comparative-bioequivalence study;
  * a brand supplement (SNDS) and a DIN application do NOT file Form V / CS-BE.

Applicability values: required | optional | conditional | suppressed | na.
"""

from app import section_tree


def _ap(sub, section, cs_be=True):
    n = section_tree.node_for(section, cs_be_only=cs_be, submission_type=sub)
    assert n is not None, f"{section} missing for {sub}"
    return n["applicability"]


# -- ANDS (generic — the tool's core) unchanged -----------------------------
def test_ands_requires_generic_artifacts_and_na_module4():
    assert _ap("ANDS", "1.2.4") == "required"   # Form V declaration
    assert _ap("ANDS", "1.6") == "required"     # CS-BE
    assert _ap("ANDS", "5.3.1") == "required"   # comparative-BE study report
    assert _ap("ANDS", "4") == "na"             # no nonclinical for a generic
    assert _ap("ANDS", "2.4") == "suppressed"   # nonclinical overview suppressed
    assert _ap("ANDS", "2.3") == "required"     # QOS always required


# -- NDS (innovator — the superset) -----------------------------------------
def test_nds_requires_nonclinical_and_clinical_not_generic_artifacts():
    # generic-only artifacts must NOT be required for an innovator
    assert _ap("NDS", "1.2.4", cs_be=False) == "na"   # Form V is generic-only
    assert _ap("NDS", "1.6", cs_be=False) == "na"     # CS-BE is generic-only
    assert _ap("NDS", "5.3.1", cs_be=False) == "na"   # comparative-BE is generic-only
    # innovator MUST file the nonclinical + clinical dossier
    assert _ap("NDS", "4", cs_be=False) == "required"   # Module 4 nonclinical
    assert _ap("NDS", "2.4", cs_be=False) == "required" # nonclinical overview
    assert _ap("NDS", "2.5", cs_be=False) == "required" # clinical overview
    assert _ap("NDS", "2.6", cs_be=False) == "required"
    assert _ap("NDS", "2.7", cs_be=False) == "required" # clinical summary
    assert _ap("NDS", "2.3", cs_be=False) == "required" # full QOS
    assert _ap("NDS", "3.2.P.8", cs_be=False) == "required"  # full CMC
    assert _ap("NDS", "4.2", cs_be=False) == "required"   # nonclinical study reports
    assert _ap("NDS", "5.3.5", cs_be=False) == "required" # controlled clinical trials


def test_generic_never_files_innovator_clinical_trials():
    # a generic ANDS demonstrates comparative BE (5.3.1), never controlled trials
    assert _ap("ANDS", "5.3.5") == "na"
    assert _ap("ANDS", "4.2") == "na"
    assert _ap("SANDS", "5.3.5", cs_be=True) == "na"
    assert _ap("DIN", "5.3.5", cs_be=False) == "na"


# -- SNDS (brand supplement) -------------------------------------------------
def test_snds_no_generic_artifacts_no_module4():
    for sec in ("1.2.4", "1.6", "5.3.1"):
        assert _ap("SNDS", sec, cs_be=False) == "na", sec
    assert _ap("SNDS", "4", cs_be=False) == "na"


# -- SANDS (generic supplement) ---------------------------------------------
def test_sands_generic_artifacts_conditional_not_forced():
    # a generic supplement may or may not touch patents / bioequivalence —
    # never FORCE them required, never wrongly mark them applicable-required
    for sec in ("1.2.4", "1.6"):
        assert _ap("SANDS", sec, cs_be=True) in ("conditional", "optional", "na"), sec
    assert _ap("SANDS", "4", cs_be=True) == "na"


# -- DIN application (DINA — a light submission) -----------------------------
def test_din_is_light_no_generic_artifacts_no_clinical():
    for sec in ("1.2.4", "1.6", "5.3.1"):
        assert _ap("DIN", sec, cs_be=False) == "na", sec
    assert _ap("DIN", "4", cs_be=False) == "na"
    # a DIN application does not carry the full generic CMC/BE dossier as required
    assert _ap("DIN", "3.2.P.8", cs_be=False) in ("optional", "conditional", "na")
    # M1 admin stays required; but the Product Monograph (1.3.1) is NOT part of a
    # DIN — a DIN bears no NOC (PM is for NDS/SNDS/ANDS/SANDS) -> na. Labelling
    # (1.3.3) stays required: the label is the DIN's product-info vehicle. [r6]
    assert _ap("DIN", "1.0", cs_be=False) == "required"
    assert _ap("DIN", "1.3.1", cs_be=False) == "na"
    assert _ap("DIN", "1.3.3", cs_be=False) == "required"


# -- the tree carries an honest scope note for non-ANDS types ---------------
def test_tree_declares_scope_for_non_ands_types():
    ands = section_tree.section_tree(submission_type="ANDS")
    assert ands.get("submission_type") == "ANDS"
    assert not ands.get("scope_note")   # ANDS is fully supported — no caveat
    for sub in ("NDS", "SNDS", "DIN"):
        tree = section_tree.section_tree(submission_type=sub, cs_be_only=False)
        assert tree.get("submission_type") == sub
        assert tree.get("scope_note"), f"{sub} must carry an honest scope note"
        assert "ANDS" in tree["scope_note"]


# -- no submission type ever forces a GENERIC-ONLY artifact required unless generic
def test_generic_only_artifacts_never_required_for_brand_or_din():
    for sub in ("NDS", "SNDS", "DIN"):
        for sec in ("1.2.4", "1.6", "5.3.1"):
            assert _ap(sub, sec, cs_be=False) != "required", (sub, sec)
