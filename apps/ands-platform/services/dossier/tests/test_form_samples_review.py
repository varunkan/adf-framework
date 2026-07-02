"""Realistic per-form samples + Health Canada content review."""
from app import form_samples, form_review


def test_sample_uses_real_facts_then_fills_gaps():
    ctx = {"drug_product": "Apo-Zentrix 50 mg tablet", "dossier_id": "e123456",
           "company_id": "61234", "sponsor": "Northline"}
    s = form_samples.sample_fields("patent_form_v", ctx)
    f = s["fields"]
    # real facts preserved
    assert f["drug_product"] == "Apo-Zentrix 50 mg tablet"
    assert f["company_id"] == "61234" and f["sponsor"] == "Northline"
    # sample fills the regulatory gaps, flagged as sample
    assert f["crp_brand"] and f["allegation"]
    assert "allegation" in s["sample_keys"] and "crp_brand" in s["sample_keys"]
    # a real fact is NOT badged as sample
    assert "company_id" not in s["sample_keys"]


def test_cs_be_sample_has_ci_values():
    s = form_samples.sample_fields("cs_be", {"drug_product": "X 10 mg"})
    assert s["fields"]["auc_ci"] and s["fields"]["cmax"]


def test_review_form_v_flags_missing_allegation_with_link():
    r = form_review.review("patent_form_v",
                           {"patents": "CA 2,845,123", "allegation": ""})
    assert not r["passed"]
    f = next(x for x in r["findings"] if x["rule"] == "formv_allegation_required")
    assert f["severity"] == "error" and f["hc_url"].startswith("https://")
    assert f["suggested_edit"]


def test_review_cs_be_requires_auc_and_cmax():
    r = form_review.review("cs_be", {"crp_brand": "Brandozole"})
    rules = {x["rule"] for x in r["findings"]}
    assert "csbe_auc_required" in rules and "csbe_cmax_required" in rules


def test_review_rep_requires_company_identity():
    r = form_review.review("rep_application_form", {"dossier_id": "e123456"})
    rules = {x["rule"] for x in r["findings"]}
    assert "rep_company_id_required" in rules
    assert "rep_company_name_required" in rules


def test_review_passes_on_complete_sample():
    for key in ("cover_letter", "rep_application_form", "patent_form_v",
                "ands_attestation", "cs_be", "qos_ce_scaffold"):
        ctx = {"drug_product": "X 10 mg tablet", "dossier_id": "e123456",
               "company_id": "61234", "sponsor": "Acme"}
        fields = form_samples.sample_fields(key, ctx)["fields"]
        r = form_review.review(key, fields)
        assert r["passed"], (key, r["findings"])


def test_api_sample_and_review(client=None):
    from types import SimpleNamespace
    import pytest
    from fastapi.testclient import TestClient
    from ands_shared import InMemoryEventBus, SqliteDb
    from app.api import build_app
    from app.repository_sqlite import SqliteDossierRepository
    from app.service import DossierService
    c = TestClient(build_app(DossierService(
        SqliteDossierRepository(SqliteDb(":memory:")), InMemoryEventBus())))
    c.post("/api/dossier/dossiers", json={"dossier_id": "e123456",
           "title": "Zx 10 mg", "drug_product": "Zx 10 mg tablet"})
    s = c.get("/api/dossier/ectd/e123456/section/1.2.4/sample")
    assert s.status_code == 200 and s.json()["fields"]["drug_product"]
    r = c.post("/api/dossier/ectd/e123456/section/1.2.4/review",
               json={"patents": "CA1", "allegation": ""})
    assert r.status_code == 200 and not r.json()["passed"]
    assert r.json()["guidance_url"]
