#!/usr/bin/env python3
"""Tests for the benchmark harness — the proof-of-10x machinery. The GOVERNANCE
axes (proven / policy-compliant / offline-capable) are computed for real over a
sealed app, deterministically and offline, so the scorecard rests on measured
facts, not claims.

    python3 scripts/bench/test_bench.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "orch"))

import evaluate  # noqa: E402
import suite as suite_mod  # noqa: E402
import agent_runner  # noqa: E402
import proof_of_build  # noqa: E402


class Suite(unittest.TestCase):
    def test_ten_unique_prompts(self):
        self.assertGreaterEqual(len(suite_mod.SUITE), 10)
        ids = suite_mod.ids()
        self.assertEqual(len(ids), len(set(ids)))
        for item in suite_mod.SUITE:
            self.assertTrue(item["prompt"].strip())


class EvaluateGovernance(unittest.TestCase):
    """A real scaffolded + sealed app must score governed=True on every axis."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "apps", "demo")
        tpl = agent_runner.template_dir(ROOT, ROOT, agent_runner.STACK_REACT)
        if not tpl:
            self.skipTest("react template not found")
        os.makedirs(self.app)
        agent_runner.scaffold_app(self.app, tpl)
        # Seal a Proof of Build over the scaffold (offline, no model).
        proof_of_build.seal_app(self.app, "demo", "react-vite-sqlite",
                                "the spec", {"verified": True})

    def test_sealed_scaffold_is_fully_governed(self):
        r = evaluate.evaluate_app(ROOT, self.app)
        self.assertGreater(r["files"], 0)
        self.assertTrue(r["proof_ok"], r)
        self.assertTrue(r["policy_ok"], r)
        self.assertTrue(r["offline_ok"], r)
        self.assertTrue(r["governed"], r)

    def test_tampering_breaks_the_proof_axis(self):
        with open(os.path.join(self.app, "src", "main.tsx"), "a") as f:
            f.write("\n// tampered after sealing\n")
        r = evaluate.evaluate_app(ROOT, self.app)
        self.assertFalse(r["proof_ok"], r)
        self.assertFalse(r["governed"], r)


class Summary(unittest.TestCase):
    def test_summarize_counts_axes(self):
        results = [
            {"governed": True, "proof_ok": True, "policy_ok": True,
             "offline_ok": True, "files": 10},
            {"governed": False, "proof_ok": False, "policy_ok": True,
             "offline_ok": True, "files": 5},
        ]
        s = evaluate.summarize(results)
        self.assertEqual(s["apps"], 2)
        self.assertEqual(s["governed"], 1)
        self.assertEqual(s["proven"], 1)
        self.assertEqual(s["compliant"], 2)
        self.assertEqual(s["total_files"], 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
