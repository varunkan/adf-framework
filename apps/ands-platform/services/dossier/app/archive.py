"""Submission archive / regulatory binder (REQ-110) — pure composition.

Snapshots a dossier sequence into an immutable binder that aggregates the
Application-Viewer Files + Outline views, the current view, and (when supplied by
the caller/gateway) the attached validation report and transmission ledger — the
read-only regulatory binder reviewers and QA browse.
"""

from __future__ import annotations

from . import assembly


def build_binder(model: dict, *, sequence: str = "0000",
                 validation_report=None, transmission=None) -> dict:
    view = assembly.current_view(model)
    return {
        "dossier_id": model["dossier_id"],
        "sequence": assembly._seq_key(sequence),
        "layout": "regulatory-binder",
        "files_view": assembly.build_files_view(model),
        "outline": assembly.build_outline_view(model, sequence),
        "current_view": view,
        "live_leaf_count": len(view["live"]),
        "validation_report": validation_report or None,
        "transmission": transmission or None,
    }
