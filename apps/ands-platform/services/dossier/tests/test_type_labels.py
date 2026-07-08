"""ANDS-specific labels/generators must not persist on a non-ANDS filing.

Swarm-confirmed (live): an innovator NDS / DIN kept the ANDS comparative-BE
section labels — Module 2.3 titled 'QOS-CE(BE)' (the bioequivalence variant) and
Section 1.2.3 titled + generating the 'ANDS Sponsor Attestation'. These are wrong
for an NDS/DIN and mislead the filer.  [gaps 12, 15, 17, 18, 24, 25]
"""

from app import section_tree


def _node(st, section):
    tree = section_tree.section_tree(submission_type=st)
    return next(n for m in tree["modules"] for n in m["nodes"]
               if n["section"] == section)


def test_innovator_nds_qos_is_not_the_ce_be_variant():
    n = _node("NDS", "2.3")
    assert "CE(BE)" not in n["title"] and "CE-BE" not in n["title"]
    assert "quality overall summary" in n["title"].lower()


def test_din_qos_is_neutral_too():
    assert "CE(BE)" not in _node("DIN", "2.3")["title"]


def test_ands_keeps_the_ce_be_qos_variant():
    assert "CE(BE)" in _node("ANDS", "2.3")["title"]


def test_non_ands_123_drops_the_ands_sponsor_attestation_label_and_generator():
    for st in ("NDS", "DIN", "SNDS", "SANDS"):
        n = _node(st, "1.2.3")
        assert "ANDS Sponsor Attestation" not in n["title"], st
        assert n["generator_key"] != "ands_attestation", st


def test_ands_keeps_its_sponsor_attestation():
    n = _node("ANDS", "1.2.3")
    assert "Attestation" in n["title"]
    assert n["generator_key"] == "ands_attestation"
