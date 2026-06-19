#!/usr/bin/env python3
"""Unit tests for process_facts.py — ADF's attested engineering-discipline facts,
sealed into the Proof of Build beside `render` and `policy`.

    python3 scripts/orch/test_process_facts.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import process_facts as pf  # noqa: E402


class RecordAndRead(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()

    def test_no_evidence_reads_none(self):
        # A build that recorded nothing has no process block (honest absence, so the
        # seal stays backward-compatible — no `process` key in the verdict).
        self.assertIsNone(pf.read_process_facts(self.app))

    def test_verification_evidence_is_proven_with_stack_gates(self):
        pf.record_verification(self.app, "react", "build + vitest passed; boots")
        facts = pf.read_process_facts(self.app)
        self.assertEqual(facts["schema"], "adf-process/1")
        ve = facts["facts"]["verification_evidence"]
        self.assertEqual(ve["status"], "proven")
        self.assertEqual(ve["gates"], ["build", "test", "boot", "render"])
        # verification_evidence is effectively fail-closed → named as enforced
        self.assertIn("verification_evidence", facts["enforced"])
        # a sealed summary never carries a blocked enforced discipline
        self.assertEqual(facts["blocked"], [])

    def test_expo_and_stdlib_gate_lists_differ(self):
        pf.record_verification(self.app, "expo")
        self.assertEqual(
            pf.read_process_facts(self.app)["facts"]["verification_evidence"]["gates"],
            ["typecheck", "test", "render"])
        app2 = tempfile.mkdtemp()
        pf.record_verification(app2, "stdlib")
        self.assertEqual(
            pf.read_process_facts(app2)["facts"]["verification_evidence"]["gates"],
            ["test", "boot"])

    def test_unknown_stack_falls_back_to_build_test(self):
        pf.record_verification(self.app, "svelte-thing")
        self.assertEqual(
            pf.read_process_facts(self.app)["facts"]["verification_evidence"]["gates"],
            ["build", "test"])

    def test_read_is_from_disk_not_memory(self):
        # Honesty: the summary must come from the durable artifact, so a fresh process
        # (no shared state) reading the same dir gets the same proven facts.
        pf.record_verification(self.app, "react")
        again = pf.read_process_facts(self.app)
        self.assertEqual(again["facts"]["verification_evidence"]["status"], "proven")


class Enforcement(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()

    def test_verification_evidence_is_enforced_and_proven(self):
        pf.record_verification(self.app, "react")
        obj = pf.read_process_facts(self.app)
        # proven → nothing blocks
        self.assertEqual(pf.enforcement_block(obj), [])

    def test_strict_tdd_skipped_blocks(self):
        # a vacuous-TDD build under strict mode must be blocked (no seal)
        pf.record_verification(self.app, "react")
        pf._write(self.app, "tdd.json",
                  {"red": False, "vacuous": True, "proven": False})
        obj = pf.read_process_facts(self.app, env={"ADF_TDD": "strict"})
        self.assertIn("tdd_followed", obj["enforced"])
        self.assertEqual(pf.enforcement_block(obj), ["tdd_followed"])

    def test_non_strict_tdd_skipped_does_not_block(self):
        pf.record_verification(self.app, "react")
        pf._write(self.app, "tdd.json",
                  {"red": False, "vacuous": True, "proven": False})
        obj = pf.read_process_facts(self.app, env={})
        self.assertNotIn("tdd_followed", obj["enforced"])
        self.assertEqual(pf.enforcement_block(obj), [])

    def test_strict_tdd_proven_does_not_block(self):
        pf.record_verification(self.app, "react")
        pf._write(self.app, "tdd.json",
                  {"red": True, "green": True, "proven": True})
        obj = pf.read_process_facts(self.app, env={"ADF_PROCESS": "strict"})
        self.assertEqual(obj["facts"]["tdd_followed"]["status"], "proven")
        self.assertEqual(pf.enforcement_block(obj), [])


class ReviewAndDesign(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()

    def test_review_proven_when_both_stages_pass(self):
        pf.record_review(self.app, spec_ok=True, quality_ok=True)
        f = pf.read_process_facts(self.app)["facts"]["review_passed"]
        self.assertEqual(f["status"], "proven")
        self.assertEqual(f["stages"], ["spec_compliance", "code_quality"])

    def test_review_skipped_when_a_stage_fails(self):
        pf.record_review(self.app, spec_ok=True, quality_ok=False)
        self.assertEqual(
            pf.read_process_facts(self.app)["facts"]["review_passed"]["status"],
            "skipped")

    def test_design_proven_needs_two_real_options(self):
        pf.record_design_options(self.app, ["mvp-first", "risk-first"],
                                 chosen="mvp-first", rationale="ship fast")
        f = pf.read_process_facts(self.app)["facts"]["design_options_considered"]
        self.assertEqual(f["status"], "proven")
        self.assertEqual(f["n_options"], 2)

    def test_design_one_option_is_skipped(self):
        pf.record_design_options(self.app, ["only-idea"])
        self.assertEqual(
            pf.read_process_facts(self.app)["facts"]
            ["design_options_considered"]["status"], "skipped")


class Surfacing(unittest.TestCase):
    def _verdict(self, facts):
        return {"process": {"schema": "adf-process/1", "facts": facts,
                            "enforced": [], "blocked": []}}

    def test_summary_line_lists_proven_with_gates(self):
        line = pf.process_summary_line(self._verdict(
            {"verification_evidence": {"status": "proven",
                                       "gates": ["build", "test"]}}))
        self.assertIn("Built WITH discipline", line)
        self.assertIn("✅ verified (build·test)", line)

    def test_summary_line_prints_skips_honestly(self):
        line = pf.process_summary_line(self._verdict(
            {"tdd_followed": {"status": "skipped"}}))
        self.assertIn("⚠ TDD (RED→GREEN): skipped", line)

    def test_na_facts_are_omitted(self):
        line = pf.process_summary_line(self._verdict(
            {"root_cause_documented": {"status": "na"}}))
        self.assertEqual(line, "")

    def test_no_process_block_is_empty_line(self):
        self.assertEqual(pf.process_summary_line({}), "")
        self.assertEqual(pf.process_summary_line({"process": None}), "")


class RequiredDisciplines(unittest.TestCase):
    def _verdict(self, *proven):
        return {"process": {"facts": {p: {"status": "proven"} for p in proven}}}

    def test_empty_requirement_is_trivially_ok(self):
        ok, missing = pf.required_disciplines_met(self._verdict(), [])
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_met_when_all_proven(self):
        ok, missing = pf.required_disciplines_met(
            self._verdict("tdd_followed", "review_passed"),
            ["tdd_followed", "review_passed"])
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_missing_when_not_proven(self):
        ok, missing = pf.required_disciplines_met(
            self._verdict("verification_evidence"), ["tdd_followed"])
        self.assertFalse(ok)
        self.assertEqual(missing, ["tdd_followed"])

    def test_skipped_does_not_satisfy_a_requirement(self):
        verdict = {"process": {"facts": {"tdd_followed": {"status": "skipped"}}}}
        ok, missing = pf.required_disciplines_met(verdict, ["tdd_followed"])
        self.assertFalse(ok)
        self.assertEqual(missing, ["tdd_followed"])


if __name__ == "__main__":
    unittest.main()
