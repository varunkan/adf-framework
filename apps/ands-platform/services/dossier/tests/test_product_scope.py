"""Dossier product-class honest scope note (Tier B).

The dossier records the product class chosen at creation and surfaces an honest
scope note on content_state when the class is outside ANDS Studio's core generic
chemical-drug authoring — so the builder plainly says 'this is a biologic /
disinfectant / etc.; the eCTD shell is correct but the science is authored to
that regime', rather than presenting the generic model as if it fit.
"""

from app import product_scope as ps


def test_small_molecule_has_no_note():
    assert ps.note("small_molecule") is None
    assert ps.note("") is None            # default = the in-core chemical drug


def test_biosimilar_note_is_honest_about_nds_not_ands():
    n = ps.note("biosimilar")
    assert n and "biosimilar" in n.lower()
    assert "NDS" in n


def test_disinfectant_note_points_to_nnhpd():
    n = ps.note("disinfectant")
    assert n and "NNHPD" in n


def test_unknown_class_gets_a_conservative_note():
    assert ps.note("frobnicator")   # not None — honest 'we don't model this'
