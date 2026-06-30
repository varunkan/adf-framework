"""The guided submission JOURNEY — ordered, gated, self-advancing (pure).

Ported from the monolith ``journey.py``. Answers the human question "what do I do
next, and what am I allowed to do yet?" — a strictly-ordered, linearly-gated walk
through a real ANDS filing, never showing step N+1 until step N's prerequisite is
met, with a plain-language reason on every locked step. Adds NO regulatory logic;
it reads completion signals the BFF service assembles (here ``content_done`` is a
plain flag, decoupled from the monolith's content_model).
"""

from __future__ import annotations

DONE = "done"
CURRENT = "current"
LOCKED = "locked"

_TX_SENT = {
    "SUBMITTED", "TRANSMITTED", "SENT", "IN_TRANSIT",
    "TRANSPORT_CONFIRMED", "TRANSPORT_UNCONFIRMED",
    "RECEIVED_BY_HC", "FDA_ACK", "MEDIA_RECEIVED",
}

# The canonical journey. Order IS the regulatory sequence (plain-language copy
# preserved from the monolith so the front-end renders the story verbatim).
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

_GATEABLE = len(STAGES) - 1            # stages 0..9 make up the filing path
_TRACK_N = STAGES[-1]["n"]            # 10


def _s(value) -> str:
    return str(value or "").strip()


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _completion(payload: dict) -> list[bool]:
    """Per-stage completion flags (index == stage number) from the BFF signals."""
    payload = payload or {}
    company = bool(_s(payload.get("company_id"))
                   or _s((payload.get("company") or {}).get("company_id")))
    dossier = bool(_s(payload.get("dossier_id")))
    submission = bool(
        _s(payload.get("sequence"))
        or payload.get("submission_created")
        or (_s(payload.get("applicant")) and _s(payload.get("drug_product"))))
    content_done = bool(payload.get("content_done"))

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
    oriented = bool(payload.get("oriented")) or company

    return [oriented, company, dossier, submission, content_done,
            validated, fees_done, approved, signed, transmitted,
            transmitted]


def _current_index(complete: list[bool]) -> int:
    for n in range(_GATEABLE):
        if not complete[n]:
            return n
    return _TRACK_N


def _gate_for(n: int) -> dict:
    prev = STAGES[n - 1]
    return {
        "reason": f"Complete “{prev['label']}” first.",
        "needs_key": prev["key"], "needs_label": prev["label"],
        "needs_route": prev["route"], "requirement": STAGES[n]["unlocks"]}


def stages(payload: dict) -> list[dict]:
    """The full, status-annotated stage list for one submission's payload."""
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
        nxt = next((s for s in STAGES if s["key"] == st["next"]), None)
        item["next_label"] = nxt["label"] if nxt else None
        item["next_route"] = nxt["route"] if nxt else None
        out.append(item)
    return out


def position(payload: dict) -> dict:
    """A compact 'where am I in the journey' summary for the dashboard card."""
    complete = _completion(payload)
    current = _current_index(complete)
    done = sum(1 for n in range(_GATEABLE) if complete[n])
    cur = STAGES[current]
    return {
        "current": current, "current_key": cur["key"],
        "current_label": cur["label"], "current_route": cur["route"],
        "resume": {"n": current, "key": cur["key"], "label": cur["label"],
                   "route": cur["route"]},
        "done": done, "total": _GATEABLE,
        "percent": round(done * 100 / _GATEABLE),
        "transmitted": complete[_TRACK_N], "complete": current == _TRACK_N}


def journey(payload: dict, *, sub_id=None, title: str = "") -> dict:
    """The full guided-journey view for one submission (the /submit stepper)."""
    payload = payload or {}
    pos = position(payload)
    return {
        "id": sub_id,
        "title": title or _s(payload.get("drug_product")) or "New submission",
        "dossier_id": _s(payload.get("dossier_id")),
        "stages": stages(payload),
        "current": pos["current"], "position": pos}


def stage_by_key(key: str) -> dict | None:
    return next((dict(s) for s in STAGES if s["key"] == key), None)
