"""REQ-102 — CA Non-eCTD validation profile (a profile axis over the catalog)."""

import pytest

from app import engine, rules


def test_profiles_listed():
    profs = {p["key"] for p in rules.list_validation_profiles()["profiles"]}
    assert profs == {"eCTD", "non-eCTD"}


def test_non_ectd_drops_backbone_rules():
    ectd_ids = {r["rule_id"] for r in rules.get_ruleset(profile="eCTD")["rules"]}
    non_ids = {r["rule_id"] for r in rules.get_ruleset(profile="non-eCTD")["rules"]}
    assert {"X01", "B07", "G01"} <= ectd_ids
    assert non_ids.isdisjoint({"X01", "B07", "G01"})
    assert non_ids < ectd_ids


def test_unknown_profile_raises():
    with pytest.raises(rules.UnknownProfileError):
        rules.get_ruleset(profile="banana")


def test_non_ectd_skips_malformed_backbone_check():
    ctx = {"dossier_id": "e1", "index_xml": "<not-well-formed",
           "files": [{"path": "m1/ca/x.pdf", "kind": "pdf",
                      "pdf_version": "1.6"}],
           "leaves": [{"leaf_id": "l", "href": "m1/ca/x.pdf",
                       "checksum": "a"}]}
    ectd = engine.run_validation(ctx, profile="eCTD")
    assert any(f["rule_id"] == "X01" for f in ectd["errors"])
    non = engine.run_validation(ctx, profile="non-eCTD")
    assert not any(f["rule_id"] == "X01" for f in non["findings"])
    assert non["profile"] == "non-eCTD"


def test_profiles_endpoint_and_invalid_profile(client):
    assert client.get("/api/validation/profiles").json()["default"] == "eCTD"
    r = client.post("/api/validation/run",
                    json={"context": {"dossier_id": "e1"}, "profile": "banana"})
    assert r.status_code == 422
