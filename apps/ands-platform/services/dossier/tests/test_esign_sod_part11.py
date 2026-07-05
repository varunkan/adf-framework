"""TIER2-ROLE-SEP (durable, dossier-local side): the e-signer must be a
DISTINCT authorized approver from the AUTHOR(S) of the content being signed —
segregation of duties for Part-11 defensibility.

Grounding: content is authored via upload/generate/confirm; the acting user's
identity flows in as ``audit_hook._actor``. We record that identity as the
section's ``content_author`` and expose the distinct author set for a dossier.
``record_esign`` then runs the SoD check (signer vs authors), records the
outcome on the Part-11 manifest + audit event, and — when the tenant enforces
it — REJECTS a signature whose signer is also an author.
"""

import pytest

from ands_shared import ProblemError
from app import audit_hook


def _create(client, did="e900001", title="Signol 10 mg tablet", tenant=None,
            user=""):
    headers = {}
    if tenant:
        headers["X-Tenant-Id"] = tenant
    if user:
        headers["X-User-Email"] = user
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _manifest(leaves, *, signer, reason="I attest.", meaning="approved",
              manifest_id="mani-sod", at="2026-07-04T00:00:00+00:00",
              enforce=False, authors=None):
    return {
        "signer": signer, "role": "authorized_signer", "auth_method": "mfa",
        "meaning": meaning, "reason": reason, "at": at, "tz": "UTC",
        "manifest_id": manifest_id, "leaf_count": len(leaves),
        "artifacts": [{"id": lid, "kind": "leaf", "checksum": cs,
                       "checksum_type": "MD5"} for lid, cs in leaves],
        # the durable side re-derives authors from recorded content; a caller
        # may also pass them explicitly (the web sign step does).
        **({"authors": authors} if authors is not None else {}),
        **({"enforce_segregation": True} if enforce else {}),
    }


# --- authorship is recorded on the section content --------------------------

def test_uploaded_content_records_its_author(ctx):
    _create(ctx.client, user="amir@sponsor.example")
    audit_hook.set_actor("amir@sponsor.example")
    try:
        ctx.service.upload_document("e900001", "1.0", "cover.pdf",
                                    "application/pdf", b"%PDF-1.4 cover")
    finally:
        audit_hook.set_actor("")
    authors = ctx.service.content_authors("e900001")
    assert "amir@sponsor.example" in authors["authors"]


# --- record_esign surfaces the SoD outcome ----------------------------------

def test_record_esign_flags_signer_is_author_conflict(ctx):
    audit_hook.set_actor("amir@sponsor.example")
    try:
        _create(ctx.client, user="amir@sponsor.example")
        ctx.service.upload_document("e900001", "1.0", "cover.pdf",
                                    "application/pdf", b"%PDF-1.4 cover")
    finally:
        audit_hook.set_actor("")
    man = _manifest([("m1-cover", "abc123")], signer="amir@sponsor.example")
    rec = ctx.service.record_esign("e900001", man, actor="amir@sponsor.example")
    sod = rec["segregation_of_duties"]
    assert sod["conflict"] is True
    assert "amir@sponsor.example" in sod["conflicting_authors"]
    # honesty: it is a role-separation check, not an SSO/IdP claim
    assert "SSO" not in sod["reason"]


def test_record_esign_clean_when_signer_distinct(ctx):
    audit_hook.set_actor("amir@sponsor.example")
    try:
        _create(ctx.client, user="amir@sponsor.example")
        ctx.service.upload_document("e900001", "1.0", "cover.pdf",
                                    "application/pdf", b"%PDF-1.4 cover")
    finally:
        audit_hook.set_actor("")
    man = _manifest([("m1-cover", "abc123")], signer="qa@sponsor.example")
    rec = ctx.service.record_esign("e900001", man, actor="qa@sponsor.example")
    assert rec["segregation_of_duties"]["conflict"] is False
    assert rec["segregation_of_duties"]["separated"] is True


def test_record_esign_hard_block_when_enforced_and_conflict(ctx):
    audit_hook.set_actor("amir@sponsor.example")
    try:
        _create(ctx.client, user="amir@sponsor.example")
        ctx.service.upload_document("e900001", "1.0", "cover.pdf",
                                    "application/pdf", b"%PDF-1.4 cover")
    finally:
        audit_hook.set_actor("")
    man = _manifest([("m1-cover", "abc123")], signer="amir@sponsor.example",
                    enforce=True)
    with pytest.raises(ProblemError) as exc:
        ctx.service.record_esign("e900001", man, actor="amir@sponsor.example")
    assert exc.value.extra.get("rule") == "segregation_of_duties"


def test_record_esign_writes_sod_onto_audit_event(ctx):
    audit_hook.set_actor("amir@sponsor.example")
    try:
        _create(ctx.client, user="amir@sponsor.example")
        ctx.service.upload_document("e900001", "1.0", "cover.pdf",
                                    "application/pdf", b"%PDF-1.4 cover")
    finally:
        audit_hook.set_actor("")
    man = _manifest([("m1-cover", "abc123")], signer="amir@sponsor.example")
    ctx.service.record_esign("e900001", man, actor="amir@sponsor.example")
    hist = ctx.service.dossier_history("e900001")
    ev = [e for e in hist["events"] if "esign" in e["event_type"]]
    assert ev
    assert ev[0]["data"]["sod_conflict"] is True
    assert ev[0]["data"]["sod_separated"] is False


# --- endpoint carries the SoD outcome ---------------------------------------

def test_esign_endpoint_returns_sod(client):
    # the web sign step supplies the authors it displayed inline; the endpoint
    # threads them through the SoD check and returns the outcome.
    _create(client, user="amir@sponsor.example")
    man = _manifest([("m1-cover", "cs1")], signer="amir@x",
                    authors=["amir@x"])
    r = client.post("/api/dossier/dossiers/e900001/esign",
                    json={"manifest": man},
                    headers={"X-User-Email": "amir@x"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["segregation_of_duties"]["conflict"] is True
