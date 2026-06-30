"""F8 / REQ-117 — extended GRP validation profile (stricter than HC minimum)."""

from app import engine, rules

from tests.conftest import clean_context


def test_grp_listed_and_adds_rules():
    assert "GRP" in {p["key"] for p in
                     rules.list_validation_profiles()["profiles"]}
    ectd_ids = {r["rule_id"] for r in rules.get_ruleset(profile="eCTD")["rules"]}
    grp_ids = {r["rule_id"] for r in rules.get_ruleset(profile="GRP")["rules"]}
    assert {"GRP01", "GRP02"} <= grp_ids
    assert {"GRP01", "GRP02"}.isdisjoint(ectd_ids)
    assert ectd_ids < grp_ids


def test_missing_bookmarks_warns_in_ectd_but_blocks_in_grp():
    ctx = clean_context()
    ctx["files"][0]["bookmarks"] = False
    assert engine.run_validation(ctx, profile="eCTD")["blocking"] is False
    grp = engine.run_validation(ctx, profile="GRP")
    assert grp["blocking"] is True
    assert any(f["rule_id"] == "GRP01" for f in grp["errors"])


def test_grp_dpi_floor():
    ctx = clean_context()
    ctx["files"][0].update(scanned=True, searchable=True, dpi=150)
    grp = engine.run_validation(ctx, profile="GRP")
    assert any(f["rule_id"] == "GRP02" for f in grp["errors"])
    ctx["files"][0]["dpi"] = 600
    assert not any(f["rule_id"] == "GRP02"
                   for f in engine.run_validation(ctx, profile="GRP")["findings"])


def test_grp_via_run_api(client):
    ctx = clean_context()
    ctx["files"][0]["bookmarks"] = False
    r = client.post("/api/validation/run",
                    json={"context": ctx, "dossier_id": "e1", "profile": "GRP"})
    assert r.json()["blocking"] is True
