"""Interactive (LLM chat) drafting: the llm_draft override, the ai_draftable
flag, and the draft-chat endpoint's eager validation."""

import pytest

from app import generators, section_tree


def _dossier(client):
    r = client.post("/api/dossier/dossiers",
                    json={"dossier_id": "e123456", "title": "Drugazole 10 mg"})
    assert r.status_code == 201
    return "e123456"


# -- llm_draft override (pure) ----------------------------------------------
@pytest.mark.parametrize("key", sorted(generators.LLM_DRAFTABLE))
def test_llm_draft_overrides_template_for_prose_docs(key):
    doc = generators.generate(key, {"llm_draft": "Dear Health Canada, DRAFT-X."})
    assert doc["content_type"] == "application/pdf"
    assert b"DRAFT-X" in doc["body"]
    title, stem = generators.LLM_DRAFTABLE[key]
    assert doc["filename"] == f"{stem}.pdf" and doc["title"] == title


def test_llm_draft_ignored_for_structured_rep_form():
    doc = generators.generate("rep_application_form",
                              {"dossier_id": "e123456",
                               "llm_draft": "prose that must not leak in"})
    assert doc["content_type"] == "application/xml"
    assert b"prose that must not leak in" not in doc["body"]


def test_empty_llm_draft_falls_back_to_template():
    doc = generators.generate("cover_letter",
                              {"dossier_id": "e123456", "llm_draft": "  "})
    assert b"e123456" in doc["body"]


# -- ai_draftable flag in the section tree ----------------------------------
def test_section_tree_flags_prose_generators_as_ai_draftable():
    by_section = {n["section"]: n for n in section_tree.all_nodes()}
    assert by_section["1.0"]["ai_draftable"] is True          # cover letter
    assert by_section["1.2.3"]["ai_draftable"] is True        # attestation
    assert by_section["1.2.4"]["ai_draftable"] is True        # Form V
    assert by_section["1.6"]["ai_draftable"] is True          # CS-BE
    assert by_section["2.3"]["ai_draftable"] is True          # QOS
    assert by_section["1.2.1"]["ai_draftable"] is False       # REP form (XML)
    assert by_section["1.3.1"]["ai_draftable"] is False       # upload-only


# -- draft-chat endpoint: eager validation ----------------------------------
def test_draft_chat_422_on_upload_only_section(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.3.1/draft-chat",
                    json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 422
    assert r.json()["rule"] == "section_not_generatable"


def test_draft_chat_422_on_structured_form(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.2.1/draft-chat",
                    json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 422
    assert r.json()["rule"] == "section_not_ai_draftable"


def test_draft_chat_503_when_llm_unconfigured(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.0/draft-chat",
                    json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503
    assert r.json()["rule"] == "llm_not_configured"


# -- finalised draft flows through the normal generate pipeline -------------
def test_generate_with_llm_draft_places_pdf(client):
    did = _dossier(client)
    r = client.post(f"/api/dossier/ectd/{did}/section/1.2.3/generate",
                    json={"llm_draft": "The sponsor attests everything."})
    assert r.status_code == 200
    node = next(n for m in r.json()["modules"] for n in m["nodes"]
                if n["section"] == "1.2.3")
    assert node["status"] == "complete" and node["action"] == "generated"
    doc = client.get(f"/api/dossier/documents/{node['document']['doc_id']}")
    assert doc.status_code == 200
    assert b"The sponsor attests everything." in doc.content
