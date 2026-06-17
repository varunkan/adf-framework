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
        # node_modules is WARM-CLONED from the template (PERF: npm ci is skipped).
        # The template carries one in normal use; tolerate its absence in a bare
        # test checkout (then it's simply not cloned — both are valid).
        tpl_has_nm = os.path.isdir(os.path.join(
            ar.template_dir(REPO_ROOT, REPO_ROOT, ar.STACK_REACT), "node_modules"))
        self.assertEqual(
            os.path.isdir(os.path.join(self.app, "node_modules")), tpl_has_nm,
            "node_modules should be cloned iff the template has one")
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


class Compaction(unittest.TestCase):
    """N12 — the runner uses the /compact engine where context actually blows up:
    the edit-mode payload (ALL app files) and the self-heal `files` block. Over
    budget, it keeps the files relevant to the request whole, outlines the rest,
    and writes a durable context card. A no-op (and importless-safe) under budget."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "apps", "demo")
        os.makedirs(self.app)
        self._prev = os.environ.get("ADF_CONTEXT_BUDGET_TOKENS")
        os.environ["ADF_CONTEXT_BUDGET_TOKENS"] = "200"  # force compaction in-test

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("ADF_CONTEXT_BUDGET_TOKENS", None)
        else:
            os.environ["ADF_CONTEXT_BUDGET_TOKENS"] = self._prev

    def test_edit_over_budget_outlines_rest_and_writes_card(self):
        files = [
            ("src/Header.tsx", "export const Header = () => <h1>hi</h1>\n"),
            ("src/Huge.tsx", "// huge\n" + "const x = 1\n" * 800),
            ("server/api/orders.mjs", "// orders\n" + "const y = 2\n" * 800),
        ]
        system, user = ar.assemble_edit(
            self.app, "demo", files, "make the Header blue", ar.STACK_REACT)
        # the relevant file is shown WHOLE...
        self.assertIn("src/Header.tsx", user)
        self.assertIn("export const Header", user)
        # ...the big, unrelated files are outlined, not dumped in full.
        self.assertIn("outline only", user.lower())
        self.assertIn("src/Huge.tsx", user)
        self.assertNotIn("const x = 1\nconst x = 1", user)  # full body NOT included
        # and the decision is recorded as a durable, reviewable context card.
        self.assertTrue(os.path.isdir(os.path.join(self.app, ".adf-context")))

    def test_edit_under_budget_is_a_no_op(self):
        os.environ["ADF_CONTEXT_BUDGET_TOKENS"] = "120000"
        files = [("a.tsx", "small"), ("b.mjs", "also small")]
        _system, user = ar.assemble_edit(
            self.app, "demo", files, "tweak a", ar.STACK_REACT)
        self.assertNotIn("outline only", user.lower())
        self.assertFalse(os.path.isdir(os.path.join(self.app, ".adf-context")))

    def test_build_edit_messages_accepts_file_summary(self):
        files = [("index.html", "<h1>hi</h1>")]
        _system, user = ar.build_edit_messages(
            "demo", files, "make it blue", ar.STACK_STDLIB,
            file_summary="- src/Other.tsx (40 lines)")
        self.assertIn("src/Other.tsx", user)
        self.assertIn("<h1>hi</h1>", user)

    def test_fix_messages_compacts_a_large_payload(self):
        files = [
            ("server/api/orders.mjs", "// the failing file\n" + "bad();\n" * 5),
            ("src/Huge.tsx", "// unrelated\n" + "const z = 3\n" * 800),
        ]
        msgs = ar.fix_messages(
            "sys", "usr", files,
            "server/api/orders.mjs:2 SyntaxError: orders route broke",
            ar.STACK_REACT)
        fixer = msgs[-1]["content"]
        self.assertIn("the failing file", fixer)      # the relevant file stays whole
        self.assertIn("src/Huge.tsx", fixer)          # the rest is outlined
        self.assertNotIn("const z = 3\nconst z = 3", fixer)


class ResolveFeatureId(unittest.TestCase):
    """The build failed because the runner mis-parsed the feature id out of prose
    ('implement phase 7' -> 'phase' -> 'no spec found'). The orchestrator now passes
    ADF_FEATURE_ID explicitly, which must always win."""

    def test_explicit_env_id_wins(self):
        self.assertEqual(
            ar.resolve_feature_id("@orch-orchestrator resume whatever",
                                  {"ADF_FEATURE_ID": "snake-ladder-games"}),
            "snake-ladder-games")

    def test_falls_back_to_prompt_when_no_env(self):
        self.assertEqual(
            ar.resolve_feature_id("@orch-orchestrator resume my-todo", {}),
            "my-todo")

    def test_rejects_the_phase_misparse(self):
        # the exact bug: a prompt that would parse to 'phase' must NOT become a
        # feature id (it would look up a non-existent spec and fail the build).
        self.assertIsNone(ar.resolve_feature_id("implement phase 7", {}))


class WarmNodeModules(unittest.TestCase):
    """Cloning the template's node_modules into each app makes `npm ci` a no-op —
    10-50x on first build + a deterministic, offline install."""

    def test_clones_template_node_modules_into_app(self):
        tpl = tempfile.mkdtemp()
        os.makedirs(os.path.join(tpl, "node_modules", "react"))
        with open(os.path.join(tpl, "node_modules", "react", "index.js"), "w") as f:
            f.write("module.exports = {}\n")
        app = tempfile.mkdtemp()
        ok = ar.warm_node_modules(tpl, app)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(
            os.path.join(app, "node_modules", "react", "index.js")))

    def test_no_op_when_template_has_none_or_app_has_one(self):
        tpl = tempfile.mkdtemp()  # no node_modules
        app = tempfile.mkdtemp()
        self.assertFalse(ar.warm_node_modules(tpl, app))
        # app already has node_modules -> don't clobber
        os.makedirs(os.path.join(tpl, "node_modules"))
        os.makedirs(os.path.join(app, "node_modules"))
        self.assertFalse(ar.warm_node_modules(tpl, app))


class ScrubbedEnv(unittest.TestCase):
    """Model-generated code, npm, and the spawned app must NEVER inherit ADF's API
    keys — that would hand the operator's secrets to arbitrary code."""

    def test_secrets_are_removed_but_normal_vars_kept(self):
        keys = ["ANTHROPIC_API_KEY", "NVIDIA_API_KEY", "OPENAI_API_KEY",
                "SOME_TOKEN", "DB_PASSWORD", "MY_SECRET"]
        saved = {k: os.environ.get(k) for k in keys + ["PAGER"]}
        try:
            for k in keys:
                os.environ[k] = "sensitive"
            os.environ["PATH"] = os.environ.get("PATH", "/usr/bin")
            os.environ["PAGER"] = "less"  # an interactive setting that must be forced off
            env = ar.scrubbed_env(PORT="8000")
            for k in keys:
                self.assertNotIn(k, env, f"{k} must be scrubbed")
            self.assertIn("PATH", env)            # normal vars kept
            self.assertEqual(env["PORT"], "8000")  # extras applied
            # Non-interactive hardening is applied so no child blocks on a pager.
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(env["PAGER"], "cat")
            self.assertEqual(env["CI"], "1")
            self.assertEqual(env["npm_config_yes"], "true")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class RetryAndClassify(unittest.TestCase):
    """5.3 — a transient provider status retries the SAME backend before
    generate() falls over to a weaker one (no silent 529→NVIDIA downgrade)."""

    def test_classify(self):
        self.assertEqual(ar.classify_http_status(429), "rate_limit")
        self.assertEqual(ar.classify_http_status(529), "capacity")
        self.assertEqual(ar.classify_http_status(503), "server_error")
        self.assertEqual(ar.classify_http_status(402), "quota")
        self.assertEqual(ar.classify_http_status(400), "client")

    def test_retries_transient_then_succeeds(self):
        n = {"c": 0}

        def call(messages, timeout):
            n["c"] += 1
            if n["c"] < 3:
                raise ar.HttpError(529)
            return ("ok", {})

        res = ar.call_with_retry(call, [], 10, attempts=5, sleeper=lambda s: None)
        self.assertEqual(res, ("ok", {}))
        self.assertEqual(n["c"], 3)

    def test_no_retry_on_client_error(self):
        n = {"c": 0}

        def call(m, t):
            n["c"] += 1
            raise ar.HttpError(400)

        self.assertIsNone(
            ar.call_with_retry(call, [], 10, attempts=5, sleeper=lambda s: None))
        self.assertEqual(n["c"], 1, "a 400 must not be retried")

    def test_exhausts_on_persistent_transient(self):
        n = {"c": 0}

        def call(m, t):
            n["c"] += 1
            raise ar.HttpError(529)

        self.assertIsNone(
            ar.call_with_retry(call, [], 10, attempts=3, sleeper=lambda s: None))
        self.assertEqual(n["c"], 3, "tries exactly `attempts` times then gives up")

    def test_missing_key_returns_none_without_retry(self):
        n = {"c": 0}

        def call(m, t):
            n["c"] += 1
            return None  # e.g. no API key configured

        self.assertIsNone(
            ar.call_with_retry(call, [], 10, attempts=3, sleeper=lambda s: None))
        self.assertEqual(n["c"], 1)

    def test_backoff_honors_retry_after_within_cap(self):
        self.assertEqual(
            ar._retry_backoff_seconds("rate_limit", 0, retry_after="5"), 5.0)
        cap = float(os.environ.get("ADF_RUNNER_RETRY_CAP_SEC", "20"))
        self.assertEqual(
            ar._retry_backoff_seconds("rate_limit", 0, retry_after="9999"), cap)


class FileWriteEvents(unittest.TestCase):
    """N21 — the runner narrates each file as it writes it, so a 1-3 min build
    doesn't go dark. Each write emits a structured `file_write` progress line the
    phase runner turns into a live trace span."""

    def test_write_files_emits_progress_events(self):
        import contextlib
        import io
        import json as _json
        tmp = tempfile.mkdtemp()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ar.write_files(tmp, "demo",
                           [("src/App.tsx", "x"), ("server/index.mjs", "y")])
        events = [_json.loads(ln) for ln in buf.getvalue().splitlines()
                  if ln.strip().startswith("{")]
        fw = [e for e in events if e.get("type") == "file_write"]
        self.assertEqual(len(fw), 2)
        self.assertEqual(fw[0]["path"], "src/App.tsx")
        self.assertEqual(fw[0]["index"], 1)
        self.assertEqual(fw[0]["total"], 2)
        self.assertEqual(fw[1]["index"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
