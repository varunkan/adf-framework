#!/usr/bin/env python3
"""Tests for the deep-agent gate in run_test_agents.py — the activation switch for
the incremental-verify lever.

Background: the slow Opus-judged behavioral agents (kind=='llm': e2e, integration,
black-box, white-box) ship `enabled: false` in registry.json, so the default gate
is fast + all-deterministic and the ADF_VERIFY_INCREMENTAL lever has NOTHING to
defer (dormant, 0x). `_apply_deep_agent_gate` wires their `enabled` to the single
ADF_DEEP_AGENTS knob: only when it is "1" do the deep agents run — and only THEN
does the incremental lever do real work (defer them while the cheap deterministic
tier is dirty, run them once it is clean). These tests prove that wiring, and that
"off/unset" preserves the prior all-deterministic behavior byte-for-byte.

    python3 scripts/orch/test_deep_agent_gate.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_test_agents as rta  # noqa: E402


def _fresh_registry():
    """A minimal registry mirroring the real kinds: deterministic agents stay
    enabled untouched; llm agents ship disabled and are gated by the env."""
    return {
        "agents": [
            {"id": "ui-visual", "kind": "dynamic", "enabled": True},
            {"id": "security-pentest", "kind": "static", "enabled": True},
            {"id": "e2e", "kind": "llm", "enabled": False},
            {"id": "integration", "kind": "llm", "enabled": False},
            {"id": "black-box", "kind": "llm", "enabled": False},
            {"id": "white-box", "kind": "llm", "enabled": False},
        ]
    }


class DeepAgentGate(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("ADF_DEEP_AGENTS")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("ADF_DEEP_AGENTS", None)
        else:
            os.environ["ADF_DEEP_AGENTS"] = self._saved

    def _llm(self, reg):
        return {a["id"]: a["enabled"] for a in reg["agents"] if a["kind"] == "llm"}

    def _det(self, reg):
        return {a["id"]: a["enabled"] for a in reg["agents"] if a["kind"] != "llm"}

    def test_unset_keeps_deep_agents_off(self):
        # Prior behavior: no ADF_DEEP_AGENTS -> all-deterministic gate (lever dormant).
        os.environ.pop("ADF_DEEP_AGENTS", None)
        reg = _fresh_registry()
        rta._apply_deep_agent_gate(reg)
        self.assertEqual(self._llm(reg), {
            "e2e": False, "integration": False,
            "black-box": False, "white-box": False})

    def test_zero_keeps_deep_agents_off(self):
        os.environ["ADF_DEEP_AGENTS"] = "0"
        reg = _fresh_registry()
        rta._apply_deep_agent_gate(reg)
        self.assertTrue(all(v is False for v in self._llm(reg).values()))

    def test_one_activates_all_deep_agents(self):
        # The activation: the incremental lever now has deep agents to defer/run.
        os.environ["ADF_DEEP_AGENTS"] = "1"
        reg = _fresh_registry()
        rta._apply_deep_agent_gate(reg)
        self.assertEqual(self._llm(reg), {
            "e2e": True, "integration": True,
            "black-box": True, "white-box": True})

    def test_never_touches_deterministic_agents(self):
        # The cheap tier is invariant under the knob — only llm agents are gated.
        for val in (None, "0", "1"):
            if val is None:
                os.environ.pop("ADF_DEEP_AGENTS", None)
            else:
                os.environ["ADF_DEEP_AGENTS"] = val
            reg = _fresh_registry()
            rta._apply_deep_agent_gate(reg)
            self.assertEqual(self._det(reg),
                             {"ui-visual": True, "security-pentest": True},
                             f"deterministic tier changed for ADF_DEEP_AGENTS={val}")

    def test_non_one_truthy_values_stay_off(self):
        # Only the exact string "1" activates — "true"/"yes"/"2" do NOT (explicit,
        # no accidental activation from a stray value).
        for val in ("true", "yes", "2", "on", ""):
            os.environ["ADF_DEEP_AGENTS"] = val
            reg = _fresh_registry()
            rta._apply_deep_agent_gate(reg)
            self.assertTrue(all(v is False for v in self._llm(reg).values()),
                            f"unexpected activation for ADF_DEEP_AGENTS={val!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
