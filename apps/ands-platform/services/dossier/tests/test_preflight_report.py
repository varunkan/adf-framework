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

from app import audit_hook, ectd_validation


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


# --- FIX-PREFLIGHT-SIG: loud, unambiguous signature status ------------------
#
# The pre-flight report previously surfaced a bare ``signature_verified=false``
# after a leaf changed (or a conflict-demo sign) since signing. A QA reviewer
# has no way to tell "never signed" from "signed but the package changed after"
# from "signer was an author". These tests pin an explicit ``signature_status``
# (one of unsigned / verified / stale_unverified / sod_conflict), a plain-
# language message, a ``handoff_ready_signature`` boolean, and demand the
# top-level readiness reflect it (a stale/conflicted signature is NOT
# hand-off-ready).

def _place_leaf(ctx, did, *, author, body=b"%PDF-1.4 cover"):
    """Author one leaf under a recorded author, returning its live checksum
    map (the exact set a manifest is signed + verified against)."""
    audit_hook.set_actor(author)
    try:
        ctx.service.upload_document(did, "1.0", "cover.pdf",
                                    "application/pdf", body)
    finally:
        audit_hook.set_actor("")
    return ctx.service._current_leaf_checksums(did)


def _manifest(leaves, *, signer, manifest_id="mani-pf"):
    return {
        "signer": signer, "role": "authorized_signer", "auth_method": "mfa",
        "meaning": "approved", "reason": "I attest.",
        "at": "2026-07-04T00:00:00+00:00", "tz": "UTC",
        "manifest_id": manifest_id, "leaf_count": len(leaves),
        "artifacts": [{"id": lid, "kind": "leaf", "checksum": cs,
                       "checksum_type": "MD5"} for lid, cs in leaves.items()],
    }


def test_signature_status_unsigned(ctx):
    _create(ctx.client, did="p623456")
    rep = ctx.service.preflight_report("p623456")
    esign = rep["esign"]
    assert esign["signature_status"] == "unsigned"
    assert esign["handoff_ready_signature"] is False
    assert esign["message"]                       # a plain-language line exists
    # readiness never claims a signature is in place when none is
    assert rep["readiness"]["signature_status"] == "unsigned"
    assert rep["readiness"]["handoff_ready_signature"] is False


def test_signature_status_verified_when_signed_clean(ctx):
    _create(ctx.client, did="p723456")
    leaves = _place_leaf(ctx, "p723456", author="author@sponsor.example")
    # a DISTINCT signer over the CURRENT package -> verify passes, no SoD clash
    ctx.service.record_esign(
        "p723456", _manifest(leaves, signer="qa@sponsor.example"),
        actor="qa@sponsor.example")
    rep = ctx.service.preflight_report("p723456")
    esign = rep["esign"]
    assert esign["signature_status"] == "verified"
    assert esign["handoff_ready_signature"] is True
    assert "verified" in esign["message"].lower()
    assert rep["readiness"]["signature_status"] == "verified"
    assert rep["readiness"]["handoff_ready_signature"] is True


def test_signature_status_stale_unverified_after_leaf_change(ctx):
    _create(ctx.client, did="p823456")
    leaves = _place_leaf(ctx, "p823456", author="author@sponsor.example")
    ctx.service.record_esign(
        "p823456", _manifest(leaves, signer="qa@sponsor.example"),
        actor="qa@sponsor.example")
    # the package CHANGES after signing (e.g. a 0001 replace / re-upload) — the
    # stored signature is now legitimately stale. The report must FLAG it, not
    # show a bare verified=false a QA reviewer would trip over.
    _place_leaf(ctx, "p823456", author="author@sponsor.example",
                body=b"%PDF-1.4 cover REVISED")
    rep = ctx.service.preflight_report("p823456")
    esign = rep["esign"]
    assert esign["signature_status"] == "stale_unverified"
    assert esign["handoff_ready_signature"] is False
    # the message explains WHY and what to do (re-sign the current package)
    assert "re-sign" in esign["message"].lower()
    # a stale signature is NOT hand-off-ready at the top level
    assert rep["readiness"]["signature_status"] == "stale_unverified"
    assert rep["readiness"]["handoff_ready_signature"] is False


def test_signature_status_sod_conflict_when_author_signs(ctx):
    _create(ctx.client, did="p923456")
    # the SAME identity authors AND signs — a segregation-of-duties conflict.
    # Under the default (warn) posture the signature is recorded but the report
    # must call it out as a conflict, not a clean 'verified'.
    leaves = _place_leaf(ctx, "p923456", author="amir@sponsor.example")
    ctx.service.record_esign(
        "p923456", _manifest(leaves, signer="amir@sponsor.example"),
        actor="amir@sponsor.example")
    rep = ctx.service.preflight_report("p923456")
    esign = rep["esign"]
    assert esign["signature_status"] == "sod_conflict"
    assert esign["handoff_ready_signature"] is False
    assert "author" in esign["message"].lower()
    assert rep["readiness"]["signature_status"] == "sod_conflict"
    assert rep["readiness"]["handoff_ready_signature"] is False


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
