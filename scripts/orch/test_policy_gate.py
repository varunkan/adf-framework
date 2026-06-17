#!/usr/bin/env python3
"""Unit tests for policy_gate.py — ADF's governance gate: static, deterministic
checks that a generated app obeys an org's policy (no secrets, no network egress,
offline-capable, no plaintext PII, vetted deps). The verdict is sealed into the
Proof of Build, so "built + verified + policy-compliant" is provable offline.

    python3 scripts/orch/test_policy_gate.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy_gate as pg  # noqa: E402


def _write(app, rel, content):
    p = os.path.join(app, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


class CleanApp(unittest.TestCase):
    """A well-formed app passes every default rule."""

    def setUp(self):
        self.app = tempfile.mkdtemp()
        _write(self.app, "package.json", json.dumps({
            "dependencies": {"react": "^18", "react-dom": "^18", "fastify": "^4",
                             "@fastify/static": "^7", "better-sqlite3": "^11"},
            "devDependencies": {"vite": "^5", "typescript": "^5", "vitest": "^2",
                                "tailwindcss": "^3", "postcss": "^8",
                                "autoprefixer": "^10", "@vitejs/plugin-react": "^4",
                                "@types/react": "^18", "@types/react-dom": "^18"},
        }))
        _write(self.app, "index.html",
               '<!doctype html><html><body><div id="root"></div>'
               '<script type="module" src="/src/main.tsx"></script></body></html>')
        _write(self.app, "schema.sql",
               "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, body TEXT);")
        _write(self.app, "src/App.tsx",
               "export default function App(){ fetch('/api/notes'); return null }")
        _write(self.app, "server/api/notes.mjs",
               "import { db } from '../db.mjs'\nexport default async function(app){}")

    def test_clean_app_passes_all_rules(self):
        res = pg.check_policy(self.app)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["n_violations"], 0)
        # Every default rule was actually evaluated.
        self.assertEqual({r["rule"] for r in res["rules"]}, set(pg.DEFAULT_POLICY["rules"]))


class Violations(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        _write(self.app, "package.json", json.dumps({
            "dependencies": {"react": "^18", "fastify": "^4", "better-sqlite3": "^11"},
            "devDependencies": {"vite": "^5", "typescript": "^5", "vitest": "^2"},
        }))
        _write(self.app, "index.html",
               '<div id="root"></div><script src="/src/main.tsx"></script>')
        _write(self.app, "schema.sql", "CREATE TABLE notes (id INTEGER, body TEXT);")
        _write(self.app, "src/App.tsx", "export default function App(){return null}")
        _write(self.app, "server/api/notes.mjs",
               "import { db } from '../db.mjs'\nexport default async function(app){}")

    def _rule(self, res, name):
        return next(r for r in res["rules"] if r["rule"] == name)

    def test_hardcoded_secret_is_flagged(self):
        _write(self.app, "server/api/keys.mjs",
               "const KEY = 'sk-abcdEFGH1234567890ZXCVbnmQWERtyui'\nexport default 1")
        res = pg.check_policy(self.app)
        self.assertFalse(res["ok"])
        r = self._rule(res, "no_secrets")
        self.assertFalse(r["ok"])
        self.assertTrue(any("keys.mjs" in v["file"] for v in r["violations"]))

    def test_external_network_egress_is_flagged(self):
        _write(self.app, "server/api/phone.mjs",
               "export default async function(app){ await fetch('https://evil.example.com/x') }")
        res = pg.check_policy(self.app)
        r = self._rule(res, "no_network_egress")
        self.assertFalse(r["ok"])
        self.assertTrue(any("phone.mjs" in v["file"] for v in r["violations"]))

    def test_localhost_calls_do_not_trip_egress(self):
        _write(self.app, "server/api/ok.mjs",
               "export default async function(app){ await fetch('http://127.0.0.1:9/x') }")
        res = pg.check_policy(self.app)
        self.assertTrue(self._rule(res, "no_network_egress")["ok"], res)

    def test_cdn_script_breaks_offline_capable(self):
        _write(self.app, "index.html",
               '<script src="https://cdn.tailwindcss.com"></script><div id="root"></div>')
        res = pg.check_policy(self.app)
        self.assertFalse(self._rule(res, "offline_capable")["ok"])

    def test_plaintext_pii_column_is_flagged(self):
        _write(self.app, "schema.sql",
               "CREATE TABLE users (id INTEGER, password TEXT, ssn TEXT);")
        res = pg.check_policy(self.app)
        r = self._rule(res, "no_plaintext_pii")
        self.assertFalse(r["ok"])
        detail = " ".join(v["detail"].lower() for v in r["violations"])
        self.assertIn("password", detail)

    def test_inline_sql_plaintext_pii_in_source_is_flagged(self):
        # X1: an Expo/mobile .ts CREATE TABLE with a plaintext password column must
        # be caught — the rule used to scan only .sql, so mobile code sailed through
        # and sealed a false "policy: compliant".
        _write(self.app, "src/db.ts",
               "export const init = (db) => db.execSync(`CREATE TABLE users (\n"
               "  id INTEGER PRIMARY KEY,\n  email TEXT,\n  password TEXT\n)`);")
        res = pg.check_policy(self.app)
        r = self._rule(res, "no_plaintext_pii")
        self.assertFalse(r["ok"])
        self.assertTrue(
            any("password" in v["detail"].lower() for v in r["violations"]))

    def test_ui_state_named_password_is_not_flagged(self):
        # must NOT false-flag a React/RN state variable that merely mentions password
        # (no SQL column type on the line).
        _write(self.app, "src/LoginForm.tsx",
               "const [password, setPassword] = useState('');\n"
               "<TextInput value={password} onChangeText={setPassword} />")
        res = pg.check_policy(self.app)
        r = self._rule(res, "no_plaintext_pii")
        self.assertTrue(r["ok"], [v["detail"] for v in r["violations"]])

    def test_hashed_column_in_source_is_ok(self):
        _write(self.app, "src/db.ts",
               "db.execSync('CREATE TABLE users (id INTEGER, password_hash TEXT)');")
        res = pg.check_policy(self.app)
        self.assertTrue(self._rule(res, "no_plaintext_pii")["ok"])

    def test_non_allowlisted_dependency_is_flagged(self):
        _write(self.app, "package.json", json.dumps({
            "dependencies": {"react": "^18", "left-pad": "^1.3.0"},
        }))
        res = pg.check_policy(self.app)
        r = self._rule(res, "dependency_allowlist")
        self.assertFalse(r["ok"])
        self.assertTrue(any("left-pad" in v["detail"] for v in r["violations"]))

    def test_disabled_rule_is_not_enforced(self):
        _write(self.app, "server/api/phone.mjs",
               "export default async function(app){ fetch('https://evil.example.com') }")
        policy = {**pg.DEFAULT_POLICY,
                  "rules": {**pg.DEFAULT_POLICY["rules"], "no_network_egress": False}}
        res = pg.check_policy(self.app, policy)
        self.assertTrue(res["ok"], res)


class PolicyResolution(unittest.TestCase):
    def test_app_policy_overrides_default(self):
        app = tempfile.mkdtemp()
        _write(app, ".adf-policy.json", json.dumps({
            "schema": "adf-policy/1",
            "rules": {"no_secrets": True}, "allowlist": ["react"],
        }))
        policy = pg.load_policy(app)
        self.assertEqual(set(policy["rules"]), {"no_secrets"})

    def test_default_when_no_policy_present(self):
        app = tempfile.mkdtemp()
        self.assertEqual(pg.load_policy(app)["rules"], pg.DEFAULT_POLICY["rules"])

    def test_verdict_summary_is_canonical_and_sealed_shape(self):
        app = tempfile.mkdtemp()
        _write(app, "package.json", "{}")
        res = pg.check_policy(app)
        summ = pg.policy_summary(res)
        self.assertIn("ok", summ)
        self.assertIn("rules", summ)
        self.assertIn("n_violations", summ)
        # JSON-serializable + stable key order for sealing.
        json.dumps(summ, sort_keys=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
