"""Validation service — HC eCTD technical validation (REQ-104).

Ported from the monolith ``validation`` engine: a versioned, severity-modeled
rule catalog run continuously (assembly-time) over a transaction context.
Emits ``validation.completed`` / ``validation.failed`` — the latter is consumed
by the collaboration service to raise blocking-defect notifications.
"""
