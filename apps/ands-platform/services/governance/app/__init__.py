"""Governance service — e-signature gate + the event-sourced audit trail.

Ported from the monolith ``esign``: a tamper-evident signature manifest + the
QA-review/transmission approval gate (REQ-039/053/068). Plus an append-only
audit trail that subscribes to the whole event bus (``"*"``) and records every
cross-service domain event — the platform's immutable governance spine.
"""
