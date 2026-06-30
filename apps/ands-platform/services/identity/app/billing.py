"""Subscription billing access rules — pure (SAAS-REQ-002).

Effective access for a tenant given its billing status + grace period: an active
tenant can do everything; a past-due tenant keeps full access through the grace
window then loses the gated actions (transmit / new sequences) while read/export
stay open; a canceled tenant is read/export only.
"""

from __future__ import annotations

from datetime import date, datetime

BILLING_ACTIVE = "active"
BILLING_PAST_DUE = "past_due"
BILLING_CANCELED = "canceled"
BILLING_STATUSES = (BILLING_ACTIVE, BILLING_PAST_DUE, BILLING_CANCELED)

GATED_ACTIONS = ("transmit", "new_sequence")
ALWAYS_ALLOWED = ("read", "export")


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value or "").strip()[:10])


def effective_access(status: str, grace_until=None, as_of=None) -> dict:
    status = str(status or "").strip() or BILLING_ACTIVE
    today = _as_date(as_of) if as_of else date.today()
    if status == BILLING_ACTIVE:
        return {"state": "ok", "billing_status": status,
                "allowed": list(GATED_ACTIONS + ALWAYS_ALLOWED), "blocked": [],
                "reason": ""}
    if status == BILLING_CANCELED:
        return {"state": "blocked", "billing_status": status,
                "allowed": list(ALWAYS_ALLOWED), "blocked": list(GATED_ACTIONS),
                "reason": "subscription canceled — read and export only"}
    # past_due
    in_grace = bool(grace_until) and today <= _as_date(grace_until)
    if in_grace:
        return {"state": "grace", "billing_status": status,
                "allowed": list(GATED_ACTIONS + ALWAYS_ALLOWED), "blocked": [],
                "grace_until": str(grace_until),
                "reason": f"payment past due — in grace period until {grace_until}"}
    return {"state": "blocked", "billing_status": status,
            "allowed": list(ALWAYS_ALLOWED), "blocked": list(GATED_ACTIONS),
            "reason": "payment past due and the grace period has ended"}


def is_allowed(access: dict, action: str) -> bool:
    return action in (access.get("allowed") or [])
