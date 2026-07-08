"""Submission-type gating — non-ANDS types must NOT inherit ANDS behaviour.

Swarm-confirmed HC gaps (all reproduced live):
 * SANDS (post-NOC supplement) asserted a comparative BE study 'is required' —
   HC supports a site change with comparative in-vitro dissolution, so the BE
   study is CHANGE-DEPENDENT (conditional), not required.  [gap 2]
 * cs_be_only (an ANDS comparative-BE concept) leaked onto NDS / DIN dossiers,
   surfacing 'CS-BE' on an innovator/DIN filing.  [gaps 4, 16, 21]
 * SANDS forced the full fresh-ANDS Module 3 CMC set as required instead of
   scoping to the changed modules.  [gap 13]
"""

from app import comparative_evidence as ce
from app import section_tree


# -- comparative evidence is submission-type aware ---------------------------
def test_ands_route_unchanged_for_solid_oral():
    r = ce.route("ir_solid_oral", submission_type="ANDS")
    assert r["requires_be_study"] is True


def test_sands_supplement_does_not_force_a_be_study():
    r = ce.route("ir_solid_oral", submission_type="SANDS")
    assert r["requires_be_study"] is False          # change-dependent, not required
    assert "dissolution" in (r["evidence"] + r["label"]).lower() \
        or "change" in r["evidence"].lower()
    assert r["citation"]


def test_section_tree_sands_comparative_evidence_is_conditional():
    tree = section_tree.section_tree(submission_type="SANDS")
    ceb = tree["comparative_evidence"]
    assert ceb is not None and ceb["requires_be_study"] is False


def test_section_tree_nds_and_din_have_no_comparative_evidence():
    for st in ("NDS", "DIN", "SNDS"):
        assert section_tree.section_tree(submission_type=st)["comparative_evidence"] is None


# -- SANDS scopes Module 3 to the change (not the full fresh-ANDS CMC set) ----
def _m3_required(st):
    tree = section_tree.section_tree(submission_type=st)
    m3 = next(m for m in tree["modules"] if m["module"] == "3")
    return [n["section"] for n in m3["nodes"]
            if n["kind"] == "document" and n["applicability"] == "required"]


def test_sands_module3_is_change_scoped_not_all_required():
    # an ANDS files the full M3 CMC; a SANDS supplement scopes to the change, so
    # the heavy M3 documents must NOT all be hard 'required'
    assert len(_m3_required("SANDS")) < len(_m3_required("ANDS"))


# -- cs_be_only never leaks onto a non-ANDS filing (backend enforced) --------
_P = "/api/dossier"


def _create(client, did, sub):
    return client.post(f"{_P}/dossiers",
                       json={"dossier_id": did, "title": f"t {sub}",
                             "submission_type": sub})


def test_cs_be_only_forced_false_for_non_ands(client):
    # a direct API create (no cs_be_only sent) must NOT default an innovator NDS
    # or a DIN to the ANDS comparative-BE flag
    for did, sub in (("e930101", "NDS"), ("e930102", "DIN"), ("e930103", "SNDS")):
        assert _create(client, did, sub).status_code in (200, 201)
        st = client.get(f"{_P}/dossiers/{did}/content").json()
        assert st["cs_be_only"] is False, sub


def test_cs_be_only_still_honoured_for_ands(client):
    assert _create(client, "e930104", "ANDS").status_code in (200, 201)
    st = client.get(f"{_P}/dossiers/e930104/content").json()
    assert st["cs_be_only"] is True
