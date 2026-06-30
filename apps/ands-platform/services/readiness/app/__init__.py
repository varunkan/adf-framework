"""Readiness BFF — event-driven submission-readiness dashboard (REQ-071).

The capstone aggregator: subscribes to the domain events every other service
emits (validation, transmission, lifecycle, bilingual-PM, content-plan) and
projects them per-dossier into the at-a-glance READY / BLOCKED tiles the
dashboard renders — no synchronous cross-service calls.
"""
