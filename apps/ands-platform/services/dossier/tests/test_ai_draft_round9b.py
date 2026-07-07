"""Round-9 ai_draft backlog — stage-2 backend pieces (web-panel enablers).

Covers (ROUND9-FIX-BACKLOG.md, AI-assisted Drafting flow):
- builder_forms MAJOR "AI drafting lacks source transparency, per-section
  off-switch, harder attestation" (n=3, ask 3) + MAJOR "Review step lacks
  guidance clause citations and side-by-side comparison" (n=9): the saved AI
  draft's TEXT is persisted with the section entry so the panel can require
  scrolling the full draft before the attest button enables, and render the
  draft side-by-side with the cited guidance before attestation.
- ai_draft BLOCKER "Attestation … exportable audit record" (n=4): the
  draft text travels in the per-section audit record.
"""


def _dossier(client, did="e123456"):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": did, "title": "Drugazole 10 mg"})
    assert r.status_code == 201
    return did


def _node(state, section):
    return next(n for m in state["modules"] for n in m["nodes"]
                if n["section"] == section)


DRAFT = ("Dear Health Canada,\n\nThis Abbreviated New Drug Submission covers "
         "Drugazole 10 mg tablets.\n\nSincerely,\nRegulatory Affairs")


def test_ai_draft_text_persisted_on_node(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.2.3/generate",
                    json={"llm_draft": DRAFT})
    assert r.status_code == 200
    node = _node(r.json(), "1.2.3")
    assert node["content_origin"] == "ai_draft"
    # the exact draft text the filer must scroll/review travels with the node
    assert node["draft_text"] == DRAFT


def test_draft_text_travels_in_section_audit_record(client):
    did = _dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.2.3/generate",
                json={"llm_draft": DRAFT})
    rec = client.get(
        f"/api/dossier/ectd/{did}/section/1.2.3/audit-record").json()
    assert rec["draft_text"] == DRAFT


def test_non_ai_generate_has_no_draft_text(client):
    did = _dossier(client)
    sample = client.get(
        f"/api/dossier/ectd/{did}/section/1.0/sample").json()["fields"]
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/generate",
                    json=sample)
    assert r.status_code == 200
    assert not _node(r.json(), "1.0").get("draft_text")


def test_upload_clears_stale_ai_draft_text(client):
    did = _dossier(client)
    client.post(f"/api/dossier/ectd/{did}/section/1.2.3/generate",
                json={"llm_draft": DRAFT})
    r = client.post(
        f"/api/dossier/ectd/{did}/section/1.2.3/upload",
        files={"file": ("cover.pdf", b"%PDF-1.7 real upload",
                        "application/pdf")})
    assert r.status_code == 200
    node = _node(r.json(), "1.2.3")
    assert node["content_origin"] == "uploaded"
    # the superseded AI draft text (and its attestation) must not linger
    assert not node.get("draft_text")
    assert not node.get("attestation")
