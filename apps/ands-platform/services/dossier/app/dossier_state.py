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
        if {"en", "fr"} <= langs:
            return COMPLETE
        return PARTIAL if langs else EMPTY
    if entry.get("doc_id") or entry.get("action") in ("uploaded", "generated"):
        return COMPLETE
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


def completeness_gate(*, cs_be_only: bool, states: dict) -> dict:
    """Which required sections across all modules are still incomplete."""
    missing = []
    for n in _required_docs(section_tree.all_nodes(cs_be_only=cs_be_only)):
        if resolve_status(n, states.get(n["section"])) != COMPLETE:
            missing.append({"section": n["section"], "title": n["title"],
                            "module": n["module"]})
    return {"complete": not missing, "missing": missing}


PASS, TODO = "pass", "todo"


def tower_view(*, cs_be_only: bool, states: dict) -> list[dict]:
    """Per-module 1–5 roll-up: pass / partial / todo / na (content_slots contract)."""
    tree = section_tree.section_tree(cs_be_only=cs_be_only)
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
