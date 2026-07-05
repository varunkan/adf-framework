"""Real-service integration paths in advance(): validate/fees against the
dossier client, review+sign against governance, transmit against transmission.
Each falls back to the guided simulation when the client is absent."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app.api import build_app
from app.mesh_clients import FakeGovernanceClient, FakeTransmissionClient
from app.repository_sqlite import SqliteSessionRepository
from app.service import JourneyService


class FakeDossierClient:
    """Dossier double with controllable validation + fee results."""

    def __init__(self, *, errors=None, warnings=None) -> None:
        self.errors = errors or []
        self.warnings = warnings or []
        self.fees_set: list[tuple] = []
        self.esigned: list[tuple] = []

    def ensure_dossier(self, dossier_id, **kw) -> None: ...

    def content_state(self, dossier_id):
        return {"gate": {"complete": True, "missing": []},
                "files_view": {"nodes": [
                    {"leaves": [{"leaf_id": "m1-0-1", "checksum": "abc123"}]}]}}

    def validate(self, dossier_id):
        return {"passed": not self.errors, "errors": self.errors,
                "warnings": self.warnings, "checked": 3}

    def set_fees(self, dossier_id, fee_paid, sme_granted):
        self.fees_set.append((dossier_id, fee_paid, sme_granted))
        return {"fees": {"fee_paid": fee_paid, "sme_granted": sme_granted,
                         "review_fee": {"fiscal_year": "2026-27",
                                        "amount": 71953.0},
                         "mitigation": {"payable": 35976.5}}}

    def record_esign(self, dossier_id, manifest, *, actor=""):
        self.esigned.append((dossier_id, manifest.get("manifest_id"), actor))
        return {"dossier_id": dossier_id, "signer": manifest.get("signer"),
                "manifest_id": manifest.get("manifest_id"),
                "leaf_count": manifest.get("leaf_count"),
                "signed_at": manifest.get("at")}


def _mesh(dossier=None, governance=None, transmission=None):
    repo = SqliteSessionRepository(SqliteDb(":memory:"))
    svc = JourneyService(repo, InMemoryEventBus(), dossier=dossier,
                         governance=governance, transmission=transmission)
    client = TestClient(build_app(svc))
    sid = client.post("/api/journey/start", json={}).json()["id"]
    # march to the validate stage (content only gates when a dossier backs it)
    steps = [("orient", {}), ("company", {"company_id": "12345"}),
             ("dossier", {"dossier_id": "e123456"}),
             ("submission", {"applicant": "Acme",
                             "drug_product": "Drugazole 10 mg"})]
    if dossier is not None:
        steps.append(("content", {}))
    for step, data in steps:
        r = client.post(f"/api/journey/{sid}/advance",
                        json={"step": step, "data": data})
        assert r.status_code == 200, (step, r.json())
    return SimpleNamespace(client=client, sid=sid)


def _advance(m, step, data=None):
    return m.client.post(f"/api/journey/{m.sid}/advance",
                         json={"step": step, "data": data or {}})


# -- validate: real eCTD validation ------------------------------------------
def test_validate_runs_real_validation_and_blocks_on_errors():
    dc = FakeDossierClient(errors=[{"message": "leaf checksum mismatch"}])
    m = _mesh(dossier=dc)
    r = _advance(m, "validate")
    assert r.status_code == 422
    assert "leaf checksum mismatch" in r.json()["detail"]


def test_validate_real_pass_marks_signal_real():
    m = _mesh(dossier=FakeDossierClient())
    r = _advance(m, "validate")
    assert r.status_code == 200
    sig = m.client.get(f"/api/journey/{m.sid}").json()["signals"]
    # WS1-b enriched the signal with the named criteria + failing rule ids so
    # the readiness 'validation' tier is legible; core fields unchanged.
    assert {k: sig["validation"][k] for k in
            ("ran", "errors", "warnings", "checked", "real")} == {
        "ran": True, "errors": 0, "warnings": 0, "checked": 3, "real": True}
    assert "criteria" in sig["validation"]
    assert sig["validation"]["failing_rules"] == []


def test_validate_without_dossier_uses_simulated_input():
    m = _mesh()   # no dossier client
    assert _advance(m, "validate", {"errors": 2}).status_code == 422
    r = _advance(m, "validate", {"errors": 0})
    assert r.status_code == 200


# -- fees: dossier index is the source of truth -------------------------------
def test_fees_sync_to_dossier_index():
    dc = FakeDossierClient()
    m = _mesh(dossier=dc)
    _advance(m, "validate")
    r = _advance(m, "fees", {"sb_granted": True})
    assert r.status_code == 200
    assert dc.fees_set == [("e123456", True, True)]
    sig = m.client.get(f"/api/journey/{m.sid}").json()["signals"]
    assert sig["fees"]["real"] is True and sig["fees"]["payable"] == 35976.5


# -- review + sign: governance ------------------------------------------------
def test_review_records_governance_qa_review():
    gov = FakeGovernanceClient()
    m = _mesh(dossier=FakeDossierClient(), governance=gov)
    _advance(m, "validate"); _advance(m, "fees")
    r = _advance(m, "review")
    assert r.status_code == 200
    assert gov.calls and gov.calls[0][0] == "qa_review"
    sig = m.client.get(f"/api/journey/{m.sid}").json()["signals"]
    assert sig["reviews"]["real"] is True


def test_review_rejected_by_governance_422():
    m = _mesh(dossier=FakeDossierClient(),
              governance=FakeGovernanceClient(review_valid=False))
    _advance(m, "validate"); _advance(m, "fees")
    r = _advance(m, "review")
    assert r.status_code == 422 and "QA review" in r.json()["title"]


def test_sign_builds_manifest_from_dossier_leaves():
    gov = FakeGovernanceClient()
    m = _mesh(dossier=FakeDossierClient(), governance=gov)
    for s in ("validate", "fees", "review"):
        _advance(m, s)
    r = _advance(m, "sign")
    assert r.status_code == 200
    assert ("sign", "Acme", 1) in gov.calls   # 1 checksummed leaf artifact
    sig = m.client.get(f"/api/journey/{m.sid}").json()["signals"]
    assert sig["esign"]["real"] is True
    assert sig["esign"]["manifest_id"] == "fake-manifest-1"


def test_sign_threads_reason_and_records_durable_part11_event():
    # ADOPT-PART11-ESIGN: the signer's explicit REASON reaches the manifest, and
    # the signed manifest is recorded to the dossier's durable Part-11 ledger.
    gov = FakeGovernanceClient()
    dc = FakeDossierClient()
    m = _mesh(dossier=dc, governance=gov)
    for s in ("validate", "fees", "review"):
        _advance(m, s)
    r = _advance(m, "sign", {"signer": "Dr. Vera Signer",
                             "reason": "I authorize transmission of this ANDS."})
    assert r.status_code == 200
    sig = m.client.get(f"/api/journey/{m.sid}").json()["signals"]
    assert sig["esign"]["signer"] == "Dr. Vera Signer"
    assert sig["esign"]["reason"] == "I authorize transmission of this ANDS."
    assert sig["esign"]["signed_at"]           # a UTC stamp is surfaced
    assert sig["esign"]["leaf_count"] == 1
    # the durable Part-11 record was written to the dossier ledger
    assert dc.esigned == [("e123456", "fake-manifest-1", "Dr. Vera Signer")]


# -- transmit: real state machine ---------------------------------------------
def test_transmit_runs_full_ack_chain():
    tx = FakeTransmissionClient()
    m = _mesh(dossier=FakeDossierClient(), transmission=tx)
    for s in ("validate", "fees", "review", "sign"):
        _advance(m, s)
    r = _advance(m, "transmit")
    assert r.status_code == 200
    assert tx.calls == [("transmit", "e123456", "0000")]
    sig = m.client.get(f"/api/journey/{m.sid}").json()["signals"]
    t = sig["transmission"]
    assert t["state"] == "RECEIVED_BY_HC" and t["hc_ack_received"] is True
    assert t["real"] is True


def test_stages_fall_back_without_mesh_services():
    m = _mesh(dossier=FakeDossierClient())   # no governance/transmission
    for s in ("validate", "fees", "review", "sign", "transmit"):
        assert _advance(m, s).status_code == 200, s
    sig = m.client.get(f"/api/journey/{m.sid}").json()["signals"]
    assert sig["reviews"]["real"] is False
    assert sig["esign"]["real"] is False
    assert sig["transmission"]["real"] is False
