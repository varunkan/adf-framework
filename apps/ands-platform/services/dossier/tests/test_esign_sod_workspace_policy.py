"""TIER3-SOD-ENFORCE (durable side): the workspace 'require segregation of
duties' policy makes SoD a HARD BLOCK on the sign path — not just an advisory
outcome on the manifest.

Grounding: ``record_esign`` already hard-blocks when the manifest carries
``enforce_segregation=True`` (TIER2). TIER3 sources that enforcement from a
per-workspace POLICY (identity ``require_sod``) so an admin's single toggle makes
every signer-is-author signature in the workspace fail — the signer no longer has
to opt into their own block. The dossier reads the policy for the tenant via an
injected best-effort port; when the policy is on, enforcement is forced even if
the manifest omits the flag. When the port is unreachable it degrades to the
manifest flag (advisory), never crashing.

Honest: a role-separation control over the SIGN path, not an SSO/IdP claim.
"""

import pytest

from ands_shared import ProblemError
from app import audit_hook


class FakePolicyClient:
    """Test double for the identity workspace-policy port."""

    def __init__(self, *, require_sod=False, raises=False):
        self._require_sod = require_sod
        self._raises = raises
        self.calls = []

    def workspace_policy(self, tenant_id):
        self.calls.append(tenant_id)
        if self._raises:
            raise RuntimeError("identity unreachable")
        return {"tenant_id": tenant_id, "require_sod": self._require_sod,
                "require_mfa": False}


def _service_with_policy(policy):
    from ands_shared import SqliteDb
    from app.repository_sqlite import SqliteDossierRepository
    from ands_shared import InMemoryEventBus
    from app.service import DossierService
    repo = SqliteDossierRepository(SqliteDb(":memory:"))
    return DossierService(repo, InMemoryEventBus(), policy=policy).register()


def _seed(svc, did="e900010", author="amir@sponsor.example"):
    svc.create_dossier({"dossier_id": did, "title": "Signol 10 mg tablet"},
                       "tenant-abc")
    audit_hook.set_actor(author)
    try:
        svc.upload_document(did, "1.0", "cover.pdf", "application/pdf",
                            b"%PDF-1.4 cover")
    finally:
        audit_hook.set_actor("")


def _manifest(signer, *, enforce=False):
    man = {
        "signer": signer, "role": "authorized_signer", "auth_method": "mfa",
        "meaning": "approved", "reason": "I attest.", "at": "2026-07-04T00:00:00+00:00",
        "tz": "UTC", "manifest_id": "mani-ws", "leaf_count": 1,
        "artifacts": [{"id": "m1-cover", "kind": "leaf", "checksum": "abc123",
                       "checksum_type": "MD5"}],
    }
    if enforce:
        man["enforce_segregation"] = True
    return man


# -- policy ON forces the block even when the manifest doesn't ----------------

def test_workspace_policy_on_hard_blocks_signer_is_author():
    policy = FakePolicyClient(require_sod=True)
    svc = _service_with_policy(policy)
    _seed(svc)
    # manifest does NOT set enforce_segregation — the POLICY must force it
    man = _manifest("amir@sponsor.example", enforce=False)
    with pytest.raises(ProblemError) as exc:
        svc.record_esign("e900010", man, actor="amir@sponsor.example",
                         tenant_id="tenant-abc")
    assert exc.value.extra.get("rule") == "segregation_of_duties"
    assert policy.calls == ["tenant-abc"]


def test_workspace_policy_on_allows_distinct_signer():
    policy = FakePolicyClient(require_sod=True)
    svc = _service_with_policy(policy)
    _seed(svc)
    man = _manifest("qa@sponsor.example", enforce=False)
    rec = svc.record_esign("e900010", man, actor="qa@sponsor.example",
                           tenant_id="tenant-abc")
    assert rec["segregation_of_duties"]["separated"] is True
    assert rec["segregation_of_duties"]["enforced"] is True


# -- policy OFF stays advisory (records the outcome, does not block) ----------

def test_workspace_policy_off_is_advisory():
    policy = FakePolicyClient(require_sod=False)
    svc = _service_with_policy(policy)
    _seed(svc)
    man = _manifest("amir@sponsor.example", enforce=False)
    rec = svc.record_esign("e900010", man, actor="amir@sponsor.example",
                           tenant_id="tenant-abc")
    # advisory: conflict recorded, but NOT enforced, NOT blocked
    assert rec["segregation_of_duties"]["conflict"] is True
    assert rec["segregation_of_duties"]["enforced"] is False


# -- unreachable policy degrades to the manifest flag, never crashes ----------

def test_policy_unreachable_falls_back_to_manifest_flag():
    policy = FakePolicyClient(raises=True)
    svc = _service_with_policy(policy)
    _seed(svc)
    # manifest opts in explicitly — must still block despite the policy read error
    man = _manifest("amir@sponsor.example", enforce=True)
    with pytest.raises(ProblemError) as exc:
        svc.record_esign("e900010", man, actor="amir@sponsor.example",
                         tenant_id="tenant-abc")
    assert exc.value.extra.get("rule") == "segregation_of_duties"


def test_policy_unreachable_without_manifest_flag_is_advisory():
    policy = FakePolicyClient(raises=True)
    svc = _service_with_policy(policy)
    _seed(svc)
    man = _manifest("amir@sponsor.example", enforce=False)
    rec = svc.record_esign("e900010", man, actor="amir@sponsor.example",
                           tenant_id="tenant-abc")
    assert rec["segregation_of_duties"]["conflict"] is True
    assert rec["segregation_of_duties"]["enforced"] is False


# -- the enforced source is recorded on the immutable Part-11 event -----------

def test_policy_source_recorded_on_audit_event():
    policy = FakePolicyClient(require_sod=True)
    svc = _service_with_policy(policy)
    _seed(svc)
    man = _manifest("qa@sponsor.example", enforce=False)
    svc.record_esign("e900010", man, actor="qa@sponsor.example",
                     tenant_id="tenant-abc")
    hist = svc.dossier_history("e900010")
    ev = [e for e in hist["events"] if "esign" in e["event_type"]]
    assert ev
    assert ev[0]["data"]["sod_enforced"] is True
    assert ev[0]["data"]["sod_policy_source"] == "workspace_policy"


def test_no_policy_client_preserves_tier2_manifest_behavior(ctx):
    """Back-compat: with NO policy client wired (the default), record_esign still
    honors the manifest ``enforce_segregation`` flag exactly as in TIER2."""
    audit_hook.set_actor("amir@sponsor.example")
    try:
        ctx.client.post("/api/dossier/dossiers",
                        json={"dossier_id": "e900011", "title": "X"},
                        headers={"X-User-Email": "amir@sponsor.example"})
        ctx.service.upload_document("e900011", "1.0", "cover.pdf",
                                    "application/pdf", b"%PDF-1.4 cover")
    finally:
        audit_hook.set_actor("")
    man = _manifest("amir@sponsor.example", enforce=True)
    man["manifest_id"] = "mani-ws2"
    with pytest.raises(ProblemError) as exc:
        ctx.service.record_esign("e900011", man, actor="amir@sponsor.example")
    assert exc.value.extra.get("rule") == "segregation_of_duties"
