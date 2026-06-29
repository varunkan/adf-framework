"""Id and timestamp helpers — one correct implementation, shared."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_id() -> str:
    """A new opaque, URL-safe identifier (uuid4 hex)."""
    return uuid.uuid4().hex


def utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat()
