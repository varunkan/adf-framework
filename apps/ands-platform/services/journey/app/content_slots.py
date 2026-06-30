"""The eCTD Module 1-5 content plan for an ANDS, as placeable SLOTS (pure).

What the guided UI drags documents onto, and what the 3D submission tower
reflects. Each leaf of the eCTD tree the filer must populate becomes a SLOT with
a regulatory ``required``/``applicable`` flag; the front-end fills slots and asks
this module for progress, the checklist gate, and the per-module tower roll-up.

Regulatory grounding (ANDS / Health Canada eCTD):
- Module 1 (Canada-specific administrative/regional) is REQUIRED: the cover
  letter, the Canadian Module-1 administrative forms, and the BILINGUAL Product
  Monograph (English + French) — treated as ONE required slot that is only
  "filled" when BOTH languages are present.
- Module 2.3 Quality Overall Summary (QOS-CE) is REQUIRED.
- Module 2.4/2.5/2.6/2.7 overviews & summaries are generally NOT required for a
  generic, and for a CS-BE-only ANDS they are explicitly SUPPRESSED (not
  applicable). The required-vs-suppressed truth is reused from
  ``drug_intake.ands_content_model(cs_be_only)`` so this module never re-encodes it.
- Module 3 (Quality / CMC) is REQUIRED.
- Module 4 (nonclinical study reports) is NOT required for a generic ANDS.
- Module 5 (clinical — the comparative bioavailability / bioequivalence reports)
  is REQUIRED for an ANDS.

Pure: deterministic, no I/O, no clock. (No date input is needed here — the eCTD
content plan is time-invariant — but if one were ever added it would be an
explicit ``as_of`` argument, never ``datetime.now()``.)
"""

from __future__ import annotations

from . import drug_intake

EMPTY = "empty"
PARTIAL = "partial"
FILLED = "filled"

# The Module-1 Canadian leaf slots (regional, always applicable for an ANDS).
# Order matters: it is the order the UI lays the slots out and the tower stacks.
_MODULE1_LEAVES = (
    {"key": "m1_cover_letter", "title": "Cover letter", "bilingual": False},
    {"key": "m1_administrative",
     "title": "Canadian Module-1 administrative & forms", "bilingual": False},
    {"key": "m1_product_monograph",
     "title": "Product Monograph (English + French)", "bilingual": True},
)


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def _module1_slots() -> list[dict]:
    out = []
    for leaf in _MODULE1_LEAVES:
        out.append({"key": leaf["key"], "module": "1", "title": leaf["title"],
                    "required": True, "applicable": True,
                    "bilingual": leaf["bilingual"], "state": EMPTY, "doc": None})
    return out


def _slot_key_for_module(module: str) -> str:
    return "m" + module.replace(".", "_")


def plan(cs_be_only: bool = False) -> list[dict]:
    """The ordered slot list for an ANDS content model.

    Module 1 expands into its Canadian leaf slots (incl. the bilingual PM);
    every other eCTD module becomes a single slot whose ``required``/
    ``applicable`` flags are taken straight from
    ``drug_intake.ands_content_model`` so a CS-BE-only plan suppresses 2.4-2.7.
    """
    model = drug_intake.ands_content_model(cs_be_only=bool(cs_be_only))
    slots: list[dict] = []
    for mod in model["modules"]:
        if mod["module"] == "1":
            slots.extend(_module1_slots())
            continue
        slots.append({
            "key": _slot_key_for_module(mod["module"]),
            "module": mod["module"], "title": mod["title"],
            "required": bool(mod["required"]),
            "applicable": bool(mod["applicable"]),
            "bilingual": False, "state": EMPTY, "doc": None})
    return slots


def _both_languages(languages) -> bool:
    langs = {_s(l).lower() for l in (languages or [])}
    return "en" in langs and "fr" in langs


def place(slots: list, slot_key: str, doc, *, languages: list = None) -> list:
    """Return a NEW slot list with ``slot_key``'s doc set and state updated.

    For the bilingual Product-Monograph slot the state is ``filled`` only when
    ``languages`` contains both ``en`` and ``fr``; otherwise ``partial``. Any
    other slot becomes ``filled`` once a doc is placed. An unknown ``slot_key``
    raises ``ValueError``. The input list is never mutated (purity).
    """
    key = _s(slot_key)
    if not any(_s(s.get("key")) == key for s in slots):
        raise ValueError(f"unknown slot_key '{slot_key}'")
    out: list[dict] = []
    for s in slots:
        nxt = dict(s)
        if _s(s.get("key")) == key:
            nxt["doc"] = doc
            nxt["languages"] = list(languages) if languages else None
            if s.get("bilingual"):
                nxt["state"] = FILLED if _both_languages(languages) else PARTIAL
            else:
                nxt["state"] = FILLED
        out.append(nxt)
    return out


def _required_applicable(slots: list) -> list[dict]:
    return [s for s in slots if s.get("required") and s.get("applicable")]


def progress(slots: list) -> dict:
    """Completion over the REQUIRED + applicable slots only, with a per-module
    breakdown the guided UI shows beside the eCTD tree."""
    required = _required_applicable(slots)
    total = len(required)
    filled = sum(1 for s in required if s.get("state") == FILLED)
    by_module: dict[str, dict] = {}
    for s in required:
        m = by_module.setdefault(s["module"], {"total": 0, "filled": 0})
        m["total"] += 1
        if s.get("state") == FILLED:
            m["filled"] += 1
    return {
        "required_total": total, "required_filled": filled,
        "percent": round(filled * 100 / total) if total else 0,
        "complete": total > 0 and filled == total,
        "by_module": by_module}


def checklist_gate(slots: list) -> dict:
    """The plain-language gate: are all required + applicable slots filled, and
    if not, which ones (by key + title) are still missing."""
    missing = [{"key": s["key"], "title": s["title"], "module": s["module"]}
               for s in _required_applicable(slots) if s.get("state") != FILLED]
    return {"complete": not missing, "missing": missing}


# The five eCTD modules the 3D tower stacks (2.x roll up into one "2" floor).
_TOWER_MODULES = ("1", "2", "3", "4", "5")

PASS = "pass"
TODO = "todo"
NA = "na"


def _tower_module_of(slot: dict) -> str:
    return _s(slot.get("module")).split(".")[0]


def tower_view(slots: list) -> list[dict]:
    """A compact per-MODULE roll-up the 3D tower consumes — one entry per module
    1..5 with ``state`` in {pass, partial, todo, na}:

    - ``na``   — the module has no applicable required slots (e.g. Module 4 for a
                 generic, or 2.x when every leaf is suppressed),
    - ``pass`` — all of the module's required slots are filled,
    - ``partial`` — some (but not all) required slots filled,
    - ``todo`` — an applicable, required module with nothing filled yet.
    """
    out: list[dict] = []
    for module in _TOWER_MODULES:
        required = [s for s in slots
                    if _tower_module_of(s) == module
                    and s.get("required") and s.get("applicable")]
        total = len(required)
        filled = sum(1 for s in required if s.get("state") == FILLED)
        if total == 0:
            state = NA
        elif filled == total:
            state = PASS
        elif filled == 0:
            state = TODO
        else:
            state = PARTIAL
        out.append({"module": module, "state": state,
                    "required_total": total, "required_filled": filled})
    return out
