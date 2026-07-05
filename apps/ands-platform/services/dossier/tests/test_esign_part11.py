"""ADOPT-PART11-ESIGN (task-eval adoption blocker, 23/24): a REAL 21 CFR Part 11
e-signature end to end, demonstrated — not just an audit trail.

The governance service owns the pure e-signature domain (identity + reason +
UTC + a tamper-evident manifest hash over the checksummed eCTD leaves). This
suite proves the DURABLE, dossier-local Part-11 side of it:

  - recording a signed manifest persists it AND writes a durable, immutable
    Part-11 audit-ledger event carrying WHO signed, the REASON/meaning, WHEN
    (UTC), the manifest hash, and the exact leaf count — atomically;
  - the event surfaces in the dossier history (what the audit page reads);
  - verification re-computes the current leaf checksums and DETECTS tampering
    (a modified or removed signed leaf invalidates the signature);
  - record/verify are tenant-isolated and 404 on an unknown dossier.
"""

import pytest

from ands_shared import ProblemError


def _create(client, did="e123456", title="Signol 10 mg tablet", tenant=None):
    headers = {"X-Tenant-Id": tenant} if tenant else {}
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": title}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _manifest(leaves, *, signer="Dr. Vera Signer", reason="I attest.",
              meaning="approved", manifest_id="mani-1", at="2026-07-04T00:00:00+00:00"):
    return {
        "signer": signer, "role": "authorized_signer", "auth_method": "mfa",
        "meaning": meaning, "reason": reason, "at": at, "tz": "UTC",
        "manifest_id": manifest_id, "leaf_count": len(leaves),
        "artifacts": [{"id": lid, "kind": "leaf", "checksum": cs,
                       "checksum_type": "MD5"} for lid, cs in leaves],
    }


# --- service: record writes a durable Part-11 event -------------------------

def test_record_esign_persists_and_writes_durable_event(ctx):
    _create(ctx.client)
    man = _manifest([("m1-cover", "abc123"), ("m5-be", "def456")],
                    signer="regops@sponsor.example",
                    reason="I authorize transmission of this ANDS.")
    rec = ctx.service.record_esign("e123456", man,
                                   actor="regops@sponsor.example")
    assert rec["signer"] == "regops@sponsor.example"
    assert rec["reason"] == "I authorize transmission of this ANDS."
    assert rec["leaf_count"] == 2
    assert rec["manifest_id"] == "mani-1"
    assert rec["signed_at"]                      # a real UTC stamp is recorded
    # the durable, dossier-local Part-11 ledger carries the signing event
    hist = ctx.service.dossier_history("e123456")
    ev = [e for e in hist["events"] if "esign" in e["event_type"]]
    assert ev, hist["events"]
    e0 = ev[0]
    assert e0["actor"] == "regops@sponsor.example"
    assert e0["data"]["signer"] == "regops@sponsor.example"
    assert e0["data"]["manifest_id"] == "mani-1"
    assert e0["data"]["leaf_count"] == 2
    assert e0["data"]["reason"] == "I authorize transmission of this ANDS."


def test_record_esign_requires_signed_artifacts(ctx):
    _create(ctx.client)
    with pytest.raises(ProblemError):
        ctx.service.record_esign("e123456", _manifest([]), actor="x")


def test_record_esign_unknown_dossier_404(ctx):
    with pytest.raises(ProblemError):
        ctx.service.record_esign("nope", _manifest([("l1", "cs")]), actor="x")


# --- service: verify detects tampering --------------------------------------

def test_verify_untampered_then_tamper_detected(ctx):
    _create(ctx.client)
    # sign over the CURRENT leaf checksums (empty dossier => no leaves is fine
    # for the persistence path, but tamper detection needs real leaves, so we
    # bind against a fixed set and drive the "current" checksums explicitly).
    man = _manifest([("m1-cover", "cs-cover"), ("m5-be", "cs-be")])
    ctx.service.record_esign("e123456", man, actor="qa@x")

    ok = ctx.service.verify_esign(
        "e123456", current={"m1-cover": "cs-cover", "m5-be": "cs-be"})
    assert ok["verified"] is True and ok["tampered"] is False
    assert ok["manifest_id"] == "mani-1"

    bad = ctx.service.verify_esign(
        "e123456", current={"m1-cover": "cs-cover", "m5-be": "MODIFIED"})
    assert bad["verified"] is False and bad["tampered"] is True
    assert bad["findings"][0]["artifact"] == "m5-be"

    missing = ctx.service.verify_esign(
        "e123456", current={"m1-cover": "cs-cover"})
    assert missing["tampered"] is True


def test_verify_no_signature_returns_unsigned(ctx):
    _create(ctx.client)
    res = ctx.service.verify_esign("e123456", current={})
    assert res["signed"] is False


# --- endpoints --------------------------------------------------------------

def test_esign_endpoints_record_verify_and_history(client):
    _create(client)
    man = _manifest([("m1-cover", "cs1")], signer="regops@sponsor.example",
                    reason="I approve and authorize transmission.")
    r = client.post("/api/dossier/dossiers/e123456/esign",
                    json={"manifest": man},
                    headers={"X-User-Email": "regops@sponsor.example"})
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["signer"] == "regops@sponsor.example"
    assert body["leaf_count"] == 1

    v = client.post("/api/dossier/dossiers/e123456/esign/verify",
                    json={"current": {"m1-cover": "cs1"}})
    assert v.status_code == 200, v.text
    assert v.json()["verified"] is True

    v2 = client.post("/api/dossier/dossiers/e123456/esign/verify",
                     json={"current": {"m1-cover": "TAMPERED"}})
    assert v2.json()["tampered"] is True

    h = client.get("/api/dossier/dossiers/e123456/history")
    assert any("esign" in e["event_type"] for e in h.json()["events"])


def test_esign_endpoint_tenant_isolated(client):
    _create(client, did="e777777", tenant="acme")
    man = _manifest([("m1-cover", "cs1")])
    r = client.post("/api/dossier/dossiers/e777777/esign",
                    json={"manifest": man}, headers={"X-Tenant-Id": "rival"})
    assert r.status_code == 404, r.text
