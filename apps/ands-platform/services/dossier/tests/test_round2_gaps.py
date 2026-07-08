"""Round-2 swarm gaps (measure -> fix -> RE-measure caught these).

 * MATERIAL: a biosimilar (out-of-core product class) filed as ANDS still built
   the generic comparative-BE pathway (cs_be_only, comparative_evidence pk_be,
   5.3.1/1.6 required) — contradicting HC (biosimilar = NDS + comparability, NO
   BE claims) AND the tool's own honest product_class scope note.  [r2 #1]
 * MAJOR (a regression from batch 1): a SANDS Module-3 tower rolled up to 'na'
   because required_total==0 (M3 is now change-scoped/conditional), rendering
   the change-locus module as "N/A".  [r2 #2]
"""

from app import section_tree
from app import dossier_state


def _tree(product_class="small_molecule", **kw):
    # content_state derives product_in_scope from the product class
    return section_tree.section_tree(
        product_in_scope=(product_class == "small_molecule"), **kw)


def _node(tree, section):
    return next(n for m in tree["modules"] for n in m["nodes"]
               if n["section"] == section)


# -- biosimilar (out-of-core) must not build the generic BE pathway ----------
def test_biosimilar_ands_does_not_require_the_be_artifacts():
    t = _tree(submission_type="ANDS", product_class="biosimilar")
    assert t["comparative_evidence"] is None
    assert _node(t, "5.3.1")["applicability"] == "na"
    assert _node(t, "1.6")["applicability"] == "na"


def test_small_molecule_ands_still_requires_the_be_artifacts():
    t = _tree(submission_type="ANDS", product_class="small_molecule")
    assert t["comparative_evidence"] is not None
    assert _node(t, "5.3.1")["applicability"] == "required"


# -- tower distinguishes 'conditional/in-scope' from genuinely 'na' ----------
def test_sands_module3_tower_is_not_na():
    t = _tree(submission_type="SANDS")
    tower = dossier_state.tower_view(cs_be_only=False, states={},
                                     submission_type="SANDS")
    m3 = next(x for x in tower if x["module"] == "3")
    m4 = next(x for x in tower if x["module"] == "4")
    assert m3["state"] != "na"          # M3 is the change locus (conditional CMC)
    assert m4["state"] == "na"          # M4 genuinely inapplicable to a generic


def test_ands_module4_still_na():
    tower = dossier_state.tower_view(cs_be_only=True, states={},
                                     submission_type="ANDS")
    m4 = next(x for x in tower if x["module"] == "4")
    assert m4["state"] == "na"


# -- gap 3: gate.missing lists eCTD section 1.2.2 at most once ----------------
def test_fee_reminder_does_not_collide_with_the_122_document(client):
    client.post("/api/dossier/dossiers", json={"dossier_id": "e930401",
                "title": "t", "submission_type": "ANDS"})
    gate = client.get("/api/dossier/dossiers/e930401/content").json()["gate"]
    secs = [m["section"] for m in gate["missing"]]
    assert secs.count("1.2.2") <= 1           # the DOCUMENT gap, once
    assert "fee_payment" in secs              # the fee reminder is distinct


# -- gap 4: 5.3.5 guidance reflects the topical comparative-clinical arm ------
def test_topical_535_guidance_mentions_the_clinical_endpoint():
    n = _node(_tree(submission_type="ANDS", dosage_form_class="topical_local"), "5.3.5")
    assert "clinical" in n["guidance"].lower() and "does not repeat" not in n["guidance"].lower()
