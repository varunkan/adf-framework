#!/usr/bin/env python3
"""Unit tests for tdd_loop.py — ADF's test-first RED→GREEN discipline.

    python3 scripts/orch/test_tdd_loop.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tdd_loop  # noqa: E402
import process_facts  # noqa: E402


class Split(unittest.TestCase):
    def test_recognizes_test_files(self):
        for p in ("test/app.test.mjs", "__tests__/data.test.tsx", "src/x.spec.ts",
                  "tests/thing.js", "test_app.py"):
            self.assertTrue(tdd_loop.is_test_file(p), p)

    def test_impl_files_are_not_tests(self):
        for p in ("src/App.tsx", "server/api/items.mjs", "schema.sql", "src/db.ts"):
            self.assertFalse(tdd_loop.is_test_file(p), p)

    def test_split_partitions(self):
        files = [("src/App.tsx", "x"), ("test/a.test.mjs", "t"),
                 ("server/api.mjs", "y"), ("__tests__/b.test.tsx", "t2")]
        tests, impl = tdd_loop.split_tests(files)
        self.assertEqual({p for p, _ in tests},
                         {"test/a.test.mjs", "__tests__/b.test.tsx"})
        self.assertEqual({p for p, _ in impl}, {"src/App.tsx", "server/api.mjs"})


class RedBaseline(unittest.TestCase):
    def _tests(self):
        return [("test/a.test.mjs", "expect(1).toBe(real())")]

    def _impl(self):
        return [("src/real.ts", "export const real = () => 1")]

    def test_failing_tests_are_a_real_red(self):
        v = tdd_loop.red_baseline(self._tests(), self._impl(),
                                  lambda: (False, "Cannot find module ./real"))
        self.assertTrue(v["red"])
        self.assertFalse(v["vacuous"])

    def test_passing_with_no_impl_is_vacuous(self):
        v = tdd_loop.red_baseline(self._tests(), self._impl(),
                                  lambda: (True, "1 passed"))
        self.assertFalse(v["red"])
        self.assertTrue(v["vacuous"])

    def test_no_tests_is_not_red(self):
        v = tdd_loop.red_baseline([], self._impl(), lambda: (False, ""))
        self.assertFalse(v["red"])
        self.assertIn("no test", v["reason"])

    def test_no_impl_is_not_a_tdd_build(self):
        v = tdd_loop.red_baseline(self._tests(), [], lambda: (False, ""))
        self.assertFalse(v["red"])

    def test_runner_error_is_inconclusive_not_red(self):
        def boom():
            raise RuntimeError("vitest crashed")
        v = tdd_loop.red_baseline(self._tests(), self._impl(), boom)
        self.assertFalse(v["red"])
        self.assertIn("errored", v["reason"])


class Record(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()

    def test_proven_only_when_red_then_green(self):
        v = {"red": True, "vacuous": False, "reason": "RED"}
        fact = tdd_loop.record(self.app, v, True, ["test/a.test.mjs"])
        self.assertTrue(fact["proven"])
        facts = process_facts.read_process_facts(self.app)
        self.assertEqual(facts["facts"]["tdd_followed"]["status"], "proven")

    def test_vacuous_seals_as_skipped(self):
        v = {"red": False, "vacuous": True, "reason": "vacuous"}
        tdd_loop.record(self.app, v, True, [])
        facts = process_facts.read_process_facts(self.app)
        self.assertEqual(facts["facts"]["tdd_followed"]["status"], "skipped")

    def test_red_without_green_is_not_proven(self):
        v = {"red": True, "vacuous": False, "reason": "RED"}
        fact = tdd_loop.record(self.app, v, False, ["test/a.test.mjs"])
        self.assertFalse(fact["proven"])


if __name__ == "__main__":
    unittest.main()
