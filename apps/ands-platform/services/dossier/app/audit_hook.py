"""Fire-and-forget audit ingest → the governance service (HTTP).

Local dev runs each service with its own in-process event bus, so the
governance ``"*"`` subscription never sees dossier events. This hook POSTs
them to governance's HTTP ingest path (``POST /api/governance/audit/record``)
instead, landing on the same append-only trail.

Deliberately best-effort: the POST runs on a daemon thread with a short
timeout and EVERY error is swallowed — an audit outage must never break
(or slow) the dossier workflow. ``GOVERNANCE_URL`` selects the target
(docker-compose sets ``http://governance:8000``); it is read per call so
tests and late env wiring both work.

Wire-up is intentionally left to the integrator: import :func:`record` and
call it after domain actions, e.g. ``record("document.uploaded", dossier_id,
{"leaf": leaf_id})``.
"""

from __future__ import annotations

import contextvars
import json
import os
import threading
import urllib.request

_TIMEOUT_SEC = 1.5
_DEFAULT_URL = "http://127.0.0.1:8012"  # local governance uvicorn

# The acting user's email for the current request — set by an ASGI middleware
# from X-User-Email so every recorded event carries who did it (a real e-sign
# / Part-11 audit needs actor attribution). ContextVar = per-request safe.
_actor: contextvars.ContextVar[str] = contextvars.ContextVar("audit_actor",
                                                             default="")
# The acting TENANT for the current request — also set by the middleware from
# X-Tenant-Id. Without it every event is written unowned (tenant_id='') and the
# tenant-scoped audit read then hides it, leaving the Part-11 trail blank.
_tenant: contextvars.ContextVar[str] = contextvars.ContextVar("audit_tenant",
                                                              default="")


def set_actor(email: str) -> None:
    _actor.set(str(email or ""))


def set_tenant(tenant_id: str) -> None:
    _tenant.set(str(tenant_id or ""))


def _ingest_url() -> str:
    base = (os.environ.get("GOVERNANCE_URL") or _DEFAULT_URL).rstrip("/")
    return base + "/api/governance/audit/record"


def _post(url: str, payload: dict) -> None:
    try:
        hdrs = {"Content-Type": "application/json"}
        tok = os.environ.get("ANDS_INTERNAL_TOKEN", "").strip()
        if tok:
            hdrs["X-Internal-Auth"] = tok
        req = urllib.request.Request(
            url, data=json.dumps(payload, default=str).encode("utf-8"),
            headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC):
            pass
    except Exception:
        pass  # best-effort by contract — audit must never break the workflow


def record(event_type: str, dossier_id: str, data: dict | None = None,
           *, tenant_id: str = "", source: str = "dossier") -> None:
    """Fire-and-forget: post one audit event to governance, return at once."""
    try:
        payload = {"source": source,
                   "event_type": str(event_type or ""),
                   "dossier_id": str(dossier_id or ""),
                   # tenant from the explicit arg, else the request contextvar,
                   # so the event is owned and visible to the tenant's audit read
                   "tenant_id": str(tenant_id or "") or _tenant.get(),
                   "actor": _actor.get(),
                   "data": dict(data or {})}
        threading.Thread(target=_post, args=(_ingest_url(), payload),
                         daemon=True).start()
    except Exception:
        pass  # even thread spawn failures stay silent
