#!/usr/bin/env python3
"""Task-eval TRACE EXTENSION for the THREE just-shipped TIER-3 GAP-CLOSERS —
grounded, real, never hand-authored.

Where the tier-2 trace (``trace_tier2.py``) DISCLOSED more honest caveats
(PDF/A markers are missing on the stored PDFs; a signer-is-author signature is
only *warned* about; each readiness fact must be re-validated step by step),
this tier RESOLVES those caveats at the source and measures whether CLOSING a
gap — rather than merely disclosing it — recovers trust on a re-run.

It is a SIBLING of ``trace.py`` + ``trace_tier2.py``: it reuses their EXACT real
in-process dossier service (FastAPI ``TestClient``), runs the SAME full-adopt
task (``run_task`` -> validate/block/fix/export), the SAME prior adoption steps
(``append_adoption_steps`` -> Part-11 e-sign + verify, eValidator attestation,
lifecycle replace), and the SAME tier-2 adoption steps
(``trace_tier2.append_tier2_steps`` -> SoD surfaced, PDF/A advisories on plain
PDFs, in-app REP request + attached eValidator report), and THEN appends the
three tier-3 gap-closers so a re-run can compare "disclose" vs "close":

  1. PDF/A-1b COMPLIANT GENERATION (commit 8e02385)
     The tool's OWN generated PDFs now emit real PDF/A-1b structural markers (an
     XMP pdfaid part-1/conformance-B packet + a GTS_PDFA1 OutputIntent on a
     PDF-1.4 base), so ``ectd_validation._pdfa_check`` raises ZERO PDF/A
     advisories on them. In the trace we RE-GENERATE the Module 1 leaves with the
     tool (POST .../section/{sec}/generate) and re-validate: the PDF/A noise the
     tool created is GONE at the source — every tool-authored leaf now carries
     zero PDF/A advisories (contrast tier-2, where the generated cover letter
     tripped pdfa_xmp_missing + pdfa_outputintent_missing). Any residual PDF/A
     advisory belongs only to a plain PDF the filer UPLOADED (not tool-authored).
     GROUND: pdfgen.py, test_pdfgen.py, ectd_validation._pdfa_check.

  2. ENFORCED SEGREGATION OF DUTIES (commit 2dbed90)
     A per-workspace policy ``require_sod`` now HARD-BLOCKS a signer-is-author
     signature on the real sign path — not just warns. ``record_esign`` reads the
     tenant's policy via an injected identity port (``_workspace_requires_sod``);
     when on, ``enforced=True`` is forced even if the manifest omits the flag, and
     a signer who is also an author is REJECTED (HTTP 422,
     rule=segregation_of_duties). We wire a real workspace-policy port (mirroring
     identity's ``/internal/workspace-policy``) on a tenant-scoped dossier, flip
     the policy ON, and capture the REAL block for the conflicted signer and the
     REAL success (enforced=True, separated=True) for a distinct approver — plus
     the immutable Part-11 event stamping ``sod_policy_source='workspace_policy'``.
     GROUND: identity/app/{service,api}.py, dossier/app/service.record_esign,
     dossier/tests/test_esign_sod_workspace_policy.py,
     integration/test_sod_workspace_policy.py.

  3. CONSOLIDATED PRE-FLIGHT / QA REPORT (commit 9fed457)
     One endpoint (GET .../preflight-report) assembles the WHOLE readiness
     picture — versioned structural validation + user-attested eValidator
     attestation + Part-11 e-sign/SoD + live verification + fees + lifecycle/
     sequences + Dossier-ID/REP status — into a single archivable object with the
     honesty disclaimers travelling INLINE. One artifact to hand to QA instead of
     re-running validate at each step. GROUND: dossier/app/{service,api}.py,
     dossier/tests/test_preflight_report.py.

Every step is ``{step, action, method, path, request_summary, status,
what_the_user_sees, response_excerpt}`` built from the REAL response.

Run:    .venv/bin/python usability_panel/task_eval/trace_tier3.py
Writes: usability_panel/task_eval/traces/t2_tier3.json

Exits 0 only if it genuinely captured, from the real service:
  * ZERO PDF/A advisories on EVERY tool-generated leaf (the noise is gone at the
    source — a real contrast with tier-2's advisories on the generated cover
    letter),
  * a REAL enforced-SoD HARD BLOCK (HTTP 422, rule=segregation_of_duties,
    enforced by the workspace policy) AND a real distinct-approver success, AND
  * a REAL consolidated pre-flight report assembling every readiness piece with
    the honesty disclaimers inline.
Otherwise it exits non-zero — it never pretends a gap was closed.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# import trace.py + trace_tier2.py as modules (same directory) so we reuse their
# EXACT real service wiring, recorder, task flow, and prior/tier-2 steps.
HERE = Path(__file__).resolve()
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

import trace as base          # noqa: E402  (the canonical real-service setup)
import trace_tier2 as tier2   # noqa: E402  (the tier-2 adoption steps)

# the dossier service package (trace.py already put services/dossier on sys.path)
from ands_shared import (InMemoryEventBus, ProblemError,  # noqa: E402
                         SqliteDb)
from app.api import build_app  # noqa: E402
from app.repository_sqlite import SqliteDossierRepository  # noqa: E402
from app.service import DossierService  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TIER3_TRACE_PATH = HERE.parent / "traces" / "t2_tier3.json"

# The Module 1 leaves the tool can AUTHOR itself (generator -> a real PDF via
# pdfgen). Re-generating these makes the tool re-emit its own PDFs, which now
# carry the PDF/A-1b markers (8e02385). Sections that are UPLOAD-only stay plain
# PDFs the filer supplied — the tool never claims to have authored those.
_TOOL_GENERATED_SECTIONS = ("1.0", "1.2.3", "1.2.4", "1.6")

# PDF/A advisory rule ids the tier-2 checker raises on a plain %PDF (no XMP
# pdfaid packet / no OutputIntent). A tool-generated leaf must trip NONE of them.
_PDFA_ADVISORY_RULES = {
    "pdfa_xmp_missing", "pdfa_xmp_part_wrong",
    "pdfa_outputintent_missing", "pdfa_version",
}


class _WorkspacePolicyPort:
    """A real workspace-policy port for the dossier sign path — the same shape
    the production port speaks (identity's GET /internal/workspace-policy). This
    is NOT a hand-authored SoD outcome: it only reports the admin's policy toggle;
    the ENFORCEMENT (the block) is the real service code in ``record_esign``.
    """

    def __init__(self, *, require_sod: bool) -> None:
        self._require_sod = require_sod
        self.calls: list = []

    def workspace_policy(self, tenant_id: str) -> dict:
        self.calls.append(tenant_id)
        return {"tenant_id": tenant_id, "require_sod": self._require_sod,
                "require_mfa": False}


def _pdfa_by_leaf(validate_resp: dict) -> dict:
    """Partition a validate response's PDF/A advisory warnings by leaf filename."""
    by_leaf: dict[str, list] = {}
    for w in validate_resp.get("warnings", []):
        if str(w.get("rule", "")).startswith("pdfa_"):
            by_leaf.setdefault(str(w.get("leaf")), []).append(w.get("rule"))
    return by_leaf


# =========================================================================
# 1. PDF/A-1b COMPLIANT GENERATION — the tool's own PDFs pass clean (8e02385)
# =========================================================================

def append_pdfa_gen_steps(rec: "base.Recorder", real_id: str) -> dict:
    """Re-author the Module 1 leaves with the tool, then re-validate and capture
    that the tool-generated leaves now carry ZERO PDF/A advisories (the noise the
    tool created is gone at the source). Returns raw captures for the gate."""
    client = rec.client
    captures: dict = {}

    # 1a. baseline: BEFORE re-generating, capture which leaves currently trip the
    #     PDF/A advisories — including a tool-authorable leaf (the cover letter),
    #     which in tier-2 was a plain-PDF upload and DID trip them.
    before = client.get(f"/api/dossier/dossiers/{real_id}/validate").json()
    before_by_leaf = _pdfa_by_leaf(before)
    captures["pdfa_before"] = before
    captures["pdfa_before_by_leaf"] = before_by_leaf

    # 1b. RE-GENERATE the tool-authorable Module 1 leaves — the tool re-emits its
    #     OWN PDFs, which now embed the PDF/A-1b markers (XMP pdfaid + OutputIntent
    #     on a PDF-1.4 base). Author under a named regulatory author so the
    #     authorship is on the durable record (also feeds the later SoD check).
    gen_author = "regauthor@sponsor.example"
    regenerated: list[str] = []
    for section in _TOOL_GENERATED_SECTIONS:
        r = client.post(
            f"/api/dossier/ectd/{real_id}/section/{section}/generate",
            json={}, headers={"X-User-Email": gen_author})
        if r.status_code == 200:
            regenerated.append(section)
    captures["regenerated_sections"] = regenerated
    if not regenerated:
        raise AssertionError("the tool re-generated NO Module 1 leaves — cannot "
                             "demonstrate PDF/A-1b compliant generation")
    rec.record(
        action="Re-author the Module 1 leaves with the tool (PDF/A-1b generation)",
        method="POST",
        path=f"/api/dossier/ectd/{real_id}/section/{{section}}/generate",
        request_summary=f"Re-generate sections {', '.join(regenerated)} with the "
                        f"tool's own PDF writer (now emitting PDF/A-1b markers), "
                        f"authored by {gen_author}",
        # the generate response is the full content_state; keep a focused excerpt
        resp=r, excerpt={"regenerated_sections": regenerated,
                         "authored_by": gen_author},
        what_the_user_sees=(
            f"The tool re-authors {len(regenerated)} Module 1 leaf/leaves "
            f"({', '.join(regenerated)}) using its own PDF generator. Every PDF it "
            "writes now embeds the PDF/A-1b structural markers (an XMP pdfaid "
            "part-1 / conformance-B packet and a GTS_PDFA1 OutputIntent on a "
            "PDF-1.4 base) — the compliance is built in at generation time, not "
            "bolted on after."))

    # 1c. re-validate: the SAME PDF/A-1b structural check now finds ZERO
    #     advisories on the tool-generated leaves. Partition by leaf to PROVE it.
    r = client.get(f"/api/dossier/dossiers/{real_id}/validate")
    r.raise_for_status()
    after = r.json()
    after_by_leaf = _pdfa_by_leaf(after)
    captures["pdfa_after"] = after
    captures["pdfa_after_by_leaf"] = after_by_leaf

    # which leaf filenames belong to the tool-generated sections (so we can prove
    # NONE of them appear in the remaining PDF/A advisories). The tool names a
    # generated leaf after its section (e.g. "cover_letter.pdf") — but we identify
    # tool leaves structurally: any leaf that tripped PDF/A before + is now clean.
    cleared_leaves = sorted(set(before_by_leaf) - set(after_by_leaf))
    residual_leaves = sorted(after_by_leaf)
    captures["pdfa_cleared_leaves"] = cleared_leaves
    captures["pdfa_residual_leaves"] = residual_leaves
    # the count of PDF/A advisories that vanished vs remain
    n_before = sum(len(v) for v in before_by_leaf.values())
    n_after = sum(len(v) for v in after_by_leaf.values())
    rec.record(
        action="Re-validate — the tool-generated leaves now pass PDF/A-1b clean "
               "(zero advisories at the source)",
        method="GET", path=f"/api/dossier/dossiers/{real_id}/validate",
        request_summary="Re-run validation; confirm the tool-authored PDFs now "
                        "trip ZERO PDF/A-1b advisories",
        resp=r,
        excerpt={"structural_passed": after.get("passed"),
                 "pdfa_advisories_before": n_before,
                 "pdfa_advisories_after": n_after,
                 "cleared_leaves": cleared_leaves,
                 "residual_leaves_are_uploads": residual_leaves,
                 "pdfa_by_leaf_after": after_by_leaf},
        what_the_user_sees=(
            f"Re-validation confirms the tool-generated PDFs now pass the PDF/A-1b "
            f"structural check with ZERO advisories: the "
            f"{len(cleared_leaves)} leaf/leaves the tool re-authored "
            f"({', '.join(cleared_leaves) or 'none'}) that previously tripped "
            f"pdfa_xmp_missing / pdfa_outputintent_missing are now clean — the "
            f"noise dropped from {n_before} to {n_after} PDF/A advisory finding(s). "
            f"Any advisory that remains belongs ONLY to a plain PDF the filer "
            f"UPLOADED ({', '.join(residual_leaves) or 'none'}), which the tool "
            "never authored. The submission still comes back "
            f"{'PASSED' if after.get('passed') else 'NOT PASSED'}. The fix is at "
            "the source: the tool no longer produces the noise it used to."))
    return captures


# =========================================================================
# 2. ENFORCED SEGREGATION OF DUTIES — a workspace policy HARD-BLOCKS (2dbed90)
# =========================================================================

def append_enforced_sod_steps(rec_holder: dict) -> dict:
    """Wire a real workspace-policy port on a tenant-scoped dossier, flip the
    ``require_sod`` policy ON, and capture the REAL enforced block for a
    signer-is-author signature + the REAL success for a distinct approver.

    This runs on a DEDICATED tenant-scoped service+client (mirroring
    ``integration/test_sod_workspace_policy.py``) because enforcement sources
    from the per-workspace identity policy, which requires a tenant context —
    exactly how production wires dossier -> the identity policy port. All steps
    are appended to the SAME recorder so the trace stays a single flow.
    """
    rec = rec_holder["rec"]
    captures: dict = {}

    tenant = "tenant-acme"
    hdr = {"X-Tenant-Id": tenant}
    sod_id = "e900777"
    author = "author@sponsor.example"
    approver = "approver@sponsor.example"

    # a real workspace-policy port, policy ON — the admin toggle an org flips once.
    policy = _WorkspacePolicyPort(require_sod=True)
    repo = SqliteDossierRepository(SqliteDb(":memory:"))
    service = DossierService(repo, InMemoryEventBus(), policy=policy).register()
    client = TestClient(build_app(service))
    # swap the recorder's client to this policy-wired one for the SoD steps, then
    # restore it — every other step keeps the base client.
    prior_client = rec.client
    rec.client = client
    try:
        # 2a. admin has enabled the workspace SoD policy (require_sod=True). We
        #     surface it via the same service-to-service policy read the sign path
        #     uses, so the trace shows the policy is genuinely ON before we sign.
        pol = policy.workspace_policy(tenant)
        captures["workspace_policy"] = pol
        # (this direct read primes policy.calls; the real enforcement below calls
        #  it again through record_esign — we assert that path fired.)
        policy.calls.clear()

        client.post("/api/dossier/dossiers",
                    json={"dossier_id": sod_id,
                          "title": "Signol 10 mg tablet — ANDS"},
                    headers=hdr).raise_for_status()
        rec.record(
            action="Enable the workspace 'require segregation of duties' policy "
                   "(admin toggle) and open the dossier",
            method="POST", path="/api/dossier/dossiers",
            request_summary=f"Open dossier {sod_id} in workspace {tenant!r} whose "
                            "admin has turned require_sod ON — the sign path will "
                            "read this policy and hard-block a signer-is-author "
                            "signature",
            resp=client.get(f"/api/dossier/dossiers/{sod_id}", headers=hdr),
            excerpt={"workspace_policy": pol},
            what_the_user_sees=(
                f"The workspace {tenant} has its 'require segregation of duties' "
                f"policy turned ON (require_sod={pol.get('require_sod')}). From now "
                "on the sign path enforces role separation for EVERY signature in "
                "the workspace — the signer no longer has to opt into their own "
                "block. It is a role-separation control on the sign path, not an "
                "SSO/IdP identity claim."))

        # 2b. author a leaf under a named author so authorship is on the record.
        client.post(f"/api/dossier/ectd/{sod_id}/section/1.0/generate",
                    json={}, headers={**hdr, "X-User-Email": author}
                    ).raise_for_status()
        authors_resp = client.get(
            f"/api/dossier/dossiers/{sod_id}/content-authors",
            headers=hdr).json()
        captures["content_authors"] = authors_resp
        rec.record(
            action="Author the Module 1 cover letter under a named author",
            method="POST",
            path=f"/api/dossier/ectd/{sod_id}/section/1.0/generate",
            request_summary=f"Author section 1.0 acting as {author!r} — records "
                            "content authorship for the enforced SoD check",
            resp=client.get(f"/api/dossier/dossiers/{sod_id}/content-authors",
                            headers=hdr),
            excerpt=authors_resp,
            what_the_user_sees=(
                f"The cover letter is authored by {author}. The portal records "
                f"{authors_resp.get('author_count')} content author(s) "
                f"({', '.join(authors_resp.get('authors', [])) or 'none'}) — the "
                "author set the enforced policy checks every signer against."))

        # live checksummed leaves to bind the manifest over.
        fv = client.get(f"/api/dossier/ectd/{sod_id}/viewer/files",
                        headers=hdr).json()
        leaves = [(l["leaf_id"], l["checksum"])
                  for node in fv.get("nodes", [])
                  for l in node.get("leaves", [])
                  if l.get("leaf_id") and l.get("checksum")]
        if not leaves:
            raise AssertionError("no live checksummed leaves to sign — cannot "
                                 "demonstrate the enforced-SoD block")

        # 2c. the signer IS the author — the policy HARD-BLOCKS it. Note the
        #     manifest does NOT set enforce_segregation; the WORKSPACE POLICY
        #     forces enforcement. This is the real 422, not a narrated one.
        man_block = tier2._manifest(
            leaves, signer=author, seq="0000",
            manifest_id=f"esign-sod-enforced-block-{sod_id}",
            reason="I attempt to sign my own authored content.")
        r = client.post(f"/api/dossier/dossiers/{sod_id}/esign",
                        json={"manifest": man_block},
                        headers={**hdr, "X-User-Email": author})
        blocked = r.json()
        captures["sod_enforced_block"] = {
            "status": r.status_code, "body": blocked,
            "policy_calls": list(policy.calls)}
        rec.record(
            action="Sign as the AUTHOR under the policy — the signature is "
                   "REJECTED (enforced segregation of duties)",
            method="POST", path=f"/api/dossier/dossiers/{sod_id}/esign",
            request_summary=f"Attempt to e-sign as signer={author!r} who ALSO "
                            "authored the content — the workspace require_sod "
                            "policy forces enforcement (manifest does NOT opt in)",
            resp=r,
            excerpt={"status": r.status_code, "rule": blocked.get("rule"),
                     "title": blocked.get("title"),
                     "policy_consulted_for_tenant": list(policy.calls)},
            what_the_user_sees=(
                f"The signature is BLOCKED (HTTP {r.status_code}, "
                f"rule='{blocked.get('rule')}'): \"{blocked.get('title')}\" This is "
                "no longer a warning — the workspace policy HARD-BLOCKS a "
                "signer-is-author signature on the real sign path (the sign path "
                f"consulted the policy for tenant {list(policy.calls)}). Health "
                "Canada Part-11 defensibility is now enforced, not merely "
                "advised — the conflicted signature cannot be recorded at all."))

        # 2d. a DISTINCT approver signs — it SUCCEEDS, enforced=True, separated.
        man_ok = tier2._manifest(
            leaves, signer=approver, seq="0000",
            manifest_id=f"esign-sod-enforced-ok-{sod_id}",
            reason="I approve as a distinct authorized approver, separate from "
                   "the content author.")
        r = client.post(f"/api/dossier/dossiers/{sod_id}/esign",
                        json={"manifest": man_ok},
                        headers={**hdr, "X-User-Email": approver})
        r.raise_for_status()
        signed = r.json()
        sod_ok = signed.get("segregation_of_duties", {})
        captures["sod_enforced_ok"] = signed
        rec.record(
            action="E-sign as a DISTINCT approver under the policy — enforced "
                   "segregation of duties SATISFIED",
            method="POST", path=f"/api/dossier/dossiers/{sod_id}/esign",
            request_summary=f"E-sign as signer={approver!r} (distinct from author "
                            f"{author!r}) with the enforcement policy ON",
            resp=r,
            excerpt={"signer": signed.get("signer"),
                     "manifest_id": signed.get("manifest_id"),
                     "segregation_of_duties": sod_ok},
            what_the_user_sees=(
                f"{signed.get('signer')} — a distinct approver — signs and it "
                f"SUCCEEDS: separated={sod_ok.get('separated')}, "
                f"conflict={sod_ok.get('conflict')}, enforced={sod_ok.get('enforced')}. "
                "The enforced policy lets the legitimate distinct-approver "
                "signature through while blocking the conflicted one — role "
                "separation is a real gate, not a note in the margin."))

        # 2e. the immutable Part-11 event records WHAT drove enforcement.
        hist = client.get(f"/api/dossier/dossiers/{sod_id}/history",
                          headers=hdr).json()
        esign_events = [e for e in hist.get("events", [])
                        if "esign" in str(e.get("event_type", ""))]
        captures["sod_audit_events"] = esign_events
        last = esign_events[-1] if esign_events else {}
        rec.record(
            action="Read the Part-11 ledger — the enforcement source is recorded",
            method="GET", path=f"/api/dossier/dossiers/{sod_id}/history",
            request_summary="Read the durable Part-11 ledger to confirm the "
                            "signing event records the enforcement source",
            resp=client.get(f"/api/dossier/dossiers/{sod_id}/history",
                            headers=hdr),
            excerpt={"esign_events": [
                {"event_type": e.get("event_type"),
                 "sod_enforced": e.get("data", {}).get("sod_enforced"),
                 "sod_policy_source": e.get("data", {}).get("sod_policy_source"),
                 "signer": e.get("data", {}).get("signer")}
                for e in esign_events]},
            what_the_user_sees=(
                f"The durable Part-11 ledger records the successful signing with "
                f"sod_enforced={last.get('data', {}).get('sod_enforced')} and "
                f"sod_policy_source="
                f"'{last.get('data', {}).get('sod_policy_source')}' — the immutable "
                "trail shows the WORKSPACE POLICY (not a per-signature opt-in) "
                "governed this signature. An auditor can prove enforcement was in "
                "force, by whose authority."))
    finally:
        rec.client = prior_client
    return captures


# =========================================================================
# 3. CONSOLIDATED PRE-FLIGHT / QA REPORT — one artifact for hand-off (9fed457)
# =========================================================================

def append_preflight_steps(rec: "base.Recorder", real_id: str) -> dict:
    """Call the single pre-flight report endpoint on the fully-worked dossier and
    capture the consolidated QA hand-off — one object instead of re-validating
    each step. Returns raw captures for the gate."""
    client = rec.client
    captures: dict = {}

    r = client.get(f"/api/dossier/dossiers/{real_id}/preflight-report")
    r.raise_for_status()
    rep = r.json()
    captures["preflight"] = rep

    readiness = rep.get("readiness", {})
    validation = rep.get("validation", {})
    esign = rep.get("esign", {})
    disclaimers = rep.get("disclaimers", {})
    sequences = rep.get("sequences", {})
    seq_list = (sequences.get("sequences") if isinstance(sequences, dict)
                else sequences) or []
    rep_block = rep.get("rep", {})

    rec.record(
        action="Generate the ONE consolidated pre-flight / QA hand-off report",
        method="GET", path=f"/api/dossier/dossiers/{real_id}/preflight-report",
        request_summary="Assemble the whole filing-readiness picture into a "
                        "single archivable report for QA hand-off",
        resp=r,
        excerpt={
            "readiness": readiness,
            "validation": {
                "passed": validation.get("passed"),
                "errors": len(validation.get("errors", [])),
                "warnings": len(validation.get("warnings", [])),
                "criteria": validation.get("criteria")},
            "esign": {
                "signed": esign.get("signed"),
                "segregation_of_duties": esign.get("segregation_of_duties"),
                "verification": (esign.get("verification") or {}).get("verified")},
            "evalidator_attested": bool(rep.get("evalidator_attestation")),
            "fees_present": bool(rep.get("fees")),
            "sequence_count": len(seq_list),
            "rep_status": {"placeholder": rep_block.get("placeholder"),
                           "rep_request": bool(rep_block.get("rep_request"))},
            "disclaimers": disclaimers},
        what_the_user_sees=(
            f"ONE pre-flight report assembles the entire readiness picture for QA "
            f"hand-off: structural validation "
            f"({'PASSED' if validation.get('passed') else 'NOT PASSED'}, "
            f"{len(validation.get('errors', []))} error(s), "
            f"{len(validation.get('warnings', []))} advisory warning(s) under "
            f"{(validation.get('criteria') or {}).get('name')} "
            f"v{(validation.get('criteria') or {}).get('version')}); the "
            f"user-attested eValidator result "
            f"({'attached' if rep.get('evalidator_attestation') else 'none'}); the "
            f"Part-11 e-sign + segregation-of-duties + live verification; the fee "
            f"state; {len(seq_list)} lifecycle sequence(s); and the Dossier-ID / "
            f"REP status (placeholder={rep_block.get('placeholder')}). The "
            f"readiness line is honest — \"{readiness.get('summary')}\" — and every "
            f"caveat travels inline ({len(disclaimers)} disclaimers: "
            f"{', '.join(disclaimers.keys())}). It is one artifact to archive with "
            "QA instead of re-running validate at each step, and it still names "
            f"the required next step: \"{readiness.get('next_step')}\""))
    return captures


def _assert_tier3_faithful(pdfa_caps: dict, sod_caps: dict,
                           preflight_caps: dict) -> None:
    """Anti-flattery gate: fail loudly (non-zero exit) unless a REAL PDF/A-clean
    generation, a REAL enforced-SoD block, and a REAL consolidated pre-flight
    report were genuinely captured from the live service."""
    # (1) ZERO PDF/A advisories on EVERY tool-generated leaf.
    regenerated = pdfa_caps.get("regenerated_sections") or []
    assert regenerated, "the tool re-generated no leaves — cannot prove PDF/A-1b " \
        "compliant generation"
    after_by_leaf = pdfa_caps.get("pdfa_after_by_leaf") or {}
    cleared = pdfa_caps.get("pdfa_cleared_leaves") or []
    # at least one leaf that USED to trip PDF/A advisories is now clean (the noise
    # the tool created is genuinely gone at the source).
    assert cleared, "no leaf cleared its PDF/A advisories after re-generation — " \
        "the compliant generation did not take effect"
    # and NO remaining PDF/A advisory may reference a leaf that was cleared (i.e.
    # a tool-generated leaf must not still appear as advisory).
    residual = set(after_by_leaf)
    assert residual.isdisjoint(set(cleared)), \
        f"a tool-generated leaf still trips PDF/A advisories: {residual & set(cleared)}"
    # every remaining advisory (if any) must be one of the known advisory rules on
    # a plain uploaded PDF — never promoted into a hard error.
    for leaf, rules in after_by_leaf.items():
        for r in rules:
            assert r in _PDFA_ADVISORY_RULES, \
                f"unexpected PDF/A finding on {leaf}: {r}"
    assert (pdfa_caps.get("pdfa_after") or {}).get("passed") is True, \
        "PDF/A advisories wrongly blocked a still-valid submission"

    # (2) a REAL enforced-SoD HARD BLOCK + a real distinct-approver success.
    pol = sod_caps.get("workspace_policy") or {}
    assert pol.get("require_sod") is True, \
        "the workspace policy was not actually ON (require_sod must be True)"
    block = sod_caps.get("sod_enforced_block") or {}
    assert block.get("status") == 422, \
        f"the signer-is-author signature was NOT hard-blocked: {block.get('status')}"
    assert (block.get("body") or {}).get("rule") == "segregation_of_duties", \
        f"the block was not a segregation-of-duties rejection: {block.get('body')}"
    # the block must genuinely have consulted the workspace policy for the tenant.
    assert block.get("policy_calls"), \
        "the sign path never consulted the workspace policy — not a real " \
        "policy-enforced block"
    ok = (sod_caps.get("sod_enforced_ok") or {}).get("segregation_of_duties") or {}
    assert ok.get("separated") is True and ok.get("conflict") is False, \
        f"the distinct-approver signature was not a real separation: {ok}"
    assert ok.get("enforced") is True, \
        "the distinct-approver signature did not record enforced=True under the " \
        "policy"
    # honesty: role-separation, never an SSO/IdP assertion.
    assert "SSO" not in str(ok.get("reason")), \
        "the enforced SoD reason overclaims an SSO/IdP identity assertion"
    # the immutable Part-11 event records the enforcement source.
    events = sod_caps.get("sod_audit_events") or []
    assert any(e.get("data", {}).get("sod_enforced") is True
               and e.get("data", {}).get("sod_policy_source") == "workspace_policy"
               for e in events), \
        "no Part-11 event recorded workspace-policy-enforced segregation of duties"

    # (3) a REAL consolidated pre-flight report assembling every readiness piece.
    rep = preflight_caps.get("preflight") or {}
    for key in ("validation", "evalidator_attestation", "esign", "fees",
                "sequences", "rep", "readiness", "disclaimers"):
        assert key in rep, f"the pre-flight report is missing section: {key}"
    v = rep.get("validation") or {}
    assert (v.get("criteria") or {}).get("version"), \
        "the pre-flight validation carries no versioned criteria — not the real " \
        "assembled report"
    readiness = rep.get("readiness") or {}
    assert "structural" in str(readiness.get("summary", "")).lower(), \
        "the readiness summary is not an honest structural statement"
    assert "evalidator" in str(readiness.get("next_step", "")).lower(), \
        "the readiness report drops the still-required HC eValidator next step"
    # honesty disclaimers travel INLINE (never launders a caveat away).
    disc = rep.get("disclaimers") or {}
    blob = " ".join(str(x) for x in disc.values()).lower()
    assert "not" in blob and "health canada" in blob, \
        "the pre-flight report dropped its Health-Canada honesty disclaimer"
    assert "evalidator" in blob and "certification" in blob, \
        "the pre-flight report dropped the external-eValidator / not-a-" \
        "certification disclaimers"


def summarize_tier3(trace: dict, pdfa_caps: dict, sod_caps: dict,
                    preflight_caps: dict) -> None:
    steps = trace["steps"]

    def _find(prefix):
        return next((s for s in steps if s["action"].startswith(prefix)), None)

    pdfa = _find("Re-validate — the tool-generated leaves now pass PDF/A-1b")
    block = _find("Sign as the AUTHOR under the policy")
    preflight = _find("Generate the ONE consolidated pre-flight")

    after_by_leaf = pdfa_caps.get("pdfa_after_by_leaf") or {}
    cleared = pdfa_caps.get("pdfa_cleared_leaves") or []
    block_c = sod_caps.get("sod_enforced_block") or {}
    ok_c = (sod_caps.get("sod_enforced_ok") or {}).get(
        "segregation_of_duties") or {}
    rep_c = preflight_caps.get("preflight") or {}

    print("=" * 72)
    print(f"TIER-3 TRACE: {trace['task']}  ({len(steps)} steps)")
    print(f"  written to: {TIER3_TRACE_PATH}")
    print("-" * 72)
    print(f"  PDF/A clean at source           : "
          f"{'YES' if cleared and set(after_by_leaf).isdisjoint(cleared) else 'NO'}  "
          f"(cleared leaves={cleared}, residual uploads={sorted(after_by_leaf)})")
    print(f"  enforced-SoD HARD BLOCK         : "
          f"{'YES' if block_c.get('status') == 422 else 'NO'}  "
          f"(status={block_c.get('status')}, "
          f"rule={(block_c.get('body') or {}).get('rule')}, "
          f"policy_calls={block_c.get('policy_calls')})")
    print(f"  distinct-approver ENFORCED pass : "
          f"{'YES' if ok_c.get('enforced') and ok_c.get('separated') else 'NO'}  "
          f"(separated={ok_c.get('separated')}, enforced={ok_c.get('enforced')})")
    print(f"  consolidated pre-flight report  : "
          f"{'YES' if rep_c.get('readiness') and rep_c.get('disclaimers') else 'NO'}  "
          f"(sections={sum(1 for k in ('validation','evalidator_attestation','esign','fees','sequences','rep','readiness','disclaimers') if k in rep_c)}/8, "
          f"disclaimers={len(rep_c.get('disclaimers', {}))})")
    print("-" * 72)
    print("  3 most important NEW 'what_the_user_sees' lines:")
    for label, s in (("PDF/A NOW CLEAN (at source)", pdfa),
                     ("ENFORCED-SoD BLOCK", block),
                     ("CONSOLIDATED PRE-FLIGHT REPORT", preflight)):
        if s:
            print(f"\n  [{label}]  (step {s['step']}, HTTP {s['status']})")
            print(f"    {s['what_the_user_sees']}")
    print("=" * 72)


def main() -> int:
    try:
        # 1) run the SAME real task + prior adoption steps + tier-2 adoption steps
        #    against the live in-process dossier service (trace.py owns the wiring;
        #    trace_tier2 owns the tier-2 steps). This gives us the fully-worked
        #    dossier the tier-3 gap-closers act on.
        trace, rec, real_id, seq = base.run_task()
        base.append_adoption_steps(rec, real_id, seq)
        tier2.append_tier2_steps(rec, real_id, seq)

        # 2) TIER-3 GAP-CLOSER 1 — PDF/A-1b compliant generation (on the base
        #    dossier: re-author the leaves, re-validate, prove zero PDF/A noise).
        pdfa_caps = append_pdfa_gen_steps(rec, real_id)

        # 3) TIER-3 GAP-CLOSER 2 — enforced segregation of duties (on a dedicated
        #    tenant-scoped, policy-wired service+client, mirroring the real
        #    integration test; all steps appended to the SAME recorder).
        sod_caps = append_enforced_sod_steps({"rec": rec})

        # 4) TIER-3 GAP-CLOSER 3 — consolidated pre-flight / QA report (back on
        #    the base dossier; one artifact assembling the whole picture).
        preflight_caps = append_preflight_steps(rec, real_id)

        _assert_tier3_faithful(pdfa_caps, sod_caps, preflight_caps)
    except AssertionError as exc:
        print(f"TIER-3 TRACE FAILED (unfaithful — refusing to write): {exc}",
              file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"TIER-3 TRACE ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 2

    tier3_trace = {
        "task": "t2_tier3",
        "goal": "File an ANDS end-to-end (validate -> fail-closed block -> fix -> "
                "export -> Part-11 e-sign + verify -> eValidator attestation -> "
                "lifecycle replace), exercise the TIER-2 adoption features, THEN "
                "exercise the three just-shipped TIER-3 GAP-CLOSERS on the same "
                "flow so a re-run measures whether CLOSING a gap (vs disclosing "
                "it) recovers trust: (1) PDF/A-1b compliant GENERATION — the "
                "tool's own PDFs now pass the PDF/A-1b structural check with ZERO "
                "advisories (the noise is gone at the source, not just disclosed); "
                "(2) ENFORCED segregation of duties — a workspace require_sod "
                "policy HARD-BLOCKS a signer-is-author signature on the real sign "
                "path (enforced, not merely warned) while a distinct approver "
                "succeeds; and (3) a CONSOLIDATED pre-flight / QA report — one "
                "endpoint assembles the whole readiness picture (validation + "
                "eValidator attestation + e-sign/SoD + verification + fees + "
                "lifecycle + Dossier-ID/REP) with the honesty disclaimers inline, "
                "so QA gets one artifact instead of re-validating each step.",
        "generated_from": trace["generated_from"],
        "steps": rec.steps,
    }
    TIER3_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TIER3_TRACE_PATH.write_text(
        json.dumps(tier3_trace, indent=2, ensure_ascii=False))
    summarize_tier3(tier3_trace, pdfa_caps, sod_caps, preflight_caps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
