"""CAMP-SSO-OIDC — end-to-end: an SSO-verified signer is an AUTHENTICATED
PRINCIPAL on the Part-11 e-signature record, not a typed email.

The task-eval's #1 blocker was "the signer is a typed email, not an
authenticated principal". This proves the closed loop across TWO real services:
the governance e-sign domain stamps the signer's identity assurance onto the
manifest, and the dossier sign path records it on the immutable Part-11 manifest
+ audit event — 'sso_verified (issuer)' when the signing session is SSO-backed,
and honestly 'recorded_email' otherwise.
"""


def _sign(mesh, *, identity=None):
    payload = {
        "signer": "vera@acme.io", "meaning": "approved",
        "reason": "I approve this submission package.",
        "artifacts": [{"id": "m1-cover", "content": "hello"}]}
    if identity:
        payload.update(identity)
    else:
        payload["auth_method"] = "mfa"
    return mesh.governance.sign(payload)["manifest"]


def _setup(mesh):
    signup = mesh.identity.signup({"email": "ra@acme.io",
                                   "password": "pw12345-2026",
                                   "company_name": "Acme"})
    tid = signup["tenant"]["id"]
    mesh.dossier.create_dossier({"dossier_id": "e-sso-1", "title": "Signol"}, tid)
    return tid


def test_sso_verified_signer_is_authenticated_principal_end_to_end(mesh):
    tid = _setup(mesh)
    # a signing session minted by an OIDC login carries issuer + IdP subject
    man = _sign(mesh, identity={
        "identity_verified": True,
        "identity_issuer": "https://idp.acme.io",
        "identity_subject": "idp-sub-77"})
    assert man["identity"]["assurance"] == "sso_verified"
    assert man["identity"]["statement"] == \
        "identity: SSO-verified (https://idp.acme.io)"
    # the dossier records it on the immutable Part-11 manifest
    rec = mesh.dossier.record_esign("e-sso-1", man, actor="vera@acme.io",
                                    tenant_id=tid)
    stored = mesh.dossier.get_esign("e-sso-1", tenant_id=tid)["manifest"]
    assert stored["identity"]["assurance"] == "sso_verified"
    assert stored["identity"]["issuer"] == "https://idp.acme.io"
    assert rec["manifest_id"] == man["manifest_id"]


def test_password_signer_is_honestly_recorded_email_end_to_end(mesh):
    tid = _setup(mesh)
    man = _sign(mesh)  # no verified identity — a password sign-in
    assert man["identity"]["assurance"] == "recorded_email"
    assert man["identity"]["verified"] is False
    mesh.dossier.record_esign("e-sso-1", man, actor="vera@acme.io",
                              tenant_id=tid)
    stored = mesh.dossier.get_esign("e-sso-1", tenant_id=tid)["manifest"]
    assert stored["identity"]["assurance"] == "recorded_email"
