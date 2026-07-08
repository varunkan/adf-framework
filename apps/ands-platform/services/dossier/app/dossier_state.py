"""Per-dossier section state → status, module progress, completeness gate, tower.

Pure. Given the section tree (:mod:`section_tree`) and the persisted per-section
state entries, resolves each section's status (empty / partial / complete / na),
rolls it up to per-module progress + a completeness gate, and emits the per-module
``tower_view`` — the SAME shape the journey's ``content_slots.tower_view`` returns,
so the 3D submission tower renders unchanged from real dossier state.
"""

from __future__ import annotations

from . import section_tree

EMPTY, PARTIAL, COMPLETE, NA = "empty", "partial", "complete", "na"

# content origins that require an explicit "I reviewed & edited this" confirm
# before the section counts as complete (WS2 patient-safety block). A worked
# EXAMPLE ("sample") or an AI draft ("ai_draft") must be structurally incapable
# of reaching a filing while it is still unconfirmed.
_REVIEW_REQUIRED_ORIGINS = ("sample", "ai_draft")


def needs_review(entry: dict | None) -> bool:
    """True when the section holds sample-origin or AI-draft content the filer
    has not yet confirmed as their own. Such content can never be complete."""
    entry = entry or {}
    return (entry.get("content_origin") in _REVIEW_REQUIRED_ORIGINS
            and not entry.get("content_confirmed"))


def resolve_status(node: dict, entry: dict | None) -> str:
    """The status of one section given its persisted state entry (or None)."""
    applic = node.get("applicability")
    if applic in ("na", "suppressed"):
        return NA
    entry = entry or {}
    if entry.get("action") == "na":
        return NA
    if node.get("bilingual"):
        langs = {str(x).lower() for x in (entry.get("languages") or [])}
        # an unconfirmed sample/AI draft is never "complete", even bilingually
        if {"en", "fr"} <= langs and not needs_review(entry):
            return COMPLETE
        return PARTIAL if langs else EMPTY
    if entry.get("doc_id") or entry.get("action") in ("uploaded", "generated"):
        # SAFETY: sample/AI content pending review stalls at PARTIAL — a placed
        # document is present, but it is not yet the filer's confirmed content.
        return PARTIAL if needs_review(entry) else COMPLETE
    return EMPTY


def _required_docs(nodes: list[dict]) -> list[dict]:
    return [n for n in nodes
            if n.get("kind") == "document" and n.get("applicability") == "required"]


def annotate(nodes: list[dict], states: dict) -> list[dict]:
    """Return the nodes with a live ``status`` + the placed doc metadata."""
    out = []
    for n in nodes:
        entry = states.get(n["section"]) or {}
        item = dict(n)
        item["status"] = resolve_status(n, entry)
        item["action"] = entry.get("action")
        item["document"] = entry.get("document")          # meta (no bytes)
        item["documents"] = entry.get("documents")        # bilingual: {en,fr}
        item["languages"] = entry.get("languages")
        item["na_reason"] = entry.get("na_reason")
        # provenance the UI needs to show the review/confirm banner + block
        item["content_origin"] = entry.get("content_origin")
        item["content_confirmed"] = bool(entry.get("content_confirmed"))
        item["needs_review"] = needs_review(entry)
        # Round-9 ai_draft/builder_forms surfaces: the per-section AI policy
        # (off-switch), the named attestation, the still-example field list
        # and the last-touched stamp all travel to the UI with the node.
        item["ai_disabled"] = bool(entry.get("ai_disabled"))
        item["attestation"] = entry.get("attestation")
        item["sample_fields"] = entry.get("sample_fields") or []
        item["content_author"] = entry.get("content_author")
        item["updated_at"] = entry.get("updated_at")
        # Round-9 builder_forms MAJOR "…harder attestation" (n=3, ask 3) +
        # ai_draft MAJOR "side-by-side comparison" (n=9): the saved AI draft's
        # exact text — the panel requires it scrolled before attest enables
        # and renders it beside the cited guidance.
        item["draft_text"] = entry.get("draft_text")
        out.append(item)
    return out


def module_progress(nodes: list[dict], states: dict) -> dict:
    req = _required_docs(nodes)
    total = len(req)
    filled = sum(1 for n in req
                 if resolve_status(n, states.get(n["section"])) == COMPLETE)
    return {"required_total": total, "required_filled": filled,
            "percent": round(filled * 100 / total) if total else 0,
            "complete": total > 0 and filled == total}


def unconfirmed_sample_count(states: dict) -> int:
    """How many sections (across ALL of them, not only required) still hold an
    unconfirmed sample/AI draft — the pre-file 'N sample values remain' count."""
    return sum(1 for entry in (states or {}).values() if needs_review(entry))


def completeness_gate(*, cs_be_only: bool, states: dict,
                      submission_type: str = "ANDS",
                      dosage_form_class: str = "ir_solid_oral") -> dict:
    """Which required sections across all modules are still incomplete.

    A required section holding an unconfirmed sample/AI draft is reported as
    still-missing AND flagged with ``needs_review`` so the caller can render a
    'review your sample' blocker distinct from a genuinely empty section."""
    missing = []
    for n in _required_docs(section_tree.all_nodes(
            cs_be_only=cs_be_only, submission_type=submission_type,
            dosage_form_class=dosage_form_class)):
        entry = states.get(n["section"])
        if resolve_status(n, entry) != COMPLETE:
            missing.append({"section": n["section"], "title": n["title"],
                            "module": n["module"],
                            "needs_review": needs_review(entry)})
    return {"complete": not missing, "missing": missing,
            "unconfirmed_sample_count": unconfirmed_sample_count(states)}


PASS, TODO = "pass", "todo"


def tower_view(*, cs_be_only: bool, states: dict,
               submission_type: str = "ANDS",
               dosage_form_class: str = "ir_solid_oral") -> list[dict]:
    """Per-module 1–5 roll-up: pass / partial / todo / na (content_slots contract)."""
    tree = section_tree.section_tree(cs_be_only=cs_be_only,
                                     submission_type=submission_type,
                                     dosage_form_class=dosage_form_class)
    out = []
    for m in tree["modules"]:
        req = _required_docs(m["nodes"])
        total = len(req)
        filled = sum(1 for n in req
                     if resolve_status(n, states.get(n["section"])) == COMPLETE)
        if total == 0:
            state = NA
        elif filled == total:
            state = PASS
        elif filled == 0:
            state = TODO
        else:
            state = PARTIAL
        out.append({"module": m["module"], "state": state,
                    "required_total": total, "required_filled": filled})
    return out
