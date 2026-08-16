#!/usr/bin/env python3
"""Systematic debugging for ADF's self-heal — root cause BEFORE the fix.

Gated by ADF_HEAL_DIAGNOSE. Superpowers' systematic-debugging discipline: instead of a
blind regenerate, the heal turn (1) READS the error to find the failing surface,
(2) is handed a known-good reference, and (3) must commit to a one-line ROOT CAUSE
before patching. The class is derived deterministically from the REAL verifier output
(the attributed stage tag the verify stages already emit) — never from model prose —
and recorded as durable evidence so process_facts can seal `root_cause_documented`.

Pure + stdlib-only so the classifier is unit-testable; the heal prompt scaffold is a
$0 prepend to the existing fixer turn.
"""
import os
import re


def is_enabled(env=None):
    env = env if env is not None else os.environ
    return env.get("ADF_HEAL_DIAGNOSE", "").strip().lower() in ("1", "true", "on")


# Classify from the verifier's REAL attributed failure text (the leading "<STAGE>
# FAILED (...)" tag the verify stages emit), most-specific first.
_CAUSE_RULES = [
    ("dependency_install", re.compile(r"DEPENDENCY INSTALL FAILED|npm ci", re.I)),
    ("type_error",         re.compile(r"BUILD FAILED|tsc --noEmit|\bTS\d{3,}\b", re.I)),
    ("test_failure",       re.compile(r"TESTS FAILED|vitest|jest|AssertionError|expect\(", re.I)),
    ("boot_crash",         re.compile(r"BOOT FAILED|SERVER BOOT", re.I)),
    ("render_blank",       re.compile(r"RENDER FAILED|white screen|did not mount|blank root", re.I)),
    ("no_files",           re.compile(r"no parseable|<<<FILE", re.I)),
    ("edit_rejected",      re.compile(r"edits were REJECTED|edit guard", re.I)),
]


def classify_failure(output):
    """The deterministic root-cause class from the real failure text, or 'unknown'."""
    text = output or ""
    for name, rx in _CAUSE_RULES:
        if rx.search(text):
            return name
    return "unknown"


def failing_stage(output):
    """The verify stage named in the leading failure tag (for 'read the error'), or
    None — e.g. 'BUILD FAILED (...)' → 'build', 'TESTS FAILED' → 'tests'."""
    m = re.match(r"\s*([A-Z][A-Z +/]+?) (?:FAILED|PASSED but)", output or "")
    if not m:
        return None
    return m.group(1).strip().lower()


def diagnose_preamble(output, reference=None):
    """The systematic-debugging scaffold prepended to the fixer turn: name the failing
    surface + class, demand a one-line ROOT CAUSE before the patch, and (optionally)
    supply a known-good reference. Returns '' when diagnosis is disabled-equivalent."""
    stage = failing_stage(output) or "the failing stage"
    cause = classify_failure(output)
    lines = [
        "SYSTEMATIC DEBUGGING — do this BEFORE editing:",
        f"1. READ THE ERROR. Failing stage: {stage} (likely class: {cause}).",
        "2. Find the SMALLEST change at the root cause — do NOT rewrite working files.",
        "3. Begin your reply with one line `ROOT CAUSE: <...>` then emit the corrected files.",
    ]
    if reference:
        lines.append(
            "\n=== KNOWN-GOOD REFERENCE (working template shape — match it) ===\n"
            + reference)
    return "\n".join(lines)


def record_root_cause(app_root, attempt, output):
    """Append the diagnosed cause (from the real failure) to durable evidence and
    return the class. Best-effort; never raises."""
    import process_facts
    cause = classify_failure(output)
    stage = failing_stage(output)
    existing = process_facts._read(app_root, "heal.json") or {"heals": []}
    existing.setdefault("heals", []).append(
        {"attempt": attempt, "stage": stage, "cause": cause})
    process_facts._write(app_root, "heal.json", existing)
    return cause
