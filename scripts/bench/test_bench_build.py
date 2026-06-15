#!/usr/bin/env python3
"""Tests for bench_build.py — the measured-capability builder. The orchestration
(scaffold → generate → verify → seal → measure) is exercised with injected
generate/verify so it's deterministic and needs no live model or npm. The live
run (run_bench --build) uses the real runner + a local model.

    python3 scripts/bench/test_bench_build.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import bench_build  # noqa: E402


def _fake_generate(messages, timeout):
    return (
        "<<<FILE: server/api/notes.mjs>>>\n"
        "export default async function (app) {\n"
        "  app.get('/notes', async () => [])\n"
        "}\n"
        "<<<END>>>\n",
        {"prompt_tokens": 120, "completion_tokens": 60},
    )


def _ok_verify(app_root, stack=None, timeout=None):
    return (True, "ok")


def _fail_verify(app_root, stack=None, timeout=None):
    return (False, "vitest: 1 failing")


class BuildOne(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.item = {"id": "notes", "prompt": "A notes app"}

    def test_measures_a_successful_build_and_seals_it(self):
        r = bench_build.build_one(self.item, self.ws,
                                  generate=_fake_generate, verify=_ok_verify)
        self.assertTrue(r["built"])
        self.assertTrue(r["tests_pass"])
        self.assertGreaterEqual(r["files"], 1)
        self.assertGreaterEqual(r["seconds"], 0)
        self.assertEqual(r["in_tokens"], 120)
        # a real Proof of Build was sealed over the built app
        self.assertTrue(os.path.isfile(
            os.path.join(self.ws, "apps", "notes", ".adf-proof.json")))

    def test_records_a_failed_build_after_retries(self):
        r = bench_build.build_one(self.item, self.ws, fix_iters=2,
                                  generate=_fake_generate, verify=_fail_verify)
        self.assertFalse(r["built"])
        self.assertEqual(r["attempts"], 2)
        self.assertFalse(os.path.isfile(
            os.path.join(self.ws, "apps", "notes", ".adf-proof.json")))


class CapabilitySummary(unittest.TestCase):
    def test_aggregates_built_and_timing(self):
        s = bench_build.capability_summary([
            {"built": True, "tests_pass": True, "seconds": 60, "out_tokens": 100},
            {"built": True, "tests_pass": True, "seconds": 80, "out_tokens": 200},
            {"built": False, "tests_pass": False, "seconds": 0, "out_tokens": 0},
        ])
        self.assertEqual(s["apps"], 3)
        self.assertEqual(s["built"], 2)
        self.assertEqual(s["avg_seconds"], 70.0)
        self.assertEqual(s["total_out_tokens"], 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
