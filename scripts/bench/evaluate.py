#!/usr/bin/env python3
"""Score a built app on the axes that matter — especially the GOVERNANCE axes
that are ADF's moat: is it PROVEN (Proof of Build verifies), GOVERNED (policy
compliant), and OFFLINE-capable? Each is computed for real by reusing the
canonical tools, deterministically and offline. Capability axes (tests-pass,
build time, cost) are recorded when a real build is run by run_bench --build."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))

_SKIP_DIRS = {"node_modules", "dist", ".git", "__pycache__", ".adf-context",
              ".adf-proof", ".adf-export", ".adf-exports"}
_SRC_EXT = (".py", ".mjs", ".js", ".ts", ".tsx", ".jsx", ".json", ".html",
            ".css", ".sql")


def count_source(app_dir):
    n = 0
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        n += sum(1 for f in files if f.endswith(_SRC_EXT))
    return n


def evaluate_app(repo_root, app_dir, spec_text=""):
    """Returns the per-app axis scorecard. Governance axes are real + offline."""
    proof_ok = policy_ok = offline_ok = False
    try:
        import proof_of_build
        proof_ok, _ = proof_of_build.verify_proof(app_dir)
    except Exception:
        proof_ok = False
    try:
        import policy_gate
        policy_ok = bool(policy_gate.check_policy(app_dir)["ok"])
    except Exception:
        policy_ok = False
    try:
        import offline_build
        offline_ok = bool(offline_build.check_offline(app_dir)["ok"])
    except Exception:
        offline_ok = False

    return {
        "app": os.path.basename(app_dir.rstrip("/")),
        "files": count_source(app_dir),
        "proof_ok": bool(proof_ok),
        "policy_ok": bool(policy_ok),
        "offline_ok": bool(offline_ok),
        "governed": bool(proof_ok and policy_ok and offline_ok),
    }


def summarize(results):
    return {
        "apps": len(results),
        "governed": sum(1 for r in results if r.get("governed")),
        "proven": sum(1 for r in results if r.get("proof_ok")),
        "compliant": sum(1 for r in results if r.get("policy_ok")),
        "offline": sum(1 for r in results if r.get("offline_ok")),
        "total_files": sum(r.get("files", 0) for r in results),
    }
