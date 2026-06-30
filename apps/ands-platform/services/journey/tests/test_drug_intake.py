"""'Tell me about your drug' decision support — routing + CRP + bioequivalence."""

from app import drug_intake


def test_route_ands_returns_content_model_module4_not_required():
    r = drug_intake.route_submission_type({"submission_type": "ands"})
    assert r["valid"] and r["submission_type"] == "ANDS"
    assert r["ands_content_model"] is True
    assert r["content_model"]["module4_required"] is False


def test_ands_new_indication_steers_off_ands():
    r = drug_intake.route_submission_type(
        {"submission_type": "ANDS", "new_indication": True})
    rules = {a["rule"] for a in r["advisories"]}
    assert "ands_not_for_new_indication" in rules


def test_unknown_submission_type_is_invalid():
    r = drug_intake.route_submission_type({"submission_type": "ZZZ"})
    assert r["valid"] is False and "not a recognised" in r["error"]


def test_cs_be_only_suppresses_modules_24_to_27():
    cm = drug_intake.ands_content_model(cs_be_only=True)
    suppressed = {m["module"] for m in cm["modules"] if m["suppressed"]}
    assert {"2.4", "2.5", "2.6", "2.7"} <= suppressed
    # 2.3 QOS and Module 3 stay required
    by_mod = {m["module"]: m for m in cm["modules"]}
    assert by_mod["2.3"]["required"] and by_mod["3"]["required"]


def test_assess_flags_not_pharmaceutically_equivalent():
    a = drug_intake.assess({
        "submission_type": "ANDS",
        "crp": {"brand_name": "Brandyl", "din": "00000001", "strength": "10mg",
                "dosage_form": "tablet", "innovator": "Innov",
                "medicinal_ingredients": "drugazole"},
        "generic": {"dosage_form": "tablet",
                    "medicinal_ingredients": "different-salt"}})
    rules = {x["rule"] for x in a["advisories"]}
    assert "not_pharmaceutically_equivalent" in rules
    assert a["eligible_ands"] is False


def test_assess_bioequivalence_m13a_branch():
    # IR solid oral filed on/after the M13A date needs the full Cmax 90% CI
    a = drug_intake.assess({
        "submission_type": "ANDS",
        "dosage_form_class": "ir_solid_oral", "submission_date": "2026-01-01",
        "be_study": {"auc": {"ci_lower": 90, "ci_upper": 110},
                     "cmax": {"point_estimate": 100}}})  # no CI -> fails M13A
    be = a["checks"]["bioequivalence"]
    assert be["ruleset"]["version"] == "M13A"
    assert be["bioequivalent"] is False
    assert any(f["rule"] == "cmax_ci_required" for f in be["findings"])


def test_assess_bioequivalence_legacy_point_estimate_passes():
    a = drug_intake.assess({
        "submission_type": "ANDS",
        "dosage_form_class": "mr_solid_oral", "submission_date": "2026-01-01",
        "be_study": {"auc": {"ci_lower": 90, "ci_upper": 110},
                     "cmax": {"point_estimate": 100}}})
    be = a["checks"]["bioequivalence"]
    assert be["ruleset"]["version"] == "legacy" and be["bioequivalent"] is True
