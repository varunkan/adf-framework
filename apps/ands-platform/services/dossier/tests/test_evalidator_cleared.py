"""POLISH-EVAL-CLEARED: "eValidator-cleared" as a FIRST-CLASS, visible dossier
state — not merely an attachment buried on the attestation record.

The ra_director / ra_officer ask (verbatim): "let me attach the actual eValidator
report and mark the filing 'eValidator-cleared' as a first-class state." The
report attachment already exists (TIER2-PARITY-UX); the missing piece is a
first-class, honestly-labeled CLEARED state that any surface (dossier state,
pre-flight readiness, validation) can key off.

HONESTY (the whole point): "cleared" is USER-ATTESTED EXTERNAL evidence, never a
tool self-claim of HC eValidator parity. It requires BOTH:
  - a recorded PASS (result == "pass"), AND
  - the ACTUAL report file attached (report_doc_id present),
so a bare pass with no report — or a report with no pass — is NOT cleared. The
honesty disclaimer + source label always travel with the state.

These tests are written FIRST (RED) and drive the backend. They EXTEND the
ADOPT-EVALIDATOR + TIER2-PARITY-UX loop; they never rewrite it.
"""


def _create(client, did="e123456", title="Attestol 10 mg tablet", tenant=None):
    headers = {"X-Tenant-Id": tenant} if tenant else {}
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


# --- the pure state helper --------------------------------------------------

def test_cleared_requires_pass_and_report(ctx):
    svc = ctx.service
    # nothing attested -> not cleared
    st = svc.evalidator_cleared_state(None)
    assert st["cleared"] is False
    assert st["source"] == "user_attested_external"
    assert st["disclaimer"]
    # a bare PASS with NO report file is NOT cleared (report is required evidence)
    st = svc.evalidator_cleared_state(
        {"source": "user_attested_external", "result": "pass",
         "validator_name": "HC eValidator"})
    assert st["cleared"] is False
    assert st["result"] == "pass"
    assert st["report_present"] is False
    # a report attached but result == fail is NOT cleared
    st = svc.evalidator_cleared_state(
        {"source": "user_attested_external", "result": "fail",
         "validator_name": "HC eValidator", "report_doc_id": "doc-1"})
    assert st["cleared"] is False
    assert st["report_present"] is True
    # PASS + report attached -> CLEARED
    st = svc.evalidator_cleared_state(
        {"source": "user_attested_external", "result": "pass",
         "validator_name": "HC eValidator", "report_doc_id": "doc-1",
         "report_filename": "e123456-0000-evalidator.pdf",
         "attested_by": "regops@sponsor.example", "validated_on": "2026-07-01"})
    assert st["cleared"] is True
    assert st["report_present"] is True
    # the honest label + downloadable report metadata travel on the state
    assert st["source"] == "user_attested_external"
    assert st["validator_name"] == "HC eValidator"
    assert st["report_doc_id"] == "doc-1"
    assert st["report_filename"] == "e123456-0000-evalidator.pdf"
    assert st["attested_by"] == "regops@sponsor.example"
    assert st["validated_on"] == "2026-07-01"


def test_cleared_state_never_self_claims(ctx):
    # the disclaimer must make clear ANDS Studio did not run eValidator itself,
    # even for the CLEARED state — it is user-attested external evidence.
    st = ctx.service.evalidator_cleared_state(
        {"source": "user_attested_external", "result": "pass",
         "validator_name": "HC eValidator", "report_doc_id": "doc-1"})
    d = st["disclaimer"].lower()
    assert "did not run" in d or "external" in d


# --- surfaced on the dossier state (content_state) --------------------------

def test_content_state_carries_evalidator_block(ctx):
    _create(ctx.client)
    st = ctx.service.content_state("e123456")
    assert "evalidator" in st
    assert st["evalidator"]["cleared"] is False

    # attest a PASS but with no report yet -> still not cleared
    ctx.service.set_evalidator_attestation(
        "e123456", {"result": "pass", "validator_name": "HC eValidator"},
        actor="regops@sponsor.example")
    st = ctx.service.content_state("e123456")
    assert st["evalidator"]["cleared"] is False
    assert st["evalidator"]["result"] == "pass"
    assert st["evalidator"]["report_present"] is False

    # attach the actual report -> NOW cleared
    ctx.service.attach_evalidator_report(
        "e123456", filename="e123456-0000-evalidator.pdf",
        content_type="application/pdf",
        body=b"%PDF-1.4 eValidator report bytes",
        actor="regops@sponsor.example")
    st = ctx.service.content_state("e123456")
    assert st["evalidator"]["cleared"] is True
    assert st["evalidator"]["report_present"] is True
    assert st["evalidator"]["report_doc_id"]


def test_content_state_endpoint_exposes_cleared(client):
    _create(client)
    client.post(
        "/api/dossier/dossiers/e123456/evalidator-attestation",
        json={"result": "pass", "validator_name": "HC eValidator"},
        headers={"X-User-Email": "regops@sponsor.example"})
    client.post(
        "/api/dossier/dossiers/e123456/evalidator-attestation/report",
        files={"file": ("evr.pdf", b"%PDF-1.4 bytes", "application/pdf")},
        headers={"X-User-Email": "regops@sponsor.example"})
    r = client.get("/api/dossier/dossiers/e123456/content")
    assert r.status_code == 200, r.text
    ev = r.json().get("evalidator")
    assert ev is not None
    assert ev["cleared"] is True
    assert ev["source"] == "user_attested_external"


# --- surfaced in validate_submission ----------------------------------------

def test_validate_submission_carries_cleared(ctx):
    _create(ctx.client)
    ctx.service.set_evalidator_attestation(
        "e123456", {"result": "pass", "validator_name": "HC eValidator"},
        actor="regops@sponsor.example")
    ctx.service.attach_evalidator_report(
        "e123456", filename="evr.pdf", content_type="application/pdf",
        body=b"%PDF-1.4 bytes", actor="regops@sponsor.example")
    res = ctx.service.validate_submission("e123456")
    assert res["evalidator_cleared"]["cleared"] is True
    # structural `passed` is INDEPENDENT of the external cleared state
    assert "passed" in res


# --- surfaced in the pre-flight readiness -----------------------------------

def test_preflight_readiness_carries_cleared(ctx):
    _create(ctx.client)
    pf = ctx.service.preflight_report("e123456")
    assert pf["readiness"]["evalidator_cleared"] is False
    # a full consolidated cleared block travels on the report too
    assert pf["evalidator_cleared"]["cleared"] is False

    ctx.service.set_evalidator_attestation(
        "e123456", {"result": "pass", "validator_name": "HC eValidator"},
        actor="regops@sponsor.example")
    ctx.service.attach_evalidator_report(
        "e123456", filename="evr.pdf", content_type="application/pdf",
        body=b"%PDF-1.4 bytes", actor="regops@sponsor.example")
    pf = ctx.service.preflight_report("e123456")
    assert pf["readiness"]["evalidator_cleared"] is True
    assert pf["evalidator_cleared"]["cleared"] is True
    # honesty preserved on the readiness — still names the external provenance
    assert pf["evalidator_cleared"]["source"] == "user_attested_external"
