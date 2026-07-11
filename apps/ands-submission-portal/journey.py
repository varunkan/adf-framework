#!/usr/bin/env python3
"""The guided submission JOURNEY — ordered, gated, self-advancing (REQ-073 / UI-6).

REQ-071's dashboard answers "is this submission ready?"; this module answers the
prior, more human question — "what do I do next, and what am I allowed to do
yet?". It is the *spine* of the product (UI-6): a user is led, step by step,
through a real ANDS drug submission in the order Health Canada's process
actually requires, never shown step N+1 until step N's prerequisites are met,
and explicitly invited to the next step on completion.

The journey is a strictly-ordered chain of stages (Get oriented → Set up your
company → Dossier ID → Start a submission → Add documents → Validate → Fees →
Approve → Sign → Transmit → Track). Each stage's *prerequisite* is simply the
previous stage being complete, so the gating is a linear walk: the first
not-yet-complete stage whose predecessor is done is the **current** stage;
everything after it is **locked** (with a plain-language reason naming the exact
unmet prerequisite and where to satisfy it); everything before it is **done**
and freely revisitable.

This adds NO new regulatory logic — exactly like :mod:`readiness`, every
completion signal it reads is already computed and persisted elsewhere (the
submission payload's ``validation`` / ``content`` / ``fees`` / ``esign`` /
``transmission`` sub-objects, plus the company/dossier identity fields and an
optional ``reviews`` approval sub-object). It is pure, side-effect-free and
unit-testable; ``server.py`` is a thin shell over it.

A submission payload (as persisted in the tenant workspace DB, the same shape
:mod:`readiness` consumes) may carry, in addition to the readiness signals:

* ``company_id``  -> the HC Company ID (or nested ``company.company_id``)
* ``dossier_id``  -> the HC Dossier ID for this product
* ``sequence`` / ``applicant`` / ``drug_product`` -> the created submission
* ``reviews``     -> ``{"approved": bool, ...}`` (or ``approval``) — REQ-076
* ``oriented``    -> bool, set once the user has read the orientation
"""

from __future__ import annotations

import content_model


# Stage status vocabulary (drives the stepper glyph ✓ done / ● current / ○ locked).
DONE = "done"
CURRENT = "current"
LOCKED = "locked"

# Transmission state codes that count as "the submission has been sent to HC" —
# the same delivered set readiness treats as positive, plus the in-flight codes
# that still mean "transmit was performed" (Stage 9 is complete once it leaves).
_TX_SENT = {
    "SUBMITTED", "TRANSMITTED", "SENT", "IN_TRANSIT",
    "TRANSPORT_CONFIRMED", "TRANSPORT_UNCONFIRMED",
    "RECEIVED_BY_HC", "FDA_ACK", "MEDIA_RECEIVED",
}


# The canonical journey. Order IS the regulatory sequence; each entry is the
# single source of truth the API and the client stepper share. ``route`` is the
# workspace page the stage's work happens on; ``cta`` is the ONE primary action
# whose success advances the route; ``next`` names the stage it advances to.
STAGES: tuple[dict, ...] = (
    {"n": 0, "key": "orient", "label": "Get oriented", "reg": "",
     "route": "/submit", "icon": "◎",
     "purpose": "Learn what an ANDS is and how this portal guides you through it.",
     "unlocks": "Always available", "cta": "Start my submission",
     "next": "company",
     "checklist": ("What an ANDS is", "How the guided journey works")},
    {"n": 1, "key": "company", "label": "Set up your company",
     "reg": "Enrolment · REP CO", "route": "/enrolment", "icon": "⛿",
     "purpose": "Register your company with Health Canada and get a Company ID.",
     "unlocks": "Your account is created", "cta": "Save Company ID",
     "next": "dossier",
     "checklist": ("Company details", "Contacts", "Company ID")},
    {"n": 2, "key": "dossier", "label": "Get your product's file number",
     "reg": "Dossier ID · REP RT", "route": "/enrolment", "icon": "▥",
     "purpose": "Obtain or enter the Health Canada Dossier ID for this product.",
     "unlocks": "A Company ID exists", "cta": "Save Dossier ID",
     "next": "submission",
     "checklist": ("Product type", "Activity", "Dossier ID format check")},
    {"n": 3, "key": "submission", "label": "Start a submission",
     "reg": "ANDS · sequence 0000", "route": "/dossiers", "icon": "✚",
     "purpose": "Create the dossier sequence (an ANDS, sequence 0000).",
     "unlocks": "A Dossier ID exists", "cta": "Create submission",
     "next": "content",
     "checklist": ("Submission type", "Applicant", "Drug product")},
    {"n": 4, "key": "content", "label": "Add your documents",
     "reg": "Content · eCTD tree", "route": "/dossiers", "icon": "▤",
     "purpose": "Upload the required documents into the right Module 1-5 slots.",
     "unlocks": "A submission exists", "cta": "Documents added",
     "next": "validate",
     "checklist": ("Module-1 required items X/Y", "PDF conformance")},
    {"n": 5, "key": "validate", "label": "Check your submission",
     "reg": "Validate", "route": "/validation", "icon": "✓",
     "purpose": "Run validation and fix any issues in plain language.",
     "unlocks": "Your content is present", "cta": "All checks pass",
     "next": "fees",
     "checklist": ("Error list with how-to-fix", "Link & checksum integrity")},
    {"n": 6, "key": "fees", "label": "Pay the fees", "reg": "Fees",
     "route": "/fees", "icon": "$",
     "purpose": "Calculate and confirm the ANDS / right-to-sell fees.",
     "unlocks": "Validation is clean (warnings allowed)",
     "cta": "Fees confirmed", "next": "review",
     "checklist": ("Fee breakdown", "Payment status")},
    {"n": 7, "key": "review", "label": "Get it approved",
     "reg": "Review & approve", "route": "/reviews", "icon": "☑",
     "purpose": "Route the submission for internal sign-off.",
     "unlocks": "Fees are confirmed", "cta": "Approved", "next": "sign",
     "checklist": ("Reviewer / approver assignment", "Decisions")},
    {"n": 8, "key": "sign", "label": "Sign", "reg": "E-signature",
     "route": "/esign", "icon": "✍",
     "purpose": "Apply the regulated e-signature.",
     "unlocks": "Approvals are recorded", "cta": "Signed", "next": "transmit",
     "checklist": ("Signer identity", "QA gate")},
    {"n": 9, "key": "transmit", "label": "Submit to Health Canada",
     "reg": "Assemble & transmit", "route": "/transmission", "icon": "➤",
     "purpose": "Build the CESG package and transmit it via the gateway.",
     "unlocks": "The submission is signed", "cta": "Transmitted",
     "next": "track",
     "checklist": ("Package export", "ESG send", "Acknowledgement")},
    {"n": 10, "key": "track", "label": "Track & respond", "reg": "Lifecycle",
     "route": "/lifecycle", "icon": "↻",
     "purpose": ("Monitor HC review, respond to clarification requests and "
                 "file follow-ups."),
     "unlocks": "The submission is transmitted", "cta": None, "next": None,
     "checklist": ("Review status", "Deadlines", "Clarification responses")},
)

# Index helpers — the gateable path is stages 0..9 (orientation through
# transmit); stage 10 is the ongoing post-filing destination, never "done".
_GATEABLE = len(STAGES) - 1            # 10 stages (0..9) make up the filing path
_TRACK_N = STAGES[-1]["n"]            # 10


def _s(value) -> str:
    return str(value or "").strip()


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _payload_of(submission) -> dict:
    """Accept either a stored record ``{"payload": {...}}`` or a bare payload."""
    rec = submission or {}
    if isinstance(rec.get("payload"), dict):
        return rec.get("payload") or {}
    return rec if isinstance(rec, dict) else {}


def _completion(payload: dict) -> list[bool]:
    """The per-stage completion flags (index == stage number) read from the
    persisted submission signals. Every flag mirrors a signal that is already
    computed and stored elsewhere — this function adds no new regulatory logic.
    """
    company = bool(_s(payload.get("company_id"))
                   or _s((payload.get("company") or {}).get("company_id")))
    dossier = bool(_s(payload.get("dossier_id")))
    submission = bool(
        _s(payload.get("sequence"))
        or payload.get("submission_created")
        or (_s(payload.get("applicant")) and _s(payload.get("drug_product"))))

    gate = content_model.checklist_gate(payload.get("content") or {})
    content_done = not gate.get("missing")

    val = payload.get("validation") or {}
    validated = (bool(val.get("ran") or "errors" in val)
                 and _as_int(val.get("errors")) == 0)

    fees_done = bool((payload.get("fees") or {}).get("paid"))

    rev = payload.get("reviews") or payload.get("approval") or {}
    approved = bool(rev.get("approved"))

    signed = bool((payload.get("esign") or {}).get("signed"))

    tx = payload.get("transmission") or {}
    transmitted = (_s(tx.get("state")).upper() in _TX_SENT
                   or bool(tx.get("transmitted")))

    # Stage 0 is the orientation prologue: complete once the user has read it OR
    # has visibly moved past it (a Company ID already exists).
    oriented = bool(payload.get("oriented")) or company

    # index:        0        1        2        3           4
    return [oriented, company, dossier, submission, content_done,
            # 5        6          7         8       9
            validated, fees_done, approved, signed, transmitted,
            # 10 — "track" is ongoing once the submission has been transmitted.
            transmitted]


def _current_index(complete: list[bool]) -> int:
    """The first not-yet-complete stage on the gateable path (0..9); when the
    whole filing path is done, the user lives in the ongoing Track stage (10)."""
    for n in range(_GATEABLE):
        if not complete[n]:
            return n
    return _TRACK_N


def _gate_for(n: int) -> dict:
    """The plain-language gate shown on a locked stage — what must happen first
    and where to do it (UI-6: 'names the precise unmet prerequisite and links to
    where to satisfy it')."""
    prev = STAGES[n - 1]
    return {
        "reason": f"Complete “{prev['label']}” first.",
        "needs_key": prev["key"],
        "needs_label": prev["label"],
        "needs_route": prev["route"],
        "requirement": STAGES[n]["unlocks"],
    }


def stages(payload: dict) -> list[dict]:
    """The full, status-annotated stage list for one submission's payload.

    Each returned stage carries every static field from :data:`STAGES` plus a
    live ``status`` (``done`` / ``current`` / ``locked``), a ``locked`` /
    ``done`` / ``current`` boolean for convenience, and — when locked — a
    ``gate`` describing the unmet prerequisite. ``track`` (stage 10) is the
    ongoing destination: ``current`` once transmitted, ``locked`` before.
    """
    complete = _completion(payload)
    current = _current_index(complete)
    out: list[dict] = []
    for st in STAGES:
        n = st["n"]
        if n == _TRACK_N:
            status = CURRENT if current == _TRACK_N else LOCKED
        elif complete[n]:
            status = DONE
        elif n == current:
            status = CURRENT
        else:
            status = LOCKED
        item = dict(st)
        item["status"] = status
        item["done"] = status == DONE
        item["current"] = status == CURRENT
        item["locked"] = status == LOCKED
        item["gate"] = _gate_for(n) if status == LOCKED else None
        # Resolve the human "Next: <label>" pointer the self-advancing CTA uses.
        nxt = next((s for s in STAGES if s["key"] == st["next"]), None)
        item["next_label"] = nxt["label"] if nxt else None
        item["next_route"] = nxt["route"] if nxt else None
        out.append(item)
    return out


def position(payload: dict) -> dict:
    """A compact 'where am I in the journey' summary for the dashboard card.

    Returns the current stage's number/key/label/route (the Resume target),
    plus the progress roll-up (done of the 10 filing steps + percent) and a
    ``transmitted`` flag. Used by REQ-071's dashboard so every submission card
    shows its journey position with a one-click Resume (UI-6).
    """
    complete = _completion(payload)
    current = _current_index(complete)
    done = sum(1 for n in range(_GATEABLE) if complete[n])
    cur = STAGES[current]
    return {
        "current": current,
        "current_key": cur["key"],
        "current_label": cur["label"],
        "current_route": cur["route"],
        "resume": {"n": current, "key": cur["key"], "label": cur["label"],
                   "route": cur["route"]},
        "done": done,
        "total": _GATEABLE,
        "percent": round(done * 100 / _GATEABLE),
        "transmitted": complete[_TRACK_N],
        "complete": current == _TRACK_N,
    }


def _title(payload: dict, sub_id) -> str:
    title = _s(payload.get("drug_product"))
    if title:
        return title
    return (f"Submission {sub_id}" if sub_id is not None
            else "New submission")


def journey(submission, *, sub_id=None) -> dict:
    """The full guided-journey view for one submission (the /submit stepper).

    ``submission`` is a stored record ``{"id", "payload", ...}`` or a bare
    payload dict (an empty dict yields a brand-new journey: stages 0/1 unlocked,
    everything else locked — exactly the UI-6 acceptance criterion for a new
    user). Returns the submission identity, the status-annotated ``stages`` and
    the compact ``position``.
    """
    rec = submission or {}
    payload = _payload_of(rec)
    if sub_id is None:
        sub_id = rec.get("id")
    pos = position(payload)
    return {
        "id": sub_id,
        "title": _title(payload, sub_id),
        "dossier_id": _s(payload.get("dossier_id")),
        "stages": stages(payload),
        "current": pos["current"],
        "position": pos,
    }
