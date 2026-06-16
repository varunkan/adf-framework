#!/usr/bin/env python3
"""Tests for the template's built-in auth (server/auth.mjs) — provably-correct,
OFFLINE auth primitives shipped in every generated app: scrypt password hashing
(never plaintext — the policy gate's no_plaintext_pii rule enforces it) and HMAC
sessions, using only node:crypto (no dependency). Exercised by shelling `node`, so
it guards correctness in CI without npm/vitest.

    python3 scripts/orch/test_template_auth.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
AUTH = os.path.join(ROOT, "templates", "react-vite-sqlite", "server", "auth.mjs")


def _node_available():
    return shutil.which("node") is not None


class TemplateAuth(unittest.TestCase):
    def setUp(self):
        if not _node_available():
            self.skipTest("node not available")
        self.assertTrue(os.path.isfile(AUTH), f"missing {AUTH}")

    def _run(self, body):
        url = "file://" + AUTH.replace("\\", "/")
        script = (f"import {{ hashPassword, verifyPassword, signToken, "
                  f"verifyToken }} from '{url}'\n" + body)
        f = tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False)
        f.write(script)
        f.close()
        try:
            r = subprocess.run(["node", f.name], capture_output=True, text=True)
        finally:
            os.unlink(f.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_password_hash_roundtrips_and_is_never_plaintext(self):
        d = self._run(
            "const h = hashPassword('hunter2')\n"
            "console.log(JSON.stringify({"
            "  plain: h.includes('hunter2'),"
            "  ok: verifyPassword('hunter2', h),"
            "  bad: verifyPassword('wrong', h),"
            "  scheme: h.split('$')[0] }))\n")
        self.assertFalse(d["plain"], "password must never be stored in plaintext")
        self.assertTrue(d["ok"])
        self.assertFalse(d["bad"])
        self.assertEqual(d["scheme"], "scrypt")

    def test_distinct_salts_make_distinct_hashes(self):
        d = self._run(
            "console.log(JSON.stringify({"
            "  same: hashPassword('x') === hashPassword('x') }))\n")
        self.assertFalse(d["same"], "each hash must use a fresh salt")

    def test_token_signs_verifies_and_rejects_tampering(self):
        d = self._run(
            "const t = signToken({ uid: 7 })\n"
            "const tampered = t.slice(0, -2) + (t.slice(-2) === 'aa' ? 'bb' : 'aa')\n"
            "console.log(JSON.stringify({"
            "  ok: verifyToken(t)?.uid,"
            "  tampered: verifyToken(tampered),"
            "  garbage: verifyToken('not.a.token') }))\n")
        self.assertEqual(d["ok"], 7)
        self.assertIsNone(d["tampered"])
        self.assertIsNone(d["garbage"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
