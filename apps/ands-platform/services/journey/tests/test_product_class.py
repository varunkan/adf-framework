"""Product-class honest-scope model (Tier B gap fix).

ANDS Studio's guided authoring is tuned for a GENERIC small-molecule chemical
drug (the ANDS pathway). Other product classes are real Health Canada regimes
with DIFFERENT directorates, filing instruments and evidence — a biosimilar
files an NDS (not an ANDS), a disinfectant gets a DIN via the NNHPD, etc. The
tool must say so HONESTLY (a scope banner), not pretend to support them and not
offer a hollow option. This model carries the verified facts each banner needs.
"""

from app import product_class as pc


def test_small_molecule_is_in_core_scope():
    r = pc.scope("small_molecule")
    assert r["in_scope"] is True
    # the core generic pathway — no out-of-scope banner
    assert r["advisory"] is None


def test_biosimilar_files_nds_not_ands_and_is_out_of_scope():
    r = pc.scope("biosimilar")
    assert r["in_scope"] is False
    assert "NDS" in r["filing_instrument"]
    # the crux: a biosimilar files a NEW (full) drug submission, never an
    # ABBREVIATED one — the honest string may say "not an ANDS" but it must not
    # present the Abbreviated pathway as the instrument
    assert "Abbreviated" not in r["filing_instrument"]
    assert r["advisory"] and "biosimilar" in r["advisory"].lower()
    assert r["citation"]


def test_biologic_routes_to_brdd_as_a_new_drug_submission():
    r = pc.scope("biologic")
    assert r["in_scope"] is False
    assert "NDS" in r["filing_instrument"]
    assert "BRDD" in r["directorate"] or "Biologic" in r["directorate"]


def test_disinfectant_is_an_nnhpd_din_not_an_ectd_review():
    r = pc.scope("disinfectant")
    assert r["in_scope"] is False
    assert "NNHPD" in r["directorate"]
    assert "DIN" in r["filing_instrument"]
    assert r["contact"]  # a real HC contact for the honest hand-off


def test_every_class_out_of_scope_has_advisory_citation_and_directorate():
    for code, _label in pc.PRODUCT_CLASSES:
        r = pc.scope(code)
        if not r["in_scope"]:
            assert r["advisory"], code
            assert r["citation"], code
            assert r["directorate"], code
            assert r["filing_instrument"], code


def test_unknown_class_is_treated_conservatively_as_out_of_scope():
    r = pc.scope("frobnicator")
    assert r["in_scope"] is False
    assert r["advisory"]


def test_list_product_classes_carries_scope_for_the_ui():
    rows = pc.list_product_classes()
    assert {r["value"] for r in rows} == {c for c, _ in pc.PRODUCT_CLASSES}
    sm = next(r for r in rows if r["value"] == "small_molecule")
    assert sm["in_scope"] is True
    bs = next(r for r in rows if r["value"] == "biosimilar")
    assert bs["in_scope"] is False and bs["advisory"]


# -- assess() surfaces the honest scope advisory --------------------------------
def test_assess_flags_an_out_of_scope_product_class():
    a = pc  # placeholder to keep import used if assess import changes
    from app import drug_intake as di
    res = di.assess({"submission_type": "ANDS", "product_class": "biosimilar"})
    rules = {adv["rule"] for adv in res["advisories"]}
    assert "product_class_out_of_scope" in rules
    assert res["checks"]["product_class"]["in_scope"] is False


def test_assess_is_quiet_for_small_molecule():
    from app import drug_intake as di
    res = di.assess({"submission_type": "ANDS", "product_class": "small_molecule"})
    rules = {adv["rule"] for adv in res["advisories"]}
    assert "product_class_out_of_scope" not in rules
