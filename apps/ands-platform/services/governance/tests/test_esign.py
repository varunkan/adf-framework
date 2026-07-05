"""Pure e-signature domain (REQ-039/053/068)."""

from app import esign


def test_qa_review_requires_role_and_confirmation():
    bad = esign.qa_review({"reviewer": "qa", "role": "intern",
                           "audit_trail_reviewed": False})
    rules = {e["rule"] for e in bad["errors"]}
    assert {"role_not_permitted", "audit_trail_not_reviewed"} <= rules
    ok = esign.qa_review({"reviewer": "qa", "audit_trail_reviewed": True})
    assert ok["valid"] and ok["review"]["role"] == "qa_reviewer"


def test_sign_binds_artifact_checksum():
    res = esign.sign({"signer": "vp", "auth_method": "mfa", "meaning": "approved",
                      "artifacts": [{"id": "leaf1", "content": "hello"}]})
    assert res["valid"]
    man = res["manifest"]
    assert man["manifest_id"]
    assert man["artifacts"][0]["checksum"] == esign.artifact_checksum("hello")


def test_sign_captures_reason_utc_and_leaf_count():
    # ADOPT-PART11-ESIGN: a real e-signature records an explicit signing REASON
    # (the human meaning-of-signature statement), a server-stamped UTC timestamp
    # when none is supplied, and the exact count of checksummed leaves signed.
    res = esign.sign({
        "signer": "Dr. Vera Signer", "auth_method": "mfa", "meaning": "approved",
        "reason": "I attest this ANDS is complete and authorized to transmit.",
        "artifacts": [{"id": "l1", "content": "a"}, {"id": "l2", "content": "b"}]})
    assert res["valid"]
    man = res["manifest"]
    assert man["reason"] == \
        "I attest this ANDS is complete and authorized to transmit."
    assert man["leaf_count"] == 2
    # no 'at' provided => the domain stamps a real UTC ISO timestamp itself
    assert man["at"].endswith("+00:00") or man["at"].endswith("Z")
    assert man["tz"] == "UTC"


def test_sign_requires_a_reason():
    res = esign.sign({"signer": "vp", "auth_method": "mfa", "meaning": "approved",
                      "reason": "", "artifacts": [{"id": "l1", "content": "a"}]})
    assert not res["valid"]
    assert "reason_required" in {e["rule"] for e in res["errors"]}


def test_sign_records_recorded_email_by_default():
    # CAMP-SSO-OIDC: with no verified principal, the signature honestly records a
    # *recorded email* — NOT an SSO-verified identity.
    man = esign.sign({"signer": "vera@acme.io", "auth_method": "mfa",
                      "meaning": "approved",
                      "artifacts": [{"id": "l1", "content": "a"}]})["manifest"]
    assert man["identity"]["assurance"] == "recorded_email"
    assert man["identity"]["verified"] is False
    assert "not SSO-verified" in man["identity"]["statement"]


def test_sign_records_sso_verified_principal():
    # CAMP-SSO-OIDC: when the signing session is SSO-backed (issuer + IdP
    # subject), the signature is an AUTHENTICATED PRINCIPAL and the Part-11
    # manifest reflects 'identity: SSO-verified (issuer)'. The signer no longer
    # needs a separate auth_method — the OIDC login IS the (re-)authentication.
    res = esign.sign({
        "signer": "vera@acme.io", "meaning": "approved",
        "identity_verified": True,
        "identity_issuer": "https://idp.acme.io",
        "identity_subject": "idp-sub-77",
        "artifacts": [{"id": "l1", "content": "a"}]})
    assert res["valid"], res.get("errors")
    ident = res["manifest"]["identity"]
    assert ident["assurance"] == "sso_verified"
    assert ident["verified"] is True
    assert ident["issuer"] == "https://idp.acme.io"
    assert ident["subject"] == "idp-sub-77"
    assert ident["statement"] == "identity: SSO-verified (https://idp.acme.io)"
    # the SSO login satisfies the re-authenticate-at-signing requirement
    assert res["manifest"]["auth_method"] == "sso_oidc"


def test_sso_claim_requires_both_issuer_and_subject():
    # honesty guardrail: 'verified' alone (no issuer/subject) must NOT be
    # allowed to claim SSO — it degrades to the truthful recorded-email posture.
    man = esign.sign({"signer": "x@y.io", "auth_method": "mfa",
                      "meaning": "approved", "identity_verified": True,
                      "artifacts": [{"id": "l1", "content": "a"}]})["manifest"]
    assert man["identity"]["assurance"] == "recorded_email"


def test_sign_rejects_wrong_role_and_meaning():
    res = esign.sign({"signer": "x", "role": "qa_reviewer", "auth_method": "",
                      "meaning": "vibes", "artifacts": []})
    rules = {e["rule"] for e in res["errors"]}
    assert {"role_not_permitted", "auth_method_required", "meaning_invalid",
            "artifacts_required"} <= rules


def test_verify_detects_modification():
    man = esign.sign({"signer": "vp", "auth_method": "mfa",
                      "artifacts": [{"id": "leaf1", "content": "hello"}]})["manifest"]
    assert esign.verify_manifest(man, {"leaf1": esign.artifact_checksum("hello")})[
        "tampered"] is False
    bad = esign.verify_manifest(man, {"leaf1": esign.artifact_checksum("changed")})
    assert bad["tampered"] and bad["findings"][0]["rule"] == "signed_content_modified"


def test_gate_requires_review_and_signature():
    blocked = esign.transmission_gate({})
    assert blocked["can_transmit"] is False
    rules = {b["rule"] for b in blocked["blockers"]}
    assert {"qa_review_missing", "signature_missing"} <= rules


def test_gate_passes_then_tamper_reblocks():
    review = esign.qa_review({"reviewer": "qa",
                              "audit_trail_reviewed": True})["review"]
    man = esign.sign({"signer": "vp", "auth_method": "mfa",
                      "artifacts": [{"id": "l1", "content": "x"}]})["manifest"]
    ok = esign.transmission_gate({"review": review, "manifest": man,
                                  "current": {"l1": esign.artifact_checksum("x")}})
    assert ok["can_transmit"] is True
    tampered = esign.transmission_gate({
        "review": review, "manifest": man,
        "current": {"l1": esign.artifact_checksum("y")}})
    assert tampered["can_transmit"] is False and tampered["tampered"]
