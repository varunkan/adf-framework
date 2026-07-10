#!/usr/bin/env python3
"""Background worker: package jobs from Postgres + manifest upload to S3."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.deps import get_package_storage, get_store  # noqa: E402


def process_once() -> bool:
    store = get_store()
    storage = get_package_storage()
    job = store.claim_next_package_job()
    if not job:
        return False

    job_id = int(job["id"])
    dossier_id = job["dossier_id"]
    sequence = job["sequence"]
    try:
        manifest = {
            "dossier_id": dossier_id,
            "sequence": sequence,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "Placeholder manifest — wire eCTD assembler in Phase 2.",
        }
        s3_key = None
        if storage is not None:
            s3_key = storage.put_package_manifest(dossier_id, sequence, manifest)
        store.complete_package_job(job_id, s3_key=s3_key)
    except Exception as exc:  # pragma: no cover - worker safety net
        store.complete_package_job(job_id, error=str(exc))
    return True


def main() -> None:
    settings = get_settings()
    print(f"ANDS worker started (esg_mode={settings.esg_mode})")
    while True:
        if not process_once():
            time.sleep(2)


if __name__ == "__main__":
    main()
