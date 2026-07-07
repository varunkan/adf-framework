"""Round-9 journey scope — J8 bilingual stage, J3 eValidator transmit gate,
J20/J21 append-only session event ledger. TDD: written RED before the
implementation (docs/ands-portal/ROUND9-FIX-BACKLOG.md, Guided Journey)."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from ands_shared import InMemoryEventBus, SqliteDb

from app import journey, readiness_card
from app.api import build_app
from app.repository_sqlite import SqliteSessionRepository
from app.service import JourneyService


# ---------------------------------------------------------------------------
# J8 — a NAMED bilingual Module 1 / Product Monograph stage in the spine
# ---------------------------------------------------------------------------

def test_bilingual_stage_present_at_n5_with_checklist():
    st = journey.stage_by_key("bilingual")
    assert st is not None, "the journey spine must name a bilingual M1/PM stage"
    assert st["n"] == 5
    assert "Bilingual" in st["label"] and "Monograph" in st["label"]
    checklist = " · ".join(st["checklist"])
    assert "parity" in checklist.lower()
    assert "translation" in checklist.lower()
    assert "mock-up" in checklist.lower()
    assert "xml" in checklist.lower()


def test_spine_renumbered_validate_through_track():
    keys = [s["key"] for s in journey.STAGES]
    assert keys == ["orient", "company", "dossier", "submission", "content",
                    "bilingual", "validate", "fees", "review", "sign",
                    "transmit", "track"]
    assert [s["n"] for s in journey.STAGES] == list(range(12))


def test_bilingual_locked_until_content_then_current():
    base = {"company_id": "1", "dossier_id": "e123456", "applicant": "A",
            "drug_product": "D"}
    stages = {s["key"]: s for s in journey.stages(base)}
    assert stages["bilingual"]["status"] == "locked"
    stages = {s["key"]: s for s in journey.stages({**base, "content_done": True})}
    assert stages["bilingual"]["status"] == "current"
    assert stages["validate"]["status"] == "locked"
    done = {**base, "content_done": True, "bilingual": {"confirmed": True}}
    stages = {s["key"]: s for s in journey.stages(done)}
    assert stages["bilingual"]["status"] == "done"
    assert stages["validate"]["status"] == "current"


def test_percent_math_over_11_gateable_stages():
    assert journey.position({})["total"] == 11
    half = {"oriented": True, "company_id": "1", "dossier_id": "e1",
            "applicant": "A", "drug_product": "D", "content_done": True}
    pos = journey.position(half)
    assert pos["done"] == 5
    assert pos["percent"] == 45          # round(5 * 100 / 11)


def test_readiness_card_has_bilingual_tile():
    c = readiness_card.card({})
    keys = [t["key"] for t in c["tiles"]]
    assert "bilingual" in keys
    assert keys.index("bilingual") == keys.index("content") + 1


def test_readiness_ready_requires_bilingual_confirmed():
    signed = {"company_id": "1", "dossier_id": "e123456", "applicant": "A",
              "drug_product": "D", "content_done": True,
              "validation": {"ran": True, "errors": 0}, "fees": {"paid": True},
              "reviews": {"approved": True}, "esign": {"signed": True}}
    assert readiness_card.card(signed)["status"] == "BLOCKED"
    signed["bilingual"] = {"confirmed": True}
    assert readiness_card.card(signed)["status"] == "READY"


def _start(client):
    return client.post("/api/journey/start", json={}).json()["id"]


def _adv(client, sid, step, **data):
    return client.post(f"/api/journey/{sid}/advance",
                       json={"step": step, "data": data})


def test_advance_bilingual_422_without_confirmations(client):
    sid = _start(client)
    r = _adv(client, sid, "bilingual")
    assert r.status_code == 422
    r = _adv(client, sid, "bilingual", en_fr_parity=True)   # translation missing
    assert r.status_code == 422


def test_advance_bilingual_records_signal(client):
    sid = _start(client)
    r = _adv(client, sid, "bilingual", en_fr_parity=True,
             translation_reviewed=True, pm_xml_validated=True,
             mockups_state="reviewed", reviewer="M. Tremblay")
    assert r.status_code == 200
    sig = r.json()["signals"]["bilingual"]
    assert sig["confirmed"] is True
    assert sig["en_fr_parity"] is True and sig["translation_reviewed"] is True
    assert sig["pm_xml_validated"] is True
    assert sig["mockups_state"] == "reviewed"
    assert sig["reviewer"] == "M. Tremblay"
    assert sig["at"]


# ---------------------------------------------------------------------------
# J3 — hard eValidator gate on transmit
# ---------------------------------------------------------------------------

class _AttDossierClient:
    """Minimal dossier double: no content, a configurable attestation."""

    def __init__(self, attestation=None):
        self.attestation = attestation

    def ensure_dossier(self, dossier_id, **kw) -> None: ...
    def content_state(self, dossier_id): return None
    def validate(self, dossier_id): return None
    def set_fees(self, dossier_id, fee_paid, sme_granted): return None
    def record_esign(self, dossier_id, manifest, *, actor=""): return None

    def evalidator_attestation(self, dossier_id):
        return self.attestation


def _svc_client(dossier=None):
    repo = SqliteSessionRepository(SqliteDb(":memory:"))
    svc = JourneyService(repo, InMemoryEventBus(), dossier=dossier)
    client = TestClient(build_app(svc))
    sid = client.post("/api/journey/start", json={}).json()["id"]
    for step, data in [("company", {"company_id": "12345"}),
                       ("dossier", {"dossier_id": "e123456"})]:
        assert _adv(client, sid, step, **data).status_code == 200
    return SimpleNamespace(client=client, sid=sid)


def test_transmit_blocked_without_evalidator_confirmation(client):
    sid = _start(client)
    r = _adv(client, sid, "transmit", state="SUBMITTED")
    assert r.status_code == 422
    body = r.json()
    assert "evalidator" in (body.get("title", "") + body.get("detail", "")).lower()
    # nothing was transmitted
    v = client.get(f"/api/journey/{sid}").json()
    assert "transmission" not in v["signals"]


def test_transmit_with_user_attested_pass_succeeds(client):
    sid = _start(client)
    r = _adv(client, sid, "transmit", state="SUBMITTED",
             evalidator_confirmed=True, evalidator_result="pass",
             validator_name="Lorenz eValidator")
    assert r.status_code == 200
    sig = r.json()["signals"]
    assert sig["evalidator"]["attested"] is True
    assert sig["evalidator"]["result"] == "pass"
    assert sig["evalidator"]["source"] == "user_attested"
    assert sig["evalidator"]["validator_name"] == "Lorenz eValidator"
    assert sig["transmission"]["state"] == "SUBMITTED"


def test_transmit_with_user_attested_fail_blocked(client):
    sid = _start(client)
    r = _adv(client, sid, "transmit", evalidator_confirmed=True,
             evalidator_result="fail")
    assert r.status_code == 422


def test_transmit_uses_dossier_attestation_pass():
    m = _svc_client(dossier=_AttDossierClient(
        {"result": "pass", "validator_name": "HC eValidator",
         "source": "user_attested_external"}))
    r = _adv(m.client, m.sid, "transmit")
    assert r.status_code == 200
    sig = m.client.get(f"/api/journey/{m.sid}").json()["signals"]
    assert sig["evalidator"]["source"] == "dossier_attestation"
    assert sig["evalidator"]["validator_name"] == "HC eValidator"


def test_transmit_blocked_on_dossier_attestation_fail():
    m = _svc_client(dossier=_AttDossierClient(
        {"result": "fail", "validator_name": "HC eValidator"}))
    # even a user-confirmed pass cannot override a recorded FAIL attestation
    r = _adv(m.client, m.sid, "transmit", evalidator_confirmed=True)
    assert r.status_code == 422


def test_transmit_unlocks_copy_names_the_evalidator_gate():
    st = journey.stage_by_key("transmit")
    assert "eValidator" in st["unlocks"]


# ---------------------------------------------------------------------------
# J20 + J21 — append-only session event ledger, from the very first action
# ---------------------------------------------------------------------------

def test_start_writes_session_started_event_at_seq_1(client):
    sid = _start(client)
    body = client.get(f"/api/journey/{sid}/events").json()
    assert body["count"] >= 1
    first = body["events"][0]
    assert first["seq"] == 1
    assert first["type"] == "journey.session_started"
    assert first["at"]


def test_every_advance_appends_with_no_seq_gaps(client):
    sid = _start(client)
    _adv(client, sid, "orient")
    _adv(client, sid, "company", company_id="12345")
    _adv(client, sid, "dossier", dossier_id="e123456")
    body = client.get(f"/api/journey/{sid}/events").json()
    types = [e["type"] for e in body["events"]]
    assert "journey.step.orient" in types
    assert "journey.step.company" in types
    assert "journey.step.dossier" in types
    seqs = [e["seq"] for e in body["events"]]
    assert seqs == list(range(1, len(seqs) + 1)), "append-only, gap-free seq"


def test_intake_place_and_notice_are_ledgered(client):
    sid = _start(client)
    client.post("/api/journey/intake",
                json={"session_id": sid, "submission_type": "ANDS",
                      "drug_product": "Drugazole"})
    client.post(f"/api/journey/{sid}/content/place",
                json={"slot_key": "m1_cover_letter", "doc": "c.pdf"})
    client.post(f"/api/journey/{sid}/track/notice",
                json={"type": "SDN", "date": "2026-06-01"})
    types = [e["type"] for e in
             client.get(f"/api/journey/{sid}/events").json()["events"]]
    assert "journey.intake" in types
    assert "journey.content.placed" in types
    assert "journey.track.notice" in types


def test_expert_mode_enable_requires_documented_reason(client):
    sid = _start(client)
    r = client.post(f"/api/journey/{sid}/events",
                    json={"type": "expert_mode", "data": {"enabled": True}})
    assert r.status_code == 422
    r = client.post(f"/api/journey/{sid}/events",
                    json={"type": "expert_mode", "reason": "re-validating M3",
                          "data": {"enabled": True}})
    assert r.status_code == 200
    ev = r.json()["event"]
    assert ev["type"] == "journey.expert_mode"
    assert ev["data"]["enabled"] is True
    assert ev["data"]["reason"] == "re-validating M3"
    # disabling needs no reason
    r = client.post(f"/api/journey/{sid}/events",
                    json={"type": "expert_mode", "data": {"enabled": False}})
    assert r.status_code == 200


def test_only_whitelisted_ux_event_types_accepted(client):
    sid = _start(client)
    r = client.post(f"/api/journey/{sid}/events",
                    json={"type": "esign_signed", "reason": "spoof",
                          "data": {}})
    assert r.status_code == 422


def test_events_are_tenant_guarded(client):
    a = {"X-Tenant-Id": "tenant-a"}
    b = {"X-Tenant-Id": "tenant-b"}
    sid = client.post("/api/journey/start", json={}, headers=a).json()["id"]
    assert client.get(f"/api/journey/{sid}/events",
                      headers=b).status_code == 404
    assert client.post(f"/api/journey/{sid}/events", headers=b,
                       json={"type": "expert_mode", "reason": "x",
                             "data": {"enabled": True}}).status_code == 404
    assert client.get(f"/api/journey/{sid}/events",
                      headers=a).status_code == 200
