#!/usr/bin/env python3
"""Tests for the ADF-vs-Lovable scorecard generator. The scorecard must be HONEST
(per the North Star): ADF wins the governed/owned/local/agent-operable wedge and
reaches credible capability parity, and it must SAY where it still trails.

    python3 scripts/bench/test_scorecard.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scorecard  # noqa: E402


class Render(unittest.TestCase):
    def test_has_the_required_sections(self):
        md = scorecard.render_scorecard()
        self.assertIn("ADF", md)
        self.assertIn("Lovable", md)
        self.assertIn("Governance", md)
        self.assertIn("Capability", md)

    def test_names_the_moat_axes(self):
        md = scorecard.render_scorecard()
        for axis in ("Proof of Build", "Policy", "Offline", "Agent-operable",
                     "Own your code"):
            self.assertIn(axis, md, axis)

    def test_is_honest_about_where_adf_trails(self):
        md = scorecard.render_scorecard()
        low = md.lower()
        self.assertTrue("trail" in low or "honest" in low,
                        "must include an honest 'where ADF trails' section")
        self.assertTrue("deploy" in low or "hosting" in low)
        self.assertTrue("ecosystem" in low or "integration" in low)

    def test_embeds_measured_bench_numbers(self):
        md = scorecard.render_scorecard(bench={
            "apps": 3, "governed": 3, "proven": 3, "compliant": 3,
            "offline": 3, "total_files": 51,
        })
        self.assertIn("3/3", md)

    def test_embeds_measured_capability(self):
        md = scorecard.render_scorecard(capability={
            "apps": 2, "built": 2, "tests_pass": 2, "avg_seconds": 95.0,
            "local": True, "backend": "ollama:qwen2.5-coder:32b",
        })
        self.assertIn("2/2 apps built", md)
        self.assertIn("$0 (local model, offline)", md)

    def test_partial_capability_is_reported_honestly(self):
        # A timed-out local-model run must NOT read as a pipeline failure: it must
        # say what was attempted and point at the e2e that proves the pipeline.
        md = scorecard.render_scorecard(capability={
            "apps": 1, "built": 0, "budget_s": 600,
            "backend": "ollama qwen2.5-coder:32b (local, $0, offline)",
        })
        self.assertIn("attempted", md.lower())
        self.assertIn("pipeline", md.lower())
        self.assertIn("e2e", md.lower())


class WriteDoc(unittest.TestCase):
    def test_writes_the_scorecard_file(self):
        tmp = tempfile.mkdtemp()
        out = os.path.join(tmp, "ADF_VS_LOVABLE.md")
        rc = scorecard._main(["--out", out])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out))
        self.assertIn("ADF", open(out, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
