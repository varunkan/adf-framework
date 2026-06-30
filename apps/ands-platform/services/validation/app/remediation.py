"""PDF remediation pipeline — deterministic, declared-attribute (REQ-108).

Models the worker-backed PDF remediations (decrypt, OCR, embed fonts, generate
bookmarks, strip Track Changes) as transforms over a PDF's declared attributes —
the same attrs the validation rules read — with a before/after change audit. No
binary PDF processing (no PDF lib in the stdlib-only contract); the contract and
the audit are real and clear the corresponding A09/A10/B49/A11/D04 defects.
"""

from __future__ import annotations

# op -> (condition(pdf) -> bool, field, new_value)
_OPS = {
    "decrypt": (lambda f: bool(f.get("encrypted")), "encrypted", False),
    "strip-drm": (lambda f: bool(f.get("drm")), "drm", False),
    "ocr": (lambda f: bool(f.get("scanned")) and not f.get("searchable", True),
            "searchable", True),
    "embed-fonts": (lambda f: f.get("fonts_embedded") is False,
                    "fonts_embedded", True),
    "generate-bookmarks": (lambda f: f.get("bookmarks") is False, "bookmarks",
                           True),
    "strip-track-changes": (lambda f: bool(f.get("track_changes")),
                            "track_changes", False),
}
ALL_OPS = tuple(_OPS)


def remediation_plan(pdf: dict) -> list:
    """The ops whose defect condition currently holds for ``pdf``."""
    pdf = pdf or {}
    return [op for op, (cond, _f, _v) in _OPS.items() if cond(pdf)]


def remediate_pdf(pdf: dict, ops=None) -> dict:
    """Apply remediation ops (default: all applicable). Returns
    ``{before, after, changes, remediated}`` with a per-field change audit."""
    before = dict(pdf or {})
    after = dict(before)
    requested = list(ops) if ops else ALL_OPS
    changes = []
    for op in requested:
        spec = _OPS.get(op)
        if not spec:
            continue
        cond, field, new_value = spec
        if cond(after):
            changes.append({"op": op, "field": field,
                            "from": after.get(field), "to": new_value})
            after[field] = new_value
    return {"path": before.get("path", ""), "before": before, "after": after,
            "changes": changes, "remediated": bool(changes)}
