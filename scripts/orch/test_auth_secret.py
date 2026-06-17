#!/usr/bin/env python3
"""SEC-4: every generated app signs sessions with its OWN HMAC secret, never a
world-known constant. Two layers are tested:

  * `agent_runner.ensure_auth_secret` writes a unique random per-app secret file
    (idempotent — never rotates a live secret);
  * `server/auth.mjs` resolves the secret env → `.adf-auth-secret` file → fail-loud
    ephemeral random, with NO shared default an attacker could forge against.

The auth.mjs half is exercised by shelling `node` (no npm/vitest needed), so it
guards the real resolution behavior across separate processes.

    python3 scripts/orch/test_auth_secret.py
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
AUTH_TPL = os.path.join(ROOT, "templates", "react-vite-sqlite", "server", "auth.mjs")
sys.path.insert(0, HERE)


def _node_available():
    return shutil.which("node") is not None


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class EnsureAuthSecret(unittest.TestCase):
    """The Python scaffold side: a unique, stable, well-formed per-app secret."""

    def setUp(self):
        import agent_runner
        self.ensure = agent_runner.ensure_auth_secret

    def _mk(self):
        d = tempfile.mkdtemp(prefix="adf-secret-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_writes_a_32_byte_hex_secret(self):
        d = self._mk()
        p = self.ensure(d)
        self.assertEqual(p, os.path.join(d, ".adf-auth-secret"))
        secret = _read(p).strip()
        self.assertEqual(len(secret), 64)            # 32 bytes, hex
        int(secret, 16)                              # raises if not hex

    def test_idempotent_never_rotates(self):
        d = self._mk()
        first = _read(self.ensure(d))
        again = _read(self.ensure(d))
        self.assertEqual(first, again, "must not rotate a live secret")

    def test_distinct_apps_get_distinct_secrets(self):
        a, b = _read(self.ensure(self._mk())), _read(self.ensure(self._mk()))
        self.assertNotEqual(a, b)


class AuthMjsResolution(unittest.TestCase):
    """The node side: env > file > ephemeral, with no forgeable constant."""

    def setUp(self):
        if not _node_available():
            self.skipTest("node not available")
        self.assertTrue(os.path.isfile(AUTH_TPL), f"missing {AUTH_TPL}")

    def _make_app(self, secret_text=None):
        app = tempfile.mkdtemp(prefix="adf-authsec-")
        self.addCleanup(shutil.rmtree, app, ignore_errors=True)
        os.makedirs(os.path.join(app, "server"))
        shutil.copy2(AUTH_TPL, os.path.join(app, "server", "auth.mjs"))
        if secret_text is not None:
            with open(os.path.join(app, ".adf-auth-secret"), "w") as f:
                f.write(secret_text)
        return app

    def _node(self, app, body, env_secret=None):
        """Run `body` in a fresh node process importing the app's auth.mjs.
        Returns (last-stdout-line-as-JSON, stderr)."""
        auth = os.path.join(app, "server", "auth.mjs").replace("\\", "/")
        script = f"import {{ signToken, verifyToken }} from 'file://{auth}'\n" + body
        sp = os.path.join(app, "_probe.mjs")
        with open(sp, "w") as f:
            f.write(script)
        env = {k: v for k, v in os.environ.items() if k != "ADF_AUTH_SECRET"}
        if env_secret is not None:
            env["ADF_AUTH_SECRET"] = env_secret
        try:
            r = subprocess.run(["node", sp], capture_output=True, text=True, env=env)
        finally:
            os.unlink(sp)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1]), r.stderr

    def _sign(self, app, env_secret=None):
        tok, _ = self._node(app, "console.log(JSON.stringify(signToken({uid:7})))",
                            env_secret=env_secret)
        return tok

    def _verify(self, app, tok, env_secret=None):
        v, err = self._node(
            app, f"console.log(JSON.stringify(verifyToken({json.dumps(tok)}) ?? null))",
            env_secret=env_secret)
        return v, err

    def test_env_secret_wins_and_is_stable_across_processes(self):
        # File present, but the env var must take priority.
        app = self._make_app(secret_text="file-secret-should-be-ignored")
        tok = self._sign(app, env_secret="ENV-SECRET-AAAA")
        v_env, _ = self._verify(app, tok, env_secret="ENV-SECRET-AAAA")
        self.assertEqual(v_env, {"uid": 7})          # stable across separate procs
        v_file, _ = self._verify(app, tok)           # file secret != env secret
        self.assertIsNone(v_file, "env secret must have been used, not the file")

    def test_file_secret_is_used_and_stable(self):
        app = self._make_app(secret_text="file-secret-stable-1234")
        tok = self._sign(app)                        # no env → uses file
        v_same, _ = self._verify(app, tok)           # second process, same file
        self.assertEqual(v_same, {"uid": 7})
        other = self._make_app(secret_text="a-completely-different-file-secret")
        v_other, _ = self._verify(other, tok)
        self.assertIsNone(v_other, "a different app's secret must not verify")

    def test_no_secret_falls_back_to_ephemeral_not_a_constant(self):
        app = self._make_app(secret_text=None)       # no env, no file
        tok = self._sign(app)
        v, err = self._verify(app, tok)              # different process → new random
        self.assertIsNone(v, "fallback must be per-process random, not a shared const")
        self.assertIn("[adf-auth]", err)
        self.assertIn("ephemeral", err.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
