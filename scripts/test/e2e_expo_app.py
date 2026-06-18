#!/usr/bin/env python3
"""M3-live / M6 end-to-end gate: the shipped `expo-rn` template is a REAL, working
cross-platform mobile app — it typechecks (`tsc --noEmit`), tests (jest), and
RENDERS on web through ADF's existing headless render gate (proving the
Proof-of-Build + render moat carry from web to mobile).

Skips cleanly when the template's deps aren't installed (a bare checkout / CI
without the one-time `npm install` in templates/expo-rn), so it never fails for
lack of a heavy toolchain — exactly like the visual render gate degrades.

    python3 scripts/test/e2e_expo_app.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))

import agent_runner as ar  # noqa: E402


def main():
    tpl = os.path.join(ROOT, "templates", "expo-rn")
    if not os.path.isdir(os.path.join(tpl, "node_modules")):
        print("SKIP: expo-rn deps not installed "
              "(run `npm install` in templates/expo-rn to enable this gate)")
        return 0
    ok, detail = ar.verify_app(tpl, ar.STACK_EXPO)
    print(detail)
    if not ok:
        print("GATE FAIL: the expo-rn template did not verify")
        return 1
    if "web render" not in detail:
        print("GATE FAIL: the web render proof did not run")
        return 1
    print("GATE PASS: the expo-rn template typechecks + tests + RENDERS on web — "
          "ADF builds + render-verifies a cross-platform mobile app, moat intact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
