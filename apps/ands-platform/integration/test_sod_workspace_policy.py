"""TIER3-SOD-ENFORCE — end-to-end: the identity workspace policy (require_sod)
drives the dossier sign path's segregation-of-duties HARD BLOCK across services.

This is the gap-closer's acceptance proof: an admin flips ONE workspace policy in
identity, and a signer-is-author e-signature is then rejected by the dossier
service on the real sign path — no per-signature opt-in required. With the policy
OFF the same signature is advisory (recorded, not blocked). Two real services on
one bus, wired exactly as production wires them (dossier -> identity policy port).
"""

import pytest

from ands_shared import ProblemError


def _manifest(signer, authors):
    return {
        "signer": signer, "role": "authorized_signer", "auth_method": "mfa",
        "meaning": "approved", "reason": "I attest.",
        "at": "2026-07-04T00:00:00+00:00", "tz": "UTC",
        "manifest_id": "mani-e2e", "leaf_count": 1,
        "authors": authors,
        "artifacts": [{"id": "m1-cover", "kind": "leaf", "checksum": "abc",
                       "checksum_type": "MD5"}],
    }


def _setup(mesh):
    signup = mesh.identity.signup({"email": "ra@acme.io", "password": "pw12345-2026",
                                   "company_name": "Acme"})
    tid = signup["tenant"]["id"]
    token = signup["token"]
    mesh.dossier.create_dossier({"dossier_id": "e-sod-1", "title": "Signol"}, tid)
    return tid, token


def test_admin_policy_on_blocks_signer_is_author_end_to_end(mesh):
    tid, token = _setup(mesh)
    # admin turns the workspace SoD-enforcement policy ON in identity
    mesh.identity.set_require_sod(token, {"require_sod": True})
    # the signer is also the author — the dossier reads identity's policy and blocks
    man = _manifest("amir@acme.io", authors=["amir@acme.io"])
    with pytest.raises(ProblemError) as exc:
        mesh.dossier.record_esign("e-sod-1", man, actor="amir@acme.io",
                                  tenant_id=tid)
    assert exc.value.extra.get("rule") == "segregation_of_duties"


def test_admin_policy_on_allows_distinct_approver_end_to_end(mesh):
    tid, token = _setup(mesh)
    mesh.identity.set_require_sod(token, {"require_sod": True})
    man = _manifest("qa@acme.io", authors=["amir@acme.io"])
    rec = mesh.dossier.record_esign("e-sod-1", man, actor="qa@acme.io",
                                    tenant_id=tid)
    assert rec["segregation_of_duties"]["separated"] is True
    assert rec["segregation_of_duties"]["enforced"] is True


def test_policy_off_is_advisory_end_to_end(mesh):
    tid, _token = _setup(mesh)
    # policy is OFF by default — the same conflict is recorded but NOT blocked
    man = _manifest("amir@acme.io", authors=["amir@acme.io"])
    rec = mesh.dossier.record_esign("e-sod-1", man, actor="amir@acme.io",
                                    tenant_id=tid)
    assert rec["segregation_of_duties"]["conflict"] is True
    assert rec["segregation_of_duties"]["enforced"] is False
