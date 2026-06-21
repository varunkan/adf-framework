#!/usr/bin/env python3
"""Unit tests for clarify_swarm.py — split → free workers → converge (offline).

    python3 scripts/orch/test_clarify_swarm.py
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clarify_swarm as cs  # noqa: E402


class Swarm(unittest.TestCase):
    def setUp(self):
        self.calls = {"split": 0, "expand": 0, "work": 0, "reduce": 0, "converge": 0}
        self.lock = threading.Lock()

    def _fake(self, prompt, role, system=None):
        with self.lock:
            if role == "split":
                self.calls["split"] += 1
                return ('{"areas":[{"area":"A1","focus":"f"},{"area":"A2","focus":"f"},'
                        '{"area":"A3","focus":"f"}]}')
            if role == "converge":                           # check by ROLE first
                self.calls["converge"] += 1
                return ('{"requirements":[{"id":"R1","shall":"store eCTD modules",'
                        '"acceptance":"persist"}],"open_questions":[{"question":"Which '
                        'modules?","why":"w","options":["1 only","1-5"]}],"risks":["r"]}')
            if role in ("verify", "extract"):                # WORK (one per task)
                self.calls["work"] += 1
                return '{"finding":"an answer","clarify":"what is the limit?"}'
            if "atomic task" in prompt:                      # EXPAND (role draft)
                self.calls["expand"] += 1
                return ('{"tasks":[{"task":"research a standard","type":"research",'
                        '"why":"w"},{"task":"verify a claim","type":"verify","why":"w"}]}')
            if "FINDINGS:" in prompt:                        # REDUCE (role draft)
                self.calls["reduce"] += 1
                return '{"facts":["fact"],"clarifications":["clar"],"risks":["risk"]}'
            return "{}"

    def _run(self):
        return cs.run("build an ANDS app", complete=self._fake, gather=lambda q, u: [],
                      areas=3, tasks_per_area=4, parallelism=4, env={})

    def test_one_worker_per_task(self):
        res = self._run()
        # 3 areas × 2 tasks each (canned) = 6 tasks → 6 workers, exactly one per task
        self.assertEqual(res["stats"]["areas"], 3)
        self.assertEqual(res["stats"]["tasks"], 6)
        self.assertEqual(res["stats"]["workers_run"], 6)
        self.assertEqual(self.calls["work"], 6)

    def test_heads_run_once_each(self):
        self._run()
        self.assertEqual(self.calls["split"], 1)      # Opus splitter: one call
        self.assertEqual(self.calls["converge"], 1)   # Opus converger: one call
        self.assertEqual(self.calls["expand"], 3)     # one per area
        self.assertEqual(self.calls["reduce"], 3)     # one per area

    def test_converged_output(self):
        res = self._run()
        self.assertEqual(res["requirements"][0]["id"], "R1")
        self.assertTrue(any("modules" in q["question"] for q in res["open_questions"]))
        self.assertEqual(res["risks"], ["r"])

    def test_scales_with_grid(self):
        # proves task-generation count scales — does NOT prove concurrent thread count
        res = cs.run("x", complete=self._fake, gather=lambda q, u: [],
                     areas=3, tasks_per_area=2, parallelism=8, env={})
        self.assertEqual(res["stats"]["tasks"], 6)   # 3 × 2-canned

    def test_track_autoscale(self):
        # L track → big default grid (1000s capable)
        a, t = cs._scale({"ADF_TRACK": "L"})
        self.assertGreaterEqual(a * t, 800)
        a2, t2 = cs._scale({"ADF_TRACK": "S"})
        self.assertLess(a2 * t2, 100)


    def test_workers_actually_concurrent(self):
        """Proves at least 2 worker threads enter the WORK wave simultaneously."""
        barrier = threading.Barrier(2, timeout=10)
        barrier_passed = threading.Event()

        def concurrent_complete(prompt, role, system=None):
            if role in ("verify", "extract"):
                # BrokenBarrierError if serialised; both threads arriving sets the event
                barrier.wait()          # raises BrokenBarrierError if serialised
                barrier_passed.set()
            return self._fake(prompt, role, system)

        # areas=1, tasks_per_area=4 → canned stub yields 2 tasks → needs 2 concurrent workers
        cs.run("test req", complete=concurrent_complete,
               gather=lambda q, u: [],
               areas=1, tasks_per_area=4, parallelism=2, env={})
        # If both workers ran concurrently the barrier unblocked and barrier_passed is set.
        # If serialised, BrokenBarrierError is raised inside the pool (swallowed as a
        # blocker by run_crew) and barrier_passed is never set.
        self.assertTrue(barrier_passed.is_set(),
                        "Barrier never unblocked — workers did not run concurrently")


if __name__ == "__main__":
    unittest.main()
