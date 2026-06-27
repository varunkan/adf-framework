#!/usr/bin/env python3
"""Submission-readiness aggregation (REQ-071 / UI-2 Dashboard).

The market-leading RIM/eCTD tools (Veeva Vault Submissions, LORENZ docuBridge,
Extedo) all lead with a *readiness dashboard* rather than a raw data-entry form.
Every signal it surfaces is already computed elsewhere in this app — validation
(:mod:`validation`), the Module-1 checklist gate (:mod:`content_model`), fees
(:mod:`fees`), e-signature (:mod:`esign`), transmission (:mod:`transmission`),
lifecycle (:mod:`lifecycle`) and regulatory deadlines (:mod:`hc_calendar`). This
module is the thin, deterministic, dependency-light layer that *aggregates* a
single submission's stored signal state into the at-a-glance tiles, the single
READY / BLOCKED indicator and the drill-in list of blocking items the Dashboard
renders. It adds NO new regulatory logic — it surfaces what the backend already
knows (REQ-071 rationale).

Pure Python 3 standard library; the only intra-app imports are the two domain
modules whose *computations* the dashboard reuses verbatim
(:func:`content_model.checklist_gate` for the X-of-Y completeness and
:func:`hc_calendar.compute_deadline` for the next deadline). Everything here is
side-effect-free and unit-testable; ``server.py`` is a thin shell over it.

A submission payload (as persisted in the tenant workspace DB) may carry any of
these optional signal sub-objects — each absent one degrades gracefully to a
"not started / to-do" tile, which is itself the correct readiness story for a
freshly-created draft:

* ``validation``   -> ``{"errors": int, "warnings": int, "ran": bool}``
* ``content``      -> the :func:`content_model.checklist_gate` input
                      (``cs_be_only``, ``present_documents``, ...)
* ``fees``         -> ``{"paid": bool, "amount": ...}``
* ``esign``        -> ``{"signed": bool, "signer": ...}``
* ``transmission`` -> ``{"state": "RECEIVED_BY_HC" | ...}``
* ``lifecycle``    -> ``{"status": "Active" | ...}``
* ``deadline``     -> ``{"start": ISO, "days": int, "notice_type": str, ...}``
"""

from __future__ import annotations

from datetime import date

import content_model
import hc_calendar


# Tile rendering states (drive the badge colour on the dashboard card).
STATE_PASS = "pass"     # green — this signal is satisfied
STATE_FAIL = "fail"     # red — this signal is blocking READY
STATE_TODO = "todo"     # amber — not started yet (also blocks, softly)
STATE_INFO = "info"     # neutral — status/outcome, never blocks READY
STATE_WARN = "warn"     # amber — non-blocking caution (e.g. warnings, near deadline)

# Overall indicators (REQ-071: a single READY / BLOCKED per submission).
READY = "READY"
BLOCKED = "BLOCKED"

# Days-remaining threshold under which the deadline tile turns to a caution.
DEADLINE_SOON_DAYS = 14

# Transmission states that count as "the submission has been filed" — surfaced
# as a positive outcome rather than a blocker (the dashboard READY signal means
# "ready to transmit"; actually transmitting is the next, separate step).
_TX_DELIVERED = {"RECEIVED_BY_HC", "FDA_ACK", "MEDIA_RECEIVED"}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _lifecycle_tile(payload: dict) -> dict:
    lc = payload.get("lifecycle") or {}
    status = str(lc.get("status") or "").strip() or "Draft"
    return {"key": "lifecycle", "label": "Lifecycle", "value": status,
            "state": STATE_INFO}


def _validation_tile(payload: dict, blocking: list) -> dict:
    val = payload.get("validation")
    if not val or not (val.get("ran") or "errors" in val or "warnings" in val):
        blocking.append({
            "signal": "validation", "rule": "validation_not_run",
            "label": "Validation has not been run",
            "route": "/validation"})
        return {"key": "validation", "label": "Validation", "value": "Not run",
                "state": STATE_TODO, "errors": None, "warnings": None}
    errors = _as_int(val.get("errors"))
    warnings = _as_int(val.get("warnings"))
    if errors > 0:
        state = STATE_FAIL
        blocking.append({
            "signal": "validation", "rule": "validation_errors",
            "label": (f"{errors} validation "
                      f"error{'s' if errors != 1 else ''} to resolve"),
            "count": errors, "route": "/validation"})
    elif warnings > 0:
        state = STATE_WARN
    else:
        state = STATE_PASS
    return {"key": "validation", "label": "Validation",
            "value": f"{errors} Errors / {warnings} Warnings",
            "state": state, "errors": errors, "warnings": warnings,
            "passed": errors == 0}


def _module1_tile(payload: dict, blocking: list) -> dict:
    content = payload.get("content") or {}
    gate = content_model.checklist_gate(content)
    satisfied = len(gate.get("satisfied") or [])
    missing = len(gate.get("missing") or [])
    total = satisfied + missing
    if missing > 0:
        blocking.append({
            "signal": "module1", "rule": "module1_incomplete",
            "label": (f"Module 1 checklist incomplete "
                      f"({satisfied} of {total} required items present)"),
            "missing": [m.get("title") or m.get("key")
                        for m in gate.get("missing") or []],
            "route": "/submit"})
        state = STATE_FAIL
    else:
        state = STATE_PASS
    return {"key": "module1", "label": "Module 1 checklist",
            "value": f"{satisfied} of {total}",
            "present": satisfied, "required": total,
            "complete": missing == 0, "state": state}


def _fees_tile(payload: dict, blocking: list) -> dict:
    fees = payload.get("fees") or {}
    paid = bool(fees.get("paid"))
    if not paid:
        blocking.append({
            "signal": "fees", "rule": "fees_unpaid",
            "label": "ANDS filing fee is unpaid",
            "route": "/fees"})
    return {"key": "fees", "label": "Fees",
            "value": "Paid" if paid else "Unpaid",
            "state": STATE_PASS if paid else STATE_TODO, "paid": paid}


def _esign_tile(payload: dict, blocking: list) -> dict:
    esign = payload.get("esign") or {}
    signed = bool(esign.get("signed"))
    if not signed:
        blocking.append({
            "signal": "esign", "rule": "signature_missing",
            "label": "Authorized e-signature is missing",
            "route": "/esign"})
    return {"key": "esign", "label": "E-signature",
            "value": "Signed" if signed else "Unsigned",
            "state": STATE_PASS if signed else STATE_TODO, "signed": signed}


def _transmission_tile(payload: dict) -> dict:
    tx = payload.get("transmission") or {}
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


def _DEADLINE_NONE_TILE() -> dict:
    return {"key": "deadline", "label": "Next deadline", "value": "None",
            "state": STATE_INFO, "due": None, "days_remaining": None}


def _resolve_due_iso(dl: dict):
    """Return the resolved ISO date string from a deadline sub-object, or None."""
    due_iso = dl.get("due")
    if not due_iso and dl.get("start") is not None and dl.get("days") is not None:
        computed = hc_calendar.compute_deadline(
            dl.get("start"), _as_int(dl.get("days")),
            basis=dl.get("basis"), notice_type=str(dl.get("notice_type") or ""))
        due_iso = computed["due"]
    return due_iso or None


def _deadline_tile(payload: dict, today) -> dict:
    """Next regulatory deadline (REQ-071 — reuses hc_calendar.compute_deadline).

    ``payload['deadline']`` may carry an already-computed ``due`` ISO date or
    the ``start``/``days``/``notice_type`` inputs to compute one. Returns the
    due date and days-remaining (negative when overdue).
    """
    dl = payload.get("deadline")
    if not dl:
        return _DEADLINE_NONE_TILE()
    label = str(dl.get("label") or dl.get("notice_type") or "Deadline")
    due_iso = _resolve_due_iso(dl)
    if not due_iso:
        return _DEADLINE_NONE_TILE()
    try:
        due_date = date.fromisoformat(str(due_iso))
    except ValueError:
        return _DEADLINE_NONE_TILE()
    days_remaining = (due_date - today).days
    if days_remaining < 0:
        state = STATE_FAIL
    elif days_remaining <= DEADLINE_SOON_DAYS:
        state = STATE_WARN
    else:
        state = STATE_INFO
    return {"key": "deadline", "label": "Next deadline",
            "value": f"{due_date.isoformat()} ({days_remaining}d)",
            "state": state, "due": due_date.isoformat(),
            "days_remaining": days_remaining, "deadline_label": label}


def submission_readiness(submission, *, today=None) -> dict:
    """Aggregate one submission's signals into a dashboard-ready summary.

    ``submission`` is a stored record ``{"id", "payload", ...}`` or a bare
    payload dict. ``today`` (a ``date`` or ISO string) anchors the
    days-remaining math; it defaults to no anchor, in which case the deadline
    tile still shows the date but no countdown.

    Returns ``{"id", "title", "dossier_id", "status" (READY|BLOCKED), "ready",
    "tiles": [...], "blocking_items": [...], "blocking_count"}``.
    """
    rec = submission or {}
    if "payload" in rec and isinstance(rec.get("payload"), dict):
        payload = rec.get("payload") or {}
        sub_id = rec.get("id")
        created_at = rec.get("created_at")
    else:
        payload = rec
        sub_id = rec.get("id")
        created_at = rec.get("created_at")

    if today is None:
        anchor = None
    elif isinstance(today, date):
        anchor = today
    else:
        try:
            anchor = date.fromisoformat(str(today))
        except ValueError:
            anchor = None

    blocking: list = []
    tiles = [
        _lifecycle_tile(payload),
        _validation_tile(payload, blocking),
        _module1_tile(payload, blocking),
        _fees_tile(payload, blocking),
        _esign_tile(payload, blocking),
        _transmission_tile(payload),
    ]
    # Deadline math needs an anchor; without one the countdown is omitted but
    # the date (if any) is still surfaced.
    tiles.append(_deadline_tile(payload, anchor) if anchor is not None
                 else _deadline_no_anchor(payload))

    ready = not blocking
    title = str(payload.get("drug_product") or "").strip()
    if not title:
        title = (f"Submission {sub_id}" if sub_id is not None
                 else "Untitled submission")
    return {
        "id": sub_id,
        "title": title,
        "dossier_id": str(payload.get("dossier_id") or "").strip(),
        "created_at": created_at,
        "status": READY if ready else BLOCKED,
        "ready": ready,
        "tiles": tiles,
        "blocking_items": blocking,
        "blocking_count": len(blocking),
    }


def _deadline_no_anchor(payload: dict) -> dict:
    """Deadline tile when no 'today' anchor is supplied — date only, no count."""
    dl = payload.get("deadline")
    if not dl:
        return _DEADLINE_NONE_TILE()
    due_iso = _resolve_due_iso(dl)
    if not due_iso:
        return _DEADLINE_NONE_TILE()
    return {"key": "deadline", "label": "Next deadline",
            "value": str(due_iso), "state": STATE_INFO,
            "due": str(due_iso), "days_remaining": None}


def dashboard(submissions, *, today=None) -> dict:
    """Build the full readiness dashboard payload for a tenant (REQ-071).

    ``submissions`` is the list of stored submission records. Returns the
    per-submission readiness cards plus at-a-glance roll-up counts and an
    ``empty`` flag that drives the "Start a submission" empty-state.
    """
    cards = [submission_readiness(s, today=today) for s in (submissions or [])]
    ready = sum(1 for c in cards if c["ready"])
    return {
        "submissions": cards,
        "total": len(cards),
        "ready": ready,
        "blocked": len(cards) - ready,
        "empty": not cards,
        "generated_for": (today.isoformat() if isinstance(today, date)
                          else (str(today) if today else None)),
    }
