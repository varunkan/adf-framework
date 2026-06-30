"""Readiness projection — pure tile/READY-BLOCKED computation (REQ-071).

Given a per-dossier ``signals`` dict (assembled from domain events), compute the
dashboard tiles, the single READY/BLOCKED indicator and the drill-in list of
blocking items. Adds no regulatory logic — it surfaces what the events already
said (ported in spirit from the monolith ``readiness`` module).
"""

from __future__ import annotations

STATE_PASS = "pass"
STATE_FAIL = "fail"
STATE_TODO = "todo"
STATE_INFO = "info"
STATE_WARN = "warn"

READY = "READY"
BLOCKED = "BLOCKED"

# transmission states that count as "filed" (a positive outcome, not a blocker)
_TX_DELIVERED = {"RECEIVED_BY_HC", "FDA_ACK", "MEDIA_RECEIVED"}


def _as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validation_tile(signals, blocking):
    val = signals.get("validation")
    if not val or not val.get("ran"):
        blocking.append({"signal": "validation", "rule": "validation_not_run",
                         "label": "Validation has not been run"})
        return {"key": "validation", "label": "Validation", "value": "Not run",
                "state": STATE_TODO}
    errors = _as_int(val.get("errors"))
    warnings = _as_int(val.get("warnings"))
    if errors > 0:
        state = STATE_FAIL
        blocking.append({"signal": "validation", "rule": "validation_errors",
                         "count": errors,
                         "label": f"{errors} validation error"
                                  f"{'s' if errors != 1 else ''} to resolve"})
    elif warnings > 0:
        state = STATE_WARN
    else:
        state = STATE_PASS
    return {"key": "validation", "label": "Validation",
            "value": f"{errors} Errors / {warnings} Warnings", "state": state,
            "errors": errors, "warnings": warnings, "passed": errors == 0}


def _bilingual_pm_tile(signals, blocking):
    pm = signals.get("bilingual_pm")
    if not pm:
        return {"key": "bilingual_pm", "label": "Bilingual PM", "value": "—",
                "state": STATE_INFO}
    if pm.get("blocked"):
        blocking.append({"signal": "bilingual_pm", "rule": "bilingual_pm_blocked",
                         "label": "Bilingual Product Monograph incomplete "
                                  "(EN + FR required)"})
        return {"key": "bilingual_pm", "label": "Bilingual PM",
                "value": "Blocked", "state": STATE_FAIL}
    return {"key": "bilingual_pm", "label": "Bilingual PM", "value": "Complete",
            "state": STATE_PASS}


def _content_plan_tile(signals):
    cp = signals.get("content_plan")
    if not cp:
        return {"key": "content_plan", "label": "Content plan", "value": "—",
                "state": STATE_INFO}
    pct = _as_int(cp.get("pct"))
    return {"key": "content_plan", "label": "Content plan",
            "value": f"{cp.get('done', 0)} of {cp.get('total', 0)} ({pct}%)",
            "state": STATE_PASS if pct >= 100 else STATE_WARN, "pct": pct}


def _lifecycle_tile(signals):
    lc = signals.get("lifecycle") or {}
    status = str(lc.get("status") or "").strip() or "Draft"
    phase = str(lc.get("phase") or "").strip()
    return {"key": "lifecycle", "label": "Lifecycle",
            "value": f"{phase} / {status}" if phase else status,
            "state": STATE_INFO}


def _transmission_tile(signals):
    tx = signals.get("transmission") or {}
    state_code = str(tx.get("state") or "").strip()
    if not state_code:
        return {"key": "transmission", "label": "Transmission",
                "value": "Not transmitted", "state": STATE_INFO,
                "delivered": False}
    delivered = state_code in _TX_DELIVERED
    return {"key": "transmission", "label": "Transmission",
            "value": state_code.replace("_", " ").title(),
            "state": STATE_PASS if delivered else STATE_INFO,
            "delivered": delivered}


def readiness(dossier_id: str, signals: dict) -> dict:
    """Aggregate one dossier's signals into a dashboard-ready summary."""
    signals = signals or {}
    blocking: list = []
    tiles = [
        _validation_tile(signals, blocking),
        _bilingual_pm_tile(signals, blocking),
        _content_plan_tile(signals),
        _lifecycle_tile(signals),
        _transmission_tile(signals),
    ]
    ready = not blocking
    return {
        "dossier_id": dossier_id,
        "title": str(signals.get("title") or "").strip()
        or f"Dossier {dossier_id}",
        "status": READY if ready else BLOCKED, "ready": ready, "tiles": tiles,
        "blocking_items": blocking, "blocking_count": len(blocking)}


def dashboard(projections: dict) -> dict:
    """Build the full dashboard from {dossier_id: signals}."""
    cards = [readiness(did, sig) for did, sig in sorted(projections.items())]
    ready = sum(1 for c in cards if c["ready"])
    return {"submissions": cards, "total": len(cards), "ready": ready,
            "blocked": len(cards) - ready, "empty": not cards}
