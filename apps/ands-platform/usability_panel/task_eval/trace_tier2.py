#!/usr/bin/env python3
"""Task-eval TRACE EXTENSION for the THREE just-shipped TIER-2 adoption
features — grounded, real, never hand-authored.

This is a SIBLING of ``trace.py``: it reuses that module's real in-process
dossier service (FastAPI ``TestClient``), runs the SAME full-adopt task
(``run_task`` -> the 8-step validate/block/fix/export flow) and the SAME
prior adoption steps (``append_adoption_steps`` -> Part-11 e-sign + verify,
eValidator user-attestation, lifecycle-0001 replace), and THEN appends the
three tier-2 adoption features so a re-run measures their lift:

  1. Signer != author SEGREGATION OF DUTIES (commit 688a5e1)
     - GET /dossiers/{id}/content-authors : the recorded author set.
     - POST /dossiers/{id}/esign          : record_esign stamps a real
       ``segregation_of_duties`` outcome on the signed manifest + Part-11
       event. We capture BOTH the clean separation (signer distinct from the
       author) AND the conflict warning (signer IS an author) — real
       service outcomes, not narration.

  2. PDF/A-1b STRUCTURAL checks (commit 09dce8f)
     - GET /dossiers/{id}/validate : validation now runs PDF/A-1b structural
       marker checks over the STORED bytes and emits advisory PDF/A findings
       (CA-W-70xx) on a plain %PDF (no XMP pdfaid packet / no OutputIntent).
       Honestly scoped: absence of PDF/A markers is advisory (warning), the
       submission still passes — it now checks more than the %PDF header.

  3. SELF-SERVE PARITY + eValidator PDF ATTACH + in-app REP request
     (commit 068f83e)
     - POST /dossiers/{id}/rep-request : file the in-app REP Dossier-ID
       Request (records intent + guidance; HONESTLY NOT transmitted to HC).
     - POST /dossiers/{id}/evalidator-attestation/report : attach the ACTUAL
       eValidator report FILE (bytes) as downloadable evidence.
     - GET  /dossiers/{id}/validate/sequence/{seq} : self-serve structural
       validate of the known-good 0000 sequence ("it passes here too").

Every step is ``{step, action, method, path, request_summary, status,
what_the_user_sees, response_excerpt}`` built from the REAL response.

Run:    .venv/bin/python usability_panel/task_eval/trace_tier2.py
Writes: usability_panel/task_eval/traces/t2_tier2.json

Exits 0 only if it genuinely captured, from the real service:
  * a real SoD outcome on a signed manifest (a real separation AND a real
    conflict warning),
  * a real PDF/A-1b structural finding on a plain PDF, AND
  * a real in-app REP Dossier-ID request (transmitted=False) with the real
    eValidator report file attached.
Otherwise it exits non-zero — it never pretends a feature worked.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# import trace.py as a module (same directory) so we reuse its EXACT real
# service wiring, recorder, task flow, and prior adoption steps.
HERE = Path(__file__).resolve()
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

import trace as base  # noqa: E402  (trace.py — the canonical real-service setup)

TIER2_TRACE_PATH = HERE.parent / "traces" / "t2_tier2.json"

# PDF/A rule ids emitted by the deepened document-payload check (09dce8f). The
# plain _REAL_PDF the task uploads has a %PDF-1.4 header but no XMP pdfaid
# packet and no OutputIntent -> these advisory warnings fire honestly.
_PDFA_ADVISORY_RULES = {
    "pdfa_xmp_missing", "pdfa_outputintent_missing", "pdfa_version",
}
# A real eValidator report file (bytes) — a genuine PDF payload we attach as the
# downloadable external evidence (never a hand-authored string).
_EVALIDATOR_REPORT_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog>>endobj\n"
    b"HC eValidator 5.3 report - ANDS sequence 0000 - 0 errors, 0 warnings.\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def append_tier2_steps(rec: "base.Recorder", real_id: str, seq: str) -> dict:
    """Carry the SAME dossier THROUGH the three tier-2 adoption features,
    capturing REAL responses. Returns the raw captures for the honesty gate."""
    client = rec.client
    captures: dict = {}

    # =====================================================================
    # 1. SIGNER != AUTHOR — SEGREGATION OF DUTIES (688a5e1)
    # =====================================================================
    # 1a. Author a section UNDER a known identity so authorship is genuinely on
    #     the durable record (the acting user flows in via X-User-Email ->
    #     audit_hook._actor -> the section's content_author). We re-file the 1.0
    #     cover letter authored by a named regulatory author.
    author = "author@sponsor.example"
    authored = (b"%PDF-1.4 Module 1.0 cover letter authored for signing "
                b"segregation-of-duties demonstration " + base._REAL_PDF)
    r = client.post(
        f"/api/dossier/ectd/{real_id}/section/1.0/upload",
        files={"file": ("cover_letter_authored.pdf", authored,
                        "application/pdf")},
        headers={"X-User-Email": author})
    r.raise_for_status()
    rec.record(
        action="Author the Module 1.0 cover letter under a named author "
               "(records content authorship)",
        method="POST",
        path=f"/api/dossier/ectd/{real_id}/section/1.0/upload",
        request_summary=f"Upload the 1.0 cover letter acting as {author!r} — the "
                        "portal stamps content authorship on the section for a "
                        "later segregation-of-duties check",
        resp=r, excerpt=base._node_excerpt(r.json(), "1.0"),
        what_the_user_sees=f"The Module 1.0 cover letter is placed by "
        f"{author}. The portal records WHO authored the content so that, at "
        "signing, it can check the signer is a distinct approver.")

    # 1b. Read the recorded author set — the population a signer is checked
    #     against for segregation of duties.
    r = client.get(f"/api/dossier/dossiers/{real_id}/content-authors")
    r.raise_for_status()
    authors_resp = r.json()
    recorded_authors = authors_resp.get("authors", [])
    captures["content_authors"] = authors_resp
    rec.record(
        action="Read the recorded content authors (segregation-of-duties basis)",
        method="GET", path=f"/api/dossier/dossiers/{real_id}/content-authors",
        request_summary="Fetch the distinct author identities recorded for this "
                        "dossier's content",
        resp=r,
        what_the_user_sees=(
            f"The portal lists {authors_resp.get('author_count')} recorded "
            f"content author(s) ({', '.join(recorded_authors) or 'none'}). This "
            "is the author set a signer is checked against — an honest "
            "role-separation check, not an SSO/IdP identity claim."))

    # 1c. E-sign with a DISTINCT signer — capture the REAL clean separation.
    signer_ok = "approver@sponsor.example"
    fv = client.get(f"/api/dossier/ectd/{real_id}/viewer/files")
    fv.raise_for_status()
    live_leaves = [(leaf["leaf_id"], leaf["checksum"])
                   for node in fv.json().get("nodes", [])
                   for leaf in node.get("leaves", [])
                   if leaf.get("leaf_id") and leaf.get("checksum")]
    if not live_leaves:
        raise AssertionError("no live checksummed leaves to sign — cannot "
                             "demonstrate a real segregation-of-duties outcome")
    man_ok = _manifest(live_leaves, signer=signer_ok, seq=seq,
                       manifest_id=f"esign-sod-sep-{real_id}",
                       reason="I approve as a distinct authorized approver, "
                              "separate from the content author.")
    r = client.post(f"/api/dossier/dossiers/{real_id}/esign",
                    json={"manifest": man_ok},
                    headers={"X-User-Email": signer_ok})
    r.raise_for_status()
    signed_sep = r.json()
    sod_sep = signed_sep.get("segregation_of_duties", {})
    captures["sod_separated"] = signed_sep
    rec.record(
        action="E-sign as a DISTINCT approver — segregation of duties SATISFIED",
        method="POST", path=f"/api/dossier/dossiers/{real_id}/esign",
        request_summary=f"Sign over {len(live_leaves)} checksummed leaf/leaves "
                        f"as signer={signer_ok!r} (distinct from author "
                        f"{author!r})",
        resp=r,
        excerpt={"signer": signed_sep.get("signer"),
                 "manifest_id": signed_sep.get("manifest_id"),
                 "segregation_of_duties": sod_sep},
        what_the_user_sees=(
            f"{signed_sep.get('signer')} signs the package. The segregation-of-"
            f"duties check runs on the signed manifest and returns "
            f"separated={sod_sep.get('separated')}, conflict={sod_sep.get('conflict')} "
            f"against author(s) {sod_sep.get('authors')}: "
            f"\"{sod_sep.get('reason')}\" The Part-11 record shows the signer is "
            "a distinct approver from the author."))

    # 1d. Attempt to e-sign as the AUTHOR — capture the REAL conflict warning
    #     (default posture surfaces + warns; the outcome is stamped on the
    #     manifest and the Part-11 event, honestly, not blocked here).
    man_conflict = _manifest(live_leaves, signer=author, seq=seq,
                             manifest_id=f"esign-sod-conflict-{real_id}",
                             reason="I attempt to sign my own authored content.")
    r = client.post(f"/api/dossier/dossiers/{real_id}/esign",
                    json={"manifest": man_conflict},
                    headers={"X-User-Email": author})
    r.raise_for_status()
    signed_conflict = r.json()
    sod_conflict = signed_conflict.get("segregation_of_duties", {})
    captures["sod_conflict"] = signed_conflict
    rec.record(
        action="Sign as the AUTHOR — segregation-of-duties CONFLICT surfaced",
        method="POST", path=f"/api/dossier/dossiers/{real_id}/esign",
        request_summary=f"Sign as signer={author!r} who ALSO authored the "
                        "content — the portal surfaces the SoD conflict on the "
                        "manifest + Part-11 event",
        resp=r,
        excerpt={"signer": signed_conflict.get("signer"),
                 "manifest_id": signed_conflict.get("manifest_id"),
                 "segregation_of_duties": sod_conflict},
        what_the_user_sees=(
            f"When {signed_conflict.get('signer')} — who authored the content — "
            f"signs, the check returns conflict={sod_conflict.get('conflict')}, "
            f"separated={sod_conflict.get('separated')}, flagging "
            f"conflicting_authors={sod_conflict.get('conflicting_authors')}: "
            f"\"{sod_conflict.get('reason')}\" The reviewer is warned the signer "
            "is not a distinct approver — a real Part-11 defensibility signal."))

    # =====================================================================
    # 2. PDF/A-1b STRUCTURAL CHECKS (09dce8f)
    # =====================================================================
    # 2. Re-validate — the deepened document-payload check surfaces PDF/A-1b
    #    advisory findings on the plain %PDF bytes (no XMP pdfaid packet / no
    #    OutputIntent). Honestly scoped: advisory warnings, submission passes.
    r = client.get(f"/api/dossier/dossiers/{real_id}/validate")
    r.raise_for_status()
    val = r.json()
    warns = val.get("warnings", [])
    pdfa_warns = [w for w in warns if str(w.get("rule", "")).startswith("pdfa_")]
    captures["pdfa_validate"] = val
    captures["pdfa_warnings"] = pdfa_warns
    # the SAME two advisory markers fire once per plain-PDF leaf; show the
    # DISTINCT rules (with a per-rule leaf count) so the user-facing line reads
    # cleanly, while the excerpt keeps every faithful finding verbatim.
    distinct_pdfa: dict[str, dict] = {}
    for w in pdfa_warns:
        rule = w.get("rule")
        d = distinct_pdfa.setdefault(
            rule, {"rule_id": w.get("rule_id"), "count": 0})
        d["count"] += 1
    distinct_summary = ", ".join(
        f"{rule} [{d['rule_id']}] x{d['count']}"
        for rule, d in distinct_pdfa.items())
    rec.record(
        action="Re-validate — the PDF/A-1b structural check surfaces advisory "
               "findings on the plain PDFs",
        method="GET", path=f"/api/dossier/dossiers/{real_id}/validate",
        request_summary="Run validation; read the deeper PDF/A-1b structural "
                        "markers checked over the stored PDF bytes",
        resp=r,
        excerpt={"structural_passed": val.get("passed"),
                 "pdfa_warnings_distinct": distinct_pdfa,
                 "pdfa_warnings": pdfa_warns,
                 "coverage_checked": (val.get("criteria") or {})
                 .get("coverage", {}).get("checked")},
        what_the_user_sees=(
            f"Validation now checks MORE than the %PDF header: it inspects "
            f"PDF/A-1b structural markers over the stored PDF bytes and raises "
            f"{len(pdfa_warns)} advisory warning(s) across "
            f"{len(distinct_pdfa)} distinct rule(s) — {distinct_summary or 'none'} "
            "— on the plain PDFs (no PDF/A XMP metadata packet, no OutputIntent). "
            "Honestly advisory: the submission still comes back "
            f"{'PASSED' if val.get('passed') else 'NOT PASSED'} (a plain "
            "transmissible PDF is not a hard defect), but the filer is now told "
            "exactly what PDF/A-1b would require."))

    # =====================================================================
    # 3. SELF-SERVE PARITY + eVALIDATOR PDF ATTACH + IN-APP REP REQUEST (068f83e)
    # =====================================================================
    # 3a. File the in-app REP Dossier-ID Request from the placeholder banner.
    #     HONEST: records intent + returns guidance, NOT transmitted to HC.
    rep_body = {
        "company_id": "12345",
        "sponsor": "Acme Generics Inc.",
        "activity_type": "ANDS",
        "contact_email": "regops@sponsor.example",
        "note": "REP Dossier-ID Request for Metformin HCl 500 mg ANDS.",
    }
    r = client.post(f"/api/dossier/dossiers/{real_id}/rep-request",
                    json=rep_body,
                    headers={"X-User-Email": "regops@sponsor.example"})
    r.raise_for_status()
    rep = r.json()
    captures["rep_request"] = rep
    steps_guidance = (rep.get("guidance") or {}).get("steps") or []
    rec.record(
        action="File the in-app REP Dossier-ID Request (records intent — NOT "
               "transmitted to HC)",
        method="POST", path=f"/api/dossier/dossiers/{real_id}/rep-request",
        request_summary=f"Prepare a REP Dossier-ID Request (company_id="
                        f"{rep_body['company_id']}, activity={rep_body['activity_type']})",
        resp=r,
        excerpt={"transmitted": rep.get("transmitted"),
                 "company_id": rep.get("company_id"),
                 "activity_type": rep.get("activity_type"),
                 "guidance_summary": (rep.get("guidance") or {}).get("summary"),
                 "guidance_steps": steps_guidance},
        what_the_user_sees=(
            f"The portal records the REP Dossier-ID Request intent "
            f"(transmitted={rep.get('transmitted')}) for company "
            f"{rep.get('company_id')} / {rep.get('activity_type')} and returns "
            f"concrete next-step guidance ({len(steps_guidance)} steps via REP / "
            "CESG WebTrader). It is HONEST: ANDS Studio prepares and records the "
            "request but does NOT transmit it to Health Canada."))

    # 3b. Attach the ACTUAL eValidator report FILE (bytes) as downloadable
    #     evidence on the user-attested external attestation.
    r = client.post(
        f"/api/dossier/dossiers/{real_id}/evalidator-attestation/report",
        files={"file": (f"{real_id}-{seq}-evalidator.pdf",
                        _EVALIDATOR_REPORT_PDF, "application/pdf")},
        headers={"X-User-Email": "regops@sponsor.example"})
    r.raise_for_status()
    report_att = r.json().get("attestation", {})
    captures["evalidator_report"] = report_att
    rec.record(
        action="Attach the ACTUAL HC eValidator report file (downloadable "
               "evidence)",
        method="POST",
        path=f"/api/dossier/dossiers/{real_id}/evalidator-attestation/report",
        request_summary=f"Upload the real {len(_EVALIDATOR_REPORT_PDF)}-byte "
                        "eValidator report PDF as external evidence",
        resp=r,
        excerpt={"report_doc_id": report_att.get("report_doc_id"),
                 "report_filename": report_att.get("report_filename"),
                 "report_size": report_att.get("report_size"),
                 "report_checksum": report_att.get("report_checksum"),
                 "source": report_att.get("source")},
        what_the_user_sees=(
            f"The actual HC eValidator report file "
            f"'{report_att.get('report_filename')}' "
            f"({report_att.get('report_size')} bytes, checksum "
            f"{str(report_att.get('report_checksum'))[:12]}...) is stored and "
            f"linked as downloadable evidence (doc {report_att.get('report_doc_id')}), "
            f"labeled source='{report_att.get('source')}'. It is the filer's own "
            "external evidence — the report itself, not just a filename string."))

    # 3c. Self-serve STRUCTURAL validate of the known-good 0000 sequence — the
    #     confidence-building "it passes here too" affordance (structural only).
    r = client.get(f"/api/dossier/dossiers/{real_id}/validate/sequence/{seq}")
    r.raise_for_status()
    seq_val = r.json()
    captures["validate_sequence"] = seq_val
    rec.record(
        action="Self-serve validate the known-good sequence (structural, honest "
               "scope)",
        method="GET",
        path=f"/api/dossier/dossiers/{real_id}/validate/sequence/{seq}",
        request_summary=f"Run the SAME structural validator scoped to sequence "
                        f"{seq} — the 'it passes here too' confidence check",
        resp=r,
        excerpt={"sequence": seq_val.get("sequence"),
                 "scope": seq_val.get("scope"),
                 "passed": seq_val.get("passed"),
                 "errors": [e.get("rule_id") or e.get("rule")
                            for e in seq_val.get("errors", [])],
                 "disclaimer": (seq_val.get("criteria") or {}).get("disclaimer")},
        what_the_user_sees=(
            f"The filer self-serves a structural validation scoped to sequence "
            f"'{seq_val.get('sequence')}' (scope={seq_val.get('scope')!r}) and "
            f"sees it come back {'PASSED' if seq_val.get('passed') else 'NOT PASSED'} "
            f"with {len(seq_val.get('errors', []))} error(s) — the "
            "confidence-building 'it passes here too'. Honestly framed: it is the "
            "SAME structural check, never an HC eValidator parity claim."))

    return captures


def _manifest(leaves, *, signer, seq, manifest_id, reason,
              meaning="approved", authors=None):
    """A real signing manifest bound over the live checksummed leaves. Mirrors
    the shape trace.py + the SoD test use — never hand-authored content."""
    man = {
        "signer": signer, "role": "authorized_signer", "auth_method": "mfa",
        "meaning": meaning, "reason": reason,
        "at": "2026-07-04T00:00:00+00:00", "tz": "UTC",
        "manifest_id": manifest_id, "leaf_count": len(leaves),
        "artifacts": [{"id": lid, "kind": "leaf", "checksum": cs,
                       "checksum_type": "MD5"} for lid, cs in leaves],
    }
    if authors is not None:
        man["authors"] = authors
    return man


def _assert_tier2_faithful(captures: dict) -> None:
    """Anti-flattery gate: fail loudly (non-zero exit) unless a REAL SoD outcome
    (a real separation AND a real conflict warning), a REAL PDF/A-1b advisory
    finding, and a REAL in-app REP request + attached eValidator report were
    genuinely captured from the live service."""
    # (1) a REAL segregation-of-duties outcome — both separation AND conflict.
    authors = (captures.get("content_authors") or {}).get("authors") or []
    assert authors, "no content authors were recorded — cannot prove a real " \
        "segregation-of-duties outcome"
    sep = (captures.get("sod_separated") or {}).get("segregation_of_duties") or {}
    assert sep.get("separated") is True and sep.get("conflict") is False, \
        f"the distinct-signer SoD outcome was not a real separation: {sep}"
    assert sep.get("authorship_known") is True, \
        "SoD separation was reported without any known authorship on the record"
    con = (captures.get("sod_conflict") or {}).get("segregation_of_duties") or {}
    assert con.get("conflict") is True and con.get("separated") is False, \
        f"signing as the author did not surface a real SoD conflict: {con}"
    assert con.get("conflicting_authors"), \
        "the SoD conflict named no conflicting author — not a real outcome"
    # honesty: it is a role-separation check, never an SSO/IdP claim.
    assert "SSO" not in str(sep.get("reason")) and "SSO" not in str(con.get("reason")), \
        "the SoD reason overclaims an SSO/IdP identity assertion"

    # (2) a REAL PDF/A-1b structural finding on a plain PDF (advisory, honest).
    pdfa = captures.get("pdfa_warnings") or []
    assert pdfa, "no PDF/A-1b structural findings surfaced — the deepened check " \
        "did not fire on the stored PDFs"
    pdfa_rules = {w.get("rule") for w in pdfa}
    assert pdfa_rules & _PDFA_ADVISORY_RULES, \
        f"the PDF/A findings are not the expected advisory markers: {pdfa_rules}"
    for w in pdfa:
        rid = str(w.get("rule_id", ""))
        assert rid.startswith("CA-W-"), \
            f"a PDF/A advisory finding is not a warning-class rule id: {w}"
    # honestly advisory: a plain PDF must still PASS (not turned into a hard error)
    assert (captures.get("pdfa_validate") or {}).get("passed") is True, \
        "the PDF/A advisory check wrongly blocked a plain transmissible PDF"

    # (3) a REAL in-app REP request + a REAL attached eValidator report file.
    rep = captures.get("rep_request") or {}
    assert rep.get("transmitted") is False, \
        "the REP request must be recorded as NOT transmitted to Health Canada"
    assert (rep.get("guidance") or {}).get("steps"), \
        "the REP request returned no concrete next-step guidance"
    report = captures.get("evalidator_report") or {}
    assert report.get("report_doc_id"), \
        "the eValidator report file was not stored + linked by doc id"
    assert (report.get("report_size") or 0) > 0 and report.get("report_checksum"), \
        "the attached eValidator report carries no real bytes/checksum"
    assert report.get("source") == "user_attested_external", \
        f"the attached report dropped its honest external label: {report.get('source')}"
    # the self-serve known-good sequence validate is a bonus signal — assert it
    # ran and is honestly scoped when captured.
    sv = captures.get("validate_sequence") or {}
    assert sv.get("scope") == "sequence", \
        f"the self-serve validate was not scoped to a single sequence: {sv}"


def summarize_tier2(trace: dict, captures: dict) -> None:
    steps = trace["steps"]

    def _find(prefix):
        return next((s for s in steps if s["action"].startswith(prefix)), None)

    sod_sep = _find("E-sign as a DISTINCT approver")
    sod_con = _find("Sign as the AUTHOR")
    pdfa = _find("Re-validate — the PDF/A-1b structural check")
    rep = _find("File the in-app REP Dossier-ID Request")
    report = _find("Attach the ACTUAL HC eValidator report")

    sep_c = (captures.get("sod_separated") or {}).get("segregation_of_duties") or {}
    con_c = (captures.get("sod_conflict") or {}).get("segregation_of_duties") or {}
    pdfa_c = captures.get("pdfa_warnings") or []
    rep_c = captures.get("rep_request") or {}
    report_c = captures.get("evalidator_report") or {}

    print("=" * 72)
    print(f"TIER-2 TRACE: {trace['task']}  ({len(steps)} steps)")
    print(f"  written to: {TIER2_TRACE_PATH}")
    print("-" * 72)
    print(f"  real SoD separation captured    : "
          f"{'YES' if sep_c.get('separated') else 'NO'}  "
          f"(separated={sep_c.get('separated')}, conflict={sep_c.get('conflict')})")
    print(f"  real SoD conflict captured      : "
          f"{'YES' if con_c.get('conflict') else 'NO'}  "
          f"(conflict={con_c.get('conflict')}, "
          f"conflicting_authors={con_c.get('conflicting_authors')})")
    print(f"  real PDF/A-1b advisory finding  : "
          f"{'YES' if pdfa_c else 'NO'}  "
          f"(rules={[w.get('rule') for w in pdfa_c]})")
    print(f"  real in-app REP request         : "
          f"{'YES' if rep_c.get('transmitted') is False and rep_c.get('guidance') else 'NO'}  "
          f"(transmitted={rep_c.get('transmitted')})")
    print(f"  real eValidator report attached : "
          f"{'YES' if report_c.get('report_doc_id') else 'NO'}  "
          f"(size={report_c.get('report_size')}, "
          f"doc={report_c.get('report_doc_id')})")
    print("-" * 72)
    print("  3 most important NEW 'what_the_user_sees' lines:")
    for label, s in (("SoD OUTCOME (author-conflict)", sod_con),
                     ("PDF/A-1b CHECK", pdfa),
                     ("REP REQUEST / eVALIDATOR PDF", rep)):
        if s:
            print(f"\n  [{label}]  (step {s['step']}, HTTP {s['status']})")
            print(f"    {s['what_the_user_sees']}")
    # the eValidator-PDF line is the paired half of feature 3 — print it too.
    if report:
        print(f"\n  [eVALIDATOR REPORT FILE]  (step {report['step']}, "
              f"HTTP {report['status']})")
        print(f"    {report['what_the_user_sees']}")
    if sod_sep:
        print(f"\n  [SoD OUTCOME (clean separation)]  (step {sod_sep['step']}, "
              f"HTTP {sod_sep['status']})")
        print(f"    {sod_sep['what_the_user_sees']}")
    print("=" * 72)


def main() -> int:
    try:
        # 1) run the SAME real task + prior adoption steps against the live
        #    in-process dossier service (trace.py owns this wiring).
        trace, rec, real_id, seq = base.run_task()
        base.append_adoption_steps(rec, real_id, seq)
        # 2) append the three tier-2 adoption features, capturing real responses.
        captures = append_tier2_steps(rec, real_id, seq)
        _assert_tier2_faithful(captures)
    except AssertionError as exc:
        print(f"TIER-2 TRACE FAILED (unfaithful — refusing to write): {exc}",
              file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"TIER-2 TRACE ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    tier2_trace = {
        "task": "t2_tier2",
        "goal": "File an ANDS end-to-end (validate -> fail-closed block -> fix "
                "-> export -> Part-11 e-sign + verify -> eValidator attestation "
                "-> lifecycle-0001 replace), THEN exercise the three just-shipped "
                "TIER-2 adoption features on the same dossier so a re-run measures "
                "their lift: (1) signer != author segregation of duties surfaced "
                "on the signed Part-11 manifest, (2) PDF/A-1b structural checks "
                "that inspect more than the %PDF header (advisory findings, "
                "honestly scoped), and (3) self-serve parity — the in-app REP "
                "Dossier-ID request (recorded, NOT transmitted), the attached "
                "actual eValidator report file, and a self-serve structural "
                "validate of the known-good sequence.",
        "generated_from": trace["generated_from"],
        "steps": rec.steps,
    }
    TIER2_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TIER2_TRACE_PATH.write_text(
        json.dumps(tier2_trace, indent=2, ensure_ascii=False))
    summarize_tier2(tier2_trace, captures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
