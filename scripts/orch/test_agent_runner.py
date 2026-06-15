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


if __name__ == "__main__":
    unittest.main(verbosity=2)
