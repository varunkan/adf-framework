#!/usr/bin/env python3
"""System gate for DAG node N5 (runner-verify): prove `verify_app(react)` really
drives the full pipeline — npm ci → `tsc --noEmit && vite build` → vitest → node
boot — against the checked-in template. The template is copied to a temp dir so
the repo stays clean (no node_modules/dist left behind). Exit 0 only on green.

    python3 scripts/test/runner_verify_check.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))
import agent_runner as ar  # noqa: E402

TPL = os.path.join(ROOT, "templates", "react-vite-sqlite")


def main():
    if not os.path.isdir(TPL):
        print(f"GATE FAIL: template missing: {TPL}", file=sys.stderr)
        return 1
    tmp = tempfile.mkdtemp(prefix="adf-verify-")
    app = os.path.join(tmp, "app")
    shutil.copytree(
        TPL, app,
        ignore=shutil.ignore_patterns("node_modules", "dist", "*.db", ".adf-deps"),
    )
    try:
        ok, out = ar.verify_app(app, ar.STACK_REACT)
        print(out[-2500:])
        print("GATE PASS: verify_app(react) green — build+vitest+boot all passed"
              if ok else "GATE FAIL: verify_app(react) red")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
