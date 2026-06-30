"""REQ-101 — annotated PM cross-reference assistant."""

from app import pm_xref


def test_targets_include_module2_and_142():
    targets = pm_xref.valid_targets()
    assert "1.4.2" in targets and "2.3" in targets and "2.7.1" in targets


def test_build_xrefs_from_sections_and_top_level():
    refs = pm_xref.build_pm_xrefs({
        "sections": [{"code": "indications", "refs": ["2.7", "1.4.2"]}],
        "refs": [{"source": "dosage", "target": "2.3"}]})
    targets = {(r["source"], r["target"]) for r in refs}
    assert ("indications", "2.7") in targets
    assert ("indications", "1.4.2") in targets
    assert ("dosage", "2.3") in targets


def test_resolve_flags_invalid_target():
    out = pm_xref.resolve_pm_xrefs([{"source": "x", "target": "9.9"}])
    assert out["all_resolved"] is False
    assert out["findings"][0]["rule"] == "xref_target_invalid"


def test_resolve_flags_missing_present_target():
    # valid target, but absent from the dossier's present targets
    out = pm_xref.resolve_pm_xrefs([{"source": "x", "target": "1.4.2"}],
                                   present_targets={"2.3"})
    assert out["findings"][0]["rule"] == "xref_target_missing"


def test_resolve_all_good():
    out = pm_xref.resolve_pm_xrefs(
        [{"source": "x", "target": "2.3"}, {"source": "y", "target": "1.4.2"}],
        present_targets={"2.3", "1.4.2"})
    assert out["all_resolved"] is True
    assert len(out["resolved"]) == 2
    assert out["resolved"][1]["label"].startswith("Bioequivalence")


def test_xref_api(client):
    assert "1.4.2" in client.get(
        "/api/dossier/monograph/xref/targets").json()["targets"]
    r = client.post("/api/dossier/monograph/xref/resolve",
                    json={"sections": [{"code": "indications",
                                        "refs": ["2.7", "bogus"]}]})
    body = r.json()
    assert body["all_resolved"] is False
    assert any(f["rule"] == "xref_target_invalid" for f in body["findings"])
