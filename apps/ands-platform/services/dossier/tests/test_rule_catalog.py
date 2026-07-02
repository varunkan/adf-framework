"""The validation rule catalogue — queryable depth surface (round-3 fix)."""

from app import ectd_validation


def test_catalog_covers_every_rule(client):
    r = client.get("/api/dossier/validation/rules")
    assert r.status_code == 200
    body = r.json()
    ids = {x["rule_id"] for x in body["rules"]}
    # every engine rule is in the catalogue, plus the REP identity gate
    for rule_id in ectd_validation.RULE_IDS.values():
        assert rule_id in ids
    assert "CA-REP-0001" in ids
    assert body["count"] == len(body["rules"]) >= 32


def test_catalog_entries_are_complete(client):
    for r in client.get("/api/dossier/validation/rules").json()["rules"]:
        assert r["rule_id"].startswith("CA-")
        assert r["family"]
        assert r["severity"] in ("error", "warning")
        assert r["description"], r["rule_id"]
    # warning-severity flags derive from the ID convention
    warn = [r for r in client.get("/api/dossier/validation/rules").json()["rules"]
            if "-W-" in r["rule_id"]]
    assert all(r["severity"] == "warning" for r in warn) and warn
