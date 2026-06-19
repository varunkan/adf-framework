#!/usr/bin/env python3
"""Unit tests for heal.py — ADF's systematic-debugging self-heal.

    python3 scripts/orch/test_heal.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heal  # noqa: E402
import process_facts  # noqa: E402


class Classify(unittest.TestCase):
    def test_classes_from_real_verifier_tags(self):
        cases = {
            "DEPENDENCY INSTALL FAILED (npm ci):\n...": "dependency_install",
            "BUILD FAILED (tsc --noEmit && vite build):\nTS2304": "type_error",
            "TESTS FAILED (vitest):\nAssertionError": "test_failure",
            "BUILD + TESTS PASSED but SERVER BOOT FAILED:\n...": "boot_crash",
            "RENDER FAILED: blank root, app did not mount": "render_blank",
            "no parseable <<<FILE:>>> blocks": "no_files",
        }
        for output, cls in cases.items():
            self.assertEqual(heal.classify_failure(output), cls, output[:30])

    def test_unknown_is_unknown(self):
        self.assertEqual(heal.classify_failure("something weird happened"), "unknown")

    def test_failing_stage_extracted(self):
        self.assertEqual(heal.failing_stage("BUILD FAILED (tsc):\n..."), "build")
        self.assertEqual(heal.failing_stage("TESTS FAILED (vitest):"), "tests")
        self.assertEqual(
            heal.failing_stage("BUILD + TESTS PASSED but SERVER BOOT FAILED:"),
            "build + tests")
        self.assertIsNone(heal.failing_stage("no tag here"))


class Preamble(unittest.TestCase):
    def test_demands_root_cause_first(self):
        p = heal.diagnose_preamble("BUILD FAILED (tsc):\nTS2304")
        self.assertIn("ROOT CAUSE", p)
        self.assertIn("SYSTEMATIC DEBUGGING", p)
        self.assertIn("build", p)

    def test_includes_reference_when_given(self):
        p = heal.diagnose_preamble("TESTS FAILED (vitest):", reference="export const x=1")
        self.assertIn("KNOWN-GOOD REFERENCE", p)
        self.assertIn("export const x=1", p)


class RecordRootCause(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()

    def test_records_cause_and_seals_root_cause_documented(self):
        heal.record_root_cause(self.app, 1, "BUILD FAILED (tsc):\nTS2304")
        heal.record_root_cause(self.app, 2, "TESTS FAILED (vitest):\nAssertionError")
        facts = process_facts.read_process_facts(self.app)
        rc = facts["facts"]["root_cause_documented"]
        self.assertEqual(rc["status"], "proven")
        self.assertEqual(rc["heals"], 2)
        self.assertIn("type_error", rc["causes"])
        self.assertIn("test_failure", rc["causes"])

    def test_no_heals_means_no_fact(self):
        # a build that never self-healed has no root_cause fact (genuinely n/a)
        self.assertIsNone(process_facts.read_process_facts(self.app))


if __name__ == "__main__":
    unittest.main()
