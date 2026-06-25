"""
ANDS Submission Portal — configurable data-retention + legal-hold + disposition
logging.

This ADDITIVE slice implements a previously-unimplemented requirement:

  REQ-054  Configurable data-retention and legal-hold policies on submission
           content, sequences, acknowledgements, audit trails and signature
           manifests that meet or exceed the genuine PIPEDA breach-record
           minimum (>=24 months) and any sponsor-contracted/provincial period;
           deletion of records under legal hold or within the retention window
           is prevented, and every disposition event is logged. Retention beyond
           the PIPEDA minimum is a configurable VALUE-ADD/contractual control,
           NOT a fixed HC mandate.

Pure, dependency-free (Python 3 standard library only) and deterministic:
"now" is supplied by the caller so retention math is reproducible.

Requirement traceability tags (REQ-xxx) reference
specs/ands-submission-portal/requirements.md.
"""

from __future__ import annotations

from datetime import datetime, timezone


# REQ-054 / NFR-006: the genuine PIPEDA breach-record minimum is 24 months. This
# is the floor; sponsor-contracted/provincial periods may be longer.
PIPEDA_BREACH_RECORD_MIN_MONTHS = 24

# Default configurable retention (months) per record class. Every value is at or
# above the PIPEDA breach-record minimum. These are DATA — updatable per tenant.
DEFAULT_RETENTION_MONTHS = {
    "submission": 120,        # submission content — long contractual default
    "sequence": 120,
    "acknowledgement": 120,
    "audit_trail": 120,
    "signature_manifest": 120,
    "breach_record": PIPEDA_BREACH_RECORD_MIN_MONTHS,  # genuine PIPEDA minimum
}

# The basis tag for each class (REQ-067 alignment): the breach record is a
# genuine PIPEDA obligation; the rest are configurable value-add/contractual.
RETENTION_BASIS = {
    "breach_record": "PIPEDA",
}
RECORD_CLASSES = tuple(DEFAULT_RETENTION_MONTHS)


def _norm(value) -> str:
    return str(value if value is not None else "").strip()


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    text = _norm(value)
    if not text:
        raise ValueError("a timestamp is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _add_months(dt: datetime, months: int) -> datetime:
    """Add ``months`` calendar months, clamping the day to the target month."""
    total = (dt.year * 12 + (dt.month - 1)) + int(months)
    year, month = divmod(total, 12)
    month += 1
    # Clamp day (e.g. Jan 31 + 1 month -> Feb 28/29).
    day = dt.day
    while day > 28:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
    return dt.replace(year=year, month=month, day=day)


def retention_months(record_class, config=None) -> int:
    """The configured retention (months) for ``record_class`` — never below the
    PIPEDA breach-record minimum."""
    config = config or {}
    rc = _norm(record_class)
    months = int(config.get(rc, DEFAULT_RETENTION_MONTHS.get(rc, 0)) or 0)
    return max(months, PIPEDA_BREACH_RECORD_MIN_MONTHS)


def retention_policy(config=None) -> dict:
    """REQ-054: the effective retention policy (months per class) as data."""
    config = config or {}
    return {
        "pipeda_breach_record_min_months": PIPEDA_BREACH_RECORD_MIN_MONTHS,
        "classes": [
            {"record_class": rc,
             "months": retention_months(rc, config),
             "basis": RETENTION_BASIS.get(rc, "value-add")}
            for rc in RECORD_CLASSES
        ],
    }


def retention_expiry(record_class, created_at, config=None) -> str:
    """The ISO date when ``record_class`` created at ``created_at`` may be
    disposed (retention window end)."""
    created = _parse_iso(created_at)
    months = retention_months(record_class, config)
    return _add_months(created, months).isoformat()


def can_dispose(record: dict, now, config=None) -> dict:
    """REQ-054: may ``record`` be disposed at ``now``?

    ``record`` carries ``record_class``, ``created_at`` and optional
    ``legal_hold`` (bool). Returns ``{"allowed", "blockers", "expires_at"}``.
    Deletion under legal hold OR within the retention window is blocked."""
    record = record or {}
    now_dt = _parse_iso(now)
    blockers = []

    if bool(record.get("legal_hold")):
        blockers.append({
            "rule": "legal_hold",
            "message": "Record is under legal hold and cannot be disposed until "
                       "the hold is released by an authorized role",
        })

    expires_at = retention_expiry(
        record.get("record_class"), record.get("created_at"), config)
    if now_dt < _parse_iso(expires_at):
        blockers.append({
            "rule": "within_retention",
            "message": (f"Record is within its retention window (until "
                        f"{expires_at}) and cannot be disposed"),
        })

    return {"allowed": not blockers, "blockers": blockers,
            "expires_at": expires_at}


def disposition_event(record: dict, actor, now, config=None) -> dict:
    """REQ-054: attempt a disposition. ALWAYS returns a logged event — whether
    blocked or executed — so the disposition log is complete (a blocked attempt
    is recorded too)."""
    verdict = can_dispose(record, now, config)
    return {
        "record_class": _norm((record or {}).get("record_class")),
        "record_id": _norm((record or {}).get("record_id")),
        "actor": _norm(actor),
        "at": _norm(now),
        "executed": verdict["allowed"],
        "blocked": not verdict["allowed"],
        "blockers": verdict["blockers"],
        "expires_at": verdict["expires_at"],
    }
