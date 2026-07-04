#!/usr/bin/env python3
"""Task-based usability TRACE GENERATOR for ANDS Studio.

Performs the trust-critical ANDS filing task END-TO-END against the REAL
``dossier`` service — in-process, via FastAPI ``TestClient``, exactly the way
``services/dossier/tests/conftest.py`` spins it up. It captures the REAL
request -> response sequence as a faithful, structured "interaction trace".

The trace is later shown to synthetic personas so they rate the experience of
DOING the task (not reading a description). Therefore it MUST be real: every
step below is generated from the running code. Nothing is hand-authored to
flatter the product. If a step blocks or fails, the trace records the real
failure (that is the point — the fail-closed export block IS the good UX here).

Canonical task (t2 — "validate, fix, export"):

    create dossier (placeholder 'd...' id)
      -> open Module 1
      -> place the required Module 1 leaves (author/generate + upload REAL bytes)
      -> run eCTD validation, capture the REAL report (rule_ids, criteria)
      -> attempt export, capture the REAL fail-closed block (409 + findings)
      -> set the real Health Canada Dossier ID (re-key placeholder -> real)
      -> re-validate (capture the PASS)
      -> export the sequence (capture the real successful zip)

Run:  .venv/bin/python usability_panel/task_eval/trace.py
Writes: usability_panel/task_eval/traces/t2_validate_fix_export.json

The script exits 0 only if it genuinely captured, from the real service:
  * a real validation report carrying rule_ids,
  * a real fail-closed export block (409) on the placeholder id, AND
  * a real successful export (200, real zip) after the fix.
Otherwise it exits non-zero — it never pretends the task worked.
"""

from __future__ import annotations

import io
import json
import os
import sys
import warnings
import zipfile
from pathlib import Path

warnings.filterwarnings("ignore")  # quiet the starlette/httpx testclient notice

# --- wire up imports exactly like the dossier tests do --------------------
# tests run from services/dossier/ with pythonpath = "." + "../../libs".
HERE = Path(__file__).resolve()
APP_ROOT = HERE.parents[2]                       # apps/ands-platform
DOSSIER_ROOT = APP_ROOT / "services" / "dossier"  # has the `app` package
LIBS_ROOT = APP_ROOT / "libs"                     # has `ands_shared`
for p in (str(DOSSIER_ROOT), str(LIBS_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient  # noqa: E402

from ands_shared import InMemoryEventBus, SqliteDb  # noqa: E402

from app.api import build_app  # noqa: E402
from app.repository_sqlite import SqliteDossierRepository  # noqa: E402
from app.service import DossierService  # noqa: E402

TRACE_PATH = HERE.parent / "traces" / "t2_validate_fix_export.json"

# a minimal but genuinely valid PDF (has the %PDF magic the document check wants)
_REAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def build_client() -> TestClient:
    """A fresh in-memory dossier service + TestClient — identical wiring to
    services/dossier/tests/conftest.py::ctx."""
    repo = SqliteDossierRepository(SqliteDb(":memory:"))
    bus = InMemoryEventBus()
    service = DossierService(repo, bus).register()
    return TestClient(build_app(service))


class Recorder:
    """Accumulates the interaction trace, one real request/response per step."""

    def __init__(self, client: TestClient):
        self.client = client
        self.steps: list[dict] = []

    def _excerpt(self, resp, kind: str):
        """A faithful, size-bounded excerpt of the real response."""
        if kind == "json":
            try:
                return _trim(resp.json())
            except Exception:
                return {"_raw": resp.text[:400]}
        if kind == "binary":
            return {
                "content_type": resp.headers.get("content-type"),
                "content_disposition": resp.headers.get("content-disposition"),
                "bytes": len(resp.content),
                "headers": {k: v for k, v in resp.headers.items()
                            if k.lower().startswith("x-export")},
            }
        return {"_text": resp.text[:400]}

    def record(self, *, action, method, path, request_summary, resp,
               what_the_user_sees, excerpt_kind="json", excerpt=None):
        step = {
            "step": len(self.steps) + 1,
            "action": action,
            "method": method,
            "path": path,
            "request_summary": request_summary,
            "status": resp.status_code,
            "what_the_user_sees": what_the_user_sees,
            # `excerpt` lets a caller substitute a focused, faithful summary in
            # place of a huge full-tree body (e.g. the content_state response) —
            # the trust-critical steps still record the raw response verbatim.
            "response_excerpt": (excerpt if excerpt is not None
                                 else self._excerpt(resp, excerpt_kind)),
        }
        self.steps.append(step)
        return step


def _trim(obj, *, _depth=0):
    """Bound a JSON response so the trace stays readable but stays faithful
    (keeps rule_ids, messages, criteria — the load-bearing evidence)."""
    if isinstance(obj, dict):
        if _depth > 6:
            return {"_truncated_keys": list(obj.keys())}
        return {k: _trim(v, _depth=_depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        head = [_trim(v, _depth=_depth + 1) for v in obj[:12]]
        if len(obj) > 12:
            head.append(f"... (+{len(obj) - 12} more)")
        return head
    if isinstance(obj, str) and len(obj) > 600:
        return obj[:600] + "..."
    return obj


def run_task() -> dict:
    client = build_client()
    rec = Recorder(client)

    placeholder_id = "d4821"           # a real 'd...' placeholder (pre-HC-ID)
    real_id = "e478210"                # the real HC Dossier ID issued via REP
    seq = "0000"                       # the initial submission sequence

    # -- 1. create the dossier under a placeholder id ----------------------
    body = {
        "dossier_id": placeholder_id,
        "title": "Metformin HCl 500 mg Tablets — ANDS",
        "submission_type": "ANDS",
        "drug_product": "Metformin HCl 500 mg",
        "company_id": "12345",
        "sponsor": "Acme Generics Inc.",
    }
    r = client.post("/api/dossier/dossiers", json=body)
    r.raise_for_status()
    rec.record(
        action="Create dossier (placeholder ID, before HC issues the real one)",
        method="POST", path="/api/dossier/dossiers",
        request_summary=f"dossier_id={placeholder_id} (placeholder), "
                        f"title={body['title']!r}, type=ANDS",
        resp=r,
        what_the_user_sees="A new dossier 'Metformin HCl 500 mg Tablets — ANDS' "
        f"opens under the working ID {placeholder_id}. A banner notes this is a "
        "placeholder until Health Canada issues the real Dossier ID via a REP "
        "Dossier ID Request.")

    # -- 2. open Module 1 — see the required sections ----------------------
    r = client.get(f"/api/dossier/dossiers/{placeholder_id}/content")
    r.raise_for_status()
    content = r.json()
    mod1 = next(m for m in content["modules"] if m["module"] == "1")
    required = [n for n in mod1["nodes"]
                if n.get("kind") == "document"
                and n.get("applicability") == "required"]
    req_labels = ", ".join(f"{n['section']} {n['title']}" for n in required[:4])
    rec.record(
        action="Open Module 1 (Administrative & regional) — see required leaves",
        method="GET", path=f"/api/dossier/dossiers/{placeholder_id}/content",
        request_summary="Load the guided module builder for Module 1",
        resp=r,
        excerpt={"module1": {"title": mod1.get("title"),
                             "progress": mod1.get("progress"),
                             "required_documents": [
                                 {"section": n["section"], "title": n["title"],
                                  "status": n.get("status"),
                                  "affordances": n.get("affordances"),
                                  "bilingual": n.get("bilingual")}
                                 for n in required]}},
        what_the_user_sees=f"The Module 1 checklist lists "
        f"{len(required)} required documents ({req_labels}, ...), each empty, "
        f"module progress {mod1['progress']['percent']}% "
        f"({mod1['progress']['required_filled']}/{mod1['progress']['required_total']}).")

    # -- 3. place required Module 1 leaves (real content) ------------------
    # 3a. author the sections the portal can generate (deterministic template
    #     fill from the dossier/company/product identity — confirmed content).
    generatable = [n for n in required if "generate" in n.get("affordances", [])]
    for n in generatable:
        section = n["section"]
        r = client.post(
            f"/api/dossier/ectd/{placeholder_id}/section/{section}/generate",
            json={})
        r.raise_for_status()
        cs = r.json()
        node = _find_node(cs, section)
        rec.record(
            action=f"Author {section} {n['title']} (portal generates it)",
            method="POST",
            path=f"/api/dossier/ectd/{placeholder_id}/section/{section}/generate",
            request_summary=f"Generate {n['title']!r} from the dossier's single "
                            f"set of identifiers (generator={n.get('generator_key')})",
            resp=r, excerpt=_node_excerpt(cs, section),
            what_the_user_sees=f"Section {section} '{n['title']}' fills in from "
            f"the company/product details and turns "
            f"{node.get('status', 'complete')} "
            f"({'confirmed as your content' if node.get('content_confirmed') else 'pending review'}).")

    # 3b. upload REAL bytes to the upload-only required leaves.
    upload_only = [n for n in required
                   if "generate" not in n.get("affordances", [])]
    for n in upload_only:
        section = n["section"]
        fmts = [str(f).lower() for f in (n.get("formats") or ["pdf"])]
        ext = "pdf" if "pdf" in fmts else fmts[0]
        if n.get("bilingual"):
            for lang in ("en", "fr"):
                fname = f"{section.replace('.', '_')}_{lang}.{ext}"
                r = client.post(
                    f"/api/dossier/ectd/{placeholder_id}/section/{section}/upload",
                    files={"file": (fname, _REAL_PDF, "application/pdf")},
                    data={"lang": lang})
                r.raise_for_status()
            cs = r.json()
            node = _find_node(cs, section)
            rec.record(
                action=f"Upload {section} {n['title']} (bilingual — EN + FR)",
                method="POST",
                path=f"/api/dossier/ectd/{placeholder_id}/section/{section}/upload",
                request_summary=f"Upload real EN and FR {ext.upper()} files for "
                                f"the bilingual section {section}",
                resp=r, excerpt=_node_excerpt(cs, section),
                what_the_user_sees=f"Section {section} '{n['title']}' shows both "
                f"EN and FR files attached and turns {node.get('status')}.")
        else:
            fname = f"{section.replace('.', '_')}.{ext}"
            r = client.post(
                f"/api/dossier/ectd/{placeholder_id}/section/{section}/upload",
                files={"file": (fname, _REAL_PDF, "application/pdf")})
            r.raise_for_status()
            cs = r.json()
            node = _find_node(cs, section)
            rec.record(
                action=f"Upload {section} {n['title']}",
                method="POST",
                path=f"/api/dossier/ectd/{placeholder_id}/section/{section}/upload",
                request_summary=f"Upload a real {ext.upper()} file for {section}",
                resp=r, excerpt=_node_excerpt(cs, section),
                what_the_user_sees=f"Section {section} '{n['title']}' shows the "
                f"uploaded file and turns {node.get('status')}.")

    # -- 4. run eCTD validation — capture the REAL report ------------------
    r = client.get(f"/api/dossier/dossiers/{placeholder_id}/validate")
    r.raise_for_status()
    report = r.json()
    rule_ids = [e.get("rule_id") for e in report.get("errors", [])]
    crit = report.get("criteria", {})
    rec.record(
        action="Run eCTD validation on the (still-placeholder) dossier",
        method="GET", path=f"/api/dossier/dossiers/{placeholder_id}/validate",
        request_summary="Run the structural eCTD validator over what's placed",
        resp=r,
        what_the_user_sees=(
            f"The validation report ({crit.get('name')} v{crit.get('version')}, "
            f"synced {crit.get('synced')}) comes back "
            f"{'PASSED' if report.get('passed') else 'NOT PASSED'} with "
            f"{len(report.get('errors', []))} blocking finding(s): "
            f"{'; '.join(rule_ids) or 'none'}. "
            + (f"The top finding {rule_ids[0]} says the dossier still uses a "
               "placeholder ID and must get its real HC Dossier ID before filing."
               if rule_ids else "")))

    # -- 5. attempt export — capture the REAL fail-closed block ------------
    r = client.get(f"/api/dossier/ectd/{placeholder_id}/export/{seq}")
    export_block = r.json() if r.status_code != 200 else None
    block_rule_ids = [e.get("rule_id")
                      for e in (export_block or {}).get("validation", {})
                      .get("errors", [])] if export_block else []
    rec.record(
        action="Attempt to export the transmissible package (placeholder ID)",
        method="GET", path=f"/api/dossier/ectd/{placeholder_id}/export/{seq}",
        request_summary=f"Export sequence {seq} for transmission",
        resp=r,
        what_the_user_sees=(
            f"Export is BLOCKED (HTTP {r.status_code} — "
            f"'{(export_block or {}).get('title')}'). The portal fails closed: it "
            f"refuses to emit a package while validation has not passed, and shows "
            f"the exact blocking finding(s) {block_rule_ids} instead of a "
            f"misleading download. To proceed you must resolve the findings (set "
            f"the real Dossier ID), or export with an explicit, reasoned, audited "
            f"override."))

    # -- 6. resolve the finding: set the real HC Dossier ID (re-key) -------
    r = client.post(
        f"/api/dossier/dossiers/{placeholder_id}/rename",
        json={"new_id": real_id,
              "reason": "Health Canada issued Dossier ID via REP Dossier ID Request"})
    r.raise_for_status()
    rec.record(
        action="Set the real Health Canada Dossier ID (re-key placeholder -> real)",
        method="POST", path=f"/api/dossier/dossiers/{placeholder_id}/rename",
        request_summary=f"Rename {placeholder_id} -> {real_id} with a "
                        f"reason-for-change (lands on the Part-11 audit trail)",
        resp=r,
        what_the_user_sees=f"The dossier is re-keyed from the placeholder "
        f"{placeholder_id} to the real HC Dossier ID {real_id}; the change and "
        f"reason are written to the audit trail, and all placed content carries "
        f"over unchanged.")

    # -- 7. re-validate — capture the PASS ---------------------------------
    r = client.get(f"/api/dossier/dossiers/{real_id}/validate")
    r.raise_for_status()
    report2 = r.json()
    rule_ids2 = [e.get("rule_id") for e in report2.get("errors", [])]
    rec.record(
        action="Re-run eCTD validation after the fix",
        method="GET", path=f"/api/dossier/dossiers/{real_id}/validate",
        request_summary="Re-run the structural eCTD validator on the real ID",
        resp=r,
        what_the_user_sees=(
            f"The validation report now comes back "
            f"{'PASSED' if report2.get('passed') else 'NOT PASSED'} — "
            f"{len(report2.get('errors', []))} blocking finding(s) "
            f"({'; '.join(rule_ids2) or 'none — the placeholder-ID block is cleared'}). "
            f"The submission is clear of the structural blocker."))

    # -- 8. export the sequence — capture the real success -----------------
    r = client.get(f"/api/dossier/ectd/{real_id}/export/{seq}")
    r.raise_for_status()
    is_zip = _looks_like_zip(r.content)
    rec.record(
        action="Export the transmissible eCTD package (after the fix)",
        method="GET", path=f"/api/dossier/ectd/{real_id}/export/{seq}",
        request_summary=f"Export sequence {seq} for transmission",
        resp=r, excerpt_kind="binary",
        what_the_user_sees=(
            f"Export SUCCEEDS (HTTP {r.status_code}). A real "
            f"{len(r.content)}-byte eCTD zip package downloads "
            f"('{_filename(r)}'), stamped "
            f"X-Export-Validation={r.headers.get('X-Export-Validation')!r} with "
            f"{r.headers.get('X-Export-Missing')} missing leaves — the package "
            f"only emitted because validation genuinely passed."))

    # -- assemble + verify the trace ---------------------------------------
    trace = {
        "task": "t2_validate_fix_export",
        "goal": "File an ANDS: assemble Module 1, hit the eCTD validation gate, "
                "run into the fail-closed export block on a placeholder Dossier "
                "ID, set the real Health Canada Dossier ID, and export the "
                "transmissible package once validation genuinely passes.",
        "generated_from": "REAL in-process dossier service (FastAPI TestClient), "
                          "not hand-authored",
        "steps": rec.steps,
    }

    # honesty gate: prove the three trust-critical moments were really captured.
    _assert_faithful(trace, report, export_block, r, is_zip)
    return trace


def _find_node(content_state: dict, section: str) -> dict:
    for m in content_state.get("modules", []):
        for n in m.get("nodes", []):
            if n.get("section") == section:
                return n
    return {}


def _node_excerpt(content_state: dict, section: str) -> dict:
    """A focused, faithful excerpt of a content_state response: the affected
    section's live status + Module 1 progress. Keeps the trace readable instead
    of embedding the entire M1–M5 section tree on every place-leaf step."""
    node = _find_node(content_state, section)
    mod1 = next((m for m in content_state.get("modules", [])
                 if m.get("module") == "1"), {})
    return {
        "section": section,
        "status": node.get("status"),
        "content_origin": node.get("content_origin"),
        "content_confirmed": node.get("content_confirmed"),
        "needs_review": node.get("needs_review"),
        "languages": node.get("languages"),
        "module1_progress": mod1.get("progress"),
    }


def _looks_like_zip(content: bytes) -> bool:
    try:
        zipfile.ZipFile(io.BytesIO(content))
        return True
    except Exception:
        return False


def _filename(resp) -> str:
    cd = resp.headers.get("content-disposition", "")
    if "filename=" in cd:
        return cd.split("filename=", 1)[1].strip('"')
    return "export.zip"


def _assert_faithful(trace, val_report, export_block, export_resp, is_zip):
    """Fail loudly (non-zero exit) unless the trace genuinely captured, from the
    real service: a validation report with rule_ids, a fail-closed export block,
    and a real successful export. This is the anti-flattery guarantee."""
    # (a) a real validation report carrying rule_ids
    val_rule_ids = [e.get("rule_id") for e in val_report.get("errors", [])]
    assert val_rule_ids, "no rule_ids in the validation report — not a real report"
    assert "criteria" in val_report and val_report["criteria"].get("version"), \
        "validation report is missing its versioned criteria"
    # (b) a real fail-closed export block (409) with the blocking finding
    assert export_block is not None, "export was NOT blocked — fail-closed gate " \
        "did not fire on the placeholder id"
    assert any(s["action"].startswith("Attempt to export") and s["status"] == 409
               for s in trace["steps"]), "no 409 export-block step recorded"
    block_ids = [e.get("rule_id")
                 for e in export_block.get("validation", {}).get("errors", [])]
    assert "CA-REP-0001" in block_ids, \
        f"export block did not surface the placeholder-ID finding: {block_ids}"
    # (c) a real successful export after the fix
    assert export_resp.status_code == 200, "final export did not succeed"
    assert is_zip and len(export_resp.content) > 0, "final export was not a real zip"
    assert export_resp.headers.get("X-Export-Validation") == "passed", \
        "final export was not stamped as validation-passed"
    # and the success step exists in the trace
    assert any(s["action"].startswith("Export the transmissible") and s["status"] == 200
               for s in trace["steps"]), "no successful-export step recorded"


def summarize(trace: dict) -> None:
    steps = trace["steps"]

    def _find(pred):
        return next((s for s in steps if pred(s)), None)

    val_step = _find(lambda s: s["action"].startswith("Run eCTD validation"))
    block_step = _find(lambda s: s["action"].startswith("Attempt to export"))
    revalidate_step = _find(lambda s: s["action"].startswith("Re-run eCTD"))
    success_step = _find(lambda s: s["action"].startswith("Export the transmissible"))

    val_rule_ids = [e.get("rule_id") for e in
                    (val_step or {}).get("response_excerpt", {}).get("errors", [])]

    print("=" * 72)
    print(f"TRACE: {trace['task']}  ({len(steps)} steps)")
    print(f"  written to: {TRACE_PATH}")
    print("-" * 72)
    print(f"  real validation report captured : "
          f"{'YES' if val_rule_ids else 'NO'}  (rule_ids: {val_rule_ids})")
    print(f"  real fail-closed export block   : "
          f"{'YES' if block_step and block_step['status'] == 409 else 'NO'}  "
          f"(HTTP {block_step['status'] if block_step else '?'})")
    print(f"  real successful export          : "
          f"{'YES' if success_step and success_step['status'] == 200 else 'NO'}  "
          f"(HTTP {success_step['status'] if success_step else '?'}, "
          f"{success_step['response_excerpt'].get('bytes') if success_step else '?'} bytes)")
    print("-" * 72)
    print("  Key 'what_the_user_sees' lines:")
    for label, s in (("VALIDATION REPORT", val_step),
                     ("EXPORT BLOCK", block_step),
                     ("RE-VALIDATION PASS", revalidate_step),
                     ("SUCCESSFUL EXPORT", success_step)):
        if s:
            print(f"\n  [{label}]  (step {s['step']}, HTTP {s['status']})")
            print(f"    {s['what_the_user_sees']}")
    print("=" * 72)


def main() -> int:
    try:
        trace = run_task()
    except AssertionError as exc:
        print(f"TRACE FAILED (unfaithful — refusing to write): {exc}",
              file=sys.stderr)
        return 1
    except Exception as exc:  # a real service failure IS a real result — but the
        # generator itself failing to complete the run is an error state.
        print(f"TRACE ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACE_PATH.write_text(json.dumps(trace, indent=2, ensure_ascii=False))
    summarize(trace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
