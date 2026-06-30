"""Lifecycle service — post-receipt DSTS lifecycle + HC deadline calendar.

Ported from the monolith ``lifecycle`` / ``hc_calendar``: the Screening → Review
→ decision (NOC/NOD/NON) state machine with statutory-holiday-aware deadline
timers and the missed-service-standard 25% fee-credit entitlement (REQ-030/031/062).
"""
