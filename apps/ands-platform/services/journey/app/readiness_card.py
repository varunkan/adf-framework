"""The persistent READY / BLOCKED card — derived from the journey spine (pure).

A plain-language "the single thing standing between you and 'ready to file'" card
(plan: 'surface readiness continuously'). It reuses the gated journey stages — no
new regulatory logic — and turns them into tiles + blocking_items + a one-click
Resume to the current step. 'READY to file' means everything up to and including
the signature is done, so transmit is unlocked.
"""

from __future__ import annotations

from . import journey as J

# The stages whose completion the readiness card surfaces as tiles, in order.
_TILE_KEYS = ("company", "dossier", "submission", "content", "validate", "fees",
              "review", "sign")


def card(payload: dict) -> dict:
    """Build the READY/BLOCKED readiness card from a submission's signals."""
    payload = payload or {}
    stages = {s["key"]: s for s in J.stages(payload)}
    pos = J.position(payload)

    tiles = []
    for key in _TILE_KEYS:
        st = stages[key]
        state = ("pass" if st["done"] else
                 "current" if st["current"] else "todo")
        tiles.append({"key": key, "label": st["label"], "state": state,
                      "reg": st.get("reg", "")})

    # READY to file once orient..sign (stages 0..8) are all done — transmit open.
    # The 'validate' stage is 'done' only when the REAL eCTD validation ran with
    # zero errors (see service.advance 'validate'), so READY is already gated on
    # validation passing — the `validation` tier below makes that legible instead
    # of leaving READY to read like a mere step-completion badge.
    ready_to_file = all(stages[k]["done"] for k in _TILE_KEYS)
    transmitted = pos["transmitted"]
    status = "READY" if (ready_to_file or transmitted) else "BLOCKED"

    # A distinct 'eCTD technical validation' tier — separate from the filing
    # checklist %. Round-7 #1 blocker: every persona read the green badge as a
    # workflow checkbox, not a validation verdict. Surface the real report.
    _v = payload.get("validation") or {}
    validation = {
        "ran": bool(_v.get("ran")),
        "passed": bool(_v.get("ran")) and int(_v.get("errors", 0) or 0) == 0,
        "errors": int(_v.get("errors", 0) or 0),
        "warnings": int(_v.get("warnings", 0) or 0),
        "checked": int(_v.get("checked", 0) or 0),
        "real": bool(_v.get("real")),
        "criteria": _v.get("criteria"),
        "failing_rules": _v.get("failing_rules") or [],
    }

    # The single thing standing between the user and 'ready to file' is the
    # current stage — surfaced in plain language (any stage, incl. orientation).
    blocking_items = []
    if status == "BLOCKED":
        cur = next((s for s in J.stages(payload) if s["current"]), None)
        if cur is not None:
            blocking_items.append({
                "key": cur["key"], "label": cur["label"],
                "requirement": cur["unlocks"], "route": cur["route"],
                "why": cur["purpose"], "cta": cur.get("cta")})

    return {
        "status": status,
        "ready_to_file": ready_to_file,
        "transmitted": transmitted,
        "percent": pos["percent"],
        "done": pos["done"], "total": pos["total"],
        "tiles": tiles,
        "validation": validation,
        "blocking_items": blocking_items,
        "resume": pos["resume"],
    }
