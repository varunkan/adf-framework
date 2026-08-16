#!/usr/bin/env python3
"""The magic, demonstrated: generate a REAL React+Vite+SQLite app through ADF,
seal a Proof of Build into it, verify it offline (VERIFIED), then tamper a single
byte and watch the seal turn TAMPERED and name the exact file.

This is the wedge Lovable structurally cannot serve: an app you can *prove*.

    python3 scripts/test/proof_of_build_demo.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REAL_TPL = os.path.join(ROOT, "templates", "react-vite-sqlite")

os.environ["ADF_STACK"] = "react-vite-sqlite"
os.environ["ADF_HEADROOM"] = "0"
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))
import agent_runner as ar  # noqa: E402
import proof_of_build as pob  # noqa: E402

FID = "notes"
# Reuse the e2e's proven canned feature so the demo is deterministic + offline.
sys.path.insert(0, os.path.join(ROOT, "scripts", "test"))
from e2e_react_app import BUILD_OUTPUT  # noqa: E402


def _verify_cli(app_dir):
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "orch", "verify_proof.py"), app_dir],
        capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def main():
    tmp = tempfile.mkdtemp(prefix="adf-proof-demo-")
    os.environ["ORCH_REPO_ROOT"] = tmp
    shutil.copytree(
        REAL_TPL, os.path.join(tmp, "templates", "react-vite-sqlite"),
        ignore=shutil.ignore_patterns("node_modules", "dist", "*.db", ".adf-deps"))
    spec_dir = os.path.join(tmp, "specs", FID)
    os.makedirs(spec_dir)
    with open(os.path.join(spec_dir, "spec.md"), "w") as f:
        f.write("# Notes\nAdd, list, delete short notes persisted in SQLite. "
                "Empty notes are rejected (400).\n")
    app_dir = os.path.join(tmp, "apps", FID)

    checks = {}
    try:
        print("\n=== 1. ADF builds a real React+Vite+SQLite app and seals it ===")
        ar.generate = lambda m, t: (BUILD_OUTPUT, {})
        sys.argv = ["agent_runner.py", f"resume {FID}", "--workspace", tmp]
        try:
            ar.main()
        except SystemExit:
            pass
        checks["proof artifacts written into the app"] = all(os.path.isfile(
            os.path.join(app_dir, p)) for p in (".adf-proof.json", "PROOF.md"))

        print("\n=== 2. Anyone verifies it offline — no network, no key ===")
        code, out = _verify_cli(app_dir)
        print(out)
        checks["fresh app verifies VERIFIED (exit 0)"] = code == 0 and "VERIFIED" in out

        print("\n=== 3. Tamper a single byte of a generated file ===")
        target = os.path.join(app_dir, "src", "App.tsx")
        with open(target, "a", encoding="utf-8") as f:
            f.write("// injected after the build\n")
        print(f"    appended one line to src/App.tsx")
        code, out = _verify_cli(app_dir)
        print(out)
        checks["tampered app reports TAMPERED (exit 1)"] = code == 1 and "TAMPERED" in out
        checks["the tampered file is named"] = "App.tsx" in out and "MODIFIED" in out

        # Programmatic cross-check.
        ok, report = pob.verify_proof(app_dir)
        checks["verify_proof flags exactly the tampered file"] = (
            not ok and [f["path"] for f in report["files"] if f["status"] == "modified"]
            == [os.path.join("src", "App.tsx")])
    finally:
        passed = all(checks.values())
        print("\n=== Result ===")
        for name, ok in checks.items():
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nGATE PASS: ADF ships apps you can prove — sealed at build, "
          "verified offline, tamper-evident."
          if passed else "GATE FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
