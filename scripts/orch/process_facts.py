#!/usr/bin/env python3
"""ADF Process Facts — attest the ENGINEERING DISCIPLINE a build was made with, and
seal it into the Proof of Build alongside the `render` and `policy` verdicts.

ADF's moat is verify-don't-trust: an app you can prove. This extends that moat to
PROCESS. "Built test-first (RED→GREEN)", "root cause documented before the fix",
"reviewed (spec + quality)", "verified (build·test·boot·render)" become recomputable,
sealed attestations — not prose claims.

The honesty contract (inherited from the streaming + render-facts work): a fact is
`proven` ONLY when re-derived from a durable on-disk artifact written at the real
event — never from the model asserting it, never from an optimistic in-memory flag.
The sealable summary is read back from disk at seal time (read_process_facts),
exactly like read_render_facts, so the proof can only ever seal what actually
happened. Facts that cannot be cheaply bound to such an artifact stay ADVISORY; only
artifact-backed facts may ever be ENFORCED (fail-closed, no seal).

Evidence lives under `.adf-process/` — a dotdir, so (like `.adf-visual/`) it is NOT
walked into the Merkle file leaves. The sealed SUMMARY folded into the build verdict
is the attestation; any digest the summary carries cross-binds its artifact.

  record_verification(app_root, stack, summary)   -> write verification evidence
  read_process_facts(app_root)                     -> sealable summary | None
  process_summary_line(verdict)                    -> human PROOF.md line | ''
  required_disciplines_met(verdict, names)         -> (ok, missing) for verify_proof
"""
import hashlib
import json
import os

PROCESS_SCHEMA = "adf-process/1"
PROCESS_DIR = ".adf-process"

# The gates each stack's verifier (verify_app) runs — and that must ALL pass for it
# to return ok. Listed structurally so a sealed build attests an explicit gate list
# rather than an implicit `verified: true` boolean.
_STACK_GATES = {
    "react": ["build", "test", "boot", "render"],
    "expo": ["typecheck", "test", "render"],
    "stdlib": ["test", "boot"],
}

# Human labels for the disciplines, for PROOF.md / verify_proof surfacing.
_FACT_LABELS = {
    "verification_evidence": "verified",
    "tdd_followed": "TDD (RED→GREEN)",
    "root_cause_documented": "root-cause documented",
    "review_passed": "reviewed",
    "design_options_considered": "design options",
}


def _evidence_dir(app_root):
    return os.path.join(app_root, PROCESS_DIR)


def _write(app_root, name, obj):
    """Persist one fact's durable evidence under `.adf-process/`. Best-effort — a
    recording failure never fails an otherwise-good build."""
    try:
        d = _evidence_dir(app_root)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
    except OSError:
        pass
    return obj


def _read(app_root, name):
    p = os.path.join(_evidence_dir(app_root), name)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# --- recorders (called at the REAL event during the pipeline) -------------------

def record_verification(app_root, stack, summary=""):
    """Record that the multi-stage verifier PASSED — the gates it ran for this stack.
    Called only after verify_app returned ok, so `proven` reflects a real pass (an
    unverified build never reaches here, and never seals)."""
    gates = _STACK_GATES.get(stack, ["build", "test"])
    return _write(app_root, "verification.json",
                  {"gates": gates, "summary": summary or "", "proven": True})


# --- the sealable summary (read back from disk at seal time) --------------------

def read_process_facts(app_root):
    """Assemble the canonical, sealable process summary from the durable evidence
    under `.adf-process/`, or None when no discipline was recorded. Read from disk
    (never from live flags) so the seal can only attest what truly happened — the
    read_render_facts pattern. Status is tri-state (proven|skipped|na), never a bare
    bool, so a skipped discipline seals honestly as `skipped`, never as silent pass.

    `enforced` names the artifact-backed disciplines treated as fail-closed; `blocked`
    is always empty in a returned (about-to-seal) summary, because a build that
    skipped an enforced discipline is blocked BEFORE sealing (the policy-gate path)."""
    facts = {}
    enforced = []

    ver = _read(app_root, "verification.json")
    if ver and ver.get("proven"):
        facts["verification_evidence"] = {
            "status": "proven", "gates": list(ver.get("gates") or [])}
        # verification_evidence is already effectively fail-closed: an unverified
        # build never reaches the seal. Naming it `enforced` makes that explicit.
        enforced.append("verification_evidence")

    # Phase 1+ facts (tdd_followed, root_cause_documented, review_passed,
    # design_options_considered) are read here as their recorders land.

    if not facts:
        return None
    return {
        "schema": PROCESS_SCHEMA,
        "facts": facts,
        "enforced": sorted(enforced),
        "blocked": [],
    }


# --- human surfacing (PROOF.md / verify_proof) ----------------------------------

def _fact_extra(key, fact):
    """The parenthetical detail for a proven fact, e.g. the gate list, or ''."""
    if key == "verification_evidence" and fact.get("gates"):
        return " (" + "·".join(fact["gates"]) + ")"
    if key == "root_cause_documented" and fact.get("heals"):
        return f" ({fact['heals']}×)"
    if key == "design_options_considered" and fact.get("n_options"):
        return f" ({fact['n_options']})"
    return ""


def process_summary_line(verdict):
    """A one-line human attestation of the disciplines a build was made with, for
    PROOF.md / verify_proof, or '' when none were recorded. Skips print honestly (⚠),
    never omitted-as-implied-pass; `na` (genuinely not applicable) facts are dropped."""
    proc = (verdict or {}).get("process")
    if not (proc and proc.get("facts")):
        return ""
    parts = []
    for key, fact in sorted(proc["facts"].items()):
        label = _FACT_LABELS.get(key, key)
        status = (fact or {}).get("status")
        if status == "proven":
            parts.append(f"✅ {label}{_fact_extra(key, fact)}")
        elif status == "skipped":
            parts.append(f"⚠ {label}: skipped")
    return "**Built WITH discipline:** " + "  ·  ".join(parts) if parts else ""


def required_disciplines_met(verdict, required):
    """For an auditor's `--require-discipline` check: (ok, missing) where `missing`
    lists the required disciplines NOT `proven` in the sealed verdict. Empty
    `required` => trivially ok (integrity-only, the default)."""
    required = list(required or [])
    if not required:
        return True, []
    facts = ((verdict or {}).get("process") or {}).get("facts") or {}
    missing = [r for r in required
               if (facts.get(r) or {}).get("status") != "proven"]
    return (not missing), sorted(missing)
