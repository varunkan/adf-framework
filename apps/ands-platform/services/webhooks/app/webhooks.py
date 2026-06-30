"""Webhook domain — subscription validation, matching, HMAC signing (pure)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets

EVENT_WILDCARD = "*"


def _s(v) -> str:
    return str(v if v is not None else "").strip()


def validate_subscription(data: dict) -> dict:
    """Validate + clean a webhook subscription. ``{valid, subscription|errors}``."""
    data = data or {}
    errors = []
    url = _s(data.get("url"))
    if not (url.startswith("http://") or url.startswith("https://")):
        errors.append({"rule": "url_invalid",
                       "message": "url must be an http(s) endpoint"})
    types = data.get("event_types") or [EVENT_WILDCARD]
    if not isinstance(types, list) or not types:
        errors.append({"rule": "event_types_invalid",
                       "message": "event_types must be a non-empty list "
                                  "(use ['*'] for all)"})
    if errors:
        return {"valid": False, "errors": errors}
    return {"valid": True, "subscription": {
        "url": url, "event_types": [_s(t) for t in types],
        "tenant_id": _s(data.get("tenant_id")) or None,
        "secret": _s(data.get("secret")) or secrets.token_hex(16)}}


def matches(subscription: dict, event_type: str, tenant_id) -> bool:
    types = subscription.get("event_types") or []
    type_ok = EVENT_WILDCARD in types or event_type in types
    sub_tenant = subscription.get("tenant_id")
    tenant_ok = not sub_tenant or sub_tenant == (tenant_id or "")
    return type_ok and tenant_ok


def sign_payload(secret: str, body: str) -> str:
    if not secret:
        return ""
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def build_delivery(subscription: dict, event_type: str,
                   payload_obj: dict) -> dict:
    body = json.dumps(payload_obj, sort_keys=True)
    return {"url": subscription["url"], "event_type": event_type,
            "payload": body,
            "signature": sign_payload(subscription.get("secret", ""), body)}
