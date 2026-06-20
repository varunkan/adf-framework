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
# rather than an implicit `verified: true` boolean. Keys are the ACTUAL stack strings
# (agent_runner.STACK_*), not nicknames — a live build seals stack="react-vite-sqlite",
# so a "react" key here would silently fall to the default and under-report the gates.
_STACK_GATES = {
    "react-vite-sqlite": ["build", "test", "boot", "render"],
    "expo-rn": ["typecheck", "test", "render"],
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


def _strict(env=None):
    """Strict process mode: ADF_PROCESS=strict (all artifact-backed disciplines
    fail-closed) or ADF_TDD=strict (TDD specifically). Default off."""
    env = env if env is not None else os.environ
    return (env.get("ADF_PROCESS", "").strip().lower() == "strict"
            or env.get("ADF_TDD", "").strip().lower() == "strict")


def enforcement_block(process_obj):
    """The enforced disciplines that are NOT `proven` — the fail-closed signal,
    mirroring policy_gate.blocking_violations. A non-empty list means the build must
    be BLOCKED (no seal) so a sealed proof always means the enforced disciplines held.
    Empty/absent => nothing blocks (advisory)."""
    if not process_obj:
        return []
    facts = process_obj.get("facts") or {}
    return sorted(
        name for name in (process_obj.get("enforced") or [])
        if (facts.get(name) or {}).get("status") != "proven")


def _evidence_dir(app_root):
    return os.path.join(app_root, PROCESS_DIR)


def _current_nonce(env=None):
    """The current build's nonce (ADF_BUILD_NONCE, set once per turn by
    agent_runner.main). Stamped into every evidence file at write and checked at
    read, so a fact can only seal when re-derived from an artifact THIS build wrote:
    `.adf-process/` is per-app and is NOT cleared on a rebuild/edit of an existing
    feature id, so a stale prior-build artifact carries a different nonce and is
    treated as absent. Empty when unset (tests / non-runner callers) — write and read
    then both see '' and agree, so the binding is a no-op rather than a false stale."""
    env = env if env is not None else os.environ
    return (env.get("ADF_BUILD_NONCE") or "").strip()


def _write(app_root, name, obj, env=None):
    """Persist one fact's durable evidence under `.adf-process/`, stamped with the
    current build nonce so a later read can tell THIS build's evidence from a prior
    build's leftover. Best-effort — a recording failure never fails an otherwise-good
    build."""
    try:
        d = _evidence_dir(app_root)
        os.makedirs(d, exist_ok=True)
        stamped = dict(obj)
        stamped["_nonce"] = _current_nonce(env)
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(stamped, f, indent=2, sort_keys=True)
    except OSError:
        pass
    return obj


def _read(app_root, name, env=None):
    """Read one fact's evidence, or None when absent — INCLUDING when the artifact's
    nonce does not match the current build (a stale prior-build leftover), so every
    caller gets nonce-binding for free without re-checking at each site."""
    p = os.path.join(_evidence_dir(app_root), name)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return None
    # Treat as absent (so it can NEVER be re-derived into a `proven` fact): anything
    # that is not a dict (corrupt / tampered / non-dict JSON — also stops a callers'
    # `.get()` crash), OR an artifact whose nonce does not match THIS build (a stale
    # prior-build leftover, or a plant that cannot know the per-build nonce).
    if not isinstance(obj, dict) or obj.get("_nonce", "") != _current_nonce(env):
        return None
    return obj


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


def record_review(app_root, spec_ok, quality_ok):
    """Two-stage review (Phase 4) — composed from gates ADF already runs, not a new
    "an LLM said it reviewed it" claim: spec-compliance (the completion audit found no
    uncovered deliverables) + code-quality (the policy verdict passed). Both inputs are
    real, recomputable verdicts, so the fact is honest. `proven` only when both held."""
    return _write(app_root, "review.json", {
        "spec_compliance": bool(spec_ok),
        "code_quality": bool(quality_ok),
        "proven": bool(spec_ok and quality_ok),
    })


def record_design_options(app_root, options, chosen=None, rationale=""):
    """Design divergence (Phase 4, advisory) — ONLY honest when `options` is a real
    captured model output from a divergence step, never the model self-asserting "I
    considered 3 options" in its file output. Records the count + the chosen design;
    process_facts never fabricates this. `proven` requires ≥2 real options."""
    opts = list(options or [])
    return _write(app_root, "design.json", {
        "n_options": len(opts),
        "options": opts,
        "chosen": chosen,
        "rationale": rationale or "",
        "proven": len(opts) >= 2,
    })


# --- the sealable summary (read back from disk at seal time) --------------------

def read_process_facts(app_root, env=None):
    """Assemble the canonical, sealable process summary from the durable evidence
    under `.adf-process/`, or None when no discipline was recorded. Read from disk
    (never from live flags) so the seal can only attest what truly happened — the
    read_render_facts pattern. Status is tri-state (proven|skipped|na), never a bare
    bool, so a skipped discipline seals honestly as `skipped`, never as silent pass.

    `enforced` names the artifact-backed disciplines treated as fail-closed; `blocked`
    is always empty in a returned (about-to-seal) summary, because a build that
    skipped an enforced discipline is blocked BEFORE sealing (the policy-gate path)."""
    env = env if env is not None else os.environ
    facts = {}
    enforced = []

    ver = _read(app_root, "verification.json", env)
    if ver and ver.get("proven"):
        facts["verification_evidence"] = {
            "status": "proven", "gates": list(ver.get("gates") or [])}
        # verification_evidence is already effectively fail-closed: an unverified
        # build never reaches the seal. Naming it `enforced` makes that explicit.
        enforced.append("verification_evidence")

    # TDD red→green (Phase 1, ADF_TDD). `proven` ONLY when a real RED preceded a real
    # GREEN; a vacuous/absent RED seals honestly as `skipped`. Enforced (fail-closed)
    # only under strict mode, so the default path is unaffected.
    tdd = _read(app_root, "tdd.json", env)
    if tdd is not None:
        if tdd.get("proven"):
            facts["tdd_followed"] = {
                "status": "proven",
                "evidence": sha256_text(json.dumps(tdd, sort_keys=True))}
        else:
            reason = "vacuous tests" if tdd.get("vacuous") else (tdd.get("reason") or "")
            facts["tdd_followed"] = {"status": "skipped", "reason": reason}
        if _strict(env):
            enforced.append("tdd_followed")

    # Root cause documented before each self-heal fix (Phase 1, ADF_HEAL_DIAGNOSE).
    # Advisory: documenting a cause is hygiene; never block a green build for it.
    heal = _read(app_root, "heal.json", env)
    if heal and heal.get("heals"):
        causes = sorted({h.get("cause") for h in heal["heals"] if h.get("cause")})
        facts["root_cause_documented"] = {
            "status": "proven", "heals": len(heal["heals"]), "causes": causes}

    # Two-stage review (Phase 4) — composed from real verdicts. Advisory.
    review = _read(app_root, "review.json", env)
    if review is not None:
        facts["review_passed"] = {
            "status": "proven" if review.get("proven") else "skipped",
            "stages": ["spec_compliance", "code_quality"]}

    # Design divergence (Phase 4, advisory) — honest only from a real divergence step.
    design = _read(app_root, "design.json", env)
    if design is not None:
        facts["design_options_considered"] = {
            "status": "proven" if design.get("proven") else "skipped",
            "n_options": design.get("n_options", 0)}

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
    # Tolerate a MALFORMED sealed proof (verify_proof feeds us whatever is on disk,
    # which may be tampered): a non-dict process/facts/fact must degrade to '' or be
    # skipped, never crash the verifier (which has already printed VERIFIED/TAMPERED).
    proc = (verdict or {}).get("process")
    facts = proc.get("facts") if isinstance(proc, dict) else None
    if not isinstance(facts, dict) or not facts:
        return ""
    parts = []
    for key, fact in sorted(facts.items()):
        if not isinstance(fact, dict):
            continue
        label = _FACT_LABELS.get(key, key)
        status = fact.get("status")
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
    proc = (verdict or {}).get("process")
    facts = proc.get("facts") if isinstance(proc, dict) else None
    facts = facts if isinstance(facts, dict) else {}

    def _proven(r):
        f = facts.get(r)
        return isinstance(f, dict) and f.get("status") == "proven"
    missing = [r for r in required if not _proven(r)]
    return (not missing), sorted(missing)
