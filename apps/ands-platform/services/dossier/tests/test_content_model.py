"""ANDS module-level applicability gating (ported)."""

from app import content_model


def test_ands_cs_be_suppresses_24_to_27_keeps_23():
    m = {x["module"]: x for x in content_model.ands_content_model(True)["modules"]}
    for s in ("2.4", "2.5", "2.6", "2.7"):
        assert m[s]["suppressed"] is True and m[s]["required"] is False
    assert m["2.3"]["required"] is True and m["2.3"]["suppressed"] is False
    assert m["3"]["required"] and m["5"]["required"]
    assert m["4"]["required"] is False


def test_module_gate_rolls_subsections_to_their_module():
    assert content_model.module_gate("3.2.S.1")["required"] is True
    assert content_model.module_gate("3.2.P.7")["applicable"] is True
    g24 = content_model.module_gate("2.4", cs_be_only=True)
    assert g24["suppressed"] is True
    g4 = content_model.module_gate("4")
    assert g4["na"] is True and g4["applicable"] is False


def test_non_cs_be_keeps_24_applicable():
    m = {x["module"]: x for x in content_model.ands_content_model(False)["modules"]}
    assert m["2.4"]["suppressed"] is False and m["2.4"]["applicable"] is True
