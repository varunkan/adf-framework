#!/usr/bin/env python3
"""Unit tests for agent_runner.py — the one-box EDIT helpers and the generalized,
PORT-aware generation prompt. Pure-function tests (no model calls):

    python3 scripts/orch/test_agent_runner.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_runner as ar  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class EditHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "apps", "demo")
        os.makedirs(self.app)

    def test_read_pending_edit_none(self):
        self.assertIsNone(ar.read_pending_edit(self.app))

    def test_read_pending_edit_text(self):
        with open(os.path.join(self.app, ar.EDIT_REQUEST_FILE), "w") as f:
            f.write("make the header blue\n")
        self.assertEqual(ar.read_pending_edit(self.app), "make the header blue")

    def test_clear_pending_edit(self):
        p = os.path.join(self.app, ar.EDIT_REQUEST_FILE)
        with open(p, "w") as f:
            f.write("x")
        ar.clear_pending_edit(self.app)
        self.assertFalse(os.path.exists(p))

    def test_current_app_files(self):
        with open(os.path.join(self.app, "index.html"), "w") as f:
            f.write("<h1>hi</h1>")
        with open(os.path.join(self.app, "server.py"), "w") as f:
            f.write("print(1)")
        files = dict(ar.current_app_files(self.app))
        self.assertIn("index.html", files)
        self.assertIn("server.py", files)
        self.assertEqual(files["index.html"], "<h1>hi</h1>")

    def test_build_edit_messages_includes_change_and_current_files(self):
        files = [("index.html", "<h1>hi</h1>")]
        system, user = ar.build_edit_messages("demo", files, "make the header blue")
        self.assertIn("make the header blue", user)
        self.assertIn("<h1>hi</h1>", user)
        self.assertIn("SMALLEST", system)


class GenerationPrompt(unittest.TestCase):
    def test_prompt_is_generic_and_port_aware(self):
        ctx = {
            "requirement": "A todo list app with add and complete.",
            "problem": "",
            "spec": "",
            "plan": "",
            "tasks": "",
        }
        system, user = ar.build_messages("todo-app", ctx, stack=ar.STACK_STDLIB)
        blob = (system + "\n" + user)
        # PORT-aware servers (so live previews never collide on 8000).
        self.assertIn("os.environ.get('PORT'", blob)
        # No URL-shortener specifics leaking into a generic builder prompt.
        self.assertNotIn("shorten", blob.lower())
        self.assertNotIn("Shorten button", blob)


class StackProfiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "apps", "demo")
        os.makedirs(self.app)

    def test_detect_stack_stdlib_vs_react(self):
        self.assertEqual(ar.detect_stack(self.app), ar.STACK_STDLIB)
        with open(os.path.join(self.app, "package.json"), "w") as f:
            f.write("{}")
        self.assertEqual(ar.detect_stack(self.app), ar.STACK_REACT)

    def test_current_app_files_is_multifile_and_skips_deps(self):
        os.makedirs(os.path.join(self.app, "src", "components"))
        os.makedirs(os.path.join(self.app, "node_modules", "react"))
        with open(os.path.join(self.app, "src", "App.tsx"), "w") as f:
            f.write("export default function App(){return null}")
        with open(os.path.join(self.app, "src", "components", "Board.tsx"), "w") as f:
            f.write("export const Board = () => null")
        with open(os.path.join(self.app, "node_modules", "react", "index.js"), "w") as f:
            f.write("module.exports = {}")
        files = dict(ar.current_app_files(self.app))
        self.assertIn(os.path.join("src", "App.tsx"), files)
        self.assertIn(os.path.join("src", "components", "Board.tsx"), files)
        self.assertFalse(any("node_modules" in k for k in files),
                         "deps must be excluded from editable files")

    def test_build_messages_selects_stack_prompt(self):
        ctx = {"requirement": "A kanban board", "problem": "",
               "spec": "", "plan": "", "tasks": ""}
        sys_s, _ = ar.build_messages("kb", ctx, stack=ar.STACK_STDLIB)
        self.assertIn("Python 3 standard library", sys_s)
        sys_r, usr_r = ar.build_messages("kb", ctx, stack=ar.STACK_REACT)
        blob = sys_r + usr_r
        self.assertIn("React", blob)
        self.assertIn("Vite", blob)
        self.assertIn("Tailwind", blob)
        self.assertNotIn("Python 3 standard library", sys_r)

    def test_stack_profile_registry_with_fallback(self):
        self.assertEqual(ar.stack_profile(ar.STACK_REACT)["name"], ar.STACK_REACT)
        self.assertEqual(ar.stack_profile(ar.STACK_STDLIB)["name"], ar.STACK_STDLIB)
        # Unknown stack falls back to stdlib (never crashes a build).
        self.assertEqual(ar.stack_profile("bogus-stack")["name"], ar.STACK_STDLIB)


class VerifyDispatch(unittest.TestCase):
    """N5 — `verify_app` dispatches to the right per-stack pipeline and fails
    gracefully (clear message, no crash) when the app is missing its entrypoints.
    These are fast/offline; the real npm pipeline is exercised by the system
    script `runner_verify_check.py`."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "apps", "demo")
        os.makedirs(self.app)

    def test_stdlib_verify_missing_tests_is_clear_error(self):
        ok, out = ar.verify_app(self.app, ar.STACK_STDLIB)
        self.assertFalse(ok)
        self.assertIn("test_app.py", out)

    def test_react_verify_missing_package_json_is_clear_error(self):
        ok, out = ar.verify_app(self.app, ar.STACK_REACT)
        self.assertFalse(ok)
        self.assertIn("package.json", out)

    def test_verify_app_detects_stack_from_manifest(self):
        # No stack arg: detect react from the .adf-stack.json manifest, so the
        # react pipeline (not stdlib) runs — proven by the package.json error.
        with open(os.path.join(self.app, ".adf-stack.json"), "w") as f:
            f.write('{"stack":"react-vite-sqlite"}')
        ok, out = ar.verify_app(self.app)
        self.assertFalse(ok)
        self.assertIn("package.json", out)

    def test_stack_profile_exposes_verify_callable(self):
        self.assertIs(ar.stack_profile(ar.STACK_REACT)["verify"], ar._react_verify)
        self.assertIs(ar.stack_profile(ar.STACK_STDLIB)["verify"], ar.run_verification)


class ScaffoldThenDiff(unittest.TestCase):
    """N7 — the react generate flow: locate the template, scaffold it into the
    app dir, strip the sample feature, and emit a generation prompt that matches
    the REAL template shape (plain-ESM `.mjs` server, routes relative to /api,
    vitest `app.inject` tests) — never the unrunnable `.ts` server it asked for."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "apps", "demo")

    def test_template_dir_resolves_to_checked_in_scaffold(self):
        tpl = ar.template_dir(REPO_ROOT, REPO_ROOT, ar.STACK_REACT)
        self.assertTrue(tpl and os.path.isdir(tpl), f"template not found: {tpl}")
        self.assertTrue(os.path.isfile(os.path.join(tpl, "package.json")))
        # stdlib has no template dir (single-file generation) -> None.
        self.assertIsNone(ar.template_dir(REPO_ROOT, REPO_ROOT, ar.STACK_STDLIB))

    def test_scaffold_app_copies_wiring_and_strips_sample(self):
        tpl = ar.template_dir(REPO_ROOT, REPO_ROOT, ar.STACK_REACT)
        ar.scaffold_app(self.app, tpl)
        # build wiring + lockfile (npm ci needs it) + manifest are copied.
        for rel in ("package.json", "package-lock.json", ".adf-stack.json",
                    "server/app.mjs", "server/db.mjs", "server/index.mjs",
                    "src/main.tsx", "vite.config.ts", "tsconfig.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.app, rel)),
                            f"scaffold missing {rel}")
        # the sample feature is stripped so the generated one is clean.
        self.assertFalse(os.path.isfile(os.path.join(self.app, "server/api/items.mjs")))
        self.assertFalse(os.path.isfile(os.path.join(self.app, "test/api.test.mjs")))
        # heavy dirs never copied.
        self.assertFalse(os.path.isdir(os.path.join(self.app, "node_modules")))
        # schema is reset (no leftover sample `items` table).
        schema = open(os.path.join(self.app, "schema.sql")).read().lower()
        self.assertNotIn("create table", schema)
        # detect_stack now sees a react app.
        self.assertEqual(ar.detect_stack(self.app), ar.STACK_REACT)

    def test_react_prompt_matches_template_shape(self):
        ctx = {"requirement": "A kanban board", "problem": "",
               "spec": "", "plan": "", "tasks": ""}
        system, user = ar.build_messages("kb", ctx, stack=ar.STACK_REACT)
        blob = system + "\n" + user
        # server routes are plain-ESM .mjs (the template runs node, not tsc on server).
        self.assertIn("server/api/", blob)
        self.assertIn(".mjs", blob)
        self.assertIn("../db.mjs", blob)
        # vitest tests use app.inject against buildApp, as .test.mjs.
        self.assertIn(".test.mjs", blob)
        self.assertIn("inject", blob)
        # MUST NOT ask for an unrunnable TypeScript server / test (the bug we fixed).
        self.assertNotIn("server/api/<feature>.ts", blob)
        self.assertNotIn(".test.ts", blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
