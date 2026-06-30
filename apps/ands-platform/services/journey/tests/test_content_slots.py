"""Tests for the eCTD Module 1-5 content-slot plan (pure)."""

from __future__ import annotations

import copy

from app import content_slots as cs


# -- plan: required vs suppressed -------------------------------------------
def test_plan_generic_required_set():
    slots = cs.plan(cs_be_only=False)
    by_module = {s["module"] for s in slots if s["required"] and s["applicable"]}
    # Module 1, 2.3 QOS, 3 CMC, 5 BE are the required ANDS slots.
    assert "1" in by_module
    assert "2.3" in by_module
    assert "3" in by_module
    assert "5" in by_module
    # Module 4 nonclinical is never required for a generic ANDS.
    assert "4" not in by_module


def test_plan_module4_present_but_not_required():
    slots = cs.plan()
    m4 = [s for s in slots if s["module"] == "4"]
    assert m4, "module 4 slot should exist in the plan"
    assert all(not s["required"] for s in m4)


def test_plan_overviews_not_required_for_generic():
    slots = cs.plan(cs_be_only=False)
    overviews = [s for s in slots if s["module"] in ("2.4", "2.5", "2.6", "2.7")]
    assert overviews, "overview slots should be present in a non-CS-BE plan"
    assert all(s["applicable"] for s in overviews)
    assert all(not s["required"] for s in overviews)


def test_plan_cs_be_only_suppresses_overviews():
    slots = cs.plan(cs_be_only=True)
    overviews = [s for s in slots if s["module"] in ("2.4", "2.5", "2.6", "2.7")]
    assert overviews
    # CS-BE-only => explicitly not applicable (suppressed).
    assert all(not s["applicable"] for s in overviews)
    assert all(not s["required"] for s in overviews)
    # The core required slots survive suppression.
    core = {s["module"] for s in slots if s["required"] and s["applicable"]}
    assert {"1", "2.3", "3", "5"} <= core


def test_plan_has_bilingual_pm_slot():
    slots = cs.plan()
    pm = [s for s in slots if s.get("bilingual")]
    assert len(pm) == 1, "exactly one bilingual (Product Monograph) slot"
    pm = pm[0]
    assert pm["module"] == "1"
    assert pm["required"] and pm["applicable"]
    assert pm["state"] == "empty"
    assert pm["doc"] is None


def test_plan_ordered_by_module():
    slots = cs.plan()
    order = [s["module"] for s in slots]
    # The first slot is a Module-1 leaf; module 5 comes last.
    assert order[0] == "1"
    assert order[-1] == "5"


# -- place: bilingual gate + purity -----------------------------------------
def test_place_simple_slot_fills():
    slots = cs.plan()
    qos = next(s for s in slots if s["module"] == "2.3")
    out = cs.place(slots, qos["key"], {"name": "qos.pdf"})
    placed = next(s for s in out if s["key"] == qos["key"])
    assert placed["state"] == "filled"
    assert placed["doc"] == {"name": "qos.pdf"}


def test_place_does_not_mutate_input():
    slots = cs.plan()
    snapshot = copy.deepcopy(slots)
    qos = next(s for s in slots if s["module"] == "2.3")
    cs.place(slots, qos["key"], "qos.pdf")
    assert slots == snapshot, "place must not mutate the input list"


def test_place_bilingual_pm_partial_with_english_only():
    slots = cs.plan()
    pm = next(s for s in slots if s.get("bilingual"))
    out = cs.place(slots, pm["key"], "pm.pdf", languages=["en"])
    placed = next(s for s in out if s["key"] == pm["key"])
    assert placed["state"] == "partial"


def test_place_bilingual_pm_filled_with_both_languages():
    slots = cs.plan()
    pm = next(s for s in slots if s.get("bilingual"))
    out = cs.place(slots, pm["key"], "pm.pdf", languages=["en", "fr"])
    placed = next(s for s in out if s["key"] == pm["key"])
    assert placed["state"] == "filled"


def test_place_unknown_slot_raises():
    slots = cs.plan()
    try:
        cs.place(slots, "no_such_slot", "x")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown slot_key must raise ValueError")


# -- progress: percent math --------------------------------------------------
def test_progress_empty_plan():
    prog = cs.progress(cs.plan())
    assert prog["required_filled"] == 0
    assert prog["percent"] == 0
    assert prog["complete"] is False
    assert prog["required_total"] >= 4


def test_progress_partial_percent_math():
    slots = cs.plan()
    required = [s for s in slots if s["required"] and s["applicable"]]
    total = len(required)
    # Fill exactly half (rounding) of the required slots with simple docs.
    fill = required[: total // 2]
    for s in fill:
        if s.get("bilingual"):
            slots = cs.place(slots, s["key"], "d", languages=["en", "fr"])
        else:
            slots = cs.place(slots, s["key"], "d")
    prog = cs.progress(slots)
    assert prog["required_total"] == total
    assert prog["required_filled"] == len(fill)
    assert prog["percent"] == round(len(fill) * 100 / total)
    assert prog["complete"] is False


def test_progress_complete_when_all_required_filled():
    slots = cs.plan()
    for s in list(slots):
        if s["required"] and s["applicable"]:
            langs = ["en", "fr"] if s.get("bilingual") else None
            slots = cs.place(slots, s["key"], "d", languages=langs)
    prog = cs.progress(slots)
    assert prog["required_filled"] == prog["required_total"]
    assert prog["percent"] == 100
    assert prog["complete"] is True
    assert prog["by_module"]["1"]["filled"] == prog["by_module"]["1"]["total"]


def test_progress_bilingual_partial_does_not_count():
    slots = cs.plan()
    pm = next(s for s in slots if s.get("bilingual"))
    slots = cs.place(slots, pm["key"], "pm.pdf", languages=["en"])
    prog = cs.progress(slots)
    # A partial PM is not a filled required slot.
    assert prog["required_filled"] == 0


# -- checklist_gate: missing naming ------------------------------------------
def test_checklist_gate_names_missing_slots():
    slots = cs.plan()
    gate = cs.checklist_gate(slots)
    assert gate["complete"] is False
    missing_keys = {m["key"] for m in gate["missing"]}
    required_keys = {s["key"] for s in slots if s["required"] and s["applicable"]}
    assert missing_keys == required_keys
    assert all("title" in m and "key" in m for m in gate["missing"])


def test_checklist_gate_complete_when_filled():
    slots = cs.plan()
    for s in list(slots):
        if s["required"] and s["applicable"]:
            langs = ["en", "fr"] if s.get("bilingual") else None
            slots = cs.place(slots, s["key"], "d", languages=langs)
    gate = cs.checklist_gate(slots)
    assert gate["complete"] is True
    assert gate["missing"] == []


def test_checklist_gate_pm_english_only_still_missing():
    slots = cs.plan()
    for s in list(slots):
        if s["required"] and s["applicable"]:
            langs = ["en"] if s.get("bilingual") else None  # PM english-only
            slots = cs.place(slots, s["key"], "d", languages=langs)
    gate = cs.checklist_gate(slots)
    assert gate["complete"] is False
    missing_keys = {m["key"] for m in gate["missing"]}
    pm = next(s for s in slots if s.get("bilingual"))
    assert pm["key"] in missing_keys


# -- tower_view: per-module roll-up ------------------------------------------
def test_tower_view_one_entry_per_module():
    tower = cs.tower_view(cs.plan())
    modules = [t["module"] for t in tower]
    assert modules == ["1", "2", "3", "4", "5"]


def test_tower_view_empty_is_todo_or_na():
    tower = {t["module"]: t for t in cs.tower_view(cs.plan())}
    # Required modules with nothing placed are "todo".
    assert tower["1"]["state"] == "todo"
    assert tower["3"]["state"] == "todo"
    assert tower["5"]["state"] == "todo"
    # Module 4 has no required slots for a generic ANDS => na.
    assert tower["4"]["state"] == "na"


def test_tower_view_pass_when_module_required_filled():
    slots = cs.plan()
    for s in list(slots):
        if s["module"] == "3" and s["required"] and s["applicable"]:
            slots = cs.place(slots, s["key"], "d")
    tower = {t["module"]: t for t in cs.tower_view(slots)}
    assert tower["3"]["state"] == "pass"
    assert tower["1"]["state"] == "todo"


def test_tower_view_partial_when_some_filled():
    slots = cs.plan()
    # Module 1 has multiple required leaves; fill only one => partial.
    m1_required = [s for s in slots if s["module"] == "1"
                   and s["required"] and s["applicable"]]
    assert len(m1_required) >= 2
    first = m1_required[0]
    langs = ["en", "fr"] if first.get("bilingual") else None
    slots = cs.place(slots, first["key"], "d", languages=langs)
    tower = {t["module"]: t for t in cs.tower_view(slots)}
    assert tower["1"]["state"] == "partial"


def test_tower_view_cs_be_only_overviews_na():
    tower = {t["module"]: t for t in cs.tower_view(cs.plan(cs_be_only=True))}
    # Module 2 rolls up 2.3 (required) + 2.4-2.7 (suppressed); still has a
    # required leaf (2.3) so it is not 'na'.
    assert tower["2"]["state"] in ("todo", "partial")
