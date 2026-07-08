"""Special pathways surfaced ON the dossier content_state (swarm r2 ENHANCEMENT).

A dossier flags the special pathways that apply (Priority Review, NOC/c, …) and
content_state emits an honest, cited advisory for each — closing the gap where
these were only in the journey catalog, never on the dossier.
"""

from app import special_pathways as sp

_P = "/api/dossier"


def test_advisories_are_cited_and_advisory_only():
    a = sp.advisories(["noc_c", "priority_review"])
    assert [x["id"] for x in a] == ["noc_c", "priority_review"]
    assert all(x["citation"] and x["advisory_only"] for x in a)


def test_unknown_pathway_dropped():
    assert sp.advisories(["teleport", "noc_c"]) == sp.advisories(["noc_c"])


def test_content_state_surfaces_flagged_pathways(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e931001", "title": "onc",
                "submission_type": "NDS",
                "special_pathways": ["priority_review", "noc_c"]})
    st = client.get(f"{_P}/dossiers/e931001/content").json()
    ids = [p["id"] for p in st.get("special_pathways", [])]
    assert "priority_review" in ids and "noc_c" in ids
    assert all(p.get("citation") for p in st["special_pathways"])


def test_content_state_empty_when_none_flagged(client):
    client.post(f"{_P}/dossiers", json={"dossier_id": "e931002", "title": "plain",
                "submission_type": "ANDS"})
    st = client.get(f"{_P}/dossiers/e931002/content").json()
    assert st.get("special_pathways") == []
