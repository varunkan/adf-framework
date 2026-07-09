"""Round-6 swarm gaps — DIN sub-type modeling + ICH Module-4 granularity.

Web-verified vs canada.ca (din-taxonomy-research, high confidence). The DIN
pathway was modeled as a single undifferentiated prescription "DINA"; HC has
distinct DIN classes with materially different content. Invariants locked here:

 (1) Product Monograph (1.3.1) is NEVER required for any DIN — a DIN bears no NOC;
     the PM is the NOC-bearing artifact for NDS/SNDS/ANDS/SANDS.  [MATERIAL fix]
 (2) Module 5 (clinical) is always na for a DIN (not a safety/efficacy review).
 (3) Module 3 CMC + 2.3 QOS-CE(DINA) are REQUIRED only for a DATA-SUPPORTED DINA
     (chemical entity needing a quality review); na for a STANDARD-REFERENCED /
     Category-IV / labelling-standard DIN (no CMC filed — GMP attested, kept on
     file); conditional when the DIN sub-type is not yet declared.
 (4) 1.3.3 Labelling is always required — the label (CDFT / labelling standard /
     Category IV monograph) is the DIN's sole product-information vehicle.
 Plus ICH M4: the tree must expose 4.2.1/4.2.2/4.2.3 + a distinct 4.3.
"""

from app import section_tree

_P = "/api/dossier"


def _node(section, st="DIN", **kw):
    tree = section_tree.section_tree(submission_type=st, **kw)
    return next((n for m in tree["modules"] for n in m["nodes"]
                 if n["section"] == section), None)


# ---- Invariant 1: PM never required for any DIN (the MATERIAL fix) ----------
def test_pm_131_never_required_for_any_din():
    for dt in ("", "standard_referenced", "data_supported"):
        assert _node("1.3.1", din_type=dt)["applicability"] == "na", dt


def test_pm_131_din_guidance_explains_no_pm():
    g = _node("1.3.1", din_type="standard_referenced")["guidance"].lower()
    assert "product monograph" in g
    assert ("drug facts" in g or "labelling standard" in g
            or "does not" in g or "no notice of compliance" in g)


# ---- Invariant 4: labelling always required; CDFT-aware for DIN -------------
def test_labelling_133_required_for_din():
    for dt in ("", "standard_referenced", "data_supported"):
        assert _node("1.3.3", din_type=dt)["applicability"] == "required", dt


def test_labelling_133_din_references_cdft():
    g = _node("1.3.3", din_type="standard_referenced")["guidance"].lower()
    assert "drug facts" in g or "cdft" in g or "plain language" in g


# ---- Invariant 3: M3 + QOS required only for data-supported DINA ------------
def test_module3_required_for_data_supported_dina():
    for sec in ("3.2.S", "3.2.S.1", "3.2.P"):
        assert _node(sec, din_type="data_supported")["applicability"] == "required", sec
    assert _node("2.3", din_type="data_supported")["applicability"] == "required"


def test_module3_na_for_standard_referenced_din():
    for sec in ("3.2.S", "3.2.S.1", "3.2.P"):
        assert _node(sec, din_type="standard_referenced")["applicability"] == "na", sec
    assert _node("2.3", din_type="standard_referenced")["applicability"] == "na"


def test_module3_conditional_when_din_type_unspecified():
    # unspecified DIN -> conditional (declare the sub-type), never blocking-required
    assert _node("3.2.S.1", din_type="")["applicability"] == "conditional"
    assert _node("2.3", din_type="")["applicability"] == "conditional"


# ---- Invariant 2: no clinical for any DIN ----------------------------------
def test_module5_na_for_din():
    for sec in ("5.3.1", "5.3.5"):
        assert _node(sec, din_type="data_supported")["applicability"] == "na", sec


# ---- non-DIN types ignore din_type entirely --------------------------------
def test_din_type_ignored_for_non_din_types():
    # an innovator NDS is unaffected by a stray din_type (PM stays required)
    assert _node("1.3.1", st="NDS", din_type="standard_referenced")["applicability"] == "required"


# ---- Module 4 ICH granularity (gap #4) -------------------------------------
def test_module4_has_ich_granular_subsections_for_nds():
    for sec in ("4.2.1", "4.2.2", "4.2.3", "4.3"):
        n = _node(sec, st="NDS")
        assert n is not None, sec
        assert n["applicability"] == "required", sec


def test_module4_granular_subsections_na_for_generic_ands():
    for sec in ("4.2.1", "4.2.2", "4.2.3", "4.3"):
        assert _node(sec, st="ANDS")["applicability"] == "na", sec


# ---- Service-level: din_type persisted + gate not blocked by PM ------------
def test_standard_referenced_din_gate_not_blocked_by_pm_or_cmc(client):
    r = client.post(f"{_P}/dossiers", json={
        "dossier_id": "e960081", "title": "Antacid oral suspension",
        "submission_type": "DIN", "din_type": "standard_referenced",
        "product_class": "small_molecule"})
    assert r.status_code in (200, 201), r.text
    cs = client.get(f"{_P}/dossiers/e960081/content").json()
    assert cs["din_type"] == "standard_referenced"
    missing = {m.get("section") for m in cs["gate"]["missing"]}
    assert "1.3.1" not in missing          # PM never blocks a DIN
    assert "3.2.S.1" not in missing        # no CMC for a standard-referenced DIN
    # the label IS still required
    pm = next(n for mod in cs["modules"] for n in mod["nodes"] if n["section"] == "1.3.1")
    assert pm["applicability"] == "na"
    lab = next(n for mod in cs["modules"] for n in mod["nodes"] if n["section"] == "1.3.3")
    assert lab["applicability"] == "required"


def test_data_supported_dina_reclassify_sets_cmc_required(client):
    client.post(f"{_P}/dossiers", json={
        "dossier_id": "e960082", "title": "Generic-quality chemical entity DIN",
        "submission_type": "DIN", "product_class": "small_molecule"})
    # correct it to data-supported after create
    r = client.post(f"{_P}/dossiers/e960082/reclassify",
                    json={"din_type": "data_supported"})
    assert r.status_code in (200, 201), r.text
    cs = client.get(f"{_P}/dossiers/e960082/content").json()
    assert cs["din_type"] == "data_supported"
    s1 = next(n for mod in cs["modules"] for n in mod["nodes"] if n["section"] == "3.2.S.1")
    assert s1["applicability"] == "required"
