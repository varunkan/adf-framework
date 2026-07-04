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


def test_criteria_carries_sync_date():
    # validate_export blocker (13 respondents): the modeled-on criteria must
    # state its version AND a sync date so the ruleset provenance is legible.
    c = ectd_validation.criteria()
    assert c.get("synced"), "criteria must declare when it was last synced to HC"
    # a year must appear so it reads as a real date, not a placeholder
    assert any(ch.isdigit() for ch in c["synced"])


def test_every_rule_maps_to_an_hc_ich_source():
    # validate_export blocker: every CA-E/CA-W id must name the HC/ICH source
    # clause it is modeled on — regops/consultant personas spot-check this.
    cat = ectd_validation.rule_catalog()
    for r in cat["rules"]:
        assert r.get("source"), f"rule {r['rule_id']} has no HC/ICH source clause"
        # the source must cite a governing document, not be a vague blurb
        assert any(tok in r["source"] for tok in ("ICH", "HC", "CA Module", "REP")), \
            f"rule {r['rule_id']} source does not cite a governing spec: {r['source']}"


def test_web_endpoint_surfaces_rule_source(client):
    r = client.get("/api/dossier/validation/rules")
    assert r.status_code == 200
    rules = r.json()["rules"]
    assert rules and all(rule.get("source") for rule in rules)
    assert r.json()["criteria"].get("synced")


# --- WS-VALIDATE: eValidator parity/handoff surface (round-8 blocker, n=12) ---
# The structural checker must NOT pass itself off as HC's official eValidator.
# parity() is the honest, actionable handoff: a per-rule parity-gap table (which
# of our CA-E/CA-W rules map to a real HC eValidator rule vs. not-covered) plus
# a persistent "run eValidator before transmission" next-step. It ADDS to (never
# rewrites) the existing criteria()/rule_catalog() source-and-version surface.


def test_parity_reports_every_catalog_rule():
    # every rule the catalogue exposes must appear in the parity table so no
    # rule silently reads as "eValidator-equivalent" by omission.
    par = ectd_validation.parity()
    cat = ectd_validation.rule_catalog()
    par_ids = {r["rule_id"] for r in par["rules"]}
    cat_ids = {r["rule_id"] for r in cat["rules"]}
    assert cat_ids <= par_ids, cat_ids - par_ids


def test_parity_rules_declare_coverage_honestly():
    par = ectd_validation.parity()
    for r in par["rules"]:
        # each rule states whether a real HC eValidator rule covers the same
        # defect (a boolean), plus a plain-English note.
        assert "hc_evalidator_covered" in r
        assert isinstance(r["hc_evalidator_covered"], bool)
        assert r.get("note")
    # honesty gate: at least one rule must be declared NOT covered, otherwise the
    # table would falsely imply full eValidator parity.
    assert any(not r["hc_evalidator_covered"] for r in par["rules"]), \
        "parity table must not claim full eValidator coverage"


def test_parity_carries_criteria_and_actionable_next_step():
    par = ectd_validation.parity()
    # the versioned criteria travels with the parity evidence
    _assert_criteria(par["criteria"])
    # the persistent, actionable next-step banner
    banner = par["next_step"]
    assert "evalidator" in banner["banner"].lower()
    # it must not merely disclaim — it must name a concrete next action
    assert banner.get("action")
    # summary counts so a report can print "N of M rules eValidator-covered"
    assert par["covered_count"] + par["not_covered_count"] == len(par["rules"])
    assert par["not_covered_count"] >= 1


def test_parity_summary_matches_rule_flags():
    par = ectd_validation.parity()
    covered = sum(1 for r in par["rules"] if r["hc_evalidator_covered"])
    assert par["covered_count"] == covered
    assert par["not_covered_count"] == len(par["rules"]) - covered
