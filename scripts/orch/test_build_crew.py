#!/usr/bin/env python3
"""Unit tests for build_crew.py — the parallel subagent build DAG (Kahn scheduler +
wave runner). Ports agent_crew.dart's buildExecutionWaves test cases to keep the two
schedulers in lockstep.

    python3 scripts/orch/test_build_crew.py
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_crew as bc  # noqa: E402


def A(name, needs=None):
    return bc.BuildAgent(name, name, needs=needs)


class Kahn(unittest.TestCase):
    def test_linear_chain_is_one_per_wave(self):
        waves = bc.build_execution_waves([A("a"), A("b", ["a"]), A("c", ["b"])])
        self.assertEqual(waves, [["a"], ["b"], ["c"]])

    def test_independent_agents_share_a_wave(self):
        waves = bc.build_execution_waves([A("a"), A("b"), A("c", ["a", "b"])])
        self.assertEqual(set(waves[0]), {"a", "b"})
        self.assertEqual(waves[1], ["c"])

    def test_diamond_dag(self):
        # the default react shape: data → (api ∥ tests) → ui
        waves = bc.build_execution_waves([
            A("data"), A("api", ["data"]), A("tests", ["data"]), A("ui", ["api"])])
        self.assertEqual(waves[0], ["data"])
        self.assertEqual(set(waves[1]), {"api", "tests"})
        self.assertEqual(waves[-1], ["ui"])

    def test_self_dependency_raises(self):
        with self.assertRaises(ValueError) as cm:
            bc.build_execution_waves([A("a", ["a"])])
        self.assertIn("itself", str(cm.exception))

    def test_unknown_dependency_raises(self):
        with self.assertRaises(ValueError) as cm:
            bc.build_execution_waves([A("a", ["ghost"])])
        self.assertIn("unknown agent", str(cm.exception))

    def test_cycle_raises(self):
        with self.assertRaises(ValueError) as cm:
            bc.build_execution_waves([A("a", ["b"]), A("b", ["a"])])
        self.assertIn("cycle", str(cm.exception))


class GlobRouting(unittest.TestCase):
    def test_routes_files_to_owning_agent(self):
        self.assertTrue(bc.matches_globs("src/components/App.tsx", ["src/**.tsx"]))
        self.assertTrue(bc.matches_globs("server/api/items.mjs", ["server/api/*.mjs"]))
        self.assertTrue(bc.matches_globs("schema.sql", ["schema.sql", "src/db.ts"]))
        self.assertTrue(bc.matches_globs("src/db.ts", ["schema.sql", "src/db.ts"]))

    def test_non_matching_path_is_false(self):
        self.assertFalse(bc.matches_globs("README.md", ["src/**.tsx"]))
        self.assertFalse(bc.matches_globs("test/a.test.mjs", ["server/**.mjs"]))

    def test_empty_globs_is_false(self):
        self.assertFalse(bc.matches_globs("x.ts", []))


class Decomposition(unittest.TestCase):
    def test_react_has_a_valid_dag(self):
        crew = bc.decomposition_for("react-vite-sqlite")
        self.assertIsNotNone(crew)
        waves = bc.build_execution_waves(crew)        # must not raise
        self.assertEqual(waves[0], ["data-layer"])
        self.assertEqual(set(waves[1]), {"api-routes", "test-author"})
        self.assertEqual(waves[-1], ["ui"])

    def test_stdlib_stays_monolithic(self):
        self.assertIsNone(bc.decomposition_for("stdlib"))


class RunCrew(unittest.TestCase):
    def test_merges_files_in_dependency_order(self):
        crew = [A("data"), A("api", ["data"]), A("ui", ["api"])]

        def run_agent(agent, prior):
            return True, [(f"{agent.name}.ts", f"// {agent.name}")], "ok"

        out = bc.run_crew(crew, run_agent, parallelism=2)
        self.assertEqual(set(out["files"]), {"data.ts", "api.ts", "ui.ts"})
        self.assertEqual(out["blockers"], [])
        self.assertEqual(out["waves"][0], ["data"])

    def test_later_wave_sees_prior_files(self):
        crew = [A("data"), A("ui", ["data"])]
        seen = {}

        def run_agent(agent, prior):
            seen[agent.name] = set(prior)
            return True, [(f"{agent.name}.ts", "x")], "ok"

        bc.run_crew(crew, run_agent, parallelism=2)
        self.assertEqual(seen["data"], set())            # first wave: no prior
        self.assertEqual(seen["ui"], {"data.ts"})        # second wave sees data's file

    def test_failing_agent_is_a_blocker_but_siblings_run(self):
        crew = [A("a"), A("b")]
        ran = []

        def run_agent(agent, prior):
            ran.append(agent.name)
            if agent.name == "a":
                return False, [], "a failed"
            return True, [("b.ts", "x")], "ok"

        out = bc.run_crew(crew, run_agent, parallelism=2)
        self.assertIn("a failed", out["blockers"])
        self.assertEqual(set(ran), {"a", "b"})           # sibling still ran
        self.assertIn("b.ts", out["files"])

    def test_agent_exception_becomes_blocker_not_crash(self):
        crew = [A("a")]

        def run_agent(agent, prior):
            raise RuntimeError("model died")

        out = bc.run_crew(crew, run_agent)
        self.assertTrue(any("errored" in b for b in out["blockers"]))

    def test_waves_actually_parallel(self):
        # two independent agents should run concurrently (both enter before either exits)
        crew = [A("a"), A("b")]
        barrier = threading.Barrier(2, timeout=5)

        def run_agent(agent, prior):
            barrier.wait()                               # deadlocks if run serially
            return True, [(f"{agent.name}.ts", "x")], "ok"

        out = bc.run_crew(crew, run_agent, parallelism=2)
        self.assertEqual(out["blockers"], [])


if __name__ == "__main__":
    unittest.main()
