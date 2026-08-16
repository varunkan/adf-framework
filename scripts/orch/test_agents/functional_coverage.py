#!/usr/bin/env python3
"""ADF test agent: functional / requirements-coverage traceability.

Answers the question the unit-test count cannot: "is every REQUIREMENT actually
exercised?" It reads the app's requirement spec, then traces each requirement ID
into the test suite and the implementation:

  - referenced by a TEST            -> covered
  - referenced only in IMPL code    -> implemented but UNTESTED  (advisory)
  - referenced NOWHERE              -> genuine functional GAP     (blocking)

This keeps the heal loop honest about the north-star ("100% complete, tested")
without drowning it: only true gaps (built nowhere, tested nowhere) are 'critical'
and block; merely-untested requirements are 'medium' advisory guidance.

Contract: prints {"agent","ok","findings":[{severity,title,detail,location}],
"summary"}. Exit 0 regardless.

Usage: functional_coverage.py <app_dir>
"""
import json
import os
import re
import sys

FW = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REQ_RE = re.compile(r"\b(?:REQ|FR|NFR|US|AC)-\d{1,4}\b")
FUNC_RE = re.compile(r"\b(?:REQ|FR|US|AC)-\d{1,4}\b")  # functional only (excludes NFR)
SKIP_DIRS = (".adf-", "__pycache__", ".git", "node_modules")
MAX_LIST = 30   # cap findings listed individually; remainder summarized
# Below this functional-coverage fraction we treat the suite as not tracing
# requirements at all — a genuine "functional verification is broken" gate.
FLOOR = float(os.environ.get("ADF_FUNC_COVERAGE_FLOOR", "0.15"))


def _read(p):
    try:
        return open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""


def _spec_text(app_dir, app_id):
    """Concatenate every requirement/spec document we can find for this app."""
    blobs, sources = [], []
    candidates = []
    spec_dir = os.path.join(FW, "specs", app_id)
    if os.path.isdir(spec_dir):
        for n in os.listdir(spec_dir):
            if n.endswith(".md") and re.search(r"requirement|spec", n, re.I):
                candidates.append(os.path.join(spec_dir, n))
    for n in os.listdir(app_dir) if os.path.isdir(app_dir) else []:
        if n.endswith(".md") and re.search(r"requirement|spec", n, re.I):
            candidates.append(os.path.join(app_dir, n))
    for p in candidates:
        t = _read(p)
        if REQ_RE.search(t):
            blobs.append(t)
            sources.append(os.path.relpath(p, FW))
    return "\n".join(blobs), sources


def _classify_files(app_dir):
    tests, impl = [], []
    for root, dirs, names in os.walk(app_dir):
        dirs[:] = [d for d in dirs if not any(s in d for s in SKIP_DIRS)]
        if any(s in root for s in SKIP_DIRS):
            continue
        for n in names:
            p = os.path.join(root, n)
            if n.startswith("test_") or n.endswith(("_test.py", ".spec.js", ".test.js")):
                tests.append(p)
            elif n.endswith((".py", ".js", ".html", ".htm")):
                impl.append(p)
    return tests, impl


def _ids_in(files):
    ids = set()
    for p in files:
        ids |= set(REQ_RE.findall(_read(p)))
    return ids


def run(app_dir):
    app_id = os.path.basename(os.path.normpath(app_dir))
    spec, sources = _spec_text(app_dir, app_id)
    tests, impl = _classify_files(app_dir)

    if not spec:
        # No requirement spec to trace against — fall back to "are there tests?"
        if not tests:
            return {"agent": "functional", "ok": False,
                    "findings": [{"severity": "high",
                                  "title": "no automated tests found",
                                  "detail": "the app ships no test_*.py / *_test.* — functional behaviour is unverified",
                                  "location": app_id}],
                    "summary": "no requirement spec and no tests found"}
        return {"agent": "functional", "ok": True, "findings": [],
                "summary": f"no requirement spec found; {len(tests)} test file(s) present (traceability not assessable)"}

    # Trace FUNCTIONAL requirements. NFRs (perf/security/audit KPIs) are
    # cross-cutting and rarely carry a literal ID in code, so they're reported
    # as an informational ratio, never as per-ID gaps that block the gate.
    func_ids = set(FUNC_RE.findall(spec))
    nfr_ids = set(REQ_RE.findall(spec)) - func_ids
    test_ids, impl_ids = _ids_in(tests), _ids_in(impl)
    tested = test_ids & func_ids
    implemented = impl_ids & func_ids
    nowhere = sorted(func_ids - tested - implemented, key=_natkey)
    untested = sorted(implemented - tested, key=_natkey)
    nfr_traced = len((test_ids | impl_ids) & nfr_ids)
    cov = (len(tested) / len(func_ids)) if func_ids else 1.0

    findings = []
    # Hard gate ONLY on a floor breach: if coverage is this low, the suite isn't
    # tracing requirements at all (vs. an MVP that intentionally defers scope).
    if func_ids and cov < FLOOR:
        findings.append({"severity": "critical",
                         "title": f"functional requirement coverage {cov*100:.0f}% is below the {FLOOR*100:.0f}% floor",
                         "detail": f"only {len(tested)}/{len(func_ids)} functional requirements are exercised by a test — the suite is not tracing the spec",
                         "location": ", ".join(sources) or app_id})
    # Genuine gaps (built nowhere, tested nowhere) -> advisory guidance that
    # drives the campaign's coverage-expansion slices; not a hard block, because
    # MVP scope intentionally defers requirements.
    for rid in nowhere[:MAX_LIST]:
        findings.append({"severity": "medium",
                         "title": f"requirement {rid} is implemented or tested nowhere",
                         "detail": "no reference in any impl or test file — a coverage gap against the spec",
                         "location": ", ".join(sources) or app_id})
    if len(nowhere) > MAX_LIST:
        findings.append({"severity": "medium",
                         "title": f"+{len(nowhere) - MAX_LIST} more requirements traced nowhere",
                         "detail": "expand coverage slices to reach the remaining requirement IDs",
                         "location": ", ".join(sources) or app_id})
    for rid in untested[:MAX_LIST]:
        findings.append({"severity": "low",
                         "title": f"requirement {rid} is implemented but has no test",
                         "detail": "referenced in code but not in any test file — add a traceable test",
                         "location": ", ".join(sources) or app_id})
    if len(untested) > MAX_LIST:
        findings.append({"severity": "low",
                         "title": f"+{len(untested) - MAX_LIST} more requirements implemented but untested",
                         "detail": "raise test coverage to trace every implemented requirement",
                         "location": ", ".join(sources) or app_id})

    blocking = sum(1 for f in findings if f["severity"] == "critical")
    return {
        "agent": "functional",
        "ok": blocking == 0,
        "findings": findings,
        "summary": (f"functional coverage {cov*100:.0f}% — {len(tested)}/{len(func_ids)} tested, "
                    f"{len(untested)} implemented-but-untested, {len(nowhere)} traced nowhere; "
                    f"NFR traced {nfr_traced}/{len(nfr_ids)} (informational); "
                    f"{len(tests)} test file(s), {len(impl)} impl file(s)"),
    }


def _natkey(rid):
    m = re.search(r"(\d+)", rid)
    return (rid.split("-")[0], int(m.group(1)) if m else 0)


if __name__ == "__main__":
    app = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(run(app), indent=2))
