"""FastAPI surface — the guided session walk start → … → READY, over TestClient."""


def test_catalog_exposes_the_whole_spine(client):
    r = client.get("/api/journey/catalog")
    assert r.status_code == 200
    body = r.json()
    keys = [s["key"] for s in body["stages"]]
    # round-9 J8: the spine gained the named bilingual M1/PM stage (12 stages)
    assert keys[0] == "orient" and keys[-1] == "track" and len(keys) == 12
    assert "ANDS" in body["submission_types"]
    assert any(rs["version"] == "M13A" for rs in body["be_rulesets"])


def test_start_returns_new_journey(client):
    r = client.post("/api/journey/start", json={"title": "Acme generic"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"]
    assert body["journey"]["position"]["current"] == 0   # orient
    assert body["readiness"]["status"] == "BLOCKED"


def test_intake_endpoint_steers_off_ands(client):
    r = client.post("/api/journey/intake",
                    json={"submission_type": "ANDS", "new_indication": True})
    assert r.status_code == 200
    rules = {a["rule"] for a in r.json()["assessment"]["advisories"]}
    assert "ands_not_for_new_indication" in rules


def _place_required_docs(client, sid):
    """Place every required + applicable eCTD slot (bilingual PM gets en+fr)."""
    v = client.get(f"/api/journey/{sid}").json()
    for s in v["content"]["slots"]:
        if not (s["required"] and s["applicable"]):
            continue
        body = {"slot_key": s["key"], "doc": f"{s['key']}.pdf"}
        if s["bilingual"]:
            body["languages"] = ["en", "fr"]
        client.post(f"/api/journey/{sid}/content/place", json=body)


def test_full_walk_to_ready(client):
    sid = client.post("/api/journey/start", json={}).json()["id"]

    def adv(step, **data):
        return client.post(f"/api/journey/{sid}/advance",
                           json={"step": step, "data": data})

    adv("orient")
    adv("company", company_id="12345")
    adv("dossier", dossier_id="e123456")
    adv("submission", applicant="Acme Pharma", drug_product="Drugazole 10mg")
    _place_required_docs(client, sid)         # required before the content gate
    adv("content")
    # round-9 J8: the named bilingual M1/PM stage sits between content and
    # validation — the walk confirms the parity + translation reviews.
    adv("bilingual", en_fr_parity=True, translation_reviewed=True)
    adv("validate", errors=0)
    adv("fees")
    adv("review")
    last = adv("sign")
    assert last.status_code == 200
    body = last.json()
    assert body["readiness"]["status"] == "READY"
    assert body["journey"]["position"]["current_key"] == "transmit"
    # round-9 J3: transmit is a hard gate on a confirmed eValidator run — the
    # filer attests their own run (honest: user-attested, never a tool claim).
    final = adv("transmit", state="SUBMITTED",
                evalidator_confirmed=True).json()
    assert final["journey"]["position"]["transmitted"] is True


def test_advance_rejects_bad_dossier_id(client):
    sid = client.post("/api/journey/start", json={}).json()["id"]
    client.post(f"/api/journey/{sid}/advance",
                json={"step": "company", "data": {"company_id": "1"}})
    bad = client.post(f"/api/journey/{sid}/advance",
                      json={"step": "dossier", "data": {"dossier_id": "nope"}})
    assert bad.status_code == 422


def test_advance_blocks_validation_with_errors(client):
    sid = client.post("/api/journey/start", json={}).json()["id"]
    for step, data in [("company", {"company_id": "1"}),
                       ("dossier", {"dossier_id": "e123456"}),
                       ("submission", {"applicant": "A", "drug_product": "D"}),
                       ("content", {})]:
        client.post(f"/api/journey/{sid}/advance",
                    json={"step": step, "data": data})
    r = client.post(f"/api/journey/{sid}/advance",
                    json={"step": "validate", "data": {"errors": 4}})
    assert r.status_code == 422


def test_get_unknown_session_404(client):
    assert client.get("/api/journey/does-not-exist").status_code == 404


def test_dossier_id_assess_endpoint(client):
    r = client.post("/api/journey/dossier-id/assess",
                    json={"dossier_id": "e123456", "request_date": "2026-01-01",
                          "first_filing_date": "2026-06-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["format_ok"] is True
    assert body["lead_time"]["too_early"] is True   # >8 weeks ahead -> warns


def test_intake_with_session_persists(ctx):
    client = ctx.client
    sid = client.post("/api/journey/start", json={}).json()["id"]
    client.post("/api/journey/intake",
                json={"session_id": sid, "submission_type": "ANDS",
                      "drug_product": "Drugazole"})
    body = client.get(f"/api/journey/{sid}").json()
    assert body["title"] == "Drugazole"
    assert body["intake"]["route"]["submission_type"] == "ANDS"


# -- content slots (drag-drop placement onto Module 1-5) --------------------
def _start(client):
    return client.post("/api/journey/start", json={}).json()["id"]


def test_view_exposes_module_tower(client):
    sid = _start(client)
    v = client.get(f"/api/journey/{sid}").json()
    tower = {t["module"]: t["state"] for t in v["content"]["tower"]}
    assert tower["1"] == "todo" and tower["4"] == "na"   # M4 n/a for a generic
    assert v["content"]["gate"]["complete"] is False


def test_place_documents_completes_content_and_lights_tower(client):
    sid = _start(client)
    v = client.get(f"/api/journey/{sid}").json()
    required = [s["key"] for s in v["content"]["slots"]
               if s["required"] and s["applicable"]]
    for key in required:
        body = {"slot_key": key, "doc": f"{key}.pdf"}
        if key == "m1_product_monograph":
            body["languages"] = ["en", "fr"]
        assert client.post(f"/api/journey/{sid}/content/place",
                           json=body).status_code == 200
    v2 = client.get(f"/api/journey/{sid}").json()
    assert v2["content"]["gate"]["complete"] is True
    assert all(t["state"] in ("pass", "na") for t in v2["content"]["tower"])


def test_bilingual_pm_needs_both_languages(client):
    sid = _start(client)
    r = client.post(f"/api/journey/{sid}/content/place",
                    json={"slot_key": "m1_product_monograph", "doc": "pm.pdf",
                          "languages": ["en"]})
    slots = {s["key"]: s for s in r.json()["content"]["slots"]}
    assert slots["m1_product_monograph"]["state"] == "partial"


def test_place_unknown_slot_422(client):
    sid = _start(client)
    r = client.post(f"/api/journey/{sid}/content/place",
                    json={"slot_key": "nope", "doc": "x"})
    assert r.status_code == 422


def test_content_advance_blocked_until_required_filled(client):
    sid = _start(client)
    client.post(f"/api/journey/{sid}/content/place",
                json={"slot_key": "m1_cover_letter", "doc": "c.pdf"})
    r = client.post(f"/api/journey/{sid}/advance",
                    json={"step": "content", "data": {}})
    assert r.status_code == 422   # slots present but required items still missing


def test_content_advance_gates_even_with_nothing_placed(client):
    # the content gate is authoritative from the live plan — content_done can
    # never stick true over an empty eCTD (review finding #1).
    sid = _start(client)
    r = client.post(f"/api/journey/{sid}/advance",
                    json={"step": "content", "data": {}})
    assert r.status_code == 422
    assert client.get(f"/api/journey/{sid}").json()["signals"].get("content_done") \
        in (None, False)


# -- post-filing tracking (deadline timers) ---------------------------------
def test_track_sdn_timer_and_srl_advisory(client):
    sid = _start(client)
    client.post(f"/api/journey/{sid}/track/notice",
                json={"type": "SDN", "date": "2026-06-01"})
    tv = client.get(f"/api/journey/{sid}/track",
                    params={"as_of": "2026-06-10"}).json()
    assert tv["phase"]["phase"] == "screening"
    timer = tv["timers"][0]
    assert timer["window_days"] == 45 and timer["days_remaining"] == 36
    assert timer["overdue"] is False
    assert any(a["rule"] == "srl_risk" for a in tv["advisories"])


def test_track_pause_the_clock(client):
    sid = _start(client)
    client.post(f"/api/journey/{sid}/track/notice",
                json={"type": "clarifax", "date": "2026-06-01"})
    overdue = client.get(f"/api/journey/{sid}/track",
                         params={"as_of": "2026-07-01"}).json()
    assert overdue["timers"][0]["overdue"] is True
    client.post(f"/api/journey/{sid}/track/pause",
                json={"type": "clarifax", "paused": True})
    paused = client.get(f"/api/journey/{sid}/track",
                        params={"as_of": "2026-07-01"}).json()
    assert paused["timers"][0]["paused"] is True
    assert paused["timers"][0]["overdue"] is False


def test_noc_moves_to_decision(client):
    sid = _start(client)
    client.post(f"/api/journey/{sid}/track/notice",
                json={"type": "NOC", "date": "2026-09-01"})
    tv = client.get(f"/api/journey/{sid}/track",
                    params={"as_of": "2026-09-02"}).json()
    assert tv["phase"]["phase"] == "decision" and tv["timers"] == []


# -- tenant isolation (CRO reg-director rejection) --------------------------
# Every guided session carries dossier_id, product, applicant + company_id, so
# a session started by tenant A must be invisible + 404 to tenant B. When the
# X-Tenant-Id header is absent (in-process mesh / existing tests) the store
# stays UNSCOPED so cross-service integration keeps working.
_A = {"X-Tenant-Id": "tenant-a"}
_B = {"X-Tenant-Id": "tenant-b"}


def test_session_started_by_a_is_invisible_and_404s_to_b(client):
    # A starts a guided session (the tenant comes from the header).
    sid = client.post("/api/journey/start",
                      json={"title": "Acme secret"}, headers=_A).json()["id"]

    # B's list never sees A's session; A's list does.
    b_list = client.get("/api/journey/sessions", headers=_B).json()
    assert all(s["id"] != sid for s in b_list["sessions"])
    a_list = client.get("/api/journey/sessions", headers=_A).json()
    assert any(s["id"] == sid for s in a_list["sessions"])

    # B cannot read A's session (404, never 403 — don't confirm existence).
    assert client.get(f"/api/journey/{sid}", headers=_B).status_code == 404
    assert client.get(f"/api/journey/{sid}", headers=_A).status_code == 200

    # B cannot advance / track / place on A's session either.
    assert client.post(f"/api/journey/{sid}/advance",
                       json={"step": "orient", "data": {}},
                       headers=_B).status_code == 404
    assert client.post(f"/api/journey/{sid}/track/notice",
                       json={"type": "SDN", "date": "2026-06-01"},
                       headers=_B).status_code == 404
    assert client.post(f"/api/journey/{sid}/content/place",
                       json={"slot_key": "m1_cover_letter", "doc": "c.pdf"},
                       headers=_B).status_code == 404
    assert client.post("/api/journey/intake",
                       json={"session_id": sid, "drug_product": "spy"},
                       headers=_B).status_code == 404


def test_no_header_stays_unscoped(client):
    # The in-process mesh passes no header — every session stays visible.
    a = client.post("/api/journey/start", json={}, headers=_A).json()["id"]
    b = client.post("/api/journey/start", json={}, headers=_B).json()["id"]
    ids = {s["id"] for s in client.get("/api/journey/sessions").json()["sessions"]}
    assert {a, b} <= ids
    # and an unscoped get reaches either tenant's session.
    assert client.get(f"/api/journey/{a}").status_code == 200
    assert client.get(f"/api/journey/{b}").status_code == 200


def test_header_wins_over_body_tenant(client):
    # The authenticated header is authoritative — a spoofed body tenant_id
    # cannot re-home the session to another workspace.
    sid = client.post("/api/journey/start",
                      json={"tenant_id": "tenant-b"}, headers=_A).json()["id"]
    assert client.get(f"/api/journey/{sid}", headers=_B).status_code == 404
    assert client.get(f"/api/journey/{sid}", headers=_A).status_code == 200


def test_unowned_session_claimed_by_first_advancing_tenant(client):
    # A session started with no header is unowned; the first advance that
    # carries a tenant stamps ownership, and thereafter another tenant 404s.
    sid = client.post("/api/journey/start", json={}).json()["id"]
    assert client.post(f"/api/journey/{sid}/advance",
                       json={"step": "orient", "data": {}},
                       headers=_A).status_code == 200
    assert client.get(f"/api/journey/{sid}", headers=_B).status_code == 404
    assert client.get(f"/api/journey/{sid}", headers=_A).status_code == 200
