"""AI-drafting transparency metadata (pure — no I/O beyond Settings reads).

Round-9 ai_draft backlog:
- BLOCKER "AI provider identity, data residency and DPA not verifiable" (n=8):
  :func:`provider_disclosure` + :func:`dpa_text` power the inspectable
  AI-provider disclosure and the downloadable data-processing document.
- builder_forms MAJOR "AI drafting lacks source transparency…" (n=3, ask 1):
  :func:`draft_context` enumerates exactly what a draft is generated from.

HONESTY BAR: everything here states what THIS deployment actually does. Facts
about the provider's own policies are linked, not asserted as our guarantees,
and the downloadable document says plainly it is NOT a countersigned DPA.
"""

from __future__ import annotations

from .config import Settings

# The single AI path in this codebase is llm_provider.stream_chat → Groq's
# OpenAI-compatible API (see llm_provider._CHAT_URL). If the provider ever
# changes, this module is the one place the user-facing disclosure lives.
_PROVIDER_NAME = "Groq (GroqCloud hosted inference)"
_PROVIDER_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
_PROVIDER_POLICY_URL = "https://groq.com/privacy-policy/"
_HOSTING_REGION = ("United States (GroqCloud's US-hosted inference "
                   "infrastructure)")


def provider_disclosure() -> dict:
    """The inspectable AI-provider disclosure — named provider, residency,
    retention, and the honest DPA note. Survives a client audit better than a
    hover tooltip because every field is a flat, quotable statement."""
    settings = Settings()
    configured = bool(settings.groq_api_key)
    return {
        "configured": configured,
        "provider": _PROVIDER_NAME,
        "model": settings.groq_model,
        "endpoint": _PROVIDER_ENDPOINT,
        "hosting_region": _HOSTING_REGION,
        # the plain data-residency answer buyers asked for: yes, it leaves
        # Canada — there is no Canadian-region inference option on this path.
        "leaves_canada": True,
        "data_residency": (
            "When you use AI drafting, the section text and dossier facts for "
            "that draft are sent to the provider's US-hosted service — the "
            "drafting data leaves Canada for the duration of the request. "
            "Everything else in ANDS Studio stays in your own deployment."
            + ("" if configured else " AI drafting is NOT configured in this "
               "deployment, so no dossier data is currently sent anywhere.")),
        "retention": (
            "ANDS Studio sends drafting data per request only and stores "
            "prompts/outputs nowhere except the dossier record you save and "
            "its audit trail. Provider-side retention is governed by the "
            "provider's own published data-usage policy (linked) — verify the "
            "current version for client audits; we do not restate it here so "
            "this disclosure can never silently drift from it."),
        "isolation": (
            "Draft requests are scoped to one dossier in one workspace — "
            "dossier text is never shared across sponsors or reused to build "
            "prompts for another client's drafts."),
        "training": (
            "ANDS Studio never submits your content to any training process. "
            "For the provider's own training/usage commitments, rely on the "
            "linked provider policy, not on this app's copy."),
        "policy_url": _PROVIDER_POLICY_URL,
        "dpa_note": (
            "The downloadable document below is ANDS Studio's data-processing "
            "disclosure for the AI-drafting path. It is NOT a countersigned "
            "data-processing agreement with the provider — execute your own "
            "DPA with the provider if your clients require one."),
    }


def dpa_text() -> str:
    """The downloadable AI data-processing disclosure (plain text) — the
    artifact a consultant can hand a client auditor or privacy team."""
    d = provider_disclosure()
    lines = [
        "ANDS Studio — AI drafting data-processing disclosure",
        "=" * 54,
        "",
        f"AI provider:      {d['provider']}",
        f"Model:            {d['model']}",
        f"API endpoint:     {d['endpoint']}",
        f"Hosting region:   {d['hosting_region']}",
        f"Provider policy:  {d['policy_url']}",
        "",
        "What is sent, and when",
        "----------------------",
        "Only when a user explicitly requests an AI draft (chat draft or a",
        "per-field draft), ANDS Studio sends: the section's title, purpose and",
        "Health Canada guidance summary, the known dossier facts (sponsor,",
        "product, IDs), and the user's chat messages. Nothing is sent in the",
        "background; a dossier that never uses AI drafting sends nothing.",
        "",
        "Data residency",
        "--------------",
        d["data_residency"],
        "",
        "Retention",
        "---------",
        d["retention"],
        "",
        "Per-sponsor isolation",
        "---------------------",
        d["isolation"],
        "",
        "Training",
        "--------",
        d["training"],
        "",
        "Audit trail",
        "-----------",
        "Every saved AI draft is stamped origin=ai_draft with a file",
        "fingerprint (md5) and written to the dossier's append-only Part-11",
        "ledger; the named review attestation that clears it is recorded",
        "there too. The per-section audit record is exportable in-app.",
        "",
        "Status of this document",
        "-----------------------",
        d["dpa_note"],
    ]
    return "\n".join(lines)


def draft_context(node: dict, ctx: dict) -> dict:
    """What ONE draft for this section is generated from — mirrors exactly the
    inputs :func:`drafting.system_prompt` assembles, so the disclosure can
    never claim less (or more) than what is really sent."""
    facts = {k: v for k, v in sorted((ctx or {}).items())
             if v not in (None, "", "—") and not isinstance(v, dict)}
    sources = [
        "This section's title, purpose and Health Canada guidance summary "
        "(shown in the 'What Health Canada needs here' box)",
        "The known dossier facts listed below (and nothing else from your "
        "workspace)",
        "Your chat messages in this drafting conversation",
    ]
    if node.get("generator_key"):
        sources.append(
            "A fixed document-structure hint for this document type "
            "(the Health Canada-expected structure, maintained in-app)")
    return {
        "section": str(node.get("section", "")),
        "sources": sources,
        "facts": facts,
        "excluded": (
            "Other dossiers, other workspaces/sponsors, uploaded document "
            "bytes and prior drafts are NOT part of the prompt."),
        "provider": provider_disclosure(),
    }
