"""TIER2-PARITY-UX (task-eval post-adopt asks): the three things regulatory
personas named to move from "I'd trial it" to "I'd ADOPT it":

  1. Attach the ACTUAL eValidator report FILE (bytes + filename), not just the
     filename string — surfaced as downloadable attached evidence on the
     user-attested external attestation.
  2. Self-serve "validate a known-good sequence": point the SAME structural
     validator at a prior/known-good sequence and see it pass too (honest
     confidence-building — structural only, never a parity claim).
  3. File the REP Dossier-ID Request from inside the placeholder banner: an
     in-app helper that RECORDS the request intent + returns guidance. Honest:
     it prepares/guides, it does NOT transmit to Health Canada.

These tests are written FIRST (RED) and drive the backend implementation. They
extend the ADOPT-EVALIDATOR loop-closer; they never rewrite it.
"""

import pytest

from ands_shared import ProblemError


def _create(client, did="e123456", title="Attestol 10 mg tablet", tenant=None):
    headers = {"X-Tenant-Id": tenant} if tenant else {}
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


# =====================================================================
# 1) eValidator report FILE (bytes + filename) attached as evidence
# =====================================================================

def test_attach_report_stores_bytes_and_links_them(ctx):
    _create(ctx.client)
    # a prior attestation is NOT required — attaching the report file records the
    # evidence and (when absent) seeds the attestation with the report metadata.
    rec = ctx.service.attach_evalidator_report(
        "e123456", filename="e123456-0000-evalidator.pdf",
        content_type="application/pdf",
        body=b"%PDF-1.4 eValidator report bytes",
        actor="regops@sponsor.example")
    att = rec["attestation"]
    assert att["report_doc_id"], "the stored report must be linked by doc id"
    assert att["report_filename"] == "e123456-0000-evalidator.pdf"
    assert att["report_content_type"] == "application/pdf"
    assert att["report_size"] == len(b"%PDF-1.4 eValidator report bytes")
    assert att["report_checksum"], "the stored report must carry a checksum"
    # honesty label is never dropped when a report file is attached
    assert att["source"] == "user_attested_external"
    assert "disclaimer" in att


def test_attach_report_preserves_existing_attestation_result(ctx):
    _create(ctx.client)
    ctx.service.set_evalidator_attestation(
        "e123456",
        {"result": "pass", "validator_name": "HC eValidator",
         "validator_version": "5.3", "validated_on": "2026-07-01"},
        actor="regops@sponsor.example")
    rec = ctx.service.attach_evalidator_report(
        "e123456", filename="report.pdf", content_type="application/pdf",
        body=b"%PDF-1.4 report", actor="regops@sponsor.example")
    att = rec["attestation"]
    # attaching the file must NOT wipe the recorded pass/fail + validator fields
    assert att["result"] == "pass"
    assert att["validator_name"] == "HC eValidator"
    assert att["validator_version"] == "5.3"
    assert att["report_doc_id"]


def test_attached_report_is_downloadable(ctx):
    _create(ctx.client)
    body = b"%PDF-1.4 downloadable eValidator report"
    ctx.service.attach_evalidator_report(
        "e123456", filename="report.pdf", content_type="application/pdf",
        body=body, actor="x")
    att = ctx.service.get_evalidator_attestation("e123456")["attestation"]
    doc = ctx.service.get_document(att["report_doc_id"])
    assert doc["body"] == body


def test_attach_report_rejects_empty_body(ctx):
    _create(ctx.client)
    with pytest.raises(ProblemError):
        ctx.service.attach_evalidator_report(
            "e123456", filename="report.pdf", content_type="application/pdf",
            body=b"", actor="x")


def test_attach_report_unknown_dossier_404(ctx):
    with pytest.raises(ProblemError):
        ctx.service.attach_evalidator_report(
            "nope", filename="r.pdf", content_type="application/pdf",
            body=b"%PDF-1.4", actor="x")


def test_attach_report_writes_durable_event(client):
    _create(client)
    files = {"file": ("report.pdf", b"%PDF-1.4 report", "application/pdf")}
    r = client.post(
        "/api/dossier/dossiers/e123456/evalidator-attestation/report",
        files=files, headers={"X-User-Email": "regops@sponsor.example"})
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["attestation"]["report_doc_id"]
    h = client.get("/api/dossier/dossiers/e123456/history")
    types = {e["event_type"] for e in h.json()["events"]}
    assert any("report" in t for t in types), types


def test_attach_report_endpoint_tenant_isolated(client):
    _create(client, did="e777777", tenant="acme")
    files = {"file": ("report.pdf", b"%PDF-1.4", "application/pdf")}
    r = client.post(
        "/api/dossier/dossiers/e777777/evalidator-attestation/report",
        files=files, headers={"X-Tenant-Id": "rival"})
    assert r.status_code == 404, r.text


# =====================================================================
# 2) Self-serve: validate a known-good (prior) sequence structurally
# =====================================================================

def _place_leaf(service, did, sequence, leaf_id, section="1.0.1"):
    """Place a real, valid live leaf in a sequence via the assembly service."""
    service.add_leaf({
        "dossier_id": did, "sequence": sequence,
        "leaf": {"leaf_id": leaf_id, "heading": section, "title": "Cover",
                 "href": f"m1/ca/10-cover/{leaf_id}.pdf",
                 "operation": "new", "content": b"%PDF-1.4 cover"}}, None)


def test_validate_sequence_scopes_to_one_sequence(ctx):
    _create(ctx.client, did="e222222")
    _place_leaf(ctx.service, "e222222", "0000", "cover-a")
    res = ctx.service.validate_sequence("e222222", "0000")
    assert res["sequence"] == "0000"
    assert "passed" in res
    # honest scope: this is the SAME structural validator, clearly labeled, and
    # never a claim of HC eValidator parity — the criteria/disclaimer travels.
    assert res["criteria"]["disclaimer"]
    assert res.get("scope") == "sequence"


def test_validate_known_good_sequence_passes(ctx):
    _create(ctx.client, did="e333333")
    _place_leaf(ctx.service, "e333333", "0000", "cover-good")
    res = ctx.service.validate_sequence("e333333", "0000")
    # a well-formed known-good sequence passes the structural check — this is the
    # confidence-building "it passes here too" the personas asked for.
    assert res["passed"] is True, res["errors"]


def test_validate_sequence_unknown_sequence_404(ctx):
    _create(ctx.client, did="e444444")
    _place_leaf(ctx.service, "e444444", "0000", "cover-x")
    with pytest.raises(ProblemError):
        ctx.service.validate_sequence("e444444", "9999")


def test_validate_sequence_endpoint(client):
    _create(client, did="e555555")
    client.post("/api/dossier/ectd/leaf", json={
        "dossier_id": "e555555", "sequence": "0000",
        "leaf": {"leaf_id": "cover-e", "heading": "1.0.1", "title": "Cover",
                 "href": "m1/ca/10-cover/cover-e.pdf", "operation": "new",
                 "content": "%PDF-1.4 cover"}})
    r = client.get("/api/dossier/dossiers/e555555/validate/sequence/0000")
    assert r.status_code == 200, r.text
    assert r.json()["sequence"] == "0000"


def test_validate_sequence_endpoint_tenant_isolated(client):
    _create(client, did="e666666", tenant="acme")
    r = client.get("/api/dossier/dossiers/e666666/validate/sequence/0000",
                   headers={"X-Tenant-Id": "rival"})
    assert r.status_code == 404


# =====================================================================
# 3) REP Dossier-ID Request helper — records intent + guidance (honest)
# =====================================================================

def test_rep_request_records_intent_and_returns_guidance(ctx):
    _create(ctx.client, did="d123456", title="Draftazole")
    rec = ctx.service.request_rep_dossier_id(
        "d123456",
        data={"company_id": "12345", "sponsor": "Acme Pharma Inc.",
              "activity_type": "ANDS",
              "contact_email": "regops@acme.example"},
        actor="regops@acme.example")
    # HONEST: it prepares/guides — it does NOT transmit to Health Canada.
    assert rec["transmitted"] is False
    assert rec["dossier_id"] == "d123456"
    assert rec["company_id"] == "12345"
    # concrete next-step guidance (REP via CESG WebTrader) is returned
    assert rec["guidance"]
    assert any("REP" in _s(step) or "CESG" in _s(step)
               for step in rec["guidance"]["steps"])
    # it flags this is a placeholder dossier that needs the real ID next
    assert rec["placeholder"] is True


def _s(v):
    return str(v or "")


def test_rep_request_writes_durable_event(client):
    _create(client, did="d654321")
    r = client.post(
        "/api/dossier/dossiers/d654321/rep-request",
        json={"company_id": "999", "sponsor": "Beta Labs",
              "activity_type": "ANDS"},
        headers={"X-User-Email": "regops@beta.example"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["transmitted"] is False
    h = client.get("/api/dossier/dossiers/d654321/history")
    types = {e["event_type"] for e in h.json()["events"]}
    assert any("rep" in t.lower() for t in types), types


def test_rep_request_reads_back_the_recorded_intent(client):
    _create(client, did="d112233")
    client.post(
        "/api/dossier/dossiers/d112233/rep-request",
        json={"company_id": "42", "sponsor": "Gamma", "activity_type": "SANDS"},
        headers={"X-User-Email": "u@gamma.example"})
    g = client.get("/api/dossier/dossiers/d112233/rep-request")
    assert g.status_code == 200
    rr = g.json()["rep_request"]
    assert rr is not None
    assert rr["company_id"] == "42"
    assert rr["transmitted"] is False


def test_rep_request_unknown_dossier_404(ctx):
    with pytest.raises(ProblemError):
        ctx.service.request_rep_dossier_id(
            "nope", data={"company_id": "1"}, actor="x")


def test_rep_request_endpoint_tenant_isolated(client):
    _create(client, did="d778899", tenant="acme")
    r = client.post(
        "/api/dossier/dossiers/d778899/rep-request",
        json={"company_id": "1"}, headers={"X-Tenant-Id": "rival"})
    assert r.status_code == 404
