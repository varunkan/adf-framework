"""Per-section status, progress, gate, and tower roll-up (pure)."""

from app import dossier_state, section_tree


def test_na_and_suppressed_sections_are_na():
    assert dossier_state.resolve_status(section_tree.node_for("4"), None) == "na"
    assert dossier_state.resolve_status(section_tree.node_for("2.4"), None) == "na"


def test_bilingual_needs_both_languages():
    pm = section_tree.node_for("1.3.1")
    assert dossier_state.resolve_status(pm, {"languages": ["en"]}) == "partial"
    assert dossier_state.resolve_status(pm, {"languages": ["en", "fr"]}) == "complete"
    assert dossier_state.resolve_status(pm, None) == "empty"


def test_uploaded_document_is_complete():
    cl = section_tree.node_for("1.0")
    assert dossier_state.resolve_status(cl, {"action": "uploaded",
                                             "doc_id": "d1"}) == "complete"


def test_tower_and_gate_reflect_state():
    # nothing placed → module 1 todo, module 4 na, gate incomplete
    tower = {t["module"]: t for t in
             dossier_state.tower_view(cs_be_only=True, states={})}
    assert tower["1"]["state"] == "todo" and tower["4"]["state"] == "na"
    gate = dossier_state.completeness_gate(cs_be_only=True, states={})
    assert gate["complete"] is False and gate["missing"]
    # a required section shows in missing
    sections = {m["section"] for m in gate["missing"]}
    assert "1.0" in sections and "5.3.1" in sections


def test_module_progress_counts_required_only():
    m1 = section_tree.module_sections("1")
    states = {"1.0": {"action": "uploaded", "doc_id": "x"}}
    prog = dossier_state.module_progress(m1, states)
    assert prog["required_filled"] == 1 and prog["required_total"] > 1
