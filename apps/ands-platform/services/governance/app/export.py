"""Tenant data export / portability bundle — pure (SAAS-REQ-004).

Assembles a checksummed export bundle: the tenant's governance audit trail plus
caller-supplied attachments (dossiers/registrations/etc. the gateway gathers from
the owning services), with a manifest. The checksum lets the recipient verify the
download was not altered.
"""

from __future__ import annotations

import hashlib
import json


def build_bundle(tenant_id: str, audit_events: list,
                 attachments: dict | None = None) -> dict:
    attachments = attachments or {}
    content = {"tenant_id": tenant_id, "audit_events": audit_events,
               "attachments": attachments}
    canonical = json.dumps(content, sort_keys=True)
    checksum = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    manifest = {"tenant_id": tenant_id,
                "audit_event_count": len(audit_events),
                "attachment_keys": sorted(attachments.keys()),
                "formats": ["json"], "checksum": checksum}
    return {"tenant_id": tenant_id, "manifest": manifest,
            "audit_events": audit_events, "attachments": attachments,
            "checksum": checksum}
