"""WS1: validation output must name its versioned criteria + an HONEST coverage
statement (what it checks and — critically — what it does not, incl. that it is
not Health Canada's official eValidator). Panel round-4 blocker themes."""

from app import assembly, ectd_validation


def _clean_dossier():
    d = assembly.new_dossier("e123456")
    assembly.add_leaf(d, "0000", {"leaf_id": "pm", "operation": "new",
                                  "heading": "1.3.1", "title": "PM"})
    return d


def _assert_criteria(c):
    assert c["name"] and c["version"]
    assert c.get("modeled_on")
    # honesty: it must NOT pass itself off as HC's official eValidator
    blob = (c["modeled_on"] + " " + c.get("disclaimer", "")).lower()
    assert "evalidator" in blob
    cov = c["coverage"]
    assert cov["checked"] and cov["not_checked"]
    # must be explicit that scientific adequacy is out of scope
    assert any("scientif" in s.lower() for s in cov["not_checked"])


def test_validate_carries_named_versioned_criteria():
    res = ectd_validation.validate(_clean_dossier())
    assert "criteria" in res
    _assert_criteria(res["criteria"])


def test_validate_submission_passthrough_carries_criteria(client):
    # the web-facing /validate endpoint must surface the same criteria block
    r = client.get("/api/dossier/validation/rules")
    assert r.status_code == 200
    assert "criteria" in r.json()
    _assert_criteria(r.json()["criteria"])


def test_rule_catalog_carries_criteria():
    cat = ectd_validation.rule_catalog()
    assert "criteria" in cat
    _assert_criteria(cat["criteria"])
