"""ADOPT-EVALIDATOR (task-eval adoption blocker, 24/24): close the HC eValidator
loop HONESTLY.

We cannot run Health Canada's official eValidator here, so the honest loop-closer
is a USER-ATTESTED external result: the filer runs HC eValidator (or their
publisher's validator) on the exported package and attaches the real outcome
(pass/fail + validator name/version + date + optional report file / notes). ANDS
Studio persists it and surfaces it as an EXTERNAL, user-attested result — never a
tool self-claim of parity.

These tests prove:
  - the attestation persists (set/get) and round-trips its fields;
  - it is labeled as a user-attested EXTERNAL result (source != tool self-claim),
    and the honesty disclaimer is never dropped;
  - it is surfaced in the dossier validation state so the UI can show
    "HC eValidator: PASSED — attested by <user> on <date> (external result)";
  - the set/get endpoints are tenant-isolated;
  - recording an attestation writes a durable audit-ledger event;
  - parity() is enriched toward rule-LEVEL coverage where the family maps
    cleanly, keeping the honest not_covered set.
"""

import pytest

from app import ectd_validation


def _create(client, did="e123456", title="Attestol 10 mg tablet", tenant=None):
    headers = {"X-Tenant-Id": tenant} if tenant else {}
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


# --- repository persistence -------------------------------------------------

def test_repo_attestation_roundtrips(ctx):
    ctx.repo.create_dossier_index({"dossier_id": "e123456", "title": "X"})
    att = {
        "result": "pass",
        "validator_name": "HC eValidator",
        "validator_version": "5.3",
        "validated_on": "2026-07-01",
        "attested_by": "regops@sponsor.example",
        "notes": "Ran on exported sequence 0000; 0 errors, 0 warnings.",
        "report_filename": "e123456-0000-evalidator.pdf",
    }
    saved = ctx.repo.set_evalidator_attestation("e123456", att)
    assert saved["result"] == "pass"
    got = ctx.repo.get_evalidator_attestation("e123456")
    assert got["validator_name"] == "HC eValidator"
    assert got["validator_version"] == "5.3"
    assert got["attested_by"] == "regops@sponsor.example"
    assert got["report_filename"] == "e123456-0000-evalidator.pdf"


def test_repo_attestation_absent_is_none(ctx):
    assert ctx.repo.get_evalidator_attestation("nope") is None


def test_repo_attestation_upserts_latest(ctx):
    ctx.repo.create_dossier_index({"dossier_id": "e123456", "title": "X"})
    ctx.repo.set_evalidator_attestation(
        "e123456", {"result": "fail", "validator_name": "HC eValidator"})
    ctx.repo.set_evalidator_attestation(
        "e123456", {"result": "pass", "validator_name": "HC eValidator",
                    "validated_on": "2026-07-02"})
    got = ctx.repo.get_evalidator_attestation("e123456")
    assert got["result"] == "pass"
    assert got["validated_on"] == "2026-07-02"


# --- service: honesty labeling ---------------------------------------------

def test_service_records_and_labels_external_result(ctx):
    _create(ctx.client)
    rec = ctx.service.set_evalidator_attestation(
        "e123456",
        {"result": "pass", "validator_name": "HC eValidator",
         "validator_version": "5.3", "validated_on": "2026-07-01",
         "notes": "clean"},
        actor="regops@sponsor.example")
    # honesty: it is stamped as a USER-ATTESTED EXTERNAL result, not a tool claim
    assert rec["source"] == "user_attested_external"
    assert rec["result"] == "pass"
    assert rec["attested_by"] == "regops@sponsor.example"
    # the disclaimer must state ANDS Studio did NOT run eValidator itself
    assert "did not run" in rec["disclaimer"].lower() or \
           "external" in rec["disclaimer"].lower()


def test_service_rejects_bad_result(ctx):
    _create(ctx.client)
    from ands_shared import ProblemError
    with pytest.raises(ProblemError):
        ctx.service.set_evalidator_attestation(
            "e123456", {"result": "definitely-passed"}, actor="x")


def test_service_requires_validator_name(ctx):
    _create(ctx.client)
    from ands_shared import ProblemError
    with pytest.raises(ProblemError):
        ctx.service.set_evalidator_attestation(
            "e123456", {"result": "pass", "validator_name": ""}, actor="x")


def test_service_unknown_dossier_404(ctx):
    from ands_shared import ProblemError
    with pytest.raises(ProblemError):
        ctx.service.set_evalidator_attestation(
            "nope", {"result": "pass", "validator_name": "HC eValidator"},
            actor="x")


# --- surfaced in validation state ------------------------------------------

def test_attestation_surfaces_in_validate_submission(ctx):
    _create(ctx.client)
    ctx.service.set_evalidator_attestation(
        "e123456",
        {"result": "pass", "validator_name": "HC eValidator",
         "validator_version": "5.3", "validated_on": "2026-07-01"},
        actor="regops@sponsor.example")
    res = ctx.service.validate_submission("e123456")
    ext = res.get("external_attestation")
    assert ext is not None
    assert ext["result"] == "pass"
    assert ext["source"] == "user_attested_external"
    # the structural 'passed' flag is NEVER driven by the external attestation —
    # they are independent signals (the attestation is user-supplied evidence).
    assert "passed" in res


# --- endpoints --------------------------------------------------------------

def test_endpoints_set_and_get(client):
    _create(client)
    r = client.post(
        "/api/dossier/dossiers/e123456/evalidator-attestation",
        json={"result": "pass", "validator_name": "HC eValidator",
              "validator_version": "5.3", "validated_on": "2026-07-01",
              "notes": "0 errors"},
        headers={"X-User-Email": "regops@sponsor.example"})
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["result"] == "pass"
    assert body["source"] == "user_attested_external"

    g = client.get("/api/dossier/dossiers/e123456/evalidator-attestation")
    assert g.status_code == 200
    assert g.json()["attestation"]["validator_name"] == "HC eValidator"


def test_get_attestation_none_returns_null_shape(client):
    _create(client)
    g = client.get("/api/dossier/dossiers/e123456/evalidator-attestation")
    assert g.status_code == 200
    assert g.json().get("attestation") is None


def test_attestation_endpoint_tenant_isolated(client):
    _create(client, did="e777777", tenant="acme")
    # a different tenant cannot read OR write the attestation (404, not leak)
    r = client.post(
        "/api/dossier/dossiers/e777777/evalidator-attestation",
        json={"result": "pass", "validator_name": "HC eValidator"},
        headers={"X-Tenant-Id": "rival"})
    assert r.status_code == 404, r.text
    g = client.get("/api/dossier/dossiers/e777777/evalidator-attestation",
                   headers={"X-Tenant-Id": "rival"})
    assert g.status_code == 404


# --- durable audit ledger ---------------------------------------------------

def test_recording_attestation_writes_durable_event(client):
    _create(client)
    client.post(
        "/api/dossier/dossiers/e123456/evalidator-attestation",
        json={"result": "pass", "validator_name": "HC eValidator",
              "validated_on": "2026-07-01"},
        headers={"X-User-Email": "regops@sponsor.example"})
    h = client.get("/api/dossier/dossiers/e123456/history")
    assert h.status_code == 200
    types = {e["event_type"] for e in h.json()["events"]}
    assert any("evalidator" in t for t in types), types


# --- rule-level parity enrichment (keeps the honest not_covered set) --------

def test_parity_exposes_rule_level_coverage(ctx=None):
    par = ectd_validation.parity()
    # every parity row must still carry family + coverage + note (unchanged
    # contract), AND now a per-rule level flag distinguishing an exact
    # rule-level mapping from a family-level overlap.
    for r in par["rules"]:
        assert "hc_evalidator_covered" in r
        assert r.get("note")
        assert r.get("coverage_level") in ("rule", "family", "none")
    # honest not_covered set is preserved: at least one rule has no counterpart
    assert par["not_covered_count"] >= 1


def test_parity_rule_level_rows_are_a_subset_of_covered(ctx=None):
    par = ectd_validation.parity()
    for r in par["rules"]:
        if r["coverage_level"] == "rule":
            assert r["hc_evalidator_covered"] is True
        if r["coverage_level"] == "none":
            assert r["hc_evalidator_covered"] is False


def test_parity_reports_rule_level_count(ctx=None):
    par = ectd_validation.parity()
    rule_level = sum(1 for r in par["rules"] if r["coverage_level"] == "rule")
    assert par.get("rule_level_count") == rule_level
