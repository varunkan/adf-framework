#!/usr/bin/env python3
"""Unit tests for requirements_crew.py — the multi-agent requirements crew (offline,
complete + gather injected).

    python3 scripts/orch/test_requirements_crew.py
"""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requirements_crew as rc  # noqa: E402
import model_router as mr  # noqa: E402

_CANNED = {
    "plan": '{"queries":["ands ectd"],"categories":["functional","data"],"seed_urls":["https://hc.gc.ca"]}',
    "draft": '{"requirements":[{"id":"R1","shall":"store eCTD modules","acceptance":"GIVEN a submission WHEN saved THEN modules persist","source":"https://x"}]}',
    "verify": '{"pass":true,"gaps":[]}',
    "judge": '{"pass":false,"gaps":["missing Health Canada validation rule"]}',
    "questions": '{"questions":["Which eCTD modules: 1 only or 1-5?"],"improvements":["add an audit trail"]}',
    "synthesis": '{"problem_statement":"An ANDS submission portal","requirements":[{"id":"R1","shall":"store eCTD modules","acceptance":"...","source":"https://x"}],"assumptions":["single tenant"],"out_of_scope":["e-signatures"],"open_questions":[]}',
    "cross_check": '{"issues":["R1 acceptance is not fully testable"]}',
}


def fake_complete(prompt, role, system=None):
    return _CANNED.get(role, "{}")


def fake_gather(queries, urls):
    return [{"url": "https://hc.gc.ca/ectd", "title": "eCTD", "facts": "5 modules",
             "citations": ["https://hc.gc.ca/ectd"]}]


class CrewRun(unittest.TestCase):
    def _run(self, sources=None, write=False):
        specs = tempfile.mkdtemp() if write else None
        verdicts = os.path.join(specs, "judge-verdicts") if write else None
        return rc.run("pharma-demo", "build a Health Canada ANDS submission app",
                      sources=sources or [], specs_dir=specs, verdict_dir=verdicts,
                      complete=fake_complete, gather=fake_gather), specs

    def test_perspective_diverse_po_fails_if_either_flags(self):
        res, _ = self._run()
        # judge flagged a gap (rigor passed) → PO does NOT pass
        self.assertFalse(res["po"]["pass"])
        self.assertIn("missing Health Canada validation rule", res["po"]["gaps"])

    def test_open_questions_surface_for_user(self):
        res, _ = self._run()
        self.assertTrue(any("eCTD modules" in q for q in res["open_questions"]))
        self.assertIn("add an audit trail", res["improvements"])

    def test_adversarial_cross_check_runs(self):
        res, _ = self._run()
        self.assertTrue(any("testable" in i for i in res["cross_check"]))

    def test_sources_traceability(self):
        sources = [{"source": "uploaded-reqs.md", "requirements": "- SHALL track status"}]
        res, _ = self._run(sources=sources)
        self.assertIn("https://hc.gc.ca/ectd", res["sources"])   # research corpus
        self.assertIn("uploaded-reqs.md", res["sources"])         # user doc

    def test_writes_spec_artifacts(self):
        res, specs = self._run(write=True)
        for fn in ("spec.md", "problem-statement.md", "requirements-draft.json",
                   "po-validation.md"):
            self.assertTrue(os.path.isfile(os.path.join(specs, fn)), fn)
        spec = open(os.path.join(specs, "spec.md")).read()
        self.assertIn("Requirements (EARS)", spec)
        self.assertIn("eCTD modules", spec)
        # the PO verdict is written where the approval gate reads it
        verdict = open(os.path.join(specs, "judge-verdicts", "phase-2.md")).read()
        self.assertIn("REVISE", verdict)   # judge flagged a gap
        # CONTRACT with the Dart gate's parseReviewerSkills (live-E2E-caught): the
        # reviewers line must be "**Reviewers:** <bare, comma-separated skills>".
        self.assertIn("**Reviewers:** bmad-agent-pm, bmad-validate-prd", verdict)
        draft = json.load(open(os.path.join(specs, "requirements-draft.json")))
        self.assertEqual(draft["feature_id"], "pharma-demo")
        # G25: the on-disk traceability contract — `sources` must round-trip as a
        # non-empty list. (fake_gather supplies one corpus URL.) An absent key would
        # raise KeyError (test ERROR); an empty list ([]) is falsy → AssertionError.
        self.assertTrue(draft["sources"])

    def test_no_garbage_orchestrator_leak(self):
        # the crew's spec must never contain the @orch-orchestrator chop the old engine produced
        _res, specs = self._run(write=True)
        spec = open(os.path.join(specs, "spec.md")).read()
        self.assertNotIn("@orch-orchestrator", spec)

    def test_questions_wave_consumes_po_gaps(self):
        # DAG edge: clarifying-questions must run AFTER the PO checks and receive their
        # gaps (its prompt asks it to focus on "the gaps") — not in parallel, blind.
        seen = {}

        def cap(prompt, role, system=None):
            seen[role] = prompt
            return _CANNED.get(role, "{}")

        rc.run("demo", "build x", sources=[], complete=cap, gather=fake_gather)
        self.assertIn("missing Health Canada validation rule", seen.get("questions", ""),
                      "questions wave did not receive the PO gaps")


class Headroom(unittest.TestCase):
    def test_caps_oversized_head_input(self):
        big = ["x" * 1000] * 100  # ~100k chars fed toward a head
        out = rc._headroom(big, limit=3000)
        self.assertLessEqual(len(out), 3100)
        self.assertIn("compacted", out)  # head+tail compaction (not a blind truncate)

    def test_small_input_passes_through(self):
        self.assertEqual(rc._headroom(["a"], limit=3000), json.dumps(["a"]))
        self.assertEqual(rc._headroom("hi", limit=3000), "hi")


class CleanRequirement(unittest.TestCase):
    def test_strips_orchestrator_spam_and_scaffolding(self):
        raw = ("# Requirement\n**Track:** M\n## Description\n"
               "Build a Health Canada ANDS submission app.\n\n"
               "## Client clarification\n@orch-orchestrator resume regulatory-affairs\n"
               "# Builder: speckit-implement phase 7\n")
        out = rc.clean_requirement(raw)
        self.assertIn("Health Canada ANDS submission app", out)
        self.assertNotIn("@orch-orchestrator", out)
        self.assertNotIn("Builder:", out)
        self.assertNotIn("**Track:**", out)

    def test_keeps_user_clarification_answer_on_rerun(self):
        # P3 answer→re-run loop: the user's clarification (appended to requirement.md)
        # must SURVIVE clean_requirement so the crew incorporates it on the next run —
        # only the heading + @orch spam are stripped, the answer prose stays.
        raw = ("# Requirement\nBuild a Health Canada ANDS app.\n\n"
               "## Client clarification (2026-06-20)\n"
               "@orch-orchestrator resume ands\n"
               "Use eCTD modules 1-5 and support multi-tenant.\n")
        out = rc.clean_requirement(raw)
        self.assertIn("eCTD modules 1-5", out)       # the answer survives
        self.assertIn("multi-tenant", out)
        self.assertNotIn("## Client clarification", out)  # heading stripped
        self.assertNotIn("@orch-orchestrator", out)       # spam stripped

    def test_conflict_policy_is_ASK_not_auto_resolve(self):
        # the plan's conflict policy = ASK ME: the synthesis head must NOT silently
        # resolve source disagreements; the PO must flag conflicts as gaps.
        head = rc._HEAD_SYS.lower()
        self.assertNotIn("resolve conflicts", head)     # the old permissive wording
        self.assertIn("conflict", head)
        self.assertIn("open_question", head)
        self.assertIn("do not", head)                   # forbids auto-resolution
        self.assertIn("conflict", rc._PO_SYS.lower())   # PO flags conflicts

    def test_renders_dict_or_string_gaps(self):
        self.assertEqual(rc._g("plain gap"), "plain gap")
        self.assertEqual(rc._g({"question": "Which modules?"}), "Which modules?")
        self.assertEqual(rc._g({"issue": "untestable"}), "untestable")


class ModelsAttribution(unittest.TestCase):
    """G11/G23 — result['models'] is a real per-role map, and the phase-2.md
    attribution line is dynamic (not the stale 'DeepSeek R1 ∥ Nemotron Ultra')."""

    def _run_default_path(self, write=False):
        """Run via the DEFAULT complete path (complete=None) with model_router.complete
        monkeypatched to stamp served identity — the only way to observe real
        per-role collection (an injected text-only fake records 'unknown')."""
        specs = tempfile.mkdtemp() if write else None
        verdicts = os.path.join(specs, "judge-verdicts") if write else None

        def fake_router_complete(prompt, role, system=None, env=None, timeout=None,
                                 call=None):
            if role in ("synthesis", "questions", "split", "converge"):
                usage = {"provider": "anthropic", "model": "claude-opus-4-8"}
            else:
                usage = {"provider": "nvidia", "model": "deepseek-ai/deepseek-v4-pro"}
            return (_CANNED.get(role, "{}"), usage)

        with mock.patch.object(mr, "complete", fake_router_complete):
            res = rc.run("pharma-demo", "build a Health Canada ANDS submission app",
                         sources=[], specs_dir=specs, verdict_dir=verdicts,
                         complete=None, gather=fake_gather)
        return res, specs

    def test_models_field_is_real_per_role_attribution(self):
        res, _ = self._run_default_path()
        self.assertIsInstance(res["models"], dict)
        self.assertNotEqual(res["models"], "free NVIDIA bulk + Opus head")
        self.assertTrue(res["models"].get("verify", "").endswith("deepseek-v4-pro"))
        self.assertTrue(res["models"].get("synthesis", "").endswith("claude-opus-4-8"))

    def test_phase2_attribution_not_stale_literal(self):
        _res, specs = self._run_default_path(write=True)
        verdict = open(os.path.join(specs, "judge-verdicts", "phase-2.md")).read()
        self.assertNotIn("DeepSeek R1 ∥ Nemotron Ultra", verdict)
        # the CONTRACT line stays byte-for-byte unchanged
        self.assertIn("**Reviewers:** bmad-agent-pm, bmad-validate-prd", verdict)

    def test_injected_complete_does_not_crash_and_yields_models_dict(self):
        """COMPAT-1: text-only injected fake still works; models is a dict."""
        res = rc.run("demo", "build x", sources=[],
                     complete=fake_complete, gather=fake_gather)
        self.assertIsInstance(res["models"], dict)
        self.assertNotEqual(res["models"], "free NVIDIA bulk + Opus head")
        for v in res["models"].values():
            self.assertIsInstance(v, str)

    def test_phase2_attribution_is_dynamic_not_r1_ultra(self):
        """G23 RED: phase-2.md attribution reflects actual router ids on the default
        free path, never the hardcoded 'DeepSeek R1' / 'Nemotron Ultra' literal."""
        specs = tempfile.mkdtemp()
        verdicts = os.path.join(specs, "judge-verdicts")
        # default free path — no ANTHROPIC_API_KEY, no ADF_QUALITY=max
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANTHROPIC_API_KEY", "ADF_QUALITY", "ORCH_QUALITY")}
        with mock.patch.dict(os.environ, env, clear=True):
            rc.run("pharma-demo", "build x", sources=[], specs_dir=specs,
                   verdict_dir=verdicts, complete=fake_complete, gather=fake_gather)
            verdict = open(os.path.join(specs, "judge-verdicts", "phase-2.md")).read()
            self.assertNotIn("DeepSeek R1", verdict)
            self.assertNotIn("Nemotron Ultra", verdict)
            expected_verify = mr.candidates("verify", {})[0][1]
            self.assertIn(expected_verify, verdict)


class MainExit(unittest.TestCase):
    """G13 — main() exits 0 on normal completion (PASS or REVISE), non-zero on crash."""

    def _make_repo(self, tmp):
        feat_dir = os.path.join(tmp, ".adf", "orchestration", "features", "feat-x")
        os.makedirs(feat_dir, exist_ok=True)
        with open(os.path.join(feat_dir, "requirement.md"), "w") as f:
            f.write("Build a thing.\n")
        return tmp

    def test_main_exits_zero_on_normal_revise(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_repo(tmp)
            canned = {"feature_id": "feat-x", "problem_statement": "x",
                      "requirements": [], "assumptions": [], "out_of_scope": [],
                      "sources": [], "open_questions": [], "improvements": [],
                      "po": {"pass": False, "gaps": ["a gap"]}, "cross_check": [],
                      "models": {}}
            env = {**os.environ, "ORCH_REPO_ROOT": tmp}
            with mock.patch.dict(os.environ, env, clear=False), \
                    mock.patch.object(rc, "run", return_value=canned), \
                    mock.patch.object(sys, "argv", ["prog", "feat-x"]):
                self.assertEqual(rc.main(), 0)

    def test_main_exits_nonzero_on_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_repo(tmp)
            env = {**os.environ, "ORCH_REPO_ROOT": tmp}

            def boom(*a, **k):
                raise RuntimeError("crew crashed")

            with mock.patch.dict(os.environ, env, clear=False), \
                    mock.patch.object(rc, "run", side_effect=boom), \
                    mock.patch.object(sys, "argv", ["prog", "feat-x"]):
                self.assertEqual(rc.main(), 2)


class Wave1Corpus(unittest.TestCase):
    """G21 — Wave 1 corpus = per-URL LLM-extracted notes assembled by _corpus_text(),
    NOT per-domain-slice Qwen summaries. research-synth (per-domain-slice Qwen synth) is
    unimplemented; per-URL Llama-70B extract is the accepted substitute (G21 descope)."""

    def test_wave1_corpus_is_per_url_extracted(self):
        self.assertIsNotNone(rc._corpus_text.__doc__)
        doc = rc._corpus_text.__doc__
        self.assertTrue("per-page" in doc or "per-URL" in doc)
        out = rc._corpus_text([{"url": "https://hc.gc.ca/ectd", "title": "eCTD",
                                "facts": "5 modules",
                                "citations": ["https://hc.gc.ca/ectd"]}])
        self.assertIn("5 modules", out)
        self.assertIn("hc.gc.ca/ectd", out)
        self.assertNotIn('"slice"', out)

    def test_wave1_docstring_describes_extraction_mechanism(self):
        # The Wave 1 block starts at the "1 research" line and continues (indented
        # continuation lines) until the next wave row ("2 draft").
        doc = rc.__doc__ or ""
        lines = doc.splitlines()
        start = next((i for i, ln in enumerate(lines) if "1 research" in ln), None)
        self.assertIsNotNone(start, "no Wave 1 docstring row found")
        end = next((i for i in range(start + 1, len(lines)) if "2 draft" in lines[i]),
                   len(lines))
        wave1 = "\n".join(lines[start:end])
        self.assertTrue(any(w in wave1
                            for w in ("per-page", "per-URL", "Llama-70B", "extract")),
                        f"Wave 1 docstring lacks mechanism description: {wave1!r}")


class FullDag(unittest.TestCase):
    """G22 — every call runs the full 5-wave DAG; no per-wave caching/skip exists."""

    def test_full_dag_runs_on_every_call(self):
        call_log = []

        def counting_complete(prompt, role, system=None):
            call_log.append(role)
            return _CANNED.get(role, "{}")

        args = ("dag-guard", "build a Health Canada ANDS submission app")
        kwargs = dict(sources=[], complete=counting_complete, gather=fake_gather)
        rc.run(*args, **kwargs)
        count_first = len(call_log)
        call_log.clear()
        rc.run(*args, **kwargs)
        count_second = len(call_log)
        self.assertEqual(count_first, count_second,
                         "a caching layer short-circuited the second call")
        self.assertGreaterEqual(count_first, 7,
                                f"only {count_first} calls — a wave was skipped")


class LoadSources(unittest.TestCase):
    """G09 — _load_sources dispatches audio + repo entries to their engines, and new
    kinds flow through run()'s sources_list with zero changes to run()."""

    def _write_sources(self, tmp, entries):
        p = os.path.join(tmp, "sources.json")
        with open(p, "w") as f:
            json.dump(entries, f)
        return p

    def test_audio_branch_dispatches_to_audio_ingest(self):
        with tempfile.TemporaryDirectory() as tmp:
            sp = self._write_sources(tmp, [{"audio": os.path.join(tmp, "x.m4a")}])
            out = rc._load_sources(tmp, sp)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["kind"], "audio")
            for k in ("source", "kind", "requirements"):
                self.assertIn(k, out[0])

    def test_repo_branch_dispatches_to_repo_analyst(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "myrepo")
            os.makedirs(repo)
            open(os.path.join(repo, "known.py"), "w").close()
            sp = self._write_sources(tmp, [{"repo": repo}])
            out = rc._load_sources(tmp, sp)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["kind"], "repo")
            blob = (out[0].get("raw", "") + out[0].get("requirements", ""))
            self.assertIn("known.py", blob)

    def test_new_source_kinds_flow_through_run_traceability(self):
        sources = [{"source": "voice-note.m4a", "requirements": "- SHALL X"}]
        res = rc.run("demo", "build x", sources=sources,
                     complete=fake_complete, gather=fake_gather)
        self.assertIn("voice-note.m4a", res["sources"])


class OrchestrationDir(unittest.TestCase):
    """G01 — Python standalone mirror of Dart's orchestration-dir precedence."""

    def test_honors_orch_orchestration_dir_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            # env points at a CUSTOM dir name that is NOT one of the probe paths AND
            # while a .cursor probe dir also exists — proving env wins over probe.
            os.makedirs(os.path.join(tmp, ".adf", "orchestration"))
            orch = os.path.join(tmp, "custom-orch")
            os.makedirs(orch, exist_ok=True)
            resolved = rc.resolve_orchestration_dir(
                tmp, {"ORCH_ORCHESTRATION_DIR": orch})
            self.assertEqual(resolved, os.path.abspath(orch))
            self.assertFalse(resolved.startswith(os.path.join(tmp, ".cursor")))

    def test_env_empty_falls_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved = rc.resolve_orchestration_dir(
                tmp, {"ORCH_ORCHESTRATION_DIR": ""})
            self.assertEqual(resolved, os.path.join(tmp, ".adf", "orchestration"))

    def test_manifest_orchestration_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "adf-framework", "orchestration"))
            with open(os.path.join(tmp, ".adf-install.json"), "w") as f:
                json.dump({"orchestration_dir": "adf-framework/orchestration"}, f)
            resolved = rc.resolve_orchestration_dir(tmp, {})
            self.assertEqual(
                resolved, os.path.join(tmp, "adf-framework", "orchestration"))

    def test_manifest_overrides_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".adf", "orchestration"))
            os.makedirs(os.path.join(tmp, ".adf", "orchestration"))
            with open(os.path.join(tmp, ".adf-install.json"), "w") as f:
                json.dump({"orchestration_dir": ".adf/orchestration"}, f)
            resolved = rc.resolve_orchestration_dir(tmp, {})
            self.assertEqual(resolved, os.path.join(tmp, ".adf", "orchestration"))

    def test_probe_cursor_wins_over_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in (".adf/orchestration", "adf-framework/orchestration",
                        ".adf/orchestration"):
                os.makedirs(os.path.join(tmp, rel))
            resolved = rc.resolve_orchestration_dir(tmp, {})
            self.assertEqual(resolved, os.path.join(tmp, ".adf", "orchestration"))

    def test_probe_package_wins_over_adf(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "adf-framework", "orchestration"))
            os.makedirs(os.path.join(tmp, ".adf", "orchestration"))
            resolved = rc.resolve_orchestration_dir(tmp, {})
            self.assertEqual(
                resolved, os.path.join(tmp, "adf-framework", "orchestration"))

    def test_default_when_nothing_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved = rc.resolve_orchestration_dir(tmp, {})
            self.assertEqual(resolved, os.path.join(tmp, ".adf", "orchestration"))


if __name__ == "__main__":
    unittest.main()
