"""Webhooks service — outbound webhooks on domain events (SAAS-REQ-011).

Subscribes to the whole event bus; tenants register endpoints (scoped by event
type and/or tenant); every matching event is enqueued to an append-only delivery
outbox with an HMAC-SHA256 signature. The actual HTTP POST is a pluggable sender
(like collaboration's email outbox) — the contract + signing live here.
"""
