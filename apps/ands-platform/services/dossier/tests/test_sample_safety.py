"""WS2 — AI-draft & sample-fill SAFETY.

Safety invariant: a section whose content is sample-origin or an AI draft that
the filer has NOT explicitly confirmed is NEVER complete — it cannot satisfy
the completeness gate, "ready to file", or export readiness — until the
filer confirms it as their own reviewed content (recorded to the audit trail).
"""

from app import dossier_state, section_tree


def _dossier(client, cs_be_only=True):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": "e123456", "title": "Drugazole 10 mg",
                          "cs_be_only": cs_be_only, "company_id": "61234",
                          "sponsor": "Acme", "drug_product": "Drugazole 10 mg"})
    assert r.status_code == 201
    return "e123456"


def _node(section, cs_be_only=True):
    return section_tree.node_for(section, cs_be_only=cs_be_only)


# -- resolve_status: unconfirmed AI/sample content is NOT complete -----------
def test_generated_document_is_complete_by_default():
    node = _node("1.0")
    entry = {"action": "generated", "doc_id": "d1", "content_confirmed": True}
    assert dossier_state.resolve_status(node, entry) == dossier_state.COMPLETE


def test_unconfirmed_ai_draft_is_not_complete():
    node = _node("1.0")
    entry = {"action": "generated", "doc_id": "d1",
             "content_origin": "ai_draft", "content_confirmed": False}
    # a placed doc, but sample/AI-origin & unconfirmed => needs review, NOT done
    assert dossier_state.resolve_status(node, entry) == dossier_state.PARTIAL


def test_unconfirmed_sample_fill_is_not_complete():
    node = _node("1.0")
    entry = {"action": "generated", "doc_id": "d1",
             "content_origin": "sample", "content_confirmed": False}
    assert dossier_state.resolve_status(node, entry) == dossier_state.PARTIAL


def test_confirming_sample_makes_it_complete():
    node = _node("1.0")
    entry = {"action": "generated", "doc_id": "d1",
             "content_origin": "sample", "content_confirmed": True}
    assert dossier_state.resolve_status(node, entry) == dossier_state.COMPLETE


# -- generate persists provenance + leaves AI/sample drafts unconfirmed ------
def test_generate_with_sample_origin_persists_unconfirmed(client, ):
    did = _dossier(client)
    c = client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                    json={"sample_origin": True}).json()
    node = next(n for m in c["modules"] for n in m["nodes"]
                if n["section"] == "1.0")
    # a sample-origin fill is NOT complete — it is flagged for review
    assert node["status"] != "complete"
    assert node["content_origin"] == "sample"
    assert node["content_confirmed"] is False


def test_generate_ai_draft_leaves_unconfirmed(client):
    did = _dossier(client)
    c = client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                    json={"llm_draft": "Dear Health Canada, ..."}).json()
    node = next(n for m in c["modules"] for n in m["nodes"]
                if n["section"] == "1.0")
    assert node["content_origin"] == "ai_draft"
    assert node["content_confirmed"] is False
    assert node["status"] != "complete"


def test_uploaded_content_is_confirmed_user_content(client):
    did = _dossier(client)
    c = client.post(f"/api/dossier/ectd/{did}/section/1.0/upload",
                    files={"file": ("cover.pdf", b"%PDF-1.4 x",
                                    "application/pdf")}).json()
    node = next(n for m in c["modules"] for n in m["nodes"]
                if n["section"] == "1.0")
    # an upload is the filer's own content — complete, confirmed
    assert node["status"] == "complete"
    assert node["content_confirmed"] is True


# -- the confirm action clears the flag + audits ----------------------------
def test_sample_cleared_by_reauthoring_real_values(client):
    """A sample block clears by EDITING the example away and re-authoring — the
    server re-derives no-longer-sample — not by a confirm rubber stamp."""
    did = _dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                json={"contact_email": "regulatory@sponsor.example"})  # example
    gate = client.get(f"/api/dossier/dossiers/{did}/content").json()["gate"]
    assert gate["unconfirmed_sample_count"] >= 1
    c = client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                    json={"contact_name": "Dana Real",
                          "contact_email": "dana@myco.com",
                          "sequence_description": "Initial ANDS for Myco"}).json()
    node = next(n for m in c["modules"] for n in m["nodes"]
                if n["section"] == "1.0")
    assert node["content_confirmed"] is True
    assert node["status"] == "complete"


def test_confirm_content_on_empty_section_422(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/confirm-content",
                    json={})
    assert r.status_code == 422


# -- the gate / ready-to-file is BLOCKED while a sample remains -------------
def test_gate_blocked_while_sample_unconfirmed(client):
    did = _dossier(client)
    # fill EVERY required section with a sample, arrange fee — the ONLY thing
    # left is that samples are unconfirmed.
    states = client.get(f"/api/dossier/dossiers/{did}/content").json()
    req = [n["section"] for m in states["modules"] for n in m["nodes"]
           if n.get("applicability") == "required" and "generate"
           in n.get("affordances", [])]
    assert req, "expected at least one authorable required section"
    for sec in req:
        client.post(f"/api/dossier/ectd/{did}/section/{sec}/generate",
                    json={"sample_origin": True})
    content = client.get(f"/api/dossier/dossiers/{did}/content").json()
    # at least one sample is counted, and the gate exposes it
    assert content["gate"]["unconfirmed_sample_count"] >= 1
    # a sample-blocked section keeps section_complete false => gate not green
    assert content["gate"]["section_complete"] is False
    assert content["gate"]["complete"] is False
    # the blocker is surfaced in the missing list as a review item
    assert any("sample" in str(x.get("title", "")).lower()
               or x.get("section") == "unconfirmed_sample"
               for x in content["gate"]["missing"])


def test_pre_file_sample_count_in_content_state(client):
    did = _dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                json={"contact_email": "regulatory@sponsor.example"})
    content = client.get(f"/api/dossier/dossiers/{did}/content").json()
    assert content["gate"]["unconfirmed_sample_count"] == 1
    # editing the example away (re-author with real values) clears the count
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                json={"contact_name": "Dana Real", "contact_email": "dana@myco.com",
                      "sequence_description": "Initial ANDS for Myco"})
    content = client.get(f"/api/dossier/dossiers/{did}/content").json()
    assert content["gate"]["unconfirmed_sample_count"] == 0


# -- export readiness is BLOCKED while a sample is unconfirmed --------------
def test_validate_submission_blocks_on_unconfirmed_sample(client):
    did = _dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                json={"contact_email": "regulatory@sponsor.example"})
    v = client.get(f"/api/dossier/dossiers/{did}/validate").json()
    assert v["passed"] is False
    assert any(e["rule"] == "unconfirmed_sample_content" for e in v["errors"])
    # replacing the example (re-author with real values) clears the export block
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                json={"contact_name": "Dana Real", "contact_email": "dana@myco.com",
                      "sequence_description": "Initial ANDS for Myco"})
    v2 = client.get(f"/api/dossier/dossiers/{did}/validate").json()
    assert not any(e["rule"] == "unconfirmed_sample_content"
                   for e in v2["errors"])


def test_export_fails_closed_on_unconfirmed_sample(client):
    did = _dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                json={"sample_origin": True})
    r = client.get(f"/api/dossier/ectd/{did}/export/0000")
    # WS1's export gate fails closed on the sample validation error — no
    # transmissible package while a worked example is unconfirmed.
    assert r.status_code == 409
    assert any(e["rule"] == "unconfirmed_sample_content"
               for e in r.json()["validation"]["errors"])


# -- completeness_gate counts unconfirmed samples (pure) --------------------
def test_completeness_gate_counts_unconfirmed_samples():
    node = _node("1.0")
    states = {"1.0": {"action": "generated", "doc_id": "d1",
                      "content_origin": "sample", "content_confirmed": False}}
    gate = dossier_state.completeness_gate(cs_be_only=True, states=states)
    assert gate["unconfirmed_sample_count"] >= 1
    # 1.0 must appear as still-missing (it is not complete)
    assert any(m["section"] == "1.0" for m in gate["missing"])


# ── WS2 trust-boundary hardening: sample detection is SERVER-side, so a client
#    that omits or forges the flag cannot slip worked-example values into a
#    filing (adversarial-review findings #1/#2). cs_be generator = section 1.6.
def _cs_be_dossier(client):
    did = "e654321"
    client.post("/api/dossier/dossiers",
                json={"dossier_id": did, "title": "Testozole 10 mg",
                      "submission_type": "ANDS"})
    return did


def test_sample_values_blocked_even_without_client_flag(client):
    """The exploit: POST generate with a worked-example value but NO
    sample_origin flag. The server must still detect + block it."""
    did = _cs_be_dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.6/generate",
                json={"crp_din": "02123456", "crp_brand": "Brandozole"})
    gate = client.get(f"/api/dossier/dossiers/{did}/content").json()["gate"]
    assert gate["unconfirmed_sample_count"] >= 1
    assert gate["complete"] is False
    v = client.get(f"/api/dossier/dossiers/{did}/validate").json()
    assert any(e.get("rule_id") == "CA-WS2-0001" for e in v["errors"])


def test_client_cannot_force_sample_off_when_values_are_examples(client):
    """A forged sample_origin=False with example values must still block."""
    did = _cs_be_dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.6/generate",
                json={"crp_din": "02123456", "sample_origin": False})
    gate = client.get(f"/api/dossier/dossiers/{did}/content").json()["gate"]
    assert gate["unconfirmed_sample_count"] >= 1
    assert gate["complete"] is False


def test_real_values_typed_over_samples_are_not_flagged(client):
    """No false-positive: replacing every example value with real content
    does not raise the sample block."""
    did = _cs_be_dossier(client)
    real = {"crp_brand": "Realbrand", "crp_din": "09998887",
            "dosage_form": "extended-release capsule", "strength": "20 mg",
            "study_design": "multi-dose steady-state crossover",
            "auc_ci": "95.1 - 104.2%", "cmax": "92.0 - 108.0%",
            "ruleset": "ICH M13A"}
    client.post(f"/api/dossier/ectd/{did}/section/1.6/generate", json=real)
    gate = client.get(f"/api/dossier/dossiers/{did}/content").json()["gate"]
    assert gate["unconfirmed_sample_count"] == 0


# ── WS2 re-verify hardening: Unicode-dash retype + no rubber-stamp confirm ────

def test_ascii_hyphen_retype_of_example_ci_is_still_flagged(client):
    """Finding #1: the cs_be CI examples use an en-dash. A filer who retypes the
    SAME fabricated range with a normal keyboard hyphen must still be caught."""
    did = _cs_be_dossier(client)
    # sample auc_ci is '94.2 – 106.8%' (en-dash); retype with ASCII hyphen
    client.post(f"/api/dossier/ectd/{did}/section/1.6/generate",
                json={"auc_ci": "94.2 - 106.8%", "cmax": "91.5 - 109.3%"})
    gate = client.get(f"/api/dossier/dossiers/{did}/content").json()["gate"]
    assert gate["unconfirmed_sample_count"] >= 1
    assert gate["complete"] is False


def test_confirm_refuses_unedited_sample(client):
    """Finding #2: confirm-content is not a rubber stamp — it cannot attest a
    section that still carries worked-example values."""
    did = _cs_be_dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.6/generate",
                json={"crp_din": "02123456"})
    r = client.post(f"/api/dossier/ectd/{did}/section/1.6/confirm-content",
                    json={})
    assert r.status_code == 422
    assert r.json()["title"].startswith("This section still shows")
    # still blocked afterwards
    gate = client.get(f"/api/dossier/dossiers/{did}/content").json()["gate"]
    assert gate["unconfirmed_sample_count"] >= 1
