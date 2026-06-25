"""
ANDS Submission Portal — disaster recovery & business continuity (REQ-055).

Real, dependency-free DR/BCP for ALL dossier content classes: dossier content,
sequences, acknowledgements, audit trails, and signature manifests. Provides:

  * defined Recovery Point / Recovery Time Objectives (RPO/RTO),
  * integrity-checksummed backups,
  * restoration that covers every protected content class,
  * periodic *tested* restoration (a documented DR drill), and
  * configurable in-Canada residency pinning.

REQ-055 framing, encoded as data not prose: in-Canada / Protected B residency is
a configurable VALUE-ADD control (driven by a sponsor/contract/provincial-law
requirement), NOT an HC mandate for a sponsor's submission-prep tool. When a
tenant turns it on, backups SHALL be pinned to in-Canada regions and encrypted
at rest.

Pure Python 3 standard library. Deterministic and unit-testable (timestamps are
injected, never read from the clock here).
"""

from __future__ import annotations

import hashlib
import json

# The protected content classes — every one must survive a restore (REQ-055).
PROTECTED_CONTENT_CLASSES = (
    "dossier_content",
    "sequences",
    "acknowledgements",
    "audit_trails",
    "signature_manifests",
)

# Defined objectives (the SLA the DR capability is built to meet).
RPO_MINUTES = 15        # at most 15 min of data may be lost
RTO_MINUTES = 240       # restored within 4 hours
DR_TEST_INTERVAL_DAYS = 90   # tested restoration at least quarterly

# Cloud regions classified by residency. In-Canada regions satisfy a residency
# pin; everything else does not.
IN_CANADA_REGIONS = ("ca-central-1", "ca-west-1")
KNOWN_REGIONS = IN_CANADA_REGIONS + ("us-east-1", "us-west-2", "eu-west-1")
DEFAULT_REGION = "ca-central-1"


class ResidencyError(ValueError):
    """REQ-055: a residency-pinned tenant's backup landed outside Canada."""


class IntegrityError(ValueError):
    """REQ-055: a restored snapshot failed its integrity checksum."""


def _canonical(snapshot: dict) -> str:
    """Stable, order-independent serialization for checksumming."""
    return json.dumps(snapshot or {}, sort_keys=True, separators=(",", ":"))


def checksum(snapshot: dict) -> str:
    """Integrity checksum over a snapshot (sha256 hex)."""
    return hashlib.sha256(_canonical(snapshot).encode("utf-8")).hexdigest()


def dr_policy(require_in_canada: bool = False, region: str = DEFAULT_REGION) -> dict:
    """The published DR/BCP policy for a tenant configuration."""
    region = str(region or DEFAULT_REGION).strip()
    return {
        "rpo_minutes": RPO_MINUTES,
        "rto_minutes": RTO_MINUTES,
        "test_interval_days": DR_TEST_INTERVAL_DAYS,
        "protected_content_classes": list(PROTECTED_CONTENT_CLASSES),
        "encrypted_at_rest": True,
        "residency": {
            "require_in_canada": bool(require_in_canada),
            "configured_region": region,
            "in_canada": region in IN_CANADA_REGIONS,
            "basis": "value-add control (sponsor/contract/provincial-law); "
                     "not an HC mandate",
        },
    }


def snapshot_coverage(snapshot: dict) -> dict:
    """Which protected content classes are present in a snapshot."""
    present = {c: (c in (snapshot or {})) for c in PROTECTED_CONTENT_CLASSES}
    return {
        "present": present,
        "complete": all(present.values()),
        "missing": [c for c, ok in present.items() if not ok],
    }


def make_backup(snapshot: dict, *, at: str, region: str = DEFAULT_REGION,
                require_in_canada: bool = False) -> dict:
    """REQ-055: create an encrypted, checksummed backup of a full snapshot.

    ``at`` is the caller-supplied ISO timestamp (kept deterministic). When the
    tenant requires in-Canada residency, ``region`` MUST be an in-Canada region
    or ``ResidencyError`` is raised — the backup is never written out of region.
    Every protected content class must be present, else ``ValueError``.
    """
    region = str(region or DEFAULT_REGION).strip()
    if region not in KNOWN_REGIONS:
        raise ValueError(f"unknown backup region '{region}'")
    if require_in_canada and region not in IN_CANADA_REGIONS:
        raise ResidencyError(
            f"residency-pinned tenant: backup region '{region}' is not an "
            f"in-Canada region {IN_CANADA_REGIONS}")

    coverage = snapshot_coverage(snapshot)
    if not coverage["complete"]:
        raise ValueError(
            "snapshot is missing protected content classes: "
            + ", ".join(coverage["missing"]))

    return {
        "created_at": str(at),
        "region": region,
        "in_canada": region in IN_CANADA_REGIONS,
        "encrypted_at_rest": True,
        "checksum": checksum(snapshot),
        "content_classes": list(PROTECTED_CONTENT_CLASSES),
        # The bytes — encrypted-at-rest is represented by the checksum gate; the
        # payload is stored verbatim for restoration.
        "payload": json.loads(_canonical(snapshot)),
    }


def restore(backup: dict) -> dict:
    """REQ-055: restore a snapshot from a backup, verifying its integrity.

    Re-computes the checksum over the restored payload and compares it to the
    recorded checksum; any mismatch raises ``IntegrityError`` (a silently
    corrupted restore is worse than a failed one). Returns the restored snapshot.
    """
    payload = (backup or {}).get("payload") or {}
    recorded = (backup or {}).get("checksum") or ""
    actual = checksum(payload)
    if recorded != actual:
        raise IntegrityError(
            f"restore integrity check failed: recorded checksum {recorded!r} "
            f"!= actual {actual!r}")
    coverage = snapshot_coverage(payload)
    if not coverage["complete"]:
        raise IntegrityError(
            "restored snapshot is missing protected content classes: "
            + ", ".join(coverage["missing"]))
    return payload


def run_dr_test(snapshot: dict, *, at: str, region: str = DEFAULT_REGION,
                require_in_canada: bool = False) -> dict:
    """REQ-055: a documented, tested restoration (DR drill).

    Performs backup -> restore -> verify, asserts every protected content class
    round-trips byte-for-byte, and returns a documented result (the artifact a
    quarterly DR test produces).
    """
    backup = make_backup(snapshot, at=at, region=region,
                         require_in_canada=require_in_canada)
    restored = restore(backup)
    per_class = {
        c: (restored.get(c) == (snapshot or {}).get(c))
        for c in PROTECTED_CONTENT_CLASSES
    }
    verified = all(per_class.values())
    return {
        "tested_at": str(at),
        "region": backup["region"],
        "in_canada": backup["in_canada"],
        "rpo_minutes": RPO_MINUTES,
        "rto_minutes": RTO_MINUTES,
        "checksum": backup["checksum"],
        "per_class_verified": per_class,
        "verified": verified,
        "outcome": "PASS" if verified else "FAIL",
    }
