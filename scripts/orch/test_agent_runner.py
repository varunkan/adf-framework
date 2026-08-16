#!/usr/bin/env python3
"""Unit tests for agent_runner.py — the one-box EDIT helpers and the generalized,
PORT-aware generation prompt. Pure-function tests (no model calls):

    python3 scripts/orch/test_agent_runner.py
"""
import contextlib
import http.client as http_client
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

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

    def test_expo_template_resolves_and_is_a_working_scaffold(self):
        # M2: the expo-rn template exists with the wiring a mobile app needs.
        tpl = ar.template_dir(REPO_ROOT, REPO_ROOT, ar.STACK_EXPO)
        self.assertTrue(tpl and os.path.isdir(tpl), f"expo template not found: {tpl}")
        for rel in ("package.json", "app.json", ".adf-stack.json", "tsconfig.json",
                    "babel.config.js", "app/_layout.tsx", "app/index.tsx",
                    "src/db.ts", "serve-web.mjs",
                    "src/components/ui/Button.tsx", "src/components/ui/index.ts"):
            self.assertTrue(os.path.isfile(os.path.join(tpl, rel)), rel)
        manifest = json.load(open(os.path.join(tpl, ".adf-stack.json")))
        self.assertEqual(manifest["stack"], "expo-rn")
        self.assertEqual(manifest["port_env"], "PORT")

    def test_scaffold_expo_strips_sample_and_resets_layout(self):
        # M3/M5 + MM3: scaffolding strips the sample app/ routes + data layer, resets
        # app/_layout.tsx to a bare Stack, and creates NO spurious schema.sql.
        tpl = ar.template_dir(REPO_ROOT, REPO_ROOT, ar.STACK_EXPO)
        ar.scaffold_app(self.app, tpl)
        for rel in ("package.json", "app.json", ".adf-stack.json", "app/_layout.tsx",
                    "serve-web.mjs", "src/components/ui/Button.tsx",
                    "src/theme/tokens.ts"):
            self.assertTrue(os.path.isfile(os.path.join(self.app, rel)), rel)
        # sample feature (routes + data layer + test) stripped
        for rel in ("app/index.tsx", "app/[id].tsx", "src/db.ts",
                    "src/hooks/useItems.ts", "__tests__/sample.test.tsx"):
            self.assertFalse(os.path.isfile(os.path.join(self.app, rel)), rel)
        # _layout reset to a bare Stack (no reference to a stripped screen)
        layout = open(os.path.join(self.app, "app", "_layout.tsx")).read()
        self.assertIn("Stack", layout)
        self.assertNotIn("Stack.Screen", layout)
        # no spurious schema.sql for a mobile app
        self.assertFalse(os.path.isfile(os.path.join(self.app, "schema.sql")))
        self.assertEqual(ar.detect_stack(self.app), ar.STACK_EXPO)

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

    def test_classify_auth_and_server_statuses(self):
        self.assertEqual(ar.classify_http_status(401), "auth")
        self.assertEqual(ar.classify_http_status(403), "auth")
        self.assertEqual(ar.classify_http_status(500), "server_error")
        self.assertEqual(ar.classify_http_status(504), "unknown")

    def test_backoff_clamps_garbage_retry_after(self):
        # bug#1: a negative / non-finite Retry-After must never become sleep(-1).
        import math as _m
        for bad in ("-1", "-999", "inf", "-inf", "nan", "garbage", None):
            d = ar._retry_backoff_seconds("rate_limit", 0, retry_after=bad)
            self.assertTrue(_m.isfinite(d) and d >= 0.0, f"bad delay for {bad!r}: {d}")

    def test_http_post_json_raises_typed_httperror(self):
        import io
        import urllib.error
        orig = ar.urllib.request.urlopen

        def fake(*a, **k):
            raise urllib.error.HTTPError(
                "http://x", 529, "overloaded",
                {"retry-after": "3"}, io.BytesIO(b"busy"))

        ar.urllib.request.urlopen = fake
        try:
            with self.assertRaises(ar.HttpError) as cm:
                ar.http_post_json("https://x", {}, {}, 1)
            self.assertEqual(cm.exception.status, 529)
            self.assertEqual(cm.exception.retry_after, "3")
        finally:
            ar.urllib.request.urlopen = orig


class OutputSinkSpill(unittest.TestCase):
    """5.6 — verify logs keep the HEAD (where the first error is) + the tail, and
    spill the complete log to disk; the old out[-3000:] kept only the tail."""

    def _app(self):
        d = tempfile.mkdtemp(prefix="adf-sink-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_short_text_passes_through_and_spills(self):
        app = self._app()
        s = ar._spill_and_bound(app, "build", "all good")
        self.assertEqual(s, "all good")
        with open(os.path.join(app, ".adf-logs", "build.log")) as f:
            self.assertEqual(f.read(), "all good")

    def test_long_text_keeps_head_and_tail_and_spills_full(self):
        app = self._app()
        full = "HEAD_ERROR " + ("x" * 5000) + " TAIL_SUMMARY"
        s = ar._spill_and_bound(app, "test", full, head=60, tail=60)
        self.assertIn("HEAD_ERROR", s)   # the first error — old tail-slice dropped it
        self.assertIn("TAIL_SUMMARY", s)
        self.assertIn("elided", s)
        self.assertLess(len(s), len(full))
        with open(os.path.join(app, ".adf-logs", "test.log")) as f:
            self.assertEqual(f.read(), full)  # complete log preserved, nothing lost


class RecallBlockers(unittest.TestCase):
    """5.4 — past failures recorded in learnings.jsonl are read back into the build
    prompt (the loop ADF collected signal for but never closed)."""

    def _repo(self, entries):
        d = tempfile.mkdtemp(prefix="adf-recall-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = os.path.join(d, ".adf", "orchestration")
        os.makedirs(p)
        with open(os.path.join(p, "learnings.jsonl"), "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        return d

    def test_empty_when_no_learnings(self):
        d = tempfile.mkdtemp(prefix="adf-recall-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.assertEqual(ar.recall_blockers(d), "")

    def test_ranks_phase_failures_and_includes_fix(self):
        repo = self._repo([
            {"phase": 7, "kind": "failure", "blockers": ["tsc: missing type X"]},
            {"phase": 7, "kind": "failure",
             "blockers": ["tsc: missing type X", "vitest red"]},
            {"phase": 7, "kind": "heal", "fix": "add the X interface to types.ts"},
            {"phase": 6, "kind": "failure", "blockers": ["wrong-phase blocker"]},
        ])
        block = ar.recall_blockers(repo, phase=7)
        self.assertIn("tsc: missing type X (seen 2×)", block)  # ranked first
        self.assertIn("vitest red", block)
        self.assertIn("add the X interface", block)            # fix surfaced
        self.assertNotIn("wrong-phase blocker", block)         # other phase excluded

    def test_disabled_by_env(self):
        repo = self._repo([{"phase": 7, "kind": "failure", "blockers": ["x"]}])
        os.environ["ADF_RECALL_BLOCKERS"] = "0"
        try:
            self.assertEqual(ar.recall_blockers(repo, phase=7), "")
        finally:
            os.environ.pop("ADF_RECALL_BLOCKERS", None)

    def test_ignores_non_object_json_lines(self):
        # bug#5: a bare-value JSON line must be skipped, not crash with AttributeError
        repo = self._repo([])
        path = os.path.join(repo, ".adf", "orchestration", "learnings.jsonl")
        with open(path, "w") as f:
            f.write("42\n\"x\"\ntrue\n[1,2]\n")
            f.write(json.dumps(
                {"phase": 7, "kind": "failure", "blockers": ["real-one"]}) + "\n")
        block = ar.recall_blockers(repo, phase=7)
        self.assertIn("real-one", block)  # didn't crash; found the valid record

    def test_record_build_outcome_then_recall_roundtrip(self):
        # bug#4: the runner records its OWN phase-7 outcomes so recall is not inert.
        repo = tempfile.mkdtemp(prefix="adf-recall-")
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        ar.record_build_outcome(
            repo, "feat-a", False, "BUILD FAILED (tsc): missing type Foo\nmore")
        self.assertIn("BUILD FAILED (tsc): missing type Foo",
                      ar.recall_blockers(repo, phase=7))
        ar.record_build_outcome(repo, "feat-b", True, "")  # success → no blocker
        self.assertIn("BUILD FAILED", ar.recall_blockers(repo, phase=7))


class EditGuards(unittest.TestCase):
    """5.7/5.8 — reject blind edits to outlined-only files; flag/skip stale
    overwrites so a model can't clobber a file it never fully saw or that changed
    out-of-band since ADF read it."""

    def _app(self, files):
        d = tempfile.mkdtemp(prefix="adf-guard-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for rel, content in files:
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p) or d, exist_ok=True)
            with open(p, "w") as f:
                f.write(content)
        return d

    def test_rejects_outlined_only_file(self):
        app = self._app([("src/A.tsx", "orig")])
        hashes = {"src/A.tsx": ar._content_hash("orig")}
        safe, notes = ar.apply_edit_guards(
            app, [("src/A.tsx", "hallucinated")], hashes, {"src/A.tsx"})
        self.assertEqual(safe, [])  # blind edit dropped
        self.assertTrue(any("outlined-only" in n for n in notes))

    def test_passes_unchanged_and_new_files(self):
        app = self._app([("src/A.tsx", "orig")])
        hashes = {"src/A.tsx": ar._content_hash("orig")}
        emitted = [("src/A.tsx", "edited"), ("src/New.tsx", "brand new")]
        safe, notes = ar.apply_edit_guards(app, emitted, hashes, set())
        self.assertEqual(len(safe), 2)
        self.assertFalse(notes)

    def test_warns_on_stale_but_still_writes_by_default(self):
        app = self._app([("src/A.tsx", "DISK CHANGED OUT OF BAND")])
        hashes = {"src/A.tsx": ar._content_hash("orig")}  # read-time hash differs
        safe, notes = ar.apply_edit_guards(
            app, [("src/A.tsx", "edited")], hashes, set())
        self.assertEqual(len(safe), 1)
        self.assertTrue(any("stale" in n.lower() for n in notes))

    def test_blocks_stale_when_configured(self):
        app = self._app([("src/A.tsx", "DISK CHANGED OUT OF BAND")])
        hashes = {"src/A.tsx": ar._content_hash("orig")}
        os.environ["ADF_EDIT_STALE_GUARD"] = "block"
        try:
            safe, notes = ar.apply_edit_guards(
                app, [("src/A.tsx", "edited")], hashes, set())
        finally:
            os.environ.pop("ADF_EDIT_STALE_GUARD", None)
        self.assertEqual(safe, [])
        self.assertTrue(any("skipped STALE" in n for n in notes))

    def test_refreshed_baseline_is_not_flagged_stale(self):
        # bug#2: after the runner writes a file, the next attempt's baseline is the
        # written content (refreshed in main); re-editing it must NOT read as stale.
        app = self._app([("src/A.tsx", "v2\n")])  # disk holds what the runner wrote
        hashes = {"src/A.tsx": ar._content_hash("v2\n")}  # refreshed baseline
        safe, notes = ar.apply_edit_guards(
            app, [("src/A.tsx", "v3")], hashes, set())
        self.assertEqual(len(safe), 1)
        self.assertFalse(any("stale" in n.lower() for n in notes))


class CompletionAudit(unittest.TestCase):
    """5.9 — a shaped feature's generated tests must cover the shape's required
    behavior before sealing; a vacuous test (GET→200 only) is flagged so one more
    heal closes the gap. Deterministic, $0, never fails an already-verified build."""

    CRUD_CTX = {"requirement": "A to-do list where you add, edit and delete tasks."}
    SINGLE_CTX = {"requirement":
                  "A settings page to view and update your profile preferences."}

    def _app(self, test_body):
        d = tempfile.mkdtemp(prefix="adf-audit-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        os.makedirs(os.path.join(d, "test"))
        with open(os.path.join(d, "test", "feature.test.mjs"), "w") as f:
            f.write(test_body)
        return d

    AUTH_CTX = {"requirement": "A login and signup page with user sessions."}

    def test_auth_requires_a_401_test(self):
        # SOLID-3: an auth feature whose tests never assert the 401 failure path
        # is flagged (a login that only tests the happy path is a security gap).
        vacuous = self._app(
            "const r = await app.inject({ method: 'POST', url: '/api/login',"
            " payload: { email: 'a', password: 'b' } });\n"
            "expect(r.statusCode).toBe(200);")
        gaps = ar.audit_completion(vacuous, ar.STACK_REACT, self.AUTH_CTX, "auth")
        self.assertTrue(any("401" in g for g in gaps), gaps)
        full = self._app(
            "const ok = await app.inject({ method: 'POST', url: '/api/login',"
            " payload: { email: 'a', password: 'b' } });\n"
            "expect(ok.statusCode).toBe(200);\n"
            "const bad = await app.inject({ method: 'POST', url: '/api/login',"
            " payload: { email: 'a', password: 'wrong' } });\n"
            "expect(bad.statusCode).toBe(401);")
        self.assertEqual(
            ar.audit_completion(full, ar.STACK_REACT, self.AUTH_CTX, "auth"), [])

    def test_single_record_requires_a_validation_test(self):
        # bug#8 + SOLID-1: a PUT-200-only single-record test is flagged (its shape
        # contract demands PUT-invalid → 400); a real PUT + 400 assertion passes.
        vacuous = self._app(
            "const r = await app.inject({ method: 'PUT', url: '/api/settings',"
            " payload: { theme: 'dark' } });\n"
            "expect(r.statusCode).toBe(200);")
        gaps = ar.audit_completion(vacuous, ar.STACK_REACT, self.SINGLE_CTX,
                                   "settings")
        self.assertTrue(any("400" in g for g in gaps), gaps)
        full = self._app(
            "const r = await app.inject({ method: 'PUT', url: '/api/settings',"
            " payload: { theme: 'dark' } });\n"
            "expect(r.statusCode).toBe(200);\n"
            "const bad = await app.inject({ method: 'PUT', url: '/api/settings',"
            " payload: { theme: 123 } });\n"
            "expect(bad.statusCode).toBe(400);")
        self.assertEqual(
            ar.audit_completion(full, ar.STACK_REACT, self.SINGLE_CTX, "settings"),
            [])

    def test_flags_vacuous_crud_test(self):
        app = self._app("it('lists', async () => {"
                        " const r = await app.inject({method:'GET', url:'/api/tasks'});"
                        " expect(r.statusCode).toBe(200) })")
        gaps = ar.audit_completion(app, ar.STACK_REACT, self.CRUD_CTX, "todo")
        self.assertTrue(any("POST" in g for g in gaps))
        self.assertTrue(any(("400" in g or "404" in g) for g in gaps))

    def test_mention_in_a_comment_is_not_real_coverage(self):
        # SOLID-1: a test that only MENTIONS the verb/status in prose/comments but
        # never actually injects/asserts it must STILL be flagged (the old regex
        # passed on bare presence — `\b400\b` in a comment counted as coverage).
        app = self._app(
            "it('lists', async () => {\n"
            "  // TODO: also POST and assert a 400 on invalid input\n"
            "  const r = await app.inject({ method: 'GET', url: '/api/tasks' });\n"
            "  expect(r.statusCode).toBe(200);\n"
            "});")
        gaps = ar.audit_completion(app, ar.STACK_REACT, self.CRUD_CTX, "todo")
        self.assertTrue(any("POST" in g for g in gaps), gaps)
        self.assertTrue(any(("400" in g or "404" in g) for g in gaps), gaps)

    def test_complete_crud_test_has_no_gaps(self):
        app = self._app(
            "it('creates and validates', async () => {\n"
            "  const c = await app.inject({ method: 'POST', url: '/api/tasks',"
            " payload: { title: 'x' } });\n"
            "  expect(c.statusCode).toBe(201);\n"
            "  const bad = await app.inject({ method: 'POST', url: '/api/tasks',"
            " payload: {} });\n"
            "  expect(bad.statusCode).toBe(400);\n"
            "  const del = await app.inject({ method: 'DELETE',"
            " url: '/api/tasks/999' });\n"
            "  expect(del.statusCode).toBe(404);\n"
            "});")
        self.assertEqual(
            ar.audit_completion(app, ar.STACK_REACT, self.CRUD_CTX, "todo"), [])

    def test_stdlib_stack_is_not_audited(self):
        app = self._app("anything")
        self.assertEqual(
            ar.audit_completion(app, ar.STACK_STDLIB, self.CRUD_CTX, "todo"), [])

    def test_disabled_by_env(self):
        app = self._app("GET only 200")
        os.environ["ADF_COMPLETION_AUDIT"] = "0"
        try:
            self.assertEqual(
                ar.audit_completion(app, ar.STACK_REACT, self.CRUD_CTX, "todo"), [])
        finally:
            os.environ.pop("ADF_COMPLETION_AUDIT", None)

    def test_missing_tests_flagged(self):
        d = tempfile.mkdtemp(prefix="adf-audit-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        gaps = ar.audit_completion(d, ar.STACK_REACT, self.CRUD_CTX, "todo")
        self.assertTrue(any("no test file" in g for g in gaps))

    # --- SOLID-2: shape-aware render audit -------------------------------
    _COMPLETE_CRUD = (
        "const c = await app.inject({ method: 'POST', url: '/api/tasks',"
        " payload: { title: 'x' } }); expect(c.statusCode).toBe(201);\n"
        "const bad = await app.inject({ method: 'POST', url: '/api/tasks',"
        " payload: {} }); expect(bad.statusCode).toBe(400);")

    def _with_render_stats(self, stats):
        # a crud-list app whose TESTS are complete, so only the render gap can show
        app = self._app(self._COMPLETE_CRUD)
        vdir = os.path.join(app, ".adf-visual")
        os.makedirs(vdir)
        with open(os.path.join(vdir, "render-stats.json"), "w") as f:
            json.dump(stats, f)
        return app

    def test_render_audit_flags_missing_controls(self):
        # a crud-list that rendered NO button/input (blank/broken UI) is flagged
        # even though its tests pass — catches "renders a wrong/empty screen".
        app = self._with_render_stats({"buttons": 0, "inputs": 0})
        gaps = ar.audit_completion(app, ar.STACK_REACT, self.CRUD_CTX, "todo")
        self.assertTrue(any("button" in g.lower() or "input" in g.lower()
                            for g in gaps), gaps)

    def test_render_audit_passes_with_controls(self):
        app = self._with_render_stats({"buttons": 2, "inputs": 1})
        self.assertEqual(
            ar.audit_completion(app, ar.STACK_REACT, self.CRUD_CTX, "todo"), [])

    def test_render_audit_skipped_when_not_measured(self):
        # no render-stats.json (browser absent / disabled) → no render gap
        app = self._app(self._COMPLETE_CRUD)
        self.assertEqual(
            ar.audit_completion(app, ar.STACK_REACT, self.CRUD_CTX, "todo"), [])


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


class MobileCompletionAudit(unittest.TestCase):
    """M8 — the completion audit runs for mobile too, with @testing-library/
    react-native signals (render/fireEvent/getBy*), not app.inject."""

    CTX = {"requirement": "A to-do list to add and delete tasks."}  # crud-list

    def _app(self, body):
        d = tempfile.mkdtemp(prefix="adf-maudit-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        os.makedirs(os.path.join(d, "__tests__"))
        with open(os.path.join(d, "__tests__", "feature.test.tsx"), "w") as f:
            f.write(body)
        return d

    def test_flags_render_only_mobile_test(self):
        # renders but never drives an interaction or asserts → flagged
        app = self._app("it('renders', () => { render(<App />); });")
        gaps = ar.audit_completion(app, ar.STACK_EXPO, self.CTX, "todo")
        self.assertTrue(
            any("fireEvent" in g or "getBy" in g for g in gaps), gaps)

    def test_complete_mobile_test_passes(self):
        app = self._app(
            "it('adds an item', () => {\n"
            "  const { getByText, getByPlaceholderText } = render(<App />);\n"
            "  fireEvent.changeText(getByPlaceholderText('Enter a title'), 'Milk');\n"
            "  fireEvent.press(getByText('Add'));\n"
            "  expect(getByText('Milk')).toBeTruthy();\n"
            "});")
        self.assertEqual(
            ar.audit_completion(app, ar.STACK_EXPO, self.CTX, "todo"), [])

    def test_mobile_test_found_in_co_located_file(self):
        d = tempfile.mkdtemp(prefix="adf-maudit-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        os.makedirs(os.path.join(d, "src"))
        with open(os.path.join(d, "src", "Todo.test.tsx"), "w") as f:
            f.write("render(<App />); fireEvent.press(getByText('Add'));")
        gaps = ar.audit_completion(d, ar.STACK_EXPO, self.CTX, "todo")
        self.assertFalse(any("no test file" in g for g in gaps), gaps)


class MobileStackProfile(unittest.TestCase):
    """M1 — the cross-platform mobile (Expo / React Native) StackProfile: the
    generation + verify CONTRACT + dispatch that lets ADF build iOS/Android apps via
    the same governed pipeline as web. Fully unit-testable in a dev box; the live
    device build + signed artifact are later nodes (M2..M7)."""

    CTX = {"requirement": "A to-do list to add and delete tasks.",
           "problem": "", "spec": "", "plan": "", "tasks": ""}

    def _tmp(self):
        d = tempfile.mkdtemp(prefix="adf-expo-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_expo_stack_registered(self):
        self.assertEqual(ar.STACK_EXPO, "expo-rn")
        self.assertIn("expo-rn", ar._STACK_PROFILES)
        prof = ar._STACK_PROFILES["expo-rn"]
        self.assertIn("build_messages", prof)
        self.assertIn("verify", prof)

    def test_detect_stack_reads_expo_manifest(self):
        d = self._tmp()
        with open(os.path.join(d, ".adf-stack.json"), "w") as f:
            json.dump({"stack": "expo-rn"}, f)
        with open(os.path.join(d, "package.json"), "w") as f:  # conflicting signal
            f.write("{}")
        self.assertEqual(ar.detect_stack(d), ar.STACK_EXPO)   # manifest wins

    def test_stack_profile_lookup_and_unknown_fallback(self):
        self.assertEqual(ar.stack_profile(ar.STACK_EXPO)["name"], "expo-rn")
        self.assertEqual(ar.stack_profile("bogus")["name"], ar.STACK_STDLIB)

    def test_build_messages_emits_expo_prompt(self):
        system, user = ar.build_messages("kb", self.CTX, stack=ar.STACK_EXPO)
        blob = system + user
        for token in ("React Native", "Expo", "react-native-web", "expo-sqlite"):
            self.assertIn(token, blob, token)
        self.assertIn("<<<FILE:", blob)
        self.assertNotIn("Python 3 standard library", system)
        rsys, ruser = ar.build_messages("kb", self.CTX, stack=ar.STACK_REACT)
        self.assertNotEqual(blob, rsys + ruser)        # distinct from the web prompt

    def test_template_mapping(self):
        self.assertEqual(ar._STACK_TEMPLATES[ar.STACK_EXPO], "expo-rn")

    def test_stack_profile_exposes_expo_verify_callable(self):
        self.assertIs(ar.stack_profile(ar.STACK_EXPO)["verify"], ar._expo_verify)

    def test_expo_verify_missing_entrypoint_is_clear_error(self):
        ok, out = ar.verify_app(self._tmp(), ar.STACK_EXPO)
        self.assertFalse(ok)
        self.assertTrue("app.json" in out or "package.json" in out)
        self.assertNotIn("Traceback", out)

    def test_verify_app_detects_expo_from_manifest(self):
        d = self._tmp()
        with open(os.path.join(d, ".adf-stack.json"), "w") as f:
            json.dump({"stack": "expo-rn"}, f)
        ok, out = ar.verify_app(d)        # no stack arg → detect → expo pipeline
        self.assertFalse(ok)
        self.assertIn("Expo", out)        # the expo message, not stdlib's

    def test_native_build_skipped_when_toolchain_absent_and_not_strict(self):
        orig = ar._native_toolchain
        ar._native_toolchain = lambda: None
        os.environ.pop("ADF_MOBILE_NATIVE", None)
        try:
            ok, msg = ar._expo_native_stage(self._tmp())
        finally:
            ar._native_toolchain = orig
        self.assertTrue(ok)
        self.assertIn("skip", msg.lower())

    def test_native_build_strict_fails_when_toolchain_absent(self):
        orig = ar._native_toolchain
        ar._native_toolchain = lambda: None
        os.environ["ADF_MOBILE_NATIVE"] = "strict"
        try:
            ok, msg = ar._expo_native_stage(self._tmp())
        finally:
            ar._native_toolchain = orig
            os.environ.pop("ADF_MOBILE_NATIVE", None)
        self.assertFalse(ok)
        self.assertIn("native build", msg.lower())


class MobileReviewFixes(unittest.TestCase):
    """Regression tests for the multi-pass review findings: scaffold must not copy
    build artifacts (which would seal STALE render facts), and render facts seal only
    platforms that ACTUALLY rendered."""

    def _tmp(self):
        d = tempfile.mkdtemp(prefix="adf-rev-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_scaffold_does_not_copy_build_artifacts(self):
        repo_root = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        tpl = ar.template_dir(repo_root, repo_root, ar.STACK_EXPO)
        d = self._tmp()
        ar.scaffold_app(d, tpl)
        self.assertFalse(os.path.isdir(os.path.join(d, ".adf-visual")),
                         "scaffold copied the template's .adf-visual artifacts")
        self.assertFalse(os.path.isdir(os.path.join(d, ".adf-proof")))
        self.assertIsNone(ar.read_render_facts(d))   # no STALE render facts inherited

    def test_render_facts_seal_only_real_platforms(self):
        d = self._tmp()
        none = ar._write_render_facts(d, [])         # nothing rendered
        self.assertEqual(none["platforms"], [])
        self.assertFalse(none["proven"])             # never a false "proven" claim
        web = ar._write_render_facts(d, ["web"])     # only web rendered
        self.assertEqual(web["platforms"], ["web"])
        self.assertTrue(web["proven"])

    def test_main_gate_scaffolds_expo_not_just_react(self):
        # THE regression that the multi-pass review caught: the main() build gate was
        # `stack == STACK_REACT`, so every fresh expo-rn build skipped the scaffold and
        # then failed verify. No test exercised the gate (they call scaffold_app
        # directly), so it slipped through. The predicate is now a pure helper — this
        # asserts BOTH template stacks scaffold, and only when un-scaffolded.
        empty = self._tmp()
        self.assertTrue(ar.should_scaffold(ar.STACK_EXPO, empty),
                        "fresh expo build must scaffold (the bug: it did not)")
        self.assertTrue(ar.should_scaffold(ar.STACK_REACT, empty))
        # stdlib has its own server.py scaffold, not the template path.
        self.assertFalse(ar.should_scaffold(ar.STACK_STDLIB, empty))
        # an already-scaffolded app (has package.json) is not re-scaffolded.
        scaffolded = self._tmp()
        with open(os.path.join(scaffolded, "package.json"), "w") as fh:
            fh.write("{}")
        self.assertFalse(ar.should_scaffold(ar.STACK_EXPO, scaffolded))
        self.assertFalse(ar.should_scaffold(ar.STACK_REACT, scaffolded))


class MobileHealAndSummaryPaths(unittest.TestCase):
    """Bug fix: the self-heal hint, the edit-mode architecture description, and the
    build summary must NOT route an Expo (mobile) build into the stdlib-Python branch
    — a mobile failure was getting `server.py`/`test_app.py`/`schema.sql` guidance."""

    def test_fix_messages_expo_is_mobile_aware_not_python(self):
        msgs = ar.fix_messages(
            "sys", "usr", [("app/index.tsx", "x")], "boom", ar.STACK_EXPO)
        fixer = msgs[-1]["content"]
        self.assertIn("app/", fixer)              # mobile route guidance
        self.assertNotIn("server.py", fixer)
        self.assertNotIn("test_app.py", fixer)
        self.assertNotIn("schema.sql", fixer)

    def test_build_edit_messages_expo_arch_is_mobile(self):
        system, _user = ar.build_edit_messages(
            "kb", [("app/index.tsx", "x")], "make the button green", ar.STACK_EXPO)
        self.assertIn("Expo", system)
        self.assertIn("mobile app", system)
        self.assertNotIn("Python stdlib", system)
        self.assertNotIn("Fastify", system)


class JestHoistHeal(unittest.TestCase):
    """The deterministic self-heal hint for the jest.mock() hoisting failure class.
    A real mobile build failed verify 3x on this exact error and never converged
    because the cure was buried; the hint now names the offending variable and rides
    at the TOP of the failure block fed back to the model."""

    # The REAL jest output captured from the failed mobile-habit-tracker build.
    REAL = ("TESTS FAILED (jest):\nFAIL __tests__/habits.test.tsx\n  ● Test suite "
            "failed to run\n\n    ReferenceError: The module factory of `jest.mock()` "
            "is not allowed to reference any out-of-scope variables.\n    Invalid "
            "variable access: store\n    Allowed objects: Array, ArrayBuffer, ...")

    def test_fires_and_names_the_offending_variable(self):
        hint = ar.jest_hoist_hint(self.REAL)
        self.assertTrue(hint)
        self.assertIn("store", hint)          # the ACTUAL offending var
        self.assertIn("mockStore", hint)      # the rename it should use
        self.assertIn("data.test.tsx", hint)  # points at the canonical few-shot

    def test_silent_on_unrelated_failures(self):
        # must not false-positive on react/stdlib/other failures (it prepends to ALL stacks)
        for other in ("", "TS2304: Cannot find name 'foo'.",
                      "AssertionError: expected 200 to equal 404 (vitest)",
                      "SyntaxError: Unexpected token", "boom"):
            self.assertEqual(ar.jest_hoist_hint(other), "", repr(other))

    def test_fix_messages_prepends_hint_above_the_failure(self):
        # integration: the hint rides at the top of the failure block, before truncation.
        msgs = ar.fix_messages(
            "sys", "usr", [("__tests__/habits.test.tsx", "x")], self.REAL, ar.STACK_EXPO)
        fixer = msgs[-1]["content"]
        self.assertIn("ACTIONABLE FIX (jest.mock hoisting)", fixer)
        # it appears INSIDE the failure-output block (i.e. after that header).
        self.assertIn("VERIFICATION FAILURE OUTPUT", fixer)
        self.assertLess(fixer.index("VERIFICATION FAILURE OUTPUT"),
                        fixer.index("ACTIONABLE FIX (jest.mock hoisting)"))
        # a non-jest failure adds no hint.
        clean = ar.fix_messages("sys", "usr", [("a.tsx", "x")], "TS2304", ar.STACK_EXPO)
        self.assertNotIn("ACTIONABLE FIX (jest.mock hoisting)", clean[-1]["content"])


class RtlMissingTextHeal(unittest.TestCase):
    """The deterministic self-heal hint for the most common RTL failure — a test
    asserts on-screen text the component never renders. A real mobile auth build
    failed 3x here (an invented email-validation message), so the hint names the
    missing text and gives a BALANCED two-way fix (either side may be wrong)."""

    # REAL jest/RTL output captured from the failed mobile-auth-login build.
    REAL = ("FAIL __tests__/loginScreen.test.tsx\n  ● LoginScreen › shows a "
            "validation error for an invalid email\n\n    Unable to find an element "
            "with text: Please enter a valid email address.\n\n    <RCTSafeAreaView>")

    def test_fires_and_names_the_missing_text(self):
        hint = ar.rtl_text_hint(self.REAL)
        self.assertTrue(hint)
        self.assertIn("Please enter a valid email address", hint)
        # balanced: both resolutions offered (implement it / fix the test).
        self.assertIn("VERBATIM", hint)
        self.assertIn("change the test", hint)

    def test_silent_on_unrelated_failures(self):
        for other in ("", "TS2304: Cannot find name 'foo'.",
                      "module factory of `jest.mock()` is not allowed ...",
                      "AssertionError: expected 200 to equal 404"):
            self.assertEqual(ar.rtl_text_hint(other), "", repr(other))

    def test_heal_hint_combines_and_is_silent_when_none_apply(self):
        # both classes present → both hints; neither present → "".
        both = ar.heal_hint(JestHoistHeal.REAL + "\n" + self.REAL)
        self.assertIn("jest.mock hoisting", both)
        self.assertIn("assertion vs. component mismatch", both)
        self.assertEqual(ar.heal_hint("a plain tsc TS2345 error"), "")

    def test_fix_messages_prepends_rtl_hint(self):
        msgs = ar.fix_messages(
            "sys", "usr", [("app/login.tsx", "x")], self.REAL, ar.STACK_EXPO)
        fixer = msgs[-1]["content"]
        self.assertIn("ACTIONABLE FIX (assertion vs. component mismatch)", fixer)
        self.assertLess(fixer.index("VERIFICATION FAILURE OUTPUT"),
                        fixer.index("ACTIONABLE FIX (assertion vs. component mismatch)"))


class WarmNodeModulesBootstrap(unittest.TestCase):
    """Win #1 cold-start: warm_node_modules clones the template's node_modules into
    each app, but on a cold checkout the template ships without one — so it must
    bootstrap the template ONCE, else every app silently falls back to a full
    `npm ci` and the COW clone never engages."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # a fake template: manifest + lockfile, but NO node_modules (cold checkout)
        self.tpl = os.path.join(self.tmp, "templates", "react-vite-sqlite")
        os.makedirs(self.tpl)
        with open(os.path.join(self.tpl, "package.json"), "w") as f:
            f.write('{"name":"tpl","version":"1.0.0"}\n')
        with open(os.path.join(self.tpl, "package-lock.json"), "w") as f:
            f.write('{"name":"tpl","lockfileVersion":3}\n')
        self.app = os.path.join(self.tmp, "apps", "demo")
        os.makedirs(self.app)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_npm_ci(self, install_ok=True):
        """A subprocess.run stand-in: `npm ci` materializes a node_modules/ (with a
        marker package) in the call's cwd; any other command "fails" so warm's clone
        falls through to the real shutil.copytree."""
        def run(cmd, *a, **kw):
            cwd = kw.get("cwd")
            if install_ok and list(cmd[:2]) == ["npm", "ci"] and cwd:
                pkg = os.path.join(cwd, "node_modules", "marker-pkg")
                os.makedirs(pkg, exist_ok=True)
                with open(os.path.join(pkg, "index.js"), "w") as f:
                    f.write("module.exports = 1\n")
                rc = 0
            else:
                rc = 1
            return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="")
        return run

    def test_ensure_noop_when_template_already_installed(self):
        os.makedirs(os.path.join(self.tpl, "node_modules"))
        with mock.patch.object(ar.subprocess, "run") as m:
            self.assertTrue(ar._ensure_template_node_modules(self.tpl))
            m.assert_not_called()   # already present → never shells npm

    def test_ensure_missing_manifest_returns_false(self):
        os.remove(os.path.join(self.tpl, "package.json"))
        with mock.patch("shutil.which", return_value="/usr/bin/npm"):
            self.assertFalse(ar._ensure_template_node_modules(self.tpl))

    def test_ensure_installs_and_publishes_atomically(self):
        with mock.patch.object(ar.subprocess, "run", self._fake_npm_ci()), \
                mock.patch("shutil.which", return_value="/usr/bin/npm"):
            ok = ar._ensure_template_node_modules(self.tpl)
        self.assertTrue(ok)
        # published into the TEMPLATE, with the install's contents intact
        self.assertTrue(os.path.isdir(
            os.path.join(self.tpl, "node_modules", "marker-pkg")))
        # the temp build dir is cleaned up — nothing leaks beside the template
        leftover = [d for d in os.listdir(os.path.dirname(self.tpl))
                    if d.startswith(".adf-tpl-deps-")]
        self.assertEqual(leftover, [], f"temp build dir leaked: {leftover}")

    def test_ensure_install_failure_leaves_no_partial_publish(self):
        with mock.patch.object(ar.subprocess, "run", self._fake_npm_ci(install_ok=False)), \
                mock.patch("shutil.which", return_value="/usr/bin/npm"):
            ok = ar._ensure_template_node_modules(self.tpl)
        self.assertFalse(ok)
        self.assertFalse(os.path.isdir(os.path.join(self.tpl, "node_modules")))

    def test_ensure_returns_false_when_npm_absent(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(ar._ensure_template_node_modules(self.tpl))

    def test_warm_bootstraps_then_clones_into_app(self):
        with mock.patch.object(ar.subprocess, "run", self._fake_npm_ci()), \
                mock.patch("shutil.which", return_value="/usr/bin/npm"):
            ok = ar.warm_node_modules(self.tpl, self.app)
        self.assertTrue(ok)
        self.assertTrue(os.path.isdir(os.path.join(self.app, "node_modules")))
        self.assertTrue(os.path.isdir(os.path.join(self.tpl, "node_modules")))

    def test_warm_noop_when_app_already_has_node_modules(self):
        os.makedirs(os.path.join(self.app, "node_modules"))
        with mock.patch.object(ar.subprocess, "run") as m:
            self.assertFalse(ar.warm_node_modules(self.tpl, self.app))
            m.assert_not_called()   # app already warmed → never bootstraps/clones


class LiveNarration(unittest.TestCase):
    """Live progress narration ('every action in words') must travel over stdout AND
    be HONEST: verdict events bind to the real return value, never optimism."""

    def _events(self, fn):
        """Run fn() capturing stdout; return the emitted JSON progress events."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn()
        return [json.loads(line) for line in buf.getvalue().splitlines()
                if line.strip()]

    def test_narrate_emits_one_typed_json_line(self):
        evs = self._events(lambda: ar.narrate("generating", attempt=2))
        self.assertEqual(evs, [{"type": "generating", "attempt": 2}])

    def test_run_stage_pass_binds_result_to_real_ok(self):
        evs = self._events(lambda: ar._run_stage("vitest", lambda: (True, "ok")))
        self.assertEqual(evs, [
            {"type": "verify_stage", "stage": "vitest"},
            {"type": "verify_stage_result", "stage": "vitest", "ok": True},
        ])

    def test_run_stage_fail_reports_failure_not_optimism(self):
        evs = self._events(lambda: ar._run_stage("build", lambda: (False, "boom")))
        self.assertEqual(
            evs[-1], {"type": "verify_stage_result", "stage": "build", "ok": False})

    def test_run_stage_announces_before_running_and_passes_value_through(self):
        order = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok, msg = ar._run_stage("boot", lambda: (order.append("ran") or (True, "m")))
        evs = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
        # the 'running' announce is emitted; the result is bound to fn()'s return
        self.assertEqual(evs[0]["type"], "verify_stage")
        self.assertEqual(evs[1], {"type": "verify_stage_result", "stage": "boot",
                                  "ok": True})
        self.assertEqual((ok, msg), (True, "m"))   # return value unchanged
        self.assertEqual(order, ["ran"])           # fn actually ran

    def test_react_verify_missing_pkg_emits_no_false_stage_result(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        evs = self._events(lambda: ar._react_verify(tmp))
        kinds = [e["type"] for e in evs]
        # returns early on missing package.json — must never claim a stage PASSED
        self.assertNotIn("verify_stage_result", kinds)


class StreamingBackends(unittest.TestCase):
    """Token streaming (ADF_RUNNER_STREAM=1): each backend streams deltas live but
    MUST return the full text byte-identical to the blocking path — parse_files /
    verify / seal see the same bytes, so the moat is untouched."""

    def _capture(self, fn):
        """Run fn() capturing stdout; return (fn_result, [emitted delta texts])."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = fn()
        deltas = []
        for line in buf.getvalue().splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("type") == "text":
                deltas.append(ev["text"])
        return out, deltas

    def test_streaming_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADF_RUNNER_STREAM", None)
            self.assertFalse(ar._streaming())

    def test_streaming_flag_on(self):
        for val in ("1", "true", "on", "yes"):
            with mock.patch.dict(os.environ, {"ADF_RUNNER_STREAM": val}):
                self.assertTrue(ar._streaming())

    def test_nvidia_stream_assembles_text_usage_and_deltas(self):
        lines = [
            'data: ' + json.dumps({"choices": [{"delta": {"content": "Hello"}}]}),
            'data: ' + json.dumps({"choices": [{"delta": {"content": " world"}}]}),
            'data: ' + json.dumps(
                {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}),
            'data: [DONE]',
        ]
        with mock.patch.object(ar, "http_post_stream", lambda *a, **k: iter(lines)):
            (text, usage), deltas = self._capture(
                lambda: ar._nvidia_stream("u", {}, {}, 1))
        self.assertEqual(text, "Hello world")
        self.assertEqual(usage, {"prompt_tokens": 3, "completion_tokens": 2})
        self.assertEqual(deltas, ["Hello", " world"])

    def test_anthropic_stream_assembles_text_usage_and_deltas(self):
        lines = [
            'data: ' + json.dumps(
                {"type": "message_start", "message": {"usage": {"input_tokens": 10}}}),
            'data: ' + json.dumps(
                {"type": "content_block_delta", "delta": {"text": "foo"}}),
            'data: ' + json.dumps(
                {"type": "content_block_delta", "delta": {"text": "bar"}}),
            'data: ' + json.dumps({"type": "message_delta", "usage": {"output_tokens": 5}}),
            'data: ' + json.dumps({"type": "message_stop"}),
        ]
        with mock.patch.object(ar, "http_post_stream", lambda *a, **k: iter(lines)):
            (text, usage), deltas = self._capture(
                lambda: ar._anthropic_stream("u", {}, {}, 1))
        self.assertEqual(text, "foobar")
        self.assertEqual(usage, {"prompt_tokens": 10, "completion_tokens": 5})
        self.assertEqual(deltas, ["foo", "bar"])

    def test_ollama_stream_assembles_text_and_deltas(self):
        lines = [
            json.dumps({"message": {"content": "abc"}, "done": False}),
            json.dumps({"message": {"content": "def"}, "done": True}),
        ]
        with mock.patch.object(ar, "http_post_stream", lambda *a, **k: iter(lines)):
            (text, _usage), deltas = self._capture(
                lambda: ar._ollama_stream("u", {}, {}, 1))
        self.assertEqual(text, "abcdef")
        self.assertEqual(deltas, ["abc", "def"])

    def test_streamed_text_equals_blocking_text_the_moat(self):
        # The exact bytes parse_files would receive must be identical streamed vs not.
        full = "<<<FILE: a.py>>>\nprint(1)\n<<<END>>>"
        chunks = [full[i:i + 7] for i in range(0, len(full), 7)]
        sse = ['data: ' + json.dumps({"choices": [{"delta": {"content": c}}]})
               for c in chunks] + ['data: [DONE]']
        blocking = {"choices": [{"message": {"content": full}}]}

        with mock.patch.dict(os.environ,
                             {"NVIDIA_API_KEY": "k", "ADF_RUNNER_STREAM": "1"}), \
                mock.patch.object(ar, "http_post_stream", lambda *a, **k: iter(sse)):
            (stream_text, _u), _d = self._capture(lambda: ar.call_nvidia([], 5))

        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "k"}, clear=False):
            os.environ.pop("ADF_RUNNER_STREAM", None)
            with mock.patch.object(ar, "http_post_json", lambda *a, **k: blocking):
                block_text, _ = ar.call_nvidia([], 5)

        self.assertEqual(stream_text, full)
        self.assertEqual(stream_text, block_text)   # byte-identical → moat intact

    def test_mid_stream_disconnect_fails_over_never_partial(self):
        # A connection that drops AFTER 200 raises http.client.IncompleteRead (NOT an
        # OSError). The backend must catch it and return None so generate() fails over
        # to a backend that produces COMPLETE output — never return partial text (a
        # moat breach) and never crash the build.
        def boom(*a, **k):
            yield 'data: ' + json.dumps({"choices": [{"delta": {"content": "par"}}]})
            raise http_client.IncompleteRead(b"par")
        with mock.patch.dict(os.environ,
                             {"NVIDIA_API_KEY": "k", "ADF_RUNNER_STREAM": "1"}), \
                mock.patch.object(ar, "http_post_stream", boom):
            with contextlib.redirect_stdout(io.StringIO()):
                res = ar.call_nvidia([{"role": "user", "content": "x"}], 5)
        self.assertIsNone(res)   # failover, not ("par", …) and not a traceback


class GenerationHeartbeat(unittest.TestCase):
    """D2: during generation the server suppresses the raw type:'text' token
    stream, so the runner must emit a throttled NL progress heartbeat — never code
    — or the live feed goes dark for the whole (longest) phase."""

    def _run(self, total_chars, chunk=500):
        events = []
        ar._reset_stream_progress()
        with mock.patch.object(ar, "emit_event", events.append):
            big = "x" * total_chars
            for i in range(0, len(big), chunk):
                ar._stream_delta(big[i:i + chunk])
        return events

    def test_emits_progress_heartbeats_without_code(self):
        events = self._run(5000)
        progress = [e for e in events if e.get("type") == "generating_progress"]
        self.assertGreaterEqual(len(progress), 1, "feed must not go dark")
        blob = json.dumps(progress)
        self.assertNotIn("<<<FILE", blob)   # never leaks code
        self.assertNotIn("xxxx", blob)      # never echoes the streamed tokens

    def test_short_stream_does_not_spam_heartbeats(self):
        # below the throttle threshold → no heartbeat (avoid noise)
        events = self._run(200, chunk=50)
        progress = [e for e in events if e.get("type") == "generating_progress"]
        self.assertEqual(len(progress), 0)

    def test_concurrent_emits_never_interleave_a_jsonl_line(self):
        # The watchdog thread + main thread both emit; every line on stdout must
        # remain a parseable JSON object (no interleaving — the _emit_lock invariant).
        import threading as _t
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            threads = [
                _t.Thread(target=lambda i=i: [
                    ar.emit_event({"type": "generating_progress", "elapsed": i, "n": k})
                    for k in range(50)
                ])
                for i in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 8 * 50)
        for ln in lines:                       # every line is valid JSON → no interleave
            json.loads(ln)

    def test_watchdog_emits_on_the_blocking_path_and_stops(self):
        # E1: the DEFAULT (non-streaming) generate() is a blocking call with no
        # deltas; a watchdog must keep the feed alive and stop cleanly.
        events = []
        with mock.patch.object(ar, "emit_event", events.append):
            hb = ar._GenerationHeartbeat(interval=0.02).start()
            time.sleep(0.07)          # ~3 ticks
            hb.stop()
            n = len([e for e in events if e["type"] == "generating_progress"])
            time.sleep(0.05)          # nothing more after stop
        progress = [e for e in events if e["type"] == "generating_progress"]
        self.assertGreaterEqual(n, 1, "the blocking path must not go dark")
        self.assertEqual(len(progress), n, "no heartbeat after stop()")
        self.assertNotIn("<<<FILE", json.dumps(progress))

    def test_default_heartbeat_interval_is_sub_2s(self):
        # S2: the live feed must move at least ~every 2s during a long blocking
        # generate(); the old 6s default left multi-second dark gaps (the user's
        # "sometimes it waited" complaint).
        self.assertLess(ar._GenerationHeartbeat().interval, 2.0)

    def test_heartbeat_interval_env_override(self):
        with mock.patch.dict(os.environ, {"ADF_GEN_HEARTBEAT_SEC": "0.5"}):
            self.assertEqual(ar._GenerationHeartbeat().interval, 0.5)


class GenerateModelRouting(unittest.TestCase):
    """G10 — generate()/call_with_retry() accept an optional per-call model= that
    threads through to the backend on every attempt, with the legacy 2-arg
    call(messages, timeout) contract preserved when model is omitted."""

    def test_generate_threads_model_to_backend(self):
        captured = {}

        def stub_backend(messages, timeout, model=None):
            captured["model"] = model
            return ("ok", {})

        with mock.patch.dict("os.environ", {"ADF_RUNNER_BACKEND": "anthropic",
                                            "ANTHROPIC_API_KEY": "dummy"}):
            with mock.patch.object(ar, "apply_headroom", side_effect=lambda m: m):
                with mock.patch.object(ar, "call_anthropic", stub_backend):
                    result = ar.generate([], 10, model="custom/model-x")

        self.assertEqual(result, ("ok", {}))
        self.assertEqual(captured["model"], "custom/model-x")

    def test_generate_default_omitted_uses_backend_env_default(self):
        captured = {}

        def stub_backend(messages, timeout, model=None):
            captured["model"] = model
            return ("ok", {})

        with mock.patch.dict("os.environ", {"ADF_RUNNER_BACKEND": "anthropic",
                                            "ANTHROPIC_API_KEY": "dummy"}):
            with mock.patch.object(ar, "apply_headroom", side_effect=lambda m: m):
                with mock.patch.object(ar, "call_anthropic", stub_backend):
                    ar.generate([], 10)

        self.assertIsNone(captured["model"],
                          "omitting model must leave the backend on its env-default path")

    def test_call_with_retry_forwards_model_on_each_attempt(self):
        seen = []
        n = {"c": 0}

        def call(messages, timeout, model=None):
            seen.append(model)
            n["c"] += 1
            if n["c"] < 2:
                raise ar.HttpError(529)
            return ("ok", {})

        result = ar.call_with_retry(
            call, [], 10, attempts=3, sleeper=lambda s: None, model="m1")

        self.assertEqual(result, ("ok", {}))
        self.assertEqual(seen, ["m1", "m1"],
                         "model must be forwarded on both the failed and succeeding attempt")

    def test_call_with_retry_2arg_callable_no_model(self):
        # A strictly 2-arg callable + no model= kwarg must still work (the
        # `model is not None` guard is a branch check, not a signature inspection).
        def call(messages, timeout):
            return ("ok", {})

        result = ar.call_with_retry(call, [], 10, attempts=1, sleeper=lambda s: None)
        self.assertEqual(result, ("ok", {}))


class TddRedBaselineGuards(unittest.TestCase):
    """G12 — direct coverage for the agent_runner._tdd_red_baseline honesty seam.
    The load-bearing test pins the deps-absent guard (no node_modules → inconclusive,
    never a fake RED); companions cover the not-applicable and no-impl branches."""

    def setUp(self):
        self._dirs = []

    def tearDown(self):
        for d in self._dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _mkdtemp(self):
        d = tempfile.mkdtemp()
        self._dirs.append(d)
        return d

    def test_deps_absent_is_inconclusive_not_red(self):
        # Both a test file AND an impl file are required so execution reaches the
        # :2043 deps guard (a test-only input would exit early at the no-impl guard).
        workspace = self._mkdtemp()
        fid = "tddapp"
        files = [
            ("test/app.test.mjs", 'import {expect} from "vitest"; expect(1).toBe(2)'),
            ("src/App.tsx", "export const real = () => 1"),
        ]
        # Patch the module-level _npm; update if renamed.
        npm_mock = mock.MagicMock(
            side_effect=AssertionError("npm invoked when deps absent"))
        with mock.patch.object(ar, "_npm", npm_mock):
            verdict, paths = ar._tdd_red_baseline(
                workspace, fid, ar.STACK_REACT, files, 30)
        self.assertIs(verdict["red"], False)
        self.assertIs(verdict["vacuous"], False)
        self.assertIn("deps absent", verdict["reason"])
        npm_mock.assert_not_called()

    def test_non_test_bearing_stack_returns_not_applicable(self):
        verdict, paths = ar._tdd_red_baseline(
            self._mkdtemp(), "x", ar.STACK_STDLIB, [("a.py", "x")], 30)
        self.assertIsNone(verdict)
        self.assertEqual(paths, [])

    def test_no_impl_files_returns_inconclusive(self):
        # Exercises the :2039 no-impl guard (distinct from the :2043 deps guard).
        npm_mock = mock.MagicMock(
            side_effect=AssertionError("npm invoked with no impl files"))
        with mock.patch.object(ar, "_npm", npm_mock):
            verdict, paths = ar._tdd_red_baseline(
                self._mkdtemp(), "x", ar.STACK_REACT,
                [("test/a.test.mjs", "t")], 30)
        self.assertIs(verdict["red"], False)
        self.assertIs(verdict["vacuous"], False)
        self.assertIn("no test or no implementation", verdict["reason"])
        npm_mock.assert_not_called()


class WarmNodeModulesNarration(unittest.TestCase):
    """G27 — the CoW fast path is platform-aware (APFS clonefile on macOS, reflink
    on Linux) and narrates an HONEST method label (clone/hardlink/copy)."""

    def test_warm_linux_uses_reflink_not_cp_c(self):
        tpl = tempfile.mkdtemp()
        os.makedirs(os.path.join(tpl, "node_modules", "pkg"))
        app = tempfile.mkdtemp()
        calls = []

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            # all subprocess commands fail -> falls through to shutil.copytree
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

        with mock.patch("sys.platform", "linux"), \
                mock.patch.object(ar.subprocess, "run", side_effect=fake_run):
            ar.warm_node_modules(tpl, app)  # return value irrelevant here

        self.assertTrue(len(calls) >= 1,
                        "subprocess.run must have been called at least once")
        self.assertEqual(
            calls[0],
            ["cp", "--reflink=auto", "-R",
             os.path.join(tpl, "node_modules"),
             os.path.join(app, "node_modules")],
            f"Expected cp --reflink=auto as first command on Linux; got {calls[0]}")

    def test_warm_narrates_hardlink_not_clone_when_cow_fails(self):
        import shutil as _shutil
        tpl = tempfile.mkdtemp()
        src = os.path.join(tpl, "node_modules")
        os.makedirs(os.path.join(src, "pkg"))
        app = tempfile.mkdtemp()
        dst = os.path.join(app, "node_modules")
        narrated = []

        def fake_run(cmd, **kw):
            cmd = list(cmd)
            # First cmd (CoW: cp -c or cp --reflink=auto): always fail.
            if "reflink" in cmd[1] or cmd[1] == "-c":
                return subprocess.CompletedProcess(cmd, 1)
            # Second cmd (cp -al): succeed by creating dst.
            if "-al" in cmd:
                _shutil.copytree(src, dst, symlinks=True)
                return subprocess.CompletedProcess(cmd, 0)
            return subprocess.CompletedProcess(cmd, 1)

        def fake_narrate(kind, **fields):
            narrated.append((kind, fields))

        with mock.patch.object(ar.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(ar, "narrate", side_effect=fake_narrate):
            result = ar.warm_node_modules(tpl, app)

        self.assertTrue(result)
        deps_warm = [(k, f) for k, f in narrated if k == "deps_warm"]
        self.assertEqual(len(deps_warm), 1)
        self.assertEqual(
            deps_warm[0][1].get("method"), "hardlink",
            f"Expected method='hardlink' but got: {deps_warm[0][1]}")


# G02 — driver run as a subprocess so sys.exit() and on-disk proof presence are
# observable. It stubs ONLY the heavy I/O (generation + verification) to reach the
# real `if verified:` policy-gate path; the policy gate itself is shadowed by a
# PYTHONPATH shim whose check_policy raises, exercising the real except handler.
_G02_DRIVER = r'''
import os, sys
import agent_runner as ar

# Reach the verified policy-gate path without an LLM or a real test run.
ar.generate = lambda messages, timeout, model=None: (
    "<<<FILE: server.py>>>\nprint('ok')\n<<<END>>>\n"
    "<<<FILE: test_app.py>>>\ndef test_ok():\n    assert True\n<<<END>>>\n", {})
ar.verify_app = lambda app_root, stack=None, timeout=None: (True, "ok")
ar.audit_completion = lambda *a, **k: []
sys.argv = ["agent_runner", "build feature stub", "--workspace", sys.argv[1]]
ar.main()
'''


class PolicyGateFailClosed(unittest.TestCase):
    """G02 — a policy-gate exception under ENFORCED policy fails CLOSED (no proof,
    exit 6); under ADF_POLICY=advisory the old record-but-ship behavior is kept."""

    def test_policy_failclosed_helper(self):
        self.assertEqual(ar._policy_failclosed(False), ["policy_gate_error"])
        self.assertEqual(ar._policy_failclosed(True), [])

    def _run_with_raising_gate(self, extra_env):
        workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
        fid = "stub"
        # Minimal spec so load_feature_context yields a non-empty ctx.
        feat_dir = os.path.join(workspace, "orchestration", "features", fid)
        os.makedirs(feat_dir, exist_ok=True)
        with open(os.path.join(feat_dir, "requirement.md"), "w") as f:
            f.write("Build a stub app.\n")
        # PYTHONPATH shim: a policy_gate whose check_policy raises, shadowing the
        # real module (prepended so it wins over scripts/orch on sys.path).
        shim = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, shim, ignore_errors=True)
        with open(os.path.join(shim, "policy_gate.py"), "w") as f:
            f.write("def check_policy(app_root, policy=None):\n"
                    "    raise RuntimeError('injected gate failure')\n")
        orch = os.path.dirname(os.path.abspath(ar.__file__))
        env = {**os.environ}
        env["PYTHONPATH"] = os.pathsep.join(
            [shim, orch, env.get("PYTHONPATH", "")])
        env["ORCH_REPO_ROOT"] = workspace
        env["ADF_FEATURE_ID"] = fid
        env["ADF_STACK"] = ar.STACK_STDLIB
        env.pop("ADF_PROCESS", None)
        env.pop("ADF_TDD", None)
        env.pop("ADF_POLICY", None)   # default strict unless extra_env opts out
        env.update(extra_env)
        driver = os.path.join(shim, "_g02_driver.py")
        with open(driver, "w") as f:
            f.write(_G02_DRIVER)
        r = subprocess.run([sys.executable, driver, workspace],
                           env=env, capture_output=True, text=True, timeout=120)
        proof = os.path.join(workspace, "apps", fid, ".adf-proof.json")
        return r, proof

    def test_policy_gate_exception_fails_closed_exit6(self):
        # ADF_POLICY unset (default strict) — the driver env does not set it.
        r, proof = self._run_with_raising_gate({})
        self.assertEqual(r.returncode, 6,
                         f"expected fail-closed exit 6; stdout/stderr:\n{r.stdout}\n{r.stderr}")
        self.assertFalse(os.path.exists(proof),
                         "a gate exception under enforced policy must NOT seal a proof")

    def test_policy_gate_exception_advisory_ships_exit0(self):
        r, proof = self._run_with_raising_gate({"ADF_POLICY": "advisory"})
        self.assertEqual(r.returncode, 0,
                         f"advisory escape hatch must ship; stdout/stderr:\n{r.stdout}\n{r.stderr}")
        self.assertTrue(os.path.exists(proof),
                        "advisory mode preserves the old record-but-ship seal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
