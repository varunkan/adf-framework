"""FORMS-WEB: the API surface the dynamic web form needs — fetch a section's
declarative form schema, and AI-draft ONE prose field of it.

The web renders every eCTD content section as a form (upload + form-fill +
per-field AI-draft + generate). It fetches the section's schema from
``GET /api/dossier/section-form-schema/{section}`` and, for a prose field,
streams a draft from ``POST /ectd/{id}/section/{section}/draft-field``.

Honesty is enforced upstream (the generated doc still carries the _DRAFT
watermark and the review gate); these endpoints only add the fetch + per-field
draft affordances.
"""

from __future__ import annotations


# --- section-form-schema fetch ---------------------------------------------

def test_section_form_schema_returns_the_declarative_schema(client):
    r = client.get("/api/dossier/section-form-schema/1.2.4")
    assert r.status_code == 200
    schema = r.json()["schema"]
    assert schema["section"] == "1.2.4"
    assert schema["generator"] == "patent_form_v"
    assert schema["title"] and schema["fields"]
    # a prose field is flagged so the web shows a "Draft with AI" button on it
    assert any(f.get("prose") for f in schema["fields"])
    # every field carries the contract keys the web renders by
    for f in schema["fields"]:
        assert set(f) >= {"name", "label", "type", "required", "prose", "help"}


def test_section_form_schema_structured_section(client):
    # a universal "structured" section (was upload-only) is now form-fillable
    r = client.get("/api/dossier/section-form-schema/3.2.P.8")
    assert r.status_code == 200
    schema = r.json()["schema"]
    assert schema["generator"] == "structured"
    assert schema["section"] == "3.2.P.8"


def test_section_form_schema_unknown_section_404(client):
    # a group node / backbone section has no authorable form
    r = client.get("/api/dossier/section-form-schema/9.9.9")
    assert r.status_code == 404
    assert r.json()["rule"] == "no_form_schema"


# --- per-field AI draft (eager validation before any stream) ---------------

def _mk_dossier(client, dossier_id="e987654"):
    client.post("/api/dossier/dossiers",
                json={"dossier_id": dossier_id, "title": "Drugazole 10 mg tablet",
                      "submission_type": "ANDS"})
    return dossier_id


def test_draft_field_unknown_field_422(client):
    did = _mk_dossier(client)
    r = client.post(
        f"/api/dossier/ectd/{did}/section/1.2.4/draft-field",
        json={"field": "not_a_field"})
    assert r.status_code == 422
    assert r.json()["rule"] == "field_not_ai_draftable"


def test_draft_field_non_prose_field_422(client):
    # crp_brand is a plain text field on Form V, not prose -> not AI-draftable
    did = _mk_dossier(client)
    r = client.post(
        f"/api/dossier/ectd/{did}/section/1.2.4/draft-field",
        json={"field": "crp_brand"})
    assert r.status_code == 422
    assert r.json()["rule"] == "field_not_ai_draftable"


def test_draft_field_llm_unconfigured_503(client, monkeypatch):
    from app import llm_provider
    monkeypatch.setattr(llm_provider, "is_configured", lambda *a, **k: False)
    did = _mk_dossier(client)
    r = client.post(
        f"/api/dossier/ectd/{did}/section/1.2.4/draft-field",
        json={"field": "allegation"})
    assert r.status_code == 503
    assert r.json()["rule"] == "llm_not_configured"


def test_draft_field_streams_when_configured(client, monkeypatch):
    # stub the LLM path so the test is deterministic + offline
    from app import llm_provider

    monkeypatch.setattr(llm_provider, "is_configured", lambda *a, **k: True)

    async def _fake_stream(messages):
        # the system prompt names the field so we can assert the wiring
        assert any("allegation" in (m.get("content") or "").lower()
                   or "s.5" in (m.get("content") or "").lower()
                   for m in messages)
        for tok in ["The Patent ", "Register lists ", "no relevant patents."]:
            yield tok

    monkeypatch.setattr(llm_provider, "stream_chat", _fake_stream)
    did = _mk_dossier(client)
    r = client.post(
        f"/api/dossier/ectd/{did}/section/1.2.4/draft-field",
        json={"field": "allegation"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "The Patent " in body
    assert "[DONE]" in body
