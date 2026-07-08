"""Round-3 swarm gaps — the deeper biosimilar/product_class inconsistencies.

 * MATERIAL [2/3]: a biosimilar (out-of-core product class) filed as ANDS was
   charged the ANDS fee and exported as ANDS — a biosimilar CANNOT be an ANDS
   (HC: it files a full NDS/SNDS). Fix: reject the contradictory combination at
   create so the wrong-pathway dossier never exists.
 * MATERIAL/MAJOR [1/7]: no way to correct a dossier's classification
   (product_class / submission_type / controlled_substance / special_pathways)
   after create — a restored stale dossier was trapped on the wrong pathway.
   Fix: a reclassify endpoint.
"""

_P = "/api/dossier"


# -- R3-1: a biosimilar/biologic cannot be a generic ANDS/SANDS ---------------
def test_biosimilar_ands_is_rejected_at_create(client):
    r = client.post(f"{_P}/dossiers", json={"dossier_id": "e932001",
                    "title": "bio", "submission_type": "ANDS",
                    "product_class": "biosimilar"})
    assert r.status_code == 422
    body = r.json()
    assert "NDS" in (body.get("detail", "") + body.get("title", ""))


def test_biosimilar_as_nds_is_allowed(client):
    r = client.post(f"{_P}/dossiers", json={"dossier_id": "e932002",
                    "title": "bio", "submission_type": "NDS",
                    "product_class": "biosimilar"})
    assert r.status_code in (200, 201)


def test_small_molecule_ands_still_allowed(client):
    r = client.post(f"{_P}/dossiers", json={"dossier_id": "e932003",
                    "title": "gen", "submission_type": "ANDS",
                    "product_class": "small_molecule"})
    assert r.status_code in (200, 201)


# -- R3-2: reclassify an existing dossier ------------------------------------
def test_reclassify_corrects_product_class_and_flags(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e932010", "title": "d",
                "submission_type": "ANDS", "product_class": "small_molecule"})
    r = client.post(f"{_P}/dossiers/e932010/reclassify",
                    json={"product_class": "small_molecule",
                          "controlled_substance": True,
                          "special_pathways": ["priority_review"]})
    assert r.status_code == 200
    st = client.get(f"{_P}/dossiers/e932010/content").json()
    assert st["controlled_substance"] is True
    assert any(p["id"] == "priority_review" for p in st["special_pathways"])


def test_reclassify_rejects_contradictory_combo(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e932011", "title": "d",
                "submission_type": "ANDS", "product_class": "small_molecule"})
    r = client.post(f"{_P}/dossiers/e932011/reclassify",
                    json={"product_class": "biosimilar"})
    # a biosimilar can't stay an ANDS — reclassify must reject or require NDS
    assert r.status_code == 422


# -- R3 section-tree gaps [4][5][8][9] + noc_c [6] ----------------------------
from app import section_tree
from app import special_pathways as sp


def _node(st, section, **kw):
    tree = section_tree.section_tree(submission_type=st, **kw)
    return next(n for m in tree["modules"] for n in m["nodes"]
               if n["section"] == section)


def test_sands_labelling_13x_is_conditional_not_required():  # gap 4
    for sec in ("1.3.1", "1.3.3"):
        assert _node("SANDS", sec)["applicability"] == "conditional", sec


def test_din_qos_23_not_required_while_m3_optional():  # gap 5
    assert _node("DIN", "2.3")["applicability"] == "optional"


def test_sands_23_not_labelled_ce_be():  # gap 8
    assert "CE(BE)" not in _node("SANDS", "2.3")["title"]


def test_din_23_labelled_dina_variant():  # gap 9
    assert "DINA" in _node("DIN", "2.3")["title"]


def test_dossier_noc_c_advisory_names_severely_debilitating():  # gap 6
    a = sp.advisory("noc_c")
    assert "severely debilitating" in a["summary"].lower()
    assert "unmet" in a["summary"].lower() or "improvement" in a["summary"].lower()
