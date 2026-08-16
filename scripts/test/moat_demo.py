#!/usr/bin/env python3
"""The whole moat in one runnable proof — offline, no model, no network. Shows a
generated app that is PROVEN, GOVERNED, OFFLINE-capable, and OWNED: scaffold → seal
→ verify → policy → air-gapped → export → re-verify the EXPORTED copy independently.
This is the chain Lovable structurally cannot show.

    python3 scripts/test/moat_demo.py
"""
import os
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))

import agent_runner as ar          # noqa: E402
import proof_of_build              # noqa: E402
import policy_gate                 # noqa: E402
import offline_build              # noqa: E402
import export_app                  # noqa: E402


def main():
    checks = {}
    work = tempfile.mkdtemp(prefix="adf-moat-demo-")
    app = os.path.join(work, "apps", "kanban")
    os.makedirs(app)

    print("=== 1. Scaffold a real React+Vite+SQLite app ===")
    tpl = ar.template_dir(ROOT, ROOT, ar.STACK_REACT)
    ar.scaffold_app(app, tpl)
    checks["scaffolded"] = os.path.isfile(os.path.join(app, "package.json"))

    print("=== 2. PROVEN — seal + verify the Proof of Build (offline) ===")
    proof_of_build.seal_app(app, "kanban", "react-vite-sqlite",
                            "A kanban board", {"verified": True})
    proof_ok, _ = proof_of_build.verify_proof(app)
    checks["proven (VERIFIED)"] = proof_ok

    print("=== 3. GOVERNED — policy gate ===")
    pol = policy_gate.check_policy(app)
    checks["governed (policy compliant)"] = pol["ok"]

    print("=== 4. OFFLINE — air-gapped structural gate ===")
    checks["offline-capable"] = offline_build.check_offline(app)["ok"]

    print("=== 5. OWNED — export a portable, self-verifying zip ===")
    out = os.path.join(work, "kanban.zip")
    rep = export_app.export_app(app, out, audit_bundle=None, feature_id="kanban")
    checks["exported (portable zip)"] = rep["ok"] and os.path.isfile(out)

    print("=== 6. The EXPORTED copy re-verifies independently ===")
    extract = os.path.join(work, "unzipped")
    with zipfile.ZipFile(out) as z:
        z.extractall(extract)
    exported_app = os.path.join(extract, "app")
    reproof_ok, _ = proof_of_build.verify_proof(exported_app)
    checks["exported copy still VERIFIED"] = reproof_ok

    shutil.rmtree(work, ignore_errors=True)

    print("\n=== Result ===")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    ok = all(checks.values())
    print("\nGATE PASS: one generated app — PROVEN, GOVERNED, OFFLINE, and OWNED, "
          "re-verifiable offline even after export. The moat, end to end."
          if ok else "\nGATE FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
