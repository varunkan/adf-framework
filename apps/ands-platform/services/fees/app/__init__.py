"""Fees service — HC drug-submission fee model (REQ-035/036/037).

A stateless calculation service (no DB): Schedule-1 fee resolution with
fiscal-year escalation, small-business remission/deferral, and the per-DIN
annual Right-to-Sell fee. Ported verbatim from the monolith ``fees`` module.
"""
