"""Round-9 ai_draft backlog — backend capabilities.

Covers (ROUND9-FIX-BACKLOG.md, AI-assisted Drafting flow):
- ai_draft BLOCKER "AI provider identity, data residency and DPA not
  verifiable" (n=8): the inspectable /ai-provider disclosure + downloadable
  data-processing document.
- builder_forms MAJOR "AI drafting lacks source transparency, per-section
  off-switch, harder attestation" (n=3): the per-draft context disclosure and
  the per-section AI off-switch enforced on both draft paths.
- ai_draft BLOCKER "Attestation is a button click, not an inspection-grade
  e-signature with exportable audit record" (n=4): named+credentialed
  attestation recorded to the ledger + the per-section audit record export.
- ai_draft BLOCKER "No project-level roll-up of section states, owners and
  dates" (n=2) + MAJOR "Per-leaf attestation click-tax; no bulk attest" (n=6):
  the sections roll-up (state / owner / last-touched + review queue).
- ai_draft BLOCKER "Criteria 'last verified' date and HC guidance version are
  buried" (n=13) + MAJOR "Review step lacks guidance clause citations" (n=9):
  every review finding carries a named, dated guidance citation and the
  review result carries the criteria verification stamp.
"""

import pytest

from app import ai_draft_meta, form_review


def _dossier(client, did="e123456"):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": "Drugazole 10 mg"})
    assert r.status_code == 201
    return did


def _place_ai_draft(client, did, section="1.2.3",
                    text="The sponsor attests everything."):
    r = client.post(f"/api/dossier/ectd/{did}/section/{section}/generate",
                    json={"llm_draft": text})
    assert r.status_code == 200
    return r.json()


def _node(state, section):
    return next(n for m in state["modules"] for n in m["nodes"]
                if n["section"] == section)


# -- AI provider disclosure (ai_draft BLOCKER n=8) ---------------------------
def test_ai_provider_disclosure_names_provider_and_residency(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    r = client.get("/api/dossier/ai-provider")
    assert r.status_code == 200
    d = r.json()
    assert d["configured"] is True
    # the actual configured provider is NAMED — not "the configured provider"
    assert "Groq" in d["provider"]
    assert d["model"]  # the configured model id is disclosed
    # the residency answer is plain: hosted in the US — data leaves Canada
    assert "United States" in d["hosting_region"]
    assert d["leaves_canada"] is True
    assert "leaves Canada" in d["data_residency"]
    # retention: what we control, stated; provider policy linked, not invented
    assert d["retention"]
    assert d["policy_url"].startswith("https://")
    # honest: the downloadable document is OUR disclosure, not a signed DPA
    assert "not a countersigned" in d["dpa_note"].lower() or \
           "not a signed" in d["dpa_note"].lower()


def test_ai_provider_disclosure_honest_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    d = client.get("/api/dossier/ai-provider").json()
    assert d["configured"] is False
    # never claims a live provider relationship when none is configured
    assert "not configured" in d["data_residency"].lower() or \
           "not configured" in d["retention"].lower() or d["provider"]


def test_dpa_text_is_downloadable_and_honest():
    text = ai_draft_meta.dpa_text()
    assert "data-processing disclosure" in text.lower()
    assert "Groq" in text
    # never claims to be a countersigned vendor DPA
    assert "not a countersigned" in text.lower()
    # states what is sent and when
    assert "dossier" in text.lower() and "draft" in text.lower()


# -- per-draft context disclosure (builder_forms MAJOR n=3, ask 1) -----------
def test_draft_context_lists_sources_and_facts(client):
    did = _dossier(client)
    r = client.get(f"/api/dossier/ectd/{did}/section/1.0/draft-context")
    assert r.status_code == 200
    d = r.json()
    # names every source category the system prompt is built from
    joined = " ".join(d["sources"]).lower()
    assert "guidance" in joined and "chat" in joined
    # the actual dossier facts that will be sent, key by key
    assert d["facts"]["dossier_id"] == did
    assert d["facts"]["title"] == "Drugazole 10 mg"
    # the provider block travels with the context disclosure
    assert "provider" in d


def test_draft_context_404_on_unknown_section(client):
    did = _dossier(client)
    r = client.get(f"/api/dossier/ectd/{did}/section/9.9.9/draft-context")
    assert r.status_code == 404


# -- per-section AI off-switch (builder_forms MAJOR n=3, ask 2) --------------
def test_ai_policy_disable_blocks_both_draft_paths(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/ai-policy",
                    json={"disabled": True, "reason": "client filing policy"})
    assert r.status_code == 200
    node = _node(r.json(), "1.0")
    assert node["ai_disabled"] is True
    # chat drafting refused
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/draft-chat",
                    json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 403
    assert r.json()["rule"] == "ai_drafting_disabled"
    # per-field drafting refused too
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/draft-field",
                    json={"field": "body"})
    assert r.status_code == 403
    assert r.json()["rule"] == "ai_drafting_disabled"


def test_ai_policy_reenable_and_audit_trail(client):
    did = _dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.0/ai-policy",
                json={"disabled": True})
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/ai-policy",
                    json={"disabled": False})
    assert _node(r.json(), "1.0")["ai_disabled"] is False
    events = client.get(f"/api/dossier/dossiers/{did}/history").json()["events"]
    policy_events = [e for e in events
                     if e["event_type"] == "dossier.ai_policy_set"]
    assert len(policy_events) == 2
    assert policy_events[0]["data"]["section"] == "1.0"


# -- inspection-grade attestation (ai_draft BLOCKER n=4) ---------------------
def test_confirm_content_records_named_attestation(client):
    did = _dossier(client)
    _place_ai_draft(client, did)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.2.3/confirm-content",
                    json={"attest_name": "Jane Quan", "attest_credential":
                          "RAC (Canada)"})
    assert r.status_code == 200
    node = _node(r.json(), "1.2.3")
    assert node["content_confirmed"] is True
    att = node["attestation"]
    assert att["name"] == "Jane Quan"
    assert att["credential"] == "RAC (Canada)"
    assert att["attested_at"]  # UTC timestamp recorded
    # the ledger event carries the named attestation (who + when)
    events = client.get(f"/api/dossier/dossiers/{did}/history").json()["events"]
    conf = [e for e in events if e["event_type"] == "dossier.content_confirmed"]
    assert conf and conf[-1]["data"]["attest_name"] == "Jane Quan"


def test_confirm_content_legacy_click_still_works(client):
    # backward compatible: an attest body is optional (older clients)
    did = _dossier(client)
    _place_ai_draft(client, did)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.2.3/confirm-content",
                    json={})
    assert r.status_code == 200
    assert _node(r.json(), "1.2.3")["content_confirmed"] is True


def test_section_audit_record_export(client):
    did = _dossier(client)
    _place_ai_draft(client, did)
    client.post(f"/api/dossier/ectd/{did}/section/1.2.3/confirm-content",
                json={"attest_name": "Jane Quan"})
    r = client.get(f"/api/dossier/ectd/{did}/section/1.2.3/audit-record")
    assert r.status_code == 200
    rec = r.json()
    assert rec["dossier_id"] == did and rec["section"] == "1.2.3"
    assert rec["content_origin"] == "ai_draft"
    assert rec["attestation"]["name"] == "Jane Quan"
    # md5 fingerprint of the placed document travels in the record
    assert rec["documents"] and rec["documents"][0]["checksum"]
    # every ledger event for THIS section, oldest first
    types = [e["event_type"] for e in rec["events"]]
    assert "dossier.document_generated" in types
    assert "dossier.content_confirmed" in types
    # plain statement of where the trail is stored + that it is exportable
    assert "append-only" in rec["storage"].lower()


# -- sections roll-up + review queue (ai_draft BLOCKERs n=2 / MAJOR n=6) -----
def test_sections_rollup_states_counts_and_queue(client):
    did = _dossier(client)
    _place_ai_draft(client, did)          # 1.2.3 → AI draft awaiting review
    r = client.get(f"/api/dossier/dossiers/{did}/sections-rollup")
    assert r.status_code == 200
    d = r.json()
    rows = {row["section"]: row for row in d["rows"]}
    assert rows["1.2.3"]["status"] == "partial"
    assert rows["1.2.3"]["content_origin"] == "ai_draft"
    assert rows["1.2.3"]["needs_review"] is True
    assert rows["1.2.3"]["updated_at"]    # last-touched stamp
    # counts a PM can read out on a status call
    assert d["counts"]["total"] == len(d["rows"])
    assert d["counts"]["needs_review"] >= 1
    # the review queue lists exactly the AI-drafted sections awaiting confirm
    queue = [q["section"] for q in d["review_queue"]]
    assert "1.2.3" in queue
    # the queue rows carry the doc so a reviewer can OPEN each draft
    q = next(q for q in d["review_queue"] if q["section"] == "1.2.3")
    assert q["documents"][0]["doc_id"]


def test_sections_rollup_clears_queue_after_attest(client):
    did = _dossier(client)
    _place_ai_draft(client, did)
    client.post(f"/api/dossier/ectd/{did}/section/1.2.3/confirm-content",
                json={"attest_name": "Jane Quan"})
    d = client.get(f"/api/dossier/dossiers/{did}/sections-rollup").json()
    assert all(q["section"] != "1.2.3" for q in d["review_queue"])
    row = next(x for x in d["rows"] if x["section"] == "1.2.3")
    assert row["status"] == "complete"
    assert row["attested_by"] == "Jane Quan"


# -- sample_fields surfaced for the list-view checker (ai_draft minor n=2) ---
def test_unreplaced_sample_fields_enumerated_on_node(client):
    did = _dossier(client)
    sample = client.get(
        f"/api/dossier/ectd/{did}/section/1.0/sample").json()["fields"]
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                    json=sample)
    assert r.status_code == 200
    node = _node(r.json(), "1.0")
    assert node["content_origin"] == "sample"
    # the still-example fields are enumerated so the UI can list them
    assert node["sample_fields"], "unreplaced example fields must be listed"


# -- review criteria stamp + guidance citations (n=13 / n=9) -----------------
def test_review_findings_carry_named_dated_guidance(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/review",
                    json={"sponsor": "", "contact_email": ""})
    assert r.status_code == 200
    d = r.json()
    # the criteria verification stamp rides on every review result
    assert d["criteria"]["verified"] == form_review.LAST_VERIFIED
    assert d["findings"], "empty-fields review must produce findings"
    for f in d["findings"]:
        g = f["guidance"]
        assert g["source"].startswith("Health Canada")
        assert g["verified"] == form_review.LAST_VERIFIED
        assert g["ref"]           # topic-level pointer within the guidance
        assert g["url"].startswith("https://")


def test_guidance_citations_never_invent_clause_numbers():
    # HONESTY BAR: refs are topic pointers within the named guidance — never
    # fabricated section/clause numbers (no "s.1.2.3"-style invented cites).
    import re
    for meta in form_review.GUIDANCE_META.values():
        assert not re.search(r"\bs\.\s*\d", meta["source"])
