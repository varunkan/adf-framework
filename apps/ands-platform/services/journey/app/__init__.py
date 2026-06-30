"""Journey BFF — the guided, story-driven façade for the drug-filing experience.

Exposes the gated journey spine (ported from the monolith ``journey.py``), the
"Tell me about your drug" decision support (submission-type routing + Canadian
Reference Product + bioequivalence), and the Dossier-ID guidance, and composes
the microservice mesh for live readiness. This is the single API the spatial
guided front-end (apps/ands-platform/web) talks to. See the plan + ADR-0001.
"""
