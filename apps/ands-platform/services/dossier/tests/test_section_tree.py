"""The deep HC eCTD section tree (M1 full depth + M2/3/5 + M4 na)."""

from app import section_tree


def test_five_modules_present():
    t = section_tree.section_tree()
    assert [m["module"] for m in t["modules"]] == ["1", "2", "3", "4", "5"]
    assert t["version"] == section_tree.SECTION_TREE_VERSION


def test_module1_full_depth_sections_present():
    secs = {n["section"] for n in section_tree.module_sections("1")}
    for s in ("1.0", "1.2.1", "1.2.5", "1.2.6", "1.3.1", "1.3.2", "1.4.2"):
        assert s in secs, f"Module 1 missing {s}"


def test_cover_letter_is_generatable_and_uploadable():
    n = section_tree.node_for("1.0")
    assert n["generator_key"] == "cover_letter"
    assert "generate" in n["affordances"] and "upload" in n["affordances"]
    assert n["leaf_id"] == "m1-0-1-cover-letter"     # from the placement table
    assert n["folder"] == "m1/ca/10-cover-letter"


def test_product_monograph_is_bilingual_pdf_and_docx():
    n = section_tree.node_for("1.3.1")
    assert n["bilingual"] is True
    assert set(n["formats"]) == {"pdf", "docx"}
    assert n["applicability"] == "required"


def test_generators_wired_for_m1_authorables():
    keys = {section_tree.node_for(s)["generator_key"]
            for s in ("1.0", "1.2.1", "1.2.5", "1.2.6", "1.4.2")}
    assert keys == {"cover_letter", "rep_application_form", "patent_form_iv",
                    "ands_attestation", "cs_be"}


def test_qos_required_and_24_suppressed_on_cs_be():
    assert section_tree.node_for("2.3")["applicability"] == "required"
    assert section_tree.node_for("2.4")["applicability"] == "suppressed"
    # non-CS-BE keeps 2.4 optional (not suppressed)
    assert section_tree.node_for("2.4", cs_be_only=False)["applicability"] == "optional"


def test_module4_is_na_and_module5_be_required():
    assert section_tree.node_for("4")["applicability"] == "na"
    assert section_tree.node_for("5.3.1")["applicability"] == "required"


def test_derived_leaf_ids_and_folders_for_deep_sections():
    s1 = section_tree.node_for("3.2.S.1")
    assert s1["leaf_id"] == "m3-2-s-1"
    assert s1["folder"] == "m3/3-2-s-1"
    assert s1["module"] == "3" and s1["depth"] == 3


def test_node_lookup_by_id():
    n = section_tree.node_for_id("1-2-1")
    assert n is not None and n["section"] == "1.2.1"
