"""Transmission service — FDA-ESG NextGen ride-along (REQ-003/025/026/027/046).

Ported from the monolith ``transmission``: ESG config + Test-gateway gate,
10 GB size routing, and the per-dossier one-at-a-time ack/transport state machine
(SENT → MDN → FDA Ack → HC Ack Receipt). Emits ``transmission.sent`` /
``transmission.hc_ack`` (the latter consumed by collaboration to notify filers).
"""
