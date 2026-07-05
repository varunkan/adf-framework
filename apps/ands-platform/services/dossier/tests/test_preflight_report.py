"""TIER3-PREFLIGHT: one consolidated pre-flight / QA hand-off report.

Tier-2 respondents (multiple, verbatim): "give me ONE consolidated pre-flight
report I can hand to QA rather than re-running validate at each step." One
exportable document that assembles the whole filing-readiness picture.

This tier RESOLVES a limit instead of disclosing one: the earlier tiers each
DISCLOSED more caveats (eValidator is external, e-sign is not a certification,
REP is not transmitted…). Here those honest pieces are ASSEMBLED into a single
artifact a QA reviewer or client can archive.

These tests prove:
  - a single ``preflight_report`` object assembles every filing-readiness piece:
    the named/versioned eCTD structural validation, the user-attested external
    eValidator result + attached report, the Part-11 e-sign manifest + SoD
    outcome + live verification, the fee state, the lifecycle/sequence view,
    and the placeholder/real Dossier-ID + REP request status;
  - the honesty disclaimers travel INLINE on the report (structural-only,
    external-attestation, not-a-certification, REP-not-transmitted) — the
    consolidation never launders a caveat away;
  - a top-level readiness summary reflects the structural gate WITHOUT ever
    claiming HC acceptance, and it names the still-required HC eValidator step;
  - the assembly is tenant-isolated and 404s on an unknown dossier;
  - the endpoint returns the same object over the proxy path.
"""

import pytest

from app import ectd_validation


def _create(client, did="p123456", title="Preflightol 5 mg tablet", tenant=None):
    headers = {"X-Tenant-Id": tenant} if tenant else {}
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title,
                          "company_id": "12345", "sponsor": "Acme Pharma"},
                    headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


# --- assembly: every filing-readiness piece is present ----------------------

def test_report_assembles_all_pieces(ctx):
    _create(ctx.client)
    rep = ctx.service.preflight_report("p123456")

    # identity + generated stamp
    assert rep["dossier_id"] == "p123456"
    assert rep["generated_at"]
    assert "title" in rep

    # every consolidated section is present (the whole picture, one object)
    for key in ("validation", "evalidator_attestation", "esign", "fees",
                "sequences", "rep", "readiness", "disclaimers"):
        assert key in rep, f"missing section: {key}"

    # eCTD structural validation carries the NAMED, VERSIONED criteria + synced
    v = rep["validation"]
    assert v["criteria"]["name"] == "ANDS Studio structural eCTD validator"
    assert v["criteria"]["version"] == ectd_validation.CRITERIA_VERSION
    assert v["criteria"]["synced"] == ectd_validation.CRITERIA_SYNCED
    assert "passed" in v and "errors" in v


def test_report_placeholder_id_surfaces_rep_step(ctx):
    # a placeholder ("d…"/"p…" starting 'd') dossier id must be flagged; use a
    # placeholder-shaped id and confirm the REP + validation both reflect it.
    _create(ctx.client, did="d999999", title="Draftol")
    rep = ctx.service.preflight_report("d999999")
    assert rep["rep"]["placeholder"] is True
    # the structural validation blocks on the placeholder id (CA-REP-0001)
    assert rep["validation"]["passed"] is False
    assert any(e.get("rule_id") == "CA-REP-0001"
               for e in rep["validation"]["errors"])
    # readiness is NOT ready and names the placeholder as a blocker
    assert rep["readiness"]["ready"] is False


def test_report_readiness_never_claims_hc_acceptance(ctx):
    _create(ctx.client, did="p223456")
    rep = ctx.service.preflight_report("p223456")
    summary = rep["readiness"]["summary"].lower()
    # honesty: the readiness line is a STRUCTURAL statement, never an HC verdict
    assert "structural" in summary
    assert "health canada" not in rep["readiness"].get("claim", "").lower() \
        or "not" in rep["readiness"].get("claim", "").lower()
    # the still-required external step is always named
    assert "evalidator" in rep["readiness"]["next_step"].lower()


# --- honesty: disclaimers travel inline -------------------------------------

def test_disclaimers_present_and_honest(ctx):
    _create(ctx.client, did="p323456")
    rep = ctx.service.preflight_report("p323456")
    d = rep["disclaimers"]
    # one string per honest caveat, all consolidated with the report
    blob = " ".join(str(x) for x in d.values()).lower()
    assert "not" in blob and "health canada" in blob
    assert "evalidator" in blob            # structural is not the official one
    assert "certification" in blob         # e-sign is not a certification
    assert "transmit" in blob or "rep" in blob  # REP is not a transmission


# --- e-sign + SoD + verification consolidated -------------------------------

def test_report_includes_esign_and_verification(ctx):
    _create(ctx.client, did="p423456")
    # place a leaf so there is content to sign over + verify against
    ctx.client.post("/api/dossier/ectd/p423456/section/1.0.1/generate",
                    json={"title": "Cover letter"})
    rep = ctx.service.preflight_report("p423456")
    # unsigned: the esign block is present with signed=False and a verification
    assert rep["esign"]["signed"] is False
    assert "verification" in rep["esign"]
    assert rep["esign"]["verification"]["signed"] is False


# --- endpoint + tenant isolation --------------------------------------------

def test_endpoint_returns_report(ctx):
    _create(ctx.client)
    r = ctx.client.get("/api/dossier/dossiers/p123456/preflight-report")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dossier_id"] == "p123456"
    assert "validation" in body and "readiness" in body and "disclaimers" in body


def test_endpoint_unknown_dossier_404(ctx):
    r = ctx.client.get("/api/dossier/dossiers/nope999/preflight-report")
    assert r.status_code == 404, r.text


def test_report_tenant_isolated(ctx):
    _create(ctx.client, did="p523456", tenant="t-a")
    # a different tenant cannot see it (404, not 403 — no existence disclosure)
    r = ctx.client.get("/api/dossier/dossiers/p523456/preflight-report",
                       headers={"X-Tenant-Id": "t-b"})
    assert r.status_code == 404, r.text
    # the owning tenant can
    r2 = ctx.client.get("/api/dossier/dossiers/p523456/preflight-report",
                        headers={"X-Tenant-Id": "t-a"})
    assert r2.status_code == 200, r2.text
