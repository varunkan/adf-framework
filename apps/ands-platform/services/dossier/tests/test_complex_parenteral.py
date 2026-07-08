"""Complex parenteral must NOT get the simple aqueous-solution biowaiver (swarm).

MATERIAL_ERROR: a long-acting injectable / microsphere / liposome / depot is a
COMPLEX generic — it needs product-specific comparative evidence (comparative PK
+ physicochemical/in-vitro characterisation, often comparative clinical), not the
in-vivo BE waiver HC allows for a simple parenteral aqueous solution. The tool
routed every parenteral to parenteral_biowaiver, understating the evidence.
[gaps 6, 22]
"""

from app import comparative_evidence as ce


def test_simple_parenteral_still_gets_the_biowaiver():
    r = ce.route("parenteral_solution")
    assert r["route"] == "parenteral_biowaiver" and r["requires_be_study"] is False


def test_complex_parenteral_is_not_a_biowaiver():
    r = ce.route("complex_parenteral")
    assert r["requires_be_study"] is True            # never a waiver
    assert "biowaiver" not in r["route"]
    assert "complex" in (r["route"] + r["label"] + r["evidence"]).lower()
    assert r["citation"]


def test_complex_parenteral_is_an_offered_dosage_form():
    assert any(v == "complex_parenteral" for v, _ in ce.DOSAGE_FORMS)
