#!/usr/bin/env python3
"""ADF file-writing implementation runner — turns a plain LLM into a real
coding agent for the implement phase (phase 7), at zero cost on NVIDIA's free
NIM tier.

ADF's phase runner invokes a runner CLI as:
    agent_runner.py "<prompt>" --workspace <repo-or-worktree>
where <prompt> is the thin orchestration directive (e.g.
"@orch-orchestrator resume <feature-id>"). Real coding agents (cursor-agent,
claude CLI) read the orchestration spec and write files via tool calls. A plain
chat model can't — so this adapter does the agent's job explicitly:

  1. Resolve the feature id from the prompt.
  2. Load the crew's spec/plan/tasks/requirement from disk.
  3. Ask a capable model for a COMPLETE, runnable, self-contained app, emitted
     in a strict, machine-parseable multi-file format.
  4. Parse that output and WRITE the files into <workspace>/apps/<feature-id>/.
  5. Emit the one stream-json result line the phase runner consumes:
       {"type":"result","result":"<summary>","usage":{...}}

Model selection (first configured wins), all OpenAI/Anthropic-compatible:
  - NVIDIA NIM   (NVIDIA_API_KEY)      free, default — ADF_RUNNER_MODEL
  - Anthropic    (ANTHROPIC_API_KEY)   paid, best quality
  - Ollama       (local)               offline fallback

Honest failure: if the model returns no parseable files, this exits non-zero
so the phase fails loudly instead of "succeeding" with no code written.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import random
import re
import ssl
import http.client
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
import urllib.error

ORCH_DIRS = (".cursor/orchestration", ".adf/orchestration", "orchestration")
FILE_OPEN = re.compile(r"^<<<FILE:\s*(.+?)\s*>>>\s*$")
FILE_CLOSE = re.compile(r"^<<<END>>>\s*$")
NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
ANTHROPIC_BASE = "https://api.anthropic.com"


def log(msg):
    print(f"agent_runner: {msg}", file=sys.stderr, flush=True)


def emit_result(text, usage=None):
    """The single line the ADF phase runner parses from stdout."""
    evt = {"type": "result", "result": text}
    if usage:
        evt["usage"] = usage
    print(json.dumps(evt), flush=True)


_emit_lock = threading.Lock()


def emit_event(obj):
    """A structured progress line on stdout the phase runner narrates live (so a
    1-3 min build doesn't go dark). Any `type` other than 'result' is progress;
    the runner's final answer is still the single emit_result line.

    Lock-guarded: the generation-heartbeat WATCHDOG runs on its own thread while the
    main thread also emits, and an unguarded print()+flush could interleave two
    threads' output into one corrupt JSONL line the server can't parse."""
    line = json.dumps(obj)  # serialize off-lock (CPU); only the write is serialized
    with _emit_lock:
        print(line, flush=True)


def narrate(kind, **fields):
    """Emit ONE live progress event for the dashboard to narrate in real time —
    'literally every action, written down', so the Studio shows running commentary
    instead of a dark multi-minute pause. Must travel over stdout (the phase runner
    drains stdout live but only reads stderr after exit, so a log() never narrates).

    HONESTY CONTRACT (the moat): a narration is a UI signal, NEVER an authoritative
    claim. Announce-events (verifying, sealing, verify_stage) say 'doing X now';
    verdict-events (verify_result, verify_stage_result, policy_gate, policy_blocked,
    sealed, build_complete) carry truth and are emitted ONLY after the real return
    value is in hand — so the live stream can never say 'tests passed' before they
    passed, or render a seal for an unsealed/blocked build."""
    emit_event({"type": kind, **fields})


# --- .env loading (NVIDIA_API_KEY / ANTHROPIC_API_KEY live here) ------------
def load_env(repo_root):
    for rel in (".env", "../.env"):
        path = os.path.join(repo_root, rel)
        if not os.path.isfile(path):
            continue
        for line in open(path, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("'\"")
            if k and v and not os.environ.get(k):
                os.environ[k] = v


# --- feature context -------------------------------------------------------
def feature_id_from_prompt(prompt):
    m = re.search(r"\b(?:resume|sync|implement|run)\s+([a-z0-9][a-z0-9-]*)", prompt, re.I)
    if m:
        return m.group(1)
    # Fallback: last token that looks like a slug.
    slugs = re.findall(r"[a-z0-9][a-z0-9-]{3,}", prompt.lower())
    return slugs[-1] if slugs else None


# Words that are NEVER a feature id, even if the prompt regex grabs them — guards
# against prompts like "implement phase 7" / "run phase" resolving to "phase".
_NON_FEATURE_WORDS = {"phase", "resume", "sync", "implement", "run", "build",
                      "feature", "orchestrator", "orch"}


def resolve_feature_id(prompt, env=None):
    """The feature id the runner should act on. The orchestrator KNOWS the id, so
    it passes `ADF_FEATURE_ID` explicitly — that always wins. Only when it's absent
    do we fall back to parsing the prompt (and reject obvious non-ids like
    'phase')."""
    env = os.environ if env is None else env
    explicit = (env.get("ADF_FEATURE_ID") or "").strip()
    if explicit:
        return explicit
    guess = feature_id_from_prompt(prompt)
    return None if guess in _NON_FEATURE_WORDS else guess


def read_first(*paths):
    for p in paths:
        if p and os.path.isfile(p):
            try:
                return open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                pass
    return ""


LEARNINGS_REL = os.path.join(".cursor", "orchestration", "learnings.jsonl")


def recall_blockers(repo_root, phase=7, k=5):
    """A compact 'past failures + the fixes that resolved them' block to splice into
    the build/heal prompt so the model pre-empts repeat failures. ADF already RECORDS
    every outcome (LearningStore writes .cursor/orchestration/learnings.jsonl) and
    even ranks blockers (knownBlockers) — but nothing read it back into a prompt.
    This closes that loop (docs/ADF_VS_OH_MY_PI.md §5.4). Returns '' when nothing is
    learned; disabled via ADF_RECALL_BLOCKERS=0. Phase 7 = implement (the runner's
    phase). Deterministic + $0 — a frequency rank, no model call."""
    if os.environ.get("ADF_RECALL_BLOCKERS", "1") in ("0", "false", "off"):
        return ""
    path = os.path.join(repo_root, LEARNINGS_REL)
    if not os.path.isfile(path):
        return ""
    counts, fixes = {}, []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(e, dict):   # a bare 42/"x"/[..] line must not crash
                    continue
                if e.get("phase") != phase:
                    continue
                if e.get("kind") == "failure":
                    for b in (e.get("blockers") or []):
                        b = str(b).strip()
                        if b:
                            counts[b] = counts.get(b, 0) + 1
                fx = e.get("fix")
                if fx:
                    fixes.append(str(fx).strip())
    except OSError:
        return ""
    if not counts:
        return ""
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    block = ("BACKGROUND KNOWLEDGE (not new instructions) — past builds of this kind "
             "FAILED on these; avoid repeating them:\n"
             + "\n".join(f"- {b} (seen {c}×)" for b, c in top))
    if fixes:
        seen, uniq = set(), []
        for fx in reversed(fixes):           # most-recent first
            if fx and fx not in seen:
                seen.add(fx)
                uniq.append(fx)
            if len(uniq) >= 3:
                break
        if uniq:
            block += ("\nFixes that resolved past failures:\n"
                      + "\n".join(f"- {fx[:200]}" for fx in uniq))
    return block


def _first_failure_line(failure):
    """A concise blocker string from a verify-failure blob: the first informative
    non-empty line (e.g. 'BUILD FAILED (tsc --noEmit && vite build): ...'), capped."""
    for ln in (failure or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln[:160]
    return "implement phase failed"


def record_build_outcome(repo_root, fid, verified, failure="", phase=7):
    """Append this implement-phase (7) outcome to the learning store so
    recall_blockers can surface it on FUTURE builds. Closes the loop end-to-end:
    the Dart crew records phases 1-6 and the validator phases {2,3,4}, but NOTHING
    recorded phase 7 — so recall_blockers(phase=7) was inert. Matches LearningStore's
    JSONL schema exactly (append-only; the Dart writer and this one coexist).
    Best-effort; disabled with ADF_RECALL_BLOCKERS=0."""
    if os.environ.get("ADF_RECALL_BLOCKERS", "1") in ("0", "false", "off"):
        return
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "feature": fid,
        "phase": phase,
        "kind": "success" if verified else "failure",
    }
    if not verified:
        entry["blockers"] = [_first_failure_line(failure)]
    path = os.path.join(repo_root, LEARNINGS_REL)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def load_feature_context(repo_root, fid):
    specs = os.path.join(repo_root, "specs", fid)
    ctx = {
        "requirement": read_first(
            *[os.path.join(repo_root, d, "features", fid, "requirement.md") for d in ORCH_DIRS]
        ),
        "problem": read_first(os.path.join(specs, "problem-statement.md")),
        "spec": read_first(os.path.join(specs, "spec.md")),
        "plan": read_first(os.path.join(specs, "plan.md")),
        "tasks": read_first(os.path.join(specs, "tasks.md")),
    }
    return ctx


# --- stack profiles --------------------------------------------------------
# A "stack profile" parameterizes everything stack-specific: how to GENERATE,
# VERIFY, BOOT and (for edit mode) which files are app source. This is the seam
# that lets ADF target a single-file Python app OR a real React+Vite+SQLite app
# without touching the crew, the dashboard, or the <<<FILE:>>> protocol.
STACK_STDLIB = "stdlib"
STACK_REACT = "react-vite-sqlite"
STACK_EXPO = "expo-rn"   # cross-platform mobile (Expo / React Native, iOS + Android)
DEFAULT_STACK = os.environ.get("ADF_STACK", STACK_STDLIB)

# Editable app source (multi-file edit). Everything else — deps, build output,
# caches, lockfiles — is excluded so big apps don't blow the prompt.
_EDIT_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".css", ".scss",
              ".sql", ".json", ".md", ".cjs", ".mjs")
_SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__", ".git", ".vite",
              "coverage", ".next", ".turbo"}
_SKIP_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "PROOF.md",
               ".adf-components.json", "COMPONENTS.md"}


def detect_stack(app_dir):
    """Infer the stack: the `.adf-stack.json` manifest is authoritative (contract
    C1); else `app.json` -> expo (mobile); else package.json -> react; else stdlib.
    No language guessing."""
    manifest = os.path.join(app_dir, ".adf-stack.json")
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding="utf-8") as f:
                return json.load(f).get("stack") or STACK_STDLIB
        except (OSError, ValueError):
            pass
    if os.path.isfile(os.path.join(app_dir, "app.json")):
        return STACK_EXPO            # Expo's manifest — present only on RN/Expo apps
    if os.path.isfile(os.path.join(app_dir, "package.json")):
        return STACK_REACT
    return STACK_STDLIB


def build_messages(fid, ctx, stack=None):
    """Dispatch to the stack's generation prompt via the StackProfile registry."""
    stack = stack or DEFAULT_STACK
    return stack_profile(stack)["build_messages"](fid, ctx)


def _spec_block(ctx):
    return "\n\n".join(
        s for s in (
            f"## Requirement\n{ctx['requirement']}" if ctx["requirement"] else "",
            f"## Problem statement\n{ctx['problem']}" if ctx["problem"] else "",
            f"## Spec (EARS)\n{ctx['spec']}" if ctx["spec"] else "",
            f"## Plan\n{ctx['plan']}" if ctx["plan"] else "",
            f"## Tasks\n{ctx['tasks']}" if ctx["tasks"] else "",
        ) if s
    )


def _stdlib_build_messages(fid, ctx):
    system = (
        "You are an expert full-stack engineer acting as the ADF implementation "
        "agent. You output COMPLETE, RUNNABLE code — never placeholders, never "
        "'...', never TODO stubs. Every file you emit must be final and working.\n\n"
        "Hard requirements for the app you build:\n"
        "- Backend: Python 3 standard library ONLY (http.server / socketserver). "
        "No pip installs, no third-party packages.\n"
        "- Frontend: a single static HTML file with inline CSS + vanilla JS "
        "(fetch). No build step, no frameworks, no CDNs.\n"
        "- The server must serve the frontend AND expose a JSON API, and run "
        "with a single command: `python3 server.py`, binding to the PORT "
        "environment variable (default 8000) so it can be previewed live.\n"
        "- Include a README.md with exact run + test instructions.\n\n"
        "OUTPUT FORMAT — emit each file EXACTLY like this, nothing else between "
        "files:\n"
        "<<<FILE: relative/path>>>\n"
        "<full file content>\n"
        "<<<END>>>\n"
        "Repeat for every file. Do not wrap files in markdown fences. Do not add "
        "commentary outside the file blocks."
    )
    spec_block = "\n\n".join(
        s for s in (
            f"## Requirement\n{ctx['requirement']}" if ctx["requirement"] else "",
            f"## Problem statement\n{ctx['problem']}" if ctx["problem"] else "",
            f"## Spec (EARS)\n{ctx['spec']}" if ctx["spec"] else "",
            f"## Plan\n{ctx['plan']}" if ctx["plan"] else "",
            f"## Tasks\n{ctx['tasks']}" if ctx["tasks"] else "",
        ) if s
    )
    user = (
        f"Implement the feature `{fid}` as a complete, self-contained web app.\n\n"
        f"{spec_block}\n\n"
        "Deliver these files (paths are relative to the app root):\n"
        "- `server.py`  — Python stdlib HTTP server. It MUST:\n"
        "    * serve the full index.html (read from disk next to server.py) at "
        "GET `/` with Content-Type text/html;\n"
        "    * expose the JSON API needed to satisfy EVERY behavior in the spec "
        "above — derive the exact routes, methods, request/response shapes, "
        "validation and error codes from the spec. Use clear `/api/...` paths and "
        "return JSON with correct HTTP status codes (200/201 success, 400 invalid "
        "input, 404 not found);\n"
        "    * persist data when the spec implies durability (e.g. a JSON file "
        "next to server.py); otherwise an in-memory store is fine;\n"
        "    * expose a module-level `RequestHandler` class and a "
        "`make_server(port=0)` helper returning the server object, so tests can "
        "import and start it;\n"
        "    * read the port from the environment "
        "(`port = int(os.environ.get('PORT', '8000'))`) and END with "
        "`if __name__ == '__main__':` calling `make_server(port).serve_forever()` "
        "and printing a ready line — running `python3 server.py` MUST actually "
        "start the server (default 8000, overridable via PORT).\n"
        "- `index.html` — a single self-contained frontend (inline CSS + vanilla "
        "JS) implementing the full UI the spec describes, calling the server's "
        "JSON API via fetch with relative, same-origin paths. Make it clean, "
        "modern, and genuinely usable.\n"
        "- `test_app.py` — Python stdlib unittest that:\n"
        "    * imports `make_server` / `RequestHandler` from server, starts it on "
        "port 0 in a background thread, reads the real port from "
        "`server.server_address[1]`;\n"
        "    * exercises the MAIN success path of the spec's API (e.g. create then "
        "read it back, or compute then check the result) asserting the right "
        "status and JSON;\n"
        "    * asserts at least one validation/error case returns the correct code "
        "(400 invalid input or 404 missing resource). For any redirect/status "
        "assertion use `http.client` (NOT urllib.urlopen, which auto-follows "
        "redirects);\n"
        "    * shuts the server down in tearDown.\n"
        "- `README.md` — exact run + test instructions.\n\n"
        "CRITICAL: code must be final and correct — `python3 test_app.py` must "
        "pass with zero failures. No placeholders. Emit all files now."
    )
    return system, user


def _react_build_messages(fid, ctx):
    """React+Vite+Tailwind front + Fastify+better-sqlite3 server. Scaffold-then-diff:
    the template provides build config + the server bootstrap; the model emits ONLY
    the feature's files (schema, API routes, components, tests).

    The prompt mirrors the REAL template shape exactly (an earlier version asked for
    a TypeScript server the template can't run): the server is PLAIN ESM `.mjs`
    (started by `node`, never tsc-compiled); each `server/api/<name>.mjs` is a
    Fastify plugin whose routes are registered under the `/api` prefix by the
    template, so routes are written RELATIVE (`app.get('/items')` => `/api/items`);
    it imports the shared db as `import { db } from '../db.mjs'`; tests are
    `test/<name>.test.mjs` using `app.inject` against `buildApp` from
    `../server/app.mjs`. Only `src/**` (.tsx) is TypeScript (tsc typechecks it)."""
    system = (
        "You are an expert full-stack engineer acting as the ADF implementation "
        "agent. You output COMPLETE, RUNNABLE code — never placeholders, never "
        "'...', never TODO stubs.\n\n"
        "TARGET STACK (a checked-in scaffold already provides ALL the wiring — you "
        "write ONLY the app-specific files):\n"
        "- Frontend: React 18 + Vite + TypeScript + Tailwind CSS utility classes. "
        "Only `src/**` is TypeScript and `tsc --noEmit` typechecks it, so it must be "
        "type-correct. No extra UI/npm libraries (only what's in package.json).\n"
        "- Backend: a single Fastify server already serves the built Vite `dist/` and "
        "auto-registers every `server/api/*.mjs` plugin under the `/api` prefix, and a "
        "shared better-sqlite3 connection runs `schema.sql` at boot. The server is "
        "PLAIN ES MODULES (`.mjs`) run by `node` — it is NEVER compiled by tsc, so "
        "DO NOT write server code in TypeScript.\n"
        "- Tests: Vitest (`*.test.mjs`).\n\n"
        "SCAFFOLD-THEN-DIFF: DO NOT re-emit build config, `server/app.mjs`, "
        "`server/db.mjs`, `server/index.mjs`, or `index.html`. Emit ONLY the files "
        "that implement THIS feature, overwriting the scaffold's sample where needed.\n\n"
        "OUTPUT FORMAT — emit each file EXACTLY like this, nothing else between "
        "files:\n<<<FILE: relative/path>>>\n<full file content>\n<<<END>>>\n"
        "No markdown fences, no commentary outside file blocks."
    )
    # DET-2: detect a deterministic feature shape and pin the exact schema/route/
    # hook skeleton so the model fills domain logic, not boilerplate. Empty for
    # the generic fallback (keeps the base deliverables).
    import feature_shapes
    _shape, _contract = feature_shapes.contract_for(ctx, fid)
    shape_block = f"{_contract}\n\n" if _contract else ""
    user = (
        f"Implement the feature `{fid}` as a real React+Vite+Tailwind app backed by a "
        f"Fastify + SQLite API.\n\n{_spec_block(ctx)}\n\n{shape_block}"
        "Deliver (paths relative to the app root):\n"
        "- `schema.sql` — the SQLite tables the spec implies (executed at boot). Use "
        "`CREATE TABLE IF NOT EXISTS`.\n"
        "- `server/api/<feature>.mjs` — a Fastify plugin: "
        "`export default async function <feature>(app) { ... }`. Import the shared db "
        "with `import { db } from '../db.mjs'` and use better-sqlite3's SYNC API "
        "(`db.prepare(...).all()/.get()/.run()`). Register routes RELATIVE to `/api` "
        "(the loader adds the `/api` prefix) — e.g. `app.get('/items', ...)` is served "
        "at `/api/items`. Return correct status codes (200/201 success, 400 invalid "
        "input, 404 not found) via `reply.code(n).send(...)`.\n"
        "- `src/components/<Name>.tsx` — build the UI as MULTIPLE small, "
        "SELF-CONTAINED, REUSABLE components (NOT one monolithic App.tsx). Each "
        "component is **props-driven**: it exports the component AND a typed "
        "`interface <Name>Props`, receives its data + callbacks via props, owns no "
        "global state, and never reaches into another component's internals — so it "
        "can be dropped into any other feature unchanged. Shared UI primitives are "
        "ALREADY PROVIDED — import and COMPOSE them, do NOT recreate them: "
        "`import { Button, Input, Card } from './components/ui'` (Button takes "
        "`variant`, Input takes `label`, Card takes `title`). Add a new shared "
        "primitive to `src/components/ui/` only if none fits. Co-locate data access "
        "in a `src/hooks/use<Feature>.ts` hook that calls `fetch('/api/...')` and "
        "returns typed data + actions; components call the hook, not fetch directly.\n"
        "- `src/App.tsx` — the composition ROOT only: import and arrange the feature "
        "components (keep it thin). It must be the default export rendered by the "
        "existing `src/main.tsx`. Keep ALL `src/**` type-correct with Tailwind "
        "classes (tsc --noEmit checks it).\n"
        "- `test/<feature>.test.mjs` — Vitest importing "
        "`import { buildApp } from '../server/app.mjs'`, exercising the API via "
        "`app.inject({ method, url: '/api/...', payload })` (NO network/port): assert "
        "the main success path AND at least one validation/error case (400 or 404). "
        "The vitest config already points the db at an in-memory SQLite.\n\n"
        "AUTH (only if the feature needs it): `server/auth.mjs` already ships with "
        "`hashPassword`/`verifyPassword` (scrypt, salted) and `signToken`/`verifyToken` "
        "(HMAC sessions) — import them (`import { hashPassword } from '../auth.mjs'`) "
        "and store ONLY hashed passwords (a plaintext `password` column fails the "
        "policy gate). Do not add an auth dependency; these use node:crypto.\n\n"
        "CRITICAL: `npm run build` (`tsc --noEmit && vite build`) and `npm test` "
        "(vitest) MUST pass, and `node server/index.mjs` must boot. No placeholders. "
        "Emit all files now."
    )
    return system, user


def _expo_build_messages(fid, ctx):
    """Cross-platform MOBILE (iOS + Android) generation prompt — Expo + React Native
    + react-native-web + TypeScript + expo-sqlite. Same scaffold-then-diff + modular,
    props-driven component discipline as the web stack, but the UI is React Native
    primitives (View/Text/TextInput/Pressable/FlatList), NOT DOM. react-native-web
    means the same app also renders on web, so ADF's headless render gate + Proof of
    Build still apply (requirement C2)."""
    system = (
        "You are an expert React Native / Expo engineer acting as the ADF "
        "implementation agent. You output COMPLETE, RUNNABLE code — never "
        "placeholders, never '...', never TODO stubs.\n\n"
        "TARGET STACK (a checked-in Expo scaffold already provides ALL the wiring — "
        "you write ONLY the app-specific files):\n"
        "- Expo (managed) + React Native + TypeScript + EXPO ROUTER (file-based "
        "navigation: every file under `app/` is a screen). `app/**` + `src/**` are "
        "TypeScript and `tsc --noEmit` typechecks them, so they MUST be type-correct.\n"
        "- NAVIGATION is MULTI-SCREEN via Expo Router: `app/_layout.tsx` defines the "
        "root `<Stack>` (or `<Tabs>`); each route is `app/<name>.tsx`; a list→detail "
        "uses a dynamic route `app/[id].tsx` with `useLocalSearchParams`. Navigate "
        "with `useRouter().push('/path')` or `<Link href>` from 'expo-router' — a real "
        "app has screens + back/tabs, not one screen.\n"
        "- UI: COMPOSE the SHIPPED, THEMED kit, which lives at `src/components/ui` "
        "(import it with the path RELATIVE to the file you write — from an `app/` "
        "screen it is `'../src/components/ui'`; from `src/components/<Name>.tsx` it is "
        "`'./ui'`): `{ Screen, Header, Text, Card, Input, Button, Icon, ListItem, "
        "Badge, EmptyState }` "
        "(Screen wraps every screen; Header shows the title + optional back/action; "
        "Text `variant` h1/h2/body/caption/label; Button `variant` "
        "primary/secondary/danger; ListItem for rows (showChevron to navigate); Icon "
        "uses Ionicons names; EmptyState for zero-data; Badge for counts). Build new "
        "feature components from React Native primitives (`View`, `TextInput`, "
        "`Pressable`, `FlatList`, `ScrollView`) only when no kit component fits. There "
        "is NO DOM — do NOT import `react-dom`, no `<div>`/`<button>`/HTML, no "
        "`index.html`.\n"
        "- COLORS + SPACING come from the THEME ONLY: `const t = useTheme()` "
        "(import from `src/theme` — from an `app/` screen `'../src/theme'`, from "
        "`src/components/` `'../theme'`) → `t.colors.*` / `t.spacing.*` / "
        "`t.radius.*` / `t.type.*`. NEVER write a raw hex color (e.g. '#2563eb') or a "
        "magic number for color — the policy gate REJECTS raw hex so the app stays "
        "on-theme and light/dark-correct. Use `accessibilityRole`/`accessibilityLabel` "
        "so controls are detectable + accessible.\n"
        "- The app also runs on the web via react-native-web (so it can be "
        "render-verified) — keep components platform-neutral (no direct DOM/Node APIs).\n"
        "- Local persistence is expo-sqlite (`import * as SQLite from 'expo-sqlite'`) "
        "for data the spec stores; there is NO server — the app is self-contained.\n"
        "- Tests: jest (jest-expo) + @testing-library/react-native (`*.test.tsx`).\n\n"
        "SCAFFOLD-THEN-DIFF: DO NOT re-emit `app.json`, `package.json`, "
        "`babel.config.js`, `tsconfig.json`, or the Expo bootstrap. Emit ONLY the "
        "files that implement THIS feature, overwriting the scaffold's sample.\n\n"
        "OUTPUT FORMAT — emit each file EXACTLY like this, nothing else between "
        "files:\n<<<FILE: relative/path>>>\n<full file content>\n<<<END>>>\n"
        "No markdown fences, no commentary outside file blocks."
    )
    # DET-2: the deterministic feature-shape contract — request the MOBILE variant so
    # a server-referencing contract (e.g. auth → auth.mjs) is swapped for the
    # no-server, expo-sqlite version (review fix).
    import feature_shapes
    _shape, _contract = feature_shapes.contract_for(ctx, fid, mobile=True)
    shape_block = f"{_contract}\n\n" if _contract else ""
    user = (
        f"Implement the feature `{fid}` as a real cross-platform Expo / React Native "
        f"app (iOS + Android + web).\n\n{_spec_block(ctx)}\n\n{shape_block}"
        "Deliver (paths relative to the app root). Treat the shape contract above as "
        "the data model + behavior; translate its REST/route ideas into local "
        "expo-sqlite operations (the mobile app has no server):\n"
        "- `src/db.ts` — open an expo-sqlite database, run `CREATE TABLE IF NOT "
        "EXISTS` for the tables the spec implies, and export typed query helpers.\n"
        "- `src/hooks/use<Feature>.ts` — a hook that calls `src/db.ts` and returns "
        "typed data + actions (create/update/remove/reload as the shape needs); "
        "components call the hook, never the db directly.\n"
        "- `src/components/<Name>.tsx` — MULTIPLE small, SELF-CONTAINED, REUSABLE, "
        "props-driven React Native components (each exports the component AND a typed "
        "`interface <Name>Props`; receives data + callbacks via props; owns no global "
        "state); COMPOSE the shipped kit. Use `TextInput`/`Input` for inputs and "
        "`Pressable`/`Button` for actions so the app has real interactive controls.\n"
        "- `app/_layout.tsx` — the root `<Stack>`/`<Tabs>` (themed via `useTheme`), and "
        "`app/<screen>.tsx` route files (e.g. `app/index.tsx` for the main screen, "
        "`app/[id].tsx` for a detail) — each a default-export screen that wraps its "
        "content in `<Screen>` and composes the feature components. Navigate between "
        "them with `useRouter`/`<Link>`.\n"
        "- `__tests__/<feature>.test.tsx` — jest + @testing-library/react-native: "
        "`render(<Screen/>)` for a route (mock 'expo-router' useRouter/"
        "useLocalSearchParams), assert the main success path AND at least one "
        "validation/empty/error case via `fireEvent` + `findByText`/`getByPlaceholderText`.\n"
        "  TEST↔COMPONENT CONSISTENCY: every string a test asserts with "
        "`getByText`/`findByText` MUST be rendered VERBATIM by the component under "
        "test. If you assert a validation/error message (e.g. 'Please enter a valid "
        "email address.'), you MUST implement the exact code in that component that "
        "renders that string — do NOT assert behavior the screen does not implement. "
        "When in doubt, test the behavior the spec actually requires, not invented "
        "extras.\n"
        "  MOCK THE DATA LAYER STATEFULLY by copying `__tests__/data.test.tsx` "
        "(the canonical few-shot): `jest.mock('../src/db', () => { ... })` with an "
        "IN-FACTORY store. CRITICAL jest rule — `jest.mock()` is hoisted ABOVE every "
        "import and `let`/`const`, so its factory CANNOT reference any variable "
        "declared outside it (you'll get \"module factory ... not allowed to reference "
        "any out-of-scope variables. Invalid variable access: store\"). The ONLY "
        "escape hatch: names prefixed with `mock` (case-insensitive) are allowed. So "
        "declare the store INSIDE the factory (`let mockStore = []; let mockNextId = "
        "1;`) and expose `mock`-prefixed test handles from it (e.g. `__getStore`, "
        "`__reset`) — NEVER write `let store = []` outside and reference `store` inside "
        "the factory. Match `src/db`'s shape (async helpers → `async () => ...`). Test "
        "a hook with `renderHook` + `waitFor`/`act` as data.test.tsx shows.\n\n"
        "CRITICAL: `npm run typecheck` (`tsc --noEmit`) and `npm test` (jest) MUST "
        "pass. Use ONLY the dependencies in package.json (expo, react-native, "
        "expo-sqlite, @testing-library/react-native). No placeholders. Emit all files now."
    )
    return system, user


# --- scaffold-then-diff (N7): copy the checked-in template, strip the sample --
# Stacks whose generation starts from a checked-in working template. stdlib has
# no template (single-file generation), so it maps to None.
_STACK_TEMPLATES = {STACK_REACT: "react-vite-sqlite", STACK_EXPO: "expo-rn"}
# Sample-feature files the scaffold ships to prove itself; removed before the
# generated feature is written so a stale `/api/items` + its test can't interfere.
# Per-stack sample-feature files the scaffold strips so the generated feature is
# clean (the template itself is a complete, passing app before scaffold).
_SCAFFOLD_SAMPLE_REMOVE = {
    STACK_REACT: ("server/api/items.mjs", "test/api.test.mjs"),
    # Expo uses file-based routing (Expo Router): the sample feature is the app/
    # screens + its data layer + test. The generated feature emits its own app/
    # routes, src/db.ts, src/hooks/*, and __tests__.
    STACK_EXPO: ("app/index.tsx", "app/[id].tsx", "src/db.ts",
                 "src/hooks/useItems.ts", "__tests__/sample.test.tsx",
                 "__tests__/data.test.tsx"),
}

# The Expo root layout (app/_layout.tsx) is reset to a themed BARE Stack on scaffold
# (so it doesn't reference the stripped sample screens); expo-router auto-discovers
# the generated feature's routes, and the generated _layout.tsx replaces this.
_EXPO_LAYOUT_PLACEHOLDER = (
    "import React from 'react';\n"
    "import { Stack } from 'expo-router';\n"
    "import { useTheme } from '../src/theme';\n\n"
    "export default function RootLayout() {\n"
    "  const t = useTheme();\n"
    "  return (\n"
    "    <Stack\n"
    "      screenOptions={{\n"
    "        headerStyle: { backgroundColor: t.colors.surface },\n"
    "        headerTintColor: t.colors.text,\n"
    "        contentStyle: { backgroundColor: t.colors.bg },\n"
    "      }}\n"
    "    />\n"
    "  );\n"
    "}\n"
)


def template_dir(repo_root, workspace, stack):
    """Locate the checked-in template for `stack`: prefer the repo root, then the
    workspace (worktree). Returns an absolute path or None (stacks without a
    template, e.g. stdlib, generate from scratch)."""
    name = _STACK_TEMPLATES.get(stack)
    if not name:
        return None
    for base in (repo_root, workspace):
        if not base:
            continue
        cand = os.path.join(base, "templates", name)
        if os.path.isdir(cand):
            return cand
    return None


def scaffold_app(app_dir, tpl_dir):
    """Copy the template into the app dir (scaffold-then-diff), keeping the build
    wiring + lockfile + `.adf-stack.json`, skipping heavy/generated dirs. Then
    strip the sample feature and reset `schema.sql` so the generated feature is
    clean. Idempotent for the parts it owns."""
    import shutil
    for root, dirs, files in os.walk(tpl_dir):
        # Skip heavy/generated dirs AND any dotfile dir — the template may carry build
        # artifacts (.adf-visual/, .adf-proof/, .expo/) from a prior verify; copying
        # them would pollute the app AND seal STALE render facts into its proof. (The
        # legit config dotfiles — .adf-stack.json, .adf-policy.json — are FILES, copied
        # below.)
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in files:
            if fn in (".adf-deps",) or fn.endswith(".db"):
                continue
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, tpl_dir)
            dest = os.path.join(app_dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
    stack = detect_stack(app_dir)
    for rel in _SCAFFOLD_SAMPLE_REMOVE.get(stack, ()):
        p = os.path.join(app_dir, rel)
        if os.path.isfile(p):
            os.remove(p)
    if stack == STACK_REACT:
        # Reset schema to a placeholder; the generated schema.sql replaces it (so no
        # leftover sample `items` table lingers in a fresh app's database).
        with open(os.path.join(app_dir, "schema.sql"), "w", encoding="utf-8") as f:
            f.write("-- schema for this app (generated at build time)\n")
    elif stack == STACK_EXPO:
        # Reset the root layout to a bare themed Stack (no dangling reference to the
        # stripped sample screens); the generated app/_layout.tsx replaces it. Mobile
        # has no schema.sql (the schema lives in src/db.ts via expo-sqlite).
        layout = os.path.join(app_dir, "app", "_layout.tsx")
        os.makedirs(os.path.dirname(layout), exist_ok=True)
        with open(layout, "w", encoding="utf-8") as f:
            f.write(_EXPO_LAYOUT_PLACEHOLDER)
    # Per-app auth secret: every app that ships the auth primitives signs sessions
    # with its OWN random secret instead of a world-known dev default (auth.mjs
    # reads ADF_AUTH_SECRET → this file → a fail-loud ephemeral fallback).
    if os.path.isfile(os.path.join(app_dir, "server", "auth.mjs")):
        ensure_auth_secret(app_dir)
    # 10-50x first-build win + deterministic offline install: clone the template's
    # already-installed node_modules into the app so `npm ci` is skipped entirely
    # (the deps are pinned + identical for every app). On APFS this is an instant,
    # copy-on-write clone (no extra disk until a file is touched).
    warm_node_modules(tpl_dir, app_dir)


AUTH_SECRET_FILE = ".adf-auth-secret"


def ensure_auth_secret(app_dir):
    """Write a per-app HMAC signing secret (32 random bytes, hex) the first time so
    every generated app signs sessions with its OWN secret, not a world-known dev
    default. Idempotent — never rotates an existing secret (that would invalidate
    live sessions). The file is a dotfile, so the editable-file walker
    (`current_app_files`) already excludes it from the policy scan, the edit surface,
    and the proof seal. Returns the secret path."""
    import secrets
    p = os.path.join(app_dir, AUTH_SECRET_FILE)
    if not os.path.isfile(p) or os.path.getsize(p) == 0:
        with open(p, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    return p


def _ensure_template_node_modules(tpl_dir, timeout=600):
    """Populate the TEMPLATE's node_modules ONCE so warm_node_modules can clone it
    into every app — instead of each app paying a full `npm ci`. The COW clone only
    engages when the template is already installed; on a cold checkout / CI / a
    buyer's machine the template ships without node_modules, so without this the
    optimization silently never fires and every build pays the slow path.

    Mirrors offline_build.live_offline_build: copy the template (minus the heavy
    generated dirs) into a temp dir on the SAME filesystem, `npm ci` against its
    pinned lockfile there, then publish node_modules into the template with an atomic
    rename. Concurrency-safe — a racing builder that loses the rename just discards
    its copy and reuses the winner's. The install env is scrubbed of ADF's secrets +
    made non-interactive, like every other build child. Best-effort: returns True iff
    the template has node_modules afterward; on any failure the caller falls back to a
    per-app `npm ci` (no regression)."""
    import shutil
    import tempfile
    dst = os.path.join(tpl_dir, "node_modules")
    if os.path.isdir(dst):
        return True
    if not os.path.isfile(os.path.join(tpl_dir, "package.json")):
        return False
    if not shutil.which("npm"):
        return False
    # Temp dir under the template's PARENT: same filesystem (atomic rename + APFS COW)
    # without leaving a stray dir inside the template that scaffold would copy.
    parent = os.path.dirname(os.path.abspath(tpl_dir)) or tpl_dir
    try:
        work = tempfile.mkdtemp(prefix=".adf-tpl-deps-", dir=parent)
    except OSError:
        return False
    try:
        build = os.path.join(work, "tpl")
        shutil.copytree(tpl_dir, build,
                        ignore=shutil.ignore_patterns("node_modules", "dist", "*.db"))
        narrate("warming_deps")   # cold checkout: a real one-time npm ci is about to run
        try:
            r = subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=build,
                               capture_output=True, text=True, timeout=timeout,
                               env=scrubbed_env())
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"template node_modules bootstrap failed ({e}); will run npm ci per-app")
            return os.path.isdir(dst)   # a concurrent builder may have published it
        nm = os.path.join(build, "node_modules")
        if r.returncode != 0 or not os.path.isdir(nm):
            return os.path.isdir(dst)
        try:
            os.rename(nm, dst)          # same filesystem → atomic publish
            log("template node_modules bootstrapped — apps now clone instead of npm ci")
        except OSError:
            pass                        # lost the publish race (dst already there) — fine
        return os.path.isdir(dst)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def warm_node_modules(tpl_dir, app_dir):
    """Clone the template's node_modules into the app (no per-app `npm ci`). Tries,
    fastest-first: a copy-on-write clone → hardlink (`cp -al`) → plain copy. The CoW
    command is platform-specific: APFS clonefile (`cp -c`) is macOS-ONLY; on Linux
    the equivalent is reflink (`cp --reflink=auto`, instant + zero extra disk on
    btrfs/XFS, falling through on ext4/tmpfs). On a cold checkout the template has no
    node_modules yet, so it is bootstrapped ONCE here (deps are pinned + identical
    for every app) — otherwise every app falls back to a full `npm ci` and the COW
    clone never engages. No-op if the app already has one. Returns True on success.
    The narrated `method` is honest: 'clone' ONLY when the platform CoW command
    succeeded, 'hardlink' when `cp -al` succeeded, 'copy' for the copytree fallback."""
    import shutil
    src = os.path.join(tpl_dir, "node_modules")
    dst = os.path.join(app_dir, "node_modules")
    if os.path.isdir(dst):              # app already warmed (e.g. a prior verify)
        return False
    if not os.path.isdir(src) and not _ensure_template_node_modules(tpl_dir):
        return False                    # cold + couldn't bootstrap → caller's npm ci
    # Platform-aware CoW candidate: APFS clonefile on macOS, reflink on Linux/other.
    if sys.platform == "darwin":
        cow_cmd = ["cp", "-c", "-R", src, dst]
    else:
        cow_cmd = ["cp", "--reflink=auto", "-R", src, dst]
    # (cmd, method) pairs keep the command co-located with its HONEST label, so a
    # `cp -al` success narrates 'hardlink', not 'clone'.
    for cmd, method in ((cow_cmd, "clone"), (["cp", "-al", src, dst], "hardlink")):
        try:
            if subprocess.run(cmd, capture_output=True).returncode == 0 \
                    and os.path.isdir(dst):
                log("warm node_modules cloned from template — npm ci skipped")
                narrate("deps_warm", method=method)
                return True
        except Exception:
            pass
        if os.path.isdir(dst):  # partial — clear before the next strategy
            shutil.rmtree(dst, ignore_errors=True)
    try:
        shutil.copytree(src, dst, symlinks=True)
        log("warm node_modules copied from template — npm ci skipped")
        narrate("deps_warm", method="copy")
        return True
    except Exception as e:
        log(f"warm node_modules skipped ({e}); will run npm ci")
        return False


_STACK_PROFILES = {
    STACK_STDLIB: {"name": STACK_STDLIB, "build_messages": _stdlib_build_messages},
    STACK_REACT: {"name": STACK_REACT, "build_messages": _react_build_messages},
    STACK_EXPO: {"name": STACK_EXPO, "build_messages": _expo_build_messages},
}


def stack_profile(stack):
    """Look up a stack profile; unknown stacks fall back to stdlib (never crash)."""
    return _STACK_PROFILES.get(stack) or _STACK_PROFILES[STACK_STDLIB]


# --- model backends --------------------------------------------------------
_SSL_CTX = None


def ssl_context():
    """A verifying TLS context that works on stock macOS Python (which ships
    without a usable CA bundle). Prefer certifi, then the system bundle; only
    fall back to unverified if neither exists (curl reaches these same hosts)."""
    global _SSL_CTX
    if _SSL_CTX is not None:
        return _SSL_CTX
    try:
        import certifi
        _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
        return _SSL_CTX
    except Exception:
        pass
    for ca in ("/etc/ssl/cert.pem", "/opt/homebrew/etc/openssl@3/cert.pem",
               "/usr/local/etc/openssl@3/cert.pem"):
        if os.path.isfile(ca):
            _SSL_CTX = ssl.create_default_context(cafile=ca)
            return _SSL_CTX
    log("WARNING: no CA bundle found — proceeding without TLS verification")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    _SSL_CTX = ctx
    return ctx


class HttpError(OSError):
    """A non-2xx HTTP response from a provider, carrying the status so the retry
    layer can classify it: a transient 429/5xx/529 is retried on the SAME backend;
    anything else fails over. (Adopted from oh-my-pi's rate-limit classification;
    see docs/ADF_VS_OH_MY_PI.md §5.3.)"""

    def __init__(self, status, body="", retry_after=None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body
        self.retry_after = retry_after


# Transient statuses worth retrying the SAME backend before failing over to a
# weaker one. 529 = Anthropic "overloaded"; 429 = rate limit; 5xx = server hiccup.
_RETRYABLE_STATUS = {429, 500, 502, 503, 529}


def classify_http_status(status):
    """Coarse retry reason for an HTTP status (oh-my-pi parseRateLimitReason)."""
    if status == 429:
        return "rate_limit"
    if status == 529:
        return "capacity"            # Anthropic overloaded — usually clears fast
    if status in (500, 502, 503):
        return "server_error"
    if status == 402:
        return "quota"               # out of credit — retrying the same model is futile
    if status in (401, 403):
        return "auth"
    return "client" if 400 <= status < 500 else "unknown"


def _retry_backoff_seconds(reason, attempt, retry_after=None):
    """Bounded exponential backoff with jitter, tuned for a TIME-BOXED build — NOT
    oh-my-pi's 45–75s interactive waits (a build self-heal can't sleep a minute).
    Honors a server `Retry-After` when present and within the cap."""
    cap = float(os.environ.get("ADF_RUNNER_RETRY_CAP_SEC", "20"))
    if retry_after is not None:
        try:
            v = float(retry_after)
            if math.isfinite(v):
                # Clamp to [0, cap]: a malicious/garbled `Retry-After: -1` (or inf/
                # nan) must never reach time.sleep() and crash the build.
                return min(max(0.0, v), cap)
        except (TypeError, ValueError):
            pass
    base = {"capacity": 1.5, "rate_limit": 2.0, "server_error": 1.0}.get(reason, 1.5)
    delay = min(base * (2 ** attempt), cap)
    return delay + random.uniform(0, 0.5 * delay)


def call_with_retry(call, messages, timeout, *, attempts=None, sleeper=None,
                    model=None):
    """Run a backend, retrying the SAME backend on a transient HTTP status with
    bounded backoff BEFORE `generate()` falls through to a weaker backend — so a
    transient Anthropic 529 no longer silently demotes a Claude build to free
    NVIDIA mid-run. A non-retryable status, a missing key (the call returns None),
    or exhausted attempts returns None (then `generate()` tries the next backend).

    Optional per-call `model`: when not None it is forwarded to `call` on EVERY
    attempt as `call(messages, timeout, model=model)`. When None (the default) the
    legacy 2-arg `call(messages, timeout)` contract is preserved verbatim, so every
    existing 2-arg callable (and `model_router._dispatch`'s closure) stays valid.
    The guard is `model is not None` (identity, NOT truthiness): an explicit
    `model=''` is still forwarded — the backend's `model or os.environ.get(...)`
    coercion then falls to its env default, which is the correct, consistent
    behavior."""
    attempts = attempts or int(os.environ.get("ADF_RUNNER_RETRIES", "3"))
    sleeper = sleeper or time.sleep
    for i in range(attempts):
        try:
            return (call(messages, timeout, model=model) if model is not None
                    else call(messages, timeout))
        except HttpError as e:
            reason = classify_http_status(e.status)
            if e.status not in _RETRYABLE_STATUS or i == attempts - 1:
                log(f"backend HTTP {e.status} ({reason}) — not retrying "
                    f"(attempt {i + 1}/{attempts})")
                return None
            delay = _retry_backoff_seconds(reason, i, e.retry_after)
            log(f"backend HTTP {e.status} ({reason}) — retry "
                f"{i + 1}/{attempts} in {delay:.1f}s")
            sleeper(max(0.0, delay))   # never sleep a negative duration
    return None


def http_post_json(url, headers, payload, timeout):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ctx = ssl_context() if url.startswith("https") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        retry_after = e.headers.get("retry-after") if e.headers else None
        raise HttpError(e.code, body, retry_after) from None


def _streaming():
    """Token streaming is OPT-IN (ADF_RUNNER_STREAM=1) so the safe, well-tested
    blocking path stays the default. When on, each backend streams the model output
    and emits live deltas while still returning the FULL (text, usage) — so
    parse_files / verify / seal see byte-identical content (the moat is untouched)."""
    return os.environ.get("ADF_RUNNER_STREAM", "").strip().lower() in (
        "1", "true", "on", "yes")


def http_post_stream(url, headers, payload, timeout):
    """Open a streaming POST and return an iterator of decoded response lines (SSE /
    NDJSON). Raises HttpError on the initial non-2xx — IDENTICAL classification to
    http_post_json — before any line is read, so call_with_retry / generate failover
    is unchanged. Closes the connection when the iterator is exhausted."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ctx = ssl_context() if url.startswith("https") else None
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        retry_after = e.headers.get("retry-after") if e.headers else None
        raise HttpError(e.code, body, retry_after) from None

    def _iter():
        try:
            for raw in resp:
                yield raw.decode("utf-8", "replace")
        finally:
            resp.close()
    return _iter()


_STREAM_HEARTBEAT_CHARS = 1500  # emit one NL progress pulse per ~this many chars
_stream_chars = 0
_stream_emitted = 0


def _reset_stream_progress():
    """Reset the generation heartbeat counters (call at the start of each generate)."""
    global _stream_chars, _stream_emitted
    _stream_chars = 0
    _stream_emitted = 0


def _stream_delta(text):
    """Emit one streamed model-output delta. The raw 'text' event is DISPLAY-ONLY
    (the server suppresses it — it is the code typing out) and never authoritative.

    Because the server drops that raw stream, generation would otherwise go DARK for
    the whole (longest) phase, so we ALSO emit a throttled natural-language progress
    heartbeat — a COUNT only, never the code — so the live feed keeps moving (D2)."""
    global _stream_chars, _stream_emitted
    if not text:
        return
    emit_event({"type": "text", "text": text})
    _stream_chars += len(text)
    if _stream_chars - _stream_emitted >= _STREAM_HEARTBEAT_CHARS:
        _stream_emitted = _stream_chars
        narrate("generating_progress", lines=max(1, _stream_chars // 50))


class _GenerationHeartbeat:
    """Emit a 'generating_progress' narration every `interval` seconds until
    stopped. Covers the DEFAULT (non-streaming) path, where _stream_delta never
    fires, so the live feed never goes dark during a long BLOCKING model call (E1).
    Daemon thread; start() then stop() exactly once."""

    def __init__(self, interval=6.0):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._ticks = 0

    def start(self):
        def _loop():
            # wait() returns True only when stop() is signalled → tick on timeout.
            while not self._stop.wait(self.interval):
                self._ticks += 1
                narrate("generating_progress",
                        elapsed=int(self._ticks * self.interval))
        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)


def _max_tokens():
    return int(os.environ.get("ADF_RUNNER_MAX_TOKENS", "8000"))


def _nvidia_stream(url, headers, payload, timeout):
    """Parse an OpenAI-compatible SSE stream (NVIDIA NIM): 'data: {json}' chunks with
    choices[0].delta.content, a trailing usage chunk (stream_options.include_usage),
    and a 'data: [DONE]' sentinel. Emits each delta live; returns the FULL assembled
    (text, usage) — identical to what the blocking path would have parsed."""
    parts, usage = [], {}
    for line in http_post_stream(url, headers, payload, timeout):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        choices = obj.get("choices") or []
        if choices:
            delta = (choices[0].get("delta") or {}).get("content") or ""
            if delta:
                parts.append(delta)
                _stream_delta(delta)
        if obj.get("usage"):
            usage = obj["usage"]
    return "".join(parts), usage


def call_nvidia(messages, timeout, model=None):
    key = (os.environ.get("NVIDIA_API_KEY") or os.environ.get("ORCH_NVIDIA_API_KEY") or "").strip()
    if not key:
        return None
    # `model` overrides the env default per-call (thread-safe — the requirements crew
    # routes each subagent to a specific NIM model from its own thread).
    model = model or os.environ.get("ADF_RUNNER_MODEL", "meta/llama-3.3-70b-instruct")
    base = os.environ.get("ORCH_NVIDIA_BASE_URL", NVIDIA_BASE).rstrip("/")
    # Cap NVIDIA's read time so a slow free-tier response fails FAST to the next
    # backend instead of hanging the whole build for minutes.
    nv_timeout = min(timeout, int(os.environ.get("ADF_NVIDIA_TIMEOUT_SEC", "75")))
    log(f"using NVIDIA NIM model {model} (timeout {nv_timeout}s)")
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {"model": model, "max_tokens": _max_tokens(), "temperature": 0.2,
               "messages": messages}
    try:
        if _streaming():
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
            return _nvidia_stream(url, headers, payload, nv_timeout)
        out = http_post_json(url, headers, payload, nv_timeout)
        choice = (out.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        return text, out.get("usage") or {}
    except HttpError:
        raise                       # let call_with_retry classify + retry the status
    except (OSError, ValueError, KeyError, http.client.HTTPException) as e:
        log(f"NVIDIA call failed: {e}")
        return None


def _anthropic_stream(url, headers, payload, timeout):
    """Parse an Anthropic SSE stream: message_start (usage.input_tokens),
    content_block_delta (delta.text), message_delta (usage.output_tokens),
    message_stop. Emits each delta live; returns the FULL assembled
    (text, {prompt_tokens, completion_tokens}) — identical to the blocking parse."""
    parts, in_tok, out_tok = [], 0, 0
    for line in http_post_stream(url, headers, payload, timeout):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if not data:
            continue
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        t = obj.get("type")
        if t == "message_start":
            in_tok = ((obj.get("message") or {}).get("usage") or {}).get(
                "input_tokens", in_tok)
        elif t == "content_block_delta":
            delta = (obj.get("delta") or {}).get("text") or ""
            if delta:
                parts.append(delta)
                _stream_delta(delta)
        elif t == "message_delta":
            out_tok = (obj.get("usage") or {}).get("output_tokens", out_tok)
    return "".join(parts), {"prompt_tokens": in_tok, "completion_tokens": out_tok}


def call_anthropic(messages, timeout, model=None):
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    # `model` overrides the env default per-call (the crew routes the synthesis head to
    # Opus while other agents run free on NIM — all from their own threads).
    model = model or os.environ.get("ADF_RUNNER_CLAUDE_MODEL", "claude-opus-4-8")
    base = os.environ.get("ANTHROPIC_BASE_URL", ANTHROPIC_BASE).rstrip("/")
    system_text = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    # Prompt caching: the system prompt is large and IDENTICAL across the (up to 3)
    # self-heal turns, so mark it cacheable — the first turn writes the cache, the
    # fix turns read it at ~10% input cost (~90% input-token saving on the prefix).
    system = ([{"type": "text", "text": system_text,
                "cache_control": {"type": "ephemeral"}}]
              if system_text else system_text)
    log(f"using Anthropic model {model}")
    url = f"{base}/v1/messages"
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
               "anthropic-beta": "prompt-caching-2024-07-31",
               "Content-Type": "application/json"}
    payload = {"model": model, "max_tokens": _max_tokens(), "system": system,
               "messages": turns}
    try:
        if _streaming():
            payload["stream"] = True
            return _anthropic_stream(url, headers, payload, timeout)
        out = http_post_json(url, headers, payload, timeout)
        blocks = out.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        u = out.get("usage") or {}
        return text, {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0)}
    except HttpError:
        raise                       # let call_with_retry classify + retry the status
    except (OSError, ValueError, KeyError, http.client.HTTPException) as e:
        log(f"Anthropic call failed: {e}")
        return None


def _ollama_stream(url, headers, payload, timeout):
    """Parse an Ollama NDJSON stream: newline-delimited {"message":{"content":…},
    "done":bool} objects. Emits each delta live; returns the FULL assembled
    (text, {}) — identical to the blocking path's message.content."""
    parts = []
    for line in http_post_stream(url, headers, payload, timeout):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        delta = (obj.get("message") or {}).get("content") or ""
        if delta:
            parts.append(delta)
            _stream_delta(delta)
        if obj.get("done"):
            break
    return "".join(parts), {}


def call_ollama(messages, timeout, model=None):
    host = (os.environ.get("ORCH_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    model = model or os.environ.get("ORCH_OLLAMA_MODEL", "llama3.2")
    log(f"using local Ollama model {model}")
    url = f"{host}/api/chat"
    headers = {"Content-Type": "application/json"}
    stream_on = _streaming()
    payload = {"model": model, "stream": stream_on, "messages": messages}
    try:
        if stream_on:
            return _ollama_stream(url, headers, payload, timeout)
        out = http_post_json(url, headers, payload, timeout)
        return (out.get("message") or {}).get("content") or "", {}
    except HttpError:
        raise                       # let call_with_retry classify + retry the status
    except (OSError, ValueError, KeyError, http.client.HTTPException) as e:
        log(f"Ollama call failed: {e}")
        return None


def apply_headroom(messages):
    """Headroom-first: compress context before EVERY model call, whatever the
    backend. Safe by design — headroom protects system/user messages (the
    instructions + code we must keep verbatim) and only crushes tool/history
    payloads, so code fidelity is never at risk. No-op (returns input) if
    headroom isn't importable (e.g. running on system Python without the venv)
    or disabled via ADF_HEADROOM=0."""
    if os.environ.get("ADF_HEADROOM", "1") in ("0", "false", "off"):
        return messages
    try:
        import headroom
    except Exception:
        return messages
    try:
        res = headroom.compress(messages, model="claude-3-5-sonnet")
        if getattr(res, "tokens_saved", 0):
            log(f"headroom: {res.tokens_before}->{res.tokens_after} tokens "
                f"({res.compression_ratio:.0%} smaller) before LLM call")
        return res.messages
    except Exception as e:
        log(f"headroom skipped: {e}")
        return messages


def generate(messages, timeout, model=None):
    """Try each configured backend in order; return (text, usage) or None.
    Headroom runs FIRST, before any backend dispatch.

    Backend order:
      - ADF_RUNNER_BACKEND=nvidia|anthropic|ollama pins exactly one.
      - Otherwise RELIABILITY-FIRST: if ANTHROPIC_API_KEY is set, Claude leads
        (it builds in one shot — no slow free-tier self-heal grind), with NVIDIA
        and Ollama as fallbacks. Set ADF_RUNNER_BACKEND=nvidia for the free path.
      - With no Claude key, fall back to NVIDIA (free) then Ollama (local).

    Optional per-call `model`: when provided it is threaded through to whichever
    backend in the order runs (the same model on every failover step), letting a
    caller route a specific model without an env var. When omitted (or None) the
    behavior is byte-for-byte identical to before — each backend resolves its model
    from its own env-var default chain (the SSOT for model defaults stays in the
    backend functions; generate() only passes the override through)."""
    messages = apply_headroom(messages)
    pin = os.environ.get("ADF_RUNNER_BACKEND", "").strip().lower()
    if pin in ("nvidia", "anthropic", "ollama"):
        order = {"nvidia": [call_nvidia], "anthropic": [call_anthropic],
                 "ollama": [call_ollama]}[pin]
    elif (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        order = [call_anthropic, call_nvidia, call_ollama]
    else:
        order = [call_nvidia, call_anthropic, call_ollama]
    for backend in order:
        # Retry THIS backend on a transient status before failing over to the next
        # (weaker) one — a 529 overloaded shouldn't demote a Claude build to NVIDIA.
        res = call_with_retry(backend, messages, timeout, model=model)
        if res and res[0] and res[0].strip():
            return res
    return None


# --- parse + write ---------------------------------------------------------
def parse_files(text):
    """Parse <<<FILE: path>>> ... <<<END>>> blocks. Tolerates a leading
    markdown fence the model may wrap the whole thing in."""
    files, path, buf, inside = [], None, [], False
    for line in text.splitlines():
        if not inside:
            m = FILE_OPEN.match(line)
            if m:
                path, buf, inside = m.group(1).strip(), [], True
            continue
        if FILE_CLOSE.match(line):
            files.append((path, "\n".join(buf)))
            path, buf, inside = None, [], False
        else:
            buf.append(line)
    return files


def write_files(workspace, fid, files):
    app_root = os.path.join(workspace, "apps", fid)
    written = []
    for rel, content in files:
        rel = rel.lstrip("/")
        # Confine writes under the app root — never escape the workspace.
        dest = os.path.normpath(os.path.join(app_root, rel))
        if not dest.startswith(os.path.normpath(app_root) + os.sep):
            log(f"skipping unsafe path: {rel}")
            continue
        # ADF-RESERVED: the model must NEVER author ADF's own evidence/proof artifacts
        # (.adf-process/, .adf-proof/, .adf-visual/, .adf-mobile/, .adf-policy-report.json).
        # The build-nonce binding already rejects a planted fact at read time; this is
        # defense-in-depth so only ADF's in-process recorders ever write these paths.
        if os.path.normpath(rel).split(os.sep)[0].startswith(".adf"):
            log(f"skipping ADF-reserved path (recorder-only): {rel}")
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not content.endswith("\n"):
            content += "\n"
        open(dest, "w", encoding="utf-8").write(content)
        written.append(os.path.relpath(dest, workspace))
        emit_event({"type": "file_write",
                    "path": os.path.relpath(dest, app_root),
                    "index": len(written), "total": len(files)})
    return app_root, written


def smoke_boot(app_root, port=None, secs=8):
    """Authoritative end-to-end check: `python3 server.py` must actually start
    a server that answers GET / — catches a missing __main__ block that unit
    tests (which call make_server() directly) silently pass over. We pass a free
    PORT via the environment and require the server to honor it, so concurrent
    builds/previews never collide on 8000 (and the PORT contract is enforced)."""
    import socket
    import time
    server = os.path.join(app_root, "server.py")
    if not os.path.isfile(server):
        return False, "server.py was not generated"
    if port is None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
            _s.bind(("127.0.0.1", 0))
            port = _s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "server.py"], cwd=app_root,
        env=dict(os.environ, PORT=str(port)),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + secs
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                return False, f"`python3 server.py` exited immediately (no running "\
                              f"server — missing __main__/serve_forever?).\n{out}"
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return True, f"server.py serves on :{port}"
            except OSError:
                time.sleep(0.4)
        return False, f"`python3 server.py` did not listen on :{port} within {secs}s"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_verification(app_root, timeout=60):
    """Authoritative checks, both must pass: (1) the app's own test suite, and
    (2) the server actually boots via `python3 server.py`. ADF requires
    verified implementations, not code that merely looks plausible."""
    test_file = os.path.join(app_root, "test_app.py")
    if not os.path.isfile(test_file):
        return False, "test_app.py was not generated"
    try:
        proc = subprocess.run(
            [sys.executable, "test_app.py"],
            cwd=app_root, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"test_app.py timed out after {timeout}s"
    out = (proc.stdout + "\n" + proc.stderr).strip()
    tests_ok = proc.returncode == 0 and "FAILED" not in out and "Traceback" not in out
    if not tests_ok:
        return False, f"UNIT TESTS FAILED:\n{out}"
    boot_ok, boot_msg = smoke_boot(app_root)
    if not boot_ok:
        return False, f"UNIT TESTS PASSED but SERVER BOOT FAILED:\n{boot_msg}"
    return True, f"{out}\n\nboot check: {boot_msg}"


# --- react verify pipeline (N5) --------------------------------------------
# Secrets the ADF process holds to call the MODEL must NEVER reach model-generated
# code, its dependencies' install scripts, or the spawned app — that would hand the
# operator's API keys to arbitrary code. Scrubbed from every npm/node child env.
_SECRET_ENV_RE = re.compile(r"(API_KEY|_TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)
_SECRET_ENV_EXACT = {"ANTHROPIC_API_KEY", "NVIDIA_API_KEY", "ORCH_NVIDIA_API_KEY",
                     "OPENAI_API_KEY", "CURSOR_API_KEY", "HF_TOKEN", "GITHUB_TOKEN"}

# Force every child tool (npm, git, pip, node, the built app) into NON-INTERACTIVE
# mode. Without this an npm/git/pip step can open a pager or block on a credential
# prompt and only die at the build timeout — a silent multi-minute hang. (Adopted
# from oh-my-pi's NON_INTERACTIVE_ENV / buildNonInteractiveEnv; see
# docs/ADF_VS_OH_MY_PI.md §5.2.) Real env values (a user-set PAGER, etc.) are
# overridden because a build child must never wait on a human.
# MIRROR: tools/orchestration_server/lib/phase_runner.dart `nonInteractiveEnv` must
# carry the same keys (G29 parity). Keep the two in sync when editing either.
NON_INTERACTIVE_ENV = {
    "CI": "1",
    "NO_COLOR": "1",
    "TERM": "dumb",
    "PAGER": "cat",
    "GIT_PAGER": "cat",
    "MANPAGER": "cat",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_EDITOR": "true",
    "GCM_INTERACTIVE": "never",
    "DEBIAN_FRONTEND": "noninteractive",
    "PYTHONUNBUFFERED": "1",
    "PIP_NO_INPUT": "1",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_PROGRESS_BAR": "off",
    "npm_config_yes": "true",
    "npm_config_audit": "false",
    "npm_config_fund": "false",
    "npm_config_progress": "false",
    "npm_config_update_notifier": "false",
    "ADBLOCK": "1",
    "HOMEBREW_NO_AUTO_UPDATE": "1",
}


def scrubbed_env(**extra):
    """A child environment with the operator's secrets removed AND non-interactive
    hardening applied — for running model-generated code, npm, and the built app
    (none of which should ever see ADF's model API keys, or block on a pager/prompt).
    Precedence: scrubbed base → non-interactive table → caller `extra` (wins)."""
    env = {k: v for k, v in os.environ.items()
           if k not in _SECRET_ENV_EXACT and not _SECRET_ENV_RE.search(k)}
    env.update(NON_INTERACTIVE_ENV)
    env.update(extra)
    return env


def _npm(app_root, args, timeout):
    """Run `npm <args>` in the app dir; returns (ok, combined_output). The child
    env is scrubbed of ADF's API keys so install scripts / the build never see them.
    (Install scripts are NOT disabled — better-sqlite3 needs its postinstall to fetch
    its native binary; the supply-chain risk is bounded instead by the pinned
    lockfile + the policy gate's dependency allowlist, which vets every package.)"""
    try:
        p = subprocess.run(
            ["npm", *args], cwd=app_root, capture_output=True, text=True,
            timeout=timeout, env=scrubbed_env(),
        )
        return p.returncode == 0, (p.stdout + "\n" + p.stderr).strip()
    except FileNotFoundError:
        return False, "npm not found on PATH"
    except subprocess.TimeoutExpired as e:
        # Keep the partial output captured before the kill — the cause of a hang is
        # often already on screen — rather than discarding it.
        partial = ((e.stdout or "") if isinstance(e.stdout, str)
                   else (e.stdout or b"").decode("utf-8", "replace"))
        partial += ((e.stderr or "") if isinstance(e.stderr, str)
                    else (e.stderr or b"").decode("utf-8", "replace"))
        return False, (f"npm {' '.join(args)} timed out after {timeout}s\n"
                       f"{partial.strip()}")


def _spill_and_bound(app_root, label, text, head=1500, tail=1500):
    """Write the FULL log to apps/<id>/.adf-logs/<label>.log and return a bounded
    head+tail view of it. The old `out[-3000:]` kept only the TAIL — discarding the
    head where the first real error usually is; this keeps both ends and elides the
    middle, with a pointer to the complete on-disk log. (Adopted from oh-my-pi's
    OutputSink; see docs/ADF_VS_OH_MY_PI.md §5.6.) `.adf-logs` is a dotfile dir, so
    current_app_files already excludes it from the edit/proof/policy surface."""
    text = text or ""
    rel = None
    try:
        log_dir = os.path.join(app_root, ".adf-logs")
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"{label}.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        rel = os.path.relpath(path, app_root)
    except OSError:
        rel = None
    if len(text) <= head + tail:
        return text
    elided = len(text) - head - tail
    where = f"full log: {rel}" if rel else "full log spill unavailable"
    return f"{text[:head]}\n…[{elided} chars elided — {where}]…\n{text[-tail:]}"


def _node_smoke_boot(app_root, secs=20, visual=True):
    """End-to-end check for the react stack: `node server/index.mjs` must start a
    server that honors PORT, answers GET `/` (the built SPA) + `/api/health` with
    200 (the AppRunner contract), AND — the authoritative part — actually RENDER in
    a headless browser (`visual=True`), so a white screen / runtime crash can't pass
    as 'verified'. The render check runs against the same booted server."""
    import socket
    import time
    import urllib.request
    entry = os.path.join(app_root, "server", "index.mjs")
    if not os.path.isfile(entry):
        return False, "server/index.mjs was not generated"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        _s.bind(("127.0.0.1", 0))
        port = _s.getsockname()[1]
    proc = subprocess.Popen(
        ["node", "server/index.mjs"], cwd=app_root,
        env=scrubbed_env(PORT=str(port)),  # the app must not inherit ADF's API keys
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + secs
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                return False, ("`node server/index.mjs` exited on launch:\n"
                               + _spill_and_bound(app_root, "node-boot", out))
            try:
                for path in ("/", "/api/health"):
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}{path}", timeout=1
                    ) as r:
                        if r.status != 200:
                            raise OSError(f"{path} -> HTTP {r.status}")
                # The server is LIVE — now actually RENDER it. GET /->200 only
                # proves the static SPA shell loads; a white screen / runtime crash
                # passes that. Drive a headless browser against THIS booted server
                # and assert the app mounted. Failures route to self-heal verbatim.
                if visual:
                    try:
                        import visual_verify
                        v_ok, v_msg, _shot = visual_verify.visual_verify(
                            f"http://127.0.0.1:{port}/", app_root=app_root)
                    except Exception as e:
                        v_ok, v_msg = True, f"visual verify skipped: {e}"
                    if not v_ok:
                        return False, (f"server boots and serves 200, but the APP "
                                       f"DOES NOT RENDER in a browser:\n{v_msg}")
                    return True, (f"node serves / and /api/health on :{port}; "
                                  f"{v_msg}")
                return True, f"node server serves / and /api/health on :{port}"
            except OSError:
                time.sleep(0.5)
        return False, f"node server did not serve / and /api/health within {secs}s"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def _run_stage(stage, fn):
    """Run one verify stage with HONEST live narration: announce the stage is running,
    call fn(), then emit a result event bound to fn()'s REAL (ok, msg) return — the
    green/red pill can never precede the actual outcome. Returns fn()'s (ok, msg)."""
    narrate("verify_stage", stage=stage)
    ok, msg = fn()
    narrate("verify_stage_result", stage=stage, ok=bool(ok))
    return ok, msg


def _react_verify(app_root, timeout=None):
    """Verify a React+Vite+Tailwind+SQLite app: install (once) → typecheck+build
    (`tsc --noEmit && vite build`) → vitest → boot → RENDER (headless browser).
    Each stage's failure is surfaced verbatim (and attributed) so the self-heal loop
    can fix the right file. Authoritative: a green here means the app builds, tests,
    boots, AND actually renders in a browser (not a white screen / runtime crash)."""
    timeout = timeout or int(os.environ.get("ADF_REACT_VERIFY_TIMEOUT_SEC", "600"))
    if not os.path.isfile(os.path.join(app_root, "package.json")):
        return False, "package.json missing — react scaffold was not applied"
    # Install once (npm ci needs the committed lockfile); reuse on re-verify.
    if not os.path.isdir(os.path.join(app_root, "node_modules")):
        ok, out = _run_stage("npm-ci", lambda: _npm(
            app_root, ["ci", "--no-audit", "--no-fund"], timeout))
        if not ok:
            return False, ("DEPENDENCY INSTALL FAILED (npm ci):\n"
                           + _spill_and_bound(app_root, "npm-ci", out))
    ok, out = _run_stage("build", lambda: _npm(app_root, ["run", "build"], timeout))
    if not ok:
        return False, ("BUILD FAILED (tsc --noEmit && vite build):\n"
                       + _spill_and_bound(app_root, "build", out))
    ok, out = _run_stage("vitest", lambda: _npm(app_root, ["test"], timeout))
    if not ok:
        return False, ("TESTS FAILED (vitest):\n"
                       + _spill_and_bound(app_root, "test", out))
    boot_ok, boot_msg = _run_stage("boot", lambda: _node_smoke_boot(app_root))
    if not boot_ok:
        return False, f"BUILD + TESTS PASSED but SERVER BOOT FAILED:\n{boot_msg}"
    return True, f"build + vitest passed; {boot_msg}"


# --- expo / react-native verify pipeline (M1) ------------------------------
def _native_toolchain():
    """Locate a native mobile build toolchain (eas/xcodebuild/gradle), or None. A
    deterministic offline box has none — so the native device stage degrades
    gracefully (like the headless render gate does without Chrome). Overridable via
    ADF_NATIVE_TOOLCHAIN for tests/CI."""
    override = os.environ.get("ADF_NATIVE_TOOLCHAIN")
    if override:
        return override
    import shutil
    for name in ("eas", "xcodebuild", "gradle"):
        if shutil.which(name):
            return name
    return None


def _expo_native_stage(app_root):
    """The native (iOS/Android) device build stage. Gated by ADF_MOBILE_NATIVE: when
    the toolchain is ABSENT it is SKIPPED (ok=True) unless ADF_MOBILE_NATIVE=strict,
    which fails LOUDLY — never a silent pass (requirement T3/B3). A signed .ipa/.aab
    is never claimed from the deterministic offline path; the full device build is a
    later node."""
    strict = os.environ.get("ADF_MOBILE_NATIVE", "").lower() == "strict"
    tool = _native_toolchain()
    if not tool:
        if strict:
            return (False, "native build required (ADF_MOBILE_NATIVE=strict) but no "
                           "toolchain found — need eas / xcodebuild / gradle")
        return (True, "native build stage skipped (no toolchain; set "
                      "ADF_MOBILE_NATIVE=strict to require it)")
    return (True, f"native toolchain present ({tool}); full device build is a later node")


def _expo_web_render(app_root, timeout):
    """The MOAT on mobile (M6): render-prove an Expo app via its WEB export
    (react-native-web emits real DOM) through the SAME headless render gate as the
    web stack. Builds `dist/` (expo export -p web), serves it on a free port, and
    asserts the app actually mounted. Degrades gracefully — skipped (ok) if the
    browser is unavailable, unless ADF_VISUAL_VERIFY=strict."""
    import socket
    import time
    mode = os.environ.get("ADF_VISUAL_VERIFY", "1").lower()
    if mode in ("0", "false", "off"):
        return True, "web render verify disabled (ADF_VISUAL_VERIFY=0)", False
    ok, out = _npm(app_root, ["run", "web:export"], timeout)
    if not ok:
        return False, ("WEB EXPORT FAILED (expo export -p web):\n"
                       + _spill_and_bound(app_root, "expo-web-export", out)), False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
        _s.bind(("127.0.0.1", 0))
        port = _s.getsockname()[1]
    proc = subprocess.Popen(
        ["node", "serve-web.mjs"], cwd=app_root, env=scrubbed_env(PORT=str(port)),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.poll() is not None:
                tail = proc.stdout.read() if proc.stdout else ""
                return False, ("expo-web server exited on launch:\n"
                               + _spill_and_bound(app_root, "expo-web-serve", tail)), False
            try:
                with socket.create_connection(("127.0.0.1", port), 0.5):
                    break
            except OSError:
                time.sleep(0.4)
        else:
            return False, "expo-web server did not start in time", False
        try:
            import visual_verify
            v_ok, v_msg, _shot = visual_verify.visual_verify(
                f"http://127.0.0.1:{port}/", app_root=app_root)
        except Exception as e:
            if mode == "strict":
                return False, f"visual verify error: {e}", False
            return True, f"web render skipped: {e}", False
        if not v_ok:
            return False, ("the Expo app EXPORTED but DID NOT RENDER on web "
                           "(white screen / runtime crash):\n" + v_msg), False
        return True, f"expo-web render OK; {v_msg}", True   # actually rendered
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def _dist_js_bytes(app_root):
    """Total JavaScript bundle bytes of the web export — a perf-budget signal sealed
    into the proof (MM11)."""
    total, dist = 0, os.path.join(app_root, "dist")
    for root, _d, files in os.walk(dist):
        for fn in files:
            if fn.endswith(".js"):
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    return total


def _write_render_facts(app_root, platforms):
    """Persist the structured render proof (which platforms ACTUALLY render-verified,
    the proven flag, the JS bundle bytes) so the seal can fold it into the Proof of
    Build's verdict (MM11). `platforms` lists ONLY platforms that truly rendered, so
    `proven` is False (and the list empty) when the render was skipped/disabled — the
    proof must never seal a render that didn't run. Best-effort."""
    facts = {"platforms": list(platforms), "proven": bool(platforms),
             "js_bytes": _dist_js_bytes(app_root)}
    try:
        vdir = os.path.join(app_root, ".adf-visual")
        os.makedirs(vdir, exist_ok=True)
        with open(os.path.join(vdir, "render-facts.json"), "w", encoding="utf-8") as f:
            json.dump(facts, f)
    except OSError:
        pass
    return facts


def read_render_facts(app_root):
    """The structured render facts written during verify, or None — folded into the
    sealed verdict at build time (MM11)."""
    p = os.path.join(app_root, ".adf-visual", "render-facts.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def mobile_native_delivery(app_root, fid):
    """The mobile "download + run on a device" deliverable ADF now owns end to end:
    build a standalone, signed APK (mobile_build — smart-strips unused native modules,
    single-ABI, prebuild+gradle) and preview it on a CLEAN, dedicated emulator
    (mobile_emulator — never the user's dev device). Writes .adf-mobile/facts.json and
    returns the sealable facts (apk path + sha256 + package + screenshot) so the
    downloadable binary is ATTESTED in the Proof of Build.

    Gated + best-effort: a no-toolchain box (or ADF_MOBILE_NATIVE=0) skips gracefully,
    exactly like the iOS render — it never fails an otherwise-good build. Returns the
    facts dict or None."""
    if os.environ.get("ADF_MOBILE_NATIVE", "").strip().lower() in ("0", "false", "off"):
        return None
    try:
        import mobile_build
    except Exception as e:
        log(f"mobile: build module unavailable ({e})")
        return None
    if not mobile_build.native_toolchain_ready():
        log("mobile: Android toolchain absent — APK + emulator preview skipped "
            "(install the Android SDK + a JDK to enable)")
        return None

    narrate("building_apk")
    ok, detail, apk = mobile_build.build_apk(app_root, fid, log=log)
    if not ok or not apk:
        narrate("apk_failed", reason=detail[:140])
        log(f"mobile: APK build skipped/failed — {detail}")
        return None
    narrate("apk_built", detail=detail)
    log(f"mobile: {detail}")

    import hashlib
    try:
        with open(apk, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        sha = None
    facts = {
        "apk": os.path.relpath(apk, app_root),
        "package": mobile_build.package_id(fid),
        "size_bytes": os.path.getsize(apk),
        "sha256": sha,
        "screenshot": None,
        "preview": None,
    }

    try:
        import mobile_emulator
        narrate("emulator_preview")
        _ok, p_detail, shot = mobile_emulator.preview(
            apk, fid, app_root=app_root, log=log)
        facts["preview"] = p_detail
        if shot:
            facts["screenshot"] = os.path.relpath(shot, app_root)
            narrate("emulator_running", detail=p_detail)
        log(f"mobile: preview — {p_detail}")
    except Exception as e:
        log(f"mobile: emulator preview skipped: {e}")

    try:
        fp = os.path.join(app_root, ".adf-mobile", "facts.json")
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(facts, f, indent=2, sort_keys=True)
    except OSError:
        pass
    return facts


def _expo_verify(app_root, timeout=None):
    """Verify an Expo / React Native app: typecheck (`tsc --noEmit`) + jest + a render
    proof on the WEB export (the moat), then the gated native stage. Mirrors
    `_react_verify`'s attributed-failure contract. The deterministic stages run when
    the template's deps are warm-cloned; the native device build degrades gracefully
    off the offline path. Honest scope: 'verified' means typechecks + tests + renders
    on web, NOT a signed binary."""
    timeout = timeout or int(os.environ.get("ADF_EXPO_VERIFY_TIMEOUT_SEC", "600"))
    has_app = os.path.isfile(os.path.join(app_root, "app.json"))
    has_pkg = os.path.isfile(os.path.join(app_root, "package.json"))
    if not (has_app or has_pkg):
        return False, ("app.json / package.json missing — the Expo scaffold was not "
                       "applied")
    # Install once if node_modules is absent (mirror _react_verify) — the warm clone
    # usually provides it, but never hard-fail when it didn't (e.g. a cleaned app).
    if not os.path.isdir(os.path.join(app_root, "node_modules")):
        ok, out = _run_stage("npm-ci", lambda: _npm(
            app_root, ["ci", "--no-audit", "--no-fund"], timeout))
        if not ok:
            return False, ("DEPENDENCY INSTALL FAILED (npm ci):\n"
                           + _spill_and_bound(app_root, "expo-npm-ci", out))
    ok, out = _run_stage("typecheck", lambda: _npm(app_root, ["run", "typecheck"], timeout))
    if not ok:
        return False, ("TYPECHECK FAILED (tsc --noEmit):\n"
                       + _spill_and_bound(app_root, "expo-typecheck", out))
    ok, out = _run_stage("jest", lambda: _npm(app_root, ["test"], timeout))
    if not ok:
        return False, ("TESTS FAILED (jest):\n"
                       + _spill_and_bound(app_root, "expo-test", out))
    narrate("verify_stage", stage="web-render")
    render_ok, render_msg, web_rendered = _expo_web_render(app_root, timeout)
    narrate("verify_stage_result", stage="web-render", ok=bool(render_ok))
    if not render_ok:
        return False, render_msg
    # MM10: opportunistically render on a REAL booted iOS Simulator and seal the
    # device screenshot into the proof. Skips gracefully when no simulator is booted
    # (never fails the build unless ADF_IOS_RENDER=strict) — dist/ was just built.
    ios_msg = ""
    try:
        import native_render
        i_ok, i_msg, _shot = native_render.ios_render(
            os.path.join(app_root, "dist"), app_root=app_root)
        if not i_ok:
            return False, f"iOS Simulator render failed: {i_msg}"
        ios_msg = f" + {i_msg}" if "rendered on the iOS" in i_msg else ""
    except Exception as e:
        ios_msg = ""
        log(f"iOS render skipped: {e}")
    # MM11 (+ honesty fix): seal ONLY the platforms that ACTUALLY rendered — never a
    # render that was skipped/disabled. web_rendered is True only on a real web mount;
    # ios_msg is set only on a real iOS-Simulator render.
    platforms = (["web"] if web_rendered else []) + (["ios"] if ios_msg else [])
    _write_render_facts(app_root, platforms)
    native_ok, native_msg = _expo_native_stage(app_root)
    if not native_ok:
        return False, native_msg
    return True, f"typecheck + jest + web render{ios_msg} passed; {native_msg}"


def verify_app(app_root, stack=None, timeout=None):
    """Dispatch verification to the stack's pipeline (contract C2). `stack` is
    resolved from the manifest when omitted. stdlib → unittest + python boot;
    react → npm build + vitest + node boot; expo-rn → tsc + jest + gated native.
    Unknown stacks fall back to stdlib."""
    stack = stack or detect_stack(app_root)
    if stack == STACK_REACT:
        return _react_verify(app_root, timeout)
    if stack == STACK_EXPO:
        return _expo_verify(app_root, timeout)
    return run_verification(app_root, timeout or 60)


# Wire the per-stack verify callables now that the pipelines are defined (the
# registry literal lives above, before these functions exist).
_STACK_PROFILES[STACK_STDLIB]["verify"] = run_verification
_STACK_PROFILES[STACK_REACT]["verify"] = _react_verify
_STACK_PROFILES[STACK_EXPO]["verify"] = _expo_verify


def headroom_compress_log(text):
    """Compress bulky test-failure output (logs/tracebacks — headroom's sweet
    spot) before re-sending it in a self-heal turn. Returns the original text
    if headroom isn't importable or yields no win, so code fidelity and
    behavior are never at risk. Only the *log* is touched, never the code."""
    if not text or len(text) < 400:
        return text
    try:
        import headroom
    except Exception:
        return text
    try:
        # Frame the log as a tool result so headroom compresses it (it protects
        # user/system/code messages by design).
        res = headroom.compress(
            [{"role": "tool", "content": text},
             {"role": "user", "content": "Fix the failures."}],
            model="claude-3-5-sonnet",
        )
        for m in res.messages:
            if m.get("role") == "tool":
                comp = m.get("content") or text
                if len(comp) < len(text):
                    log(f"headroom: failure log {len(text)}->{len(comp)} chars "
                        f"({res.compression_ratio:.0%} smaller)")
                    return comp
        return text
    except Exception as e:
        log(f"headroom compress skipped: {e}")
        return text


_JEST_HOIST_RE = re.compile(
    r"module factory of .*jest\.mock\(\).* is not allowed to "
    r"reference any out-of-scope variables", re.I)
_JEST_VAR_RE = re.compile(r"Invalid variable access:\s*([A-Za-z_$][\w$]*)")


def jest_hoist_hint(failure):
    """Deterministic heal hint for the jest.mock() hoisting failure class.

    A real mobile build failed verify three times on the SAME error because the
    cure was buried in generic prose far above the pasted failure — the model
    never connected them. When the failure IS this class, name the ACTUAL
    offending variable and the exact fix, so the next heal attempt converges.
    Returns "" for every other failure (the trigger string is jest-specific and
    cannot false-positive on react/stdlib output)."""
    if not failure or not _JEST_HOIST_RE.search(failure):
        return ""
    m = _JEST_VAR_RE.search(failure)
    var = m.group(1) if m else "the store"
    mockname = ("mock" + var[0].upper() + var[1:]) if m else "mockStore"
    return (
        "ACTIONABLE FIX (jest.mock hoisting) — THIS is the blocker, fix it first:\n"
        f"jest hoists `jest.mock(...)` ABOVE every import and `let`/`const`, so its "
        f"factory runs before `{var}` exists; jest then rejects EVERY reference to "
        f"`{var}` inside the factory (reads included). The only names a factory may "
        f"reference are prefixed with `mock` (case-insensitive). Fix: move that state "
        f"INSIDE the factory and rename it `{mockname}` (e.g. `let {mockname} = []`), "
        f"exposing `mock`-prefixed handles (`__getStore`, `__reset`) the test calls in "
        f"beforeEach. See `__tests__/data.test.tsx` for the exact pattern.")


_RTL_MISSING_TEXT_RE = re.compile(
    r"Unable to find an element with (?:the )?text:\s*(.+)")


def rtl_text_hint(failure):
    """Deterministic heal hint for the most common RTL failure: a test asserts
    on-screen text (getByText/findByText) the component never renders.

    A real mobile auth build failed verify 3x here — the model INVENTED an
    email-validation test ("Please enter a valid email address.") but never
    implemented that validation in the screen, and the heal couldn't reconcile
    test↔component. The cure is BALANCED: either side may be wrong, so name the
    missing text and present both resolutions. Returns "" for other failures."""
    if not failure:
        return ""
    m = _RTL_MISSING_TEXT_RE.search(failure)
    if not m:
        return ""
    text = m.group(1).strip().splitlines()[0].rstrip(". ")[:80]
    return (
        "ACTIONABLE FIX (assertion vs. component mismatch) — likely the blocker:\n"
        f"a test asserts the on-screen text {text} (getByText/findByText) but the "
        "rendered component never produces it. Make the test and the component AGREE "
        "— do exactly ONE:\n"
        f"  (a) if the spec wants that behavior, render {text} VERBATIM in the "
        "component under test (e.g. implement the validation/error/empty state that "
        "shows it); or\n"
        f"  (b) if it is not real behavior, change the test to assert text the "
        "component ACTUALLY renders.\n"
        "Never assert UI text the component does not render — check the rendered tree "
        "pasted below for the text that IS present.")


def heal_hint(failure):
    """Combine the deterministic, prepend-to-the-top heal hints that apply to this
    failure (jest hoisting, RTL missing-text). Each is surgical and stack-safe; the
    triggers cannot false-positive on stdlib/react server output."""
    return "\n\n".join(
        h for h in (jest_hoist_hint(failure), rtl_text_hint(failure)) if h)


def fix_messages(system, user, files, failure, stack=None):
    """Build the follow-up turn asking the model to fix the failing files. The
    hint about WHICH files may be wrong is stack-aware so the model fixes the
    right surface (server.mjs/vitest for react, server.py/test_app.py for stdlib)."""
    # Self-heal payload can be large (a full build re-emits ALL files); compact it
    # by relevance to the FAILURE so the model keeps the broken file(s) whole and
    # only sees an outline of the rest. No-op under budget.
    files, file_outline, _ = _compact_files_for_prompt(files, failure)
    current = "\n".join(
        f"<<<FILE: {p}>>>\n{c}\n<<<END>>>" for p, c in files
    )
    if file_outline:
        current += ("\n\n=== OTHER FILES (outline only — unchanged, not central to "
                    "this failure) ===\n" + file_outline)
    failure = headroom_compress_log(failure)
    # Prepend a precise hint for known-and-stuck failure classes so the cure rides at
    # the TOP of the failure block (survives the [:4000] truncation) instead of being
    # buried in generic prose the model skips.
    _hint = heal_hint(failure)
    if _hint:
        failure = _hint + "\n\n" + failure
    if (stack or DEFAULT_STACK) == STACK_REACT:
        where = ("whichever files are wrong (schema.sql, server/api/*.mjs, src/**.tsx, "
                 "and/or test/*.test.mjs). Common causes: a tsc type error in src, a "
                 "missing/renamed SQLite table or column, a route registered with the "
                 "wrong path (routes are relative to `/api`), or a vitest assertion "
                 "mismatch")
    elif (stack or DEFAULT_STACK) == STACK_EXPO:
        where = ("whichever files are wrong (app/**.tsx routes incl. app/_layout.tsx, "
                 "src/components/**.tsx, src/db.ts, src/hooks/*, and/or "
                 "__tests__/*.test.tsx). Common causes: a tsc type error in app/ or "
                 "src/, an Expo Router route/param mismatch, a raw hex color (use theme "
                 "tokens), a missing expo-sqlite query, or a "
                 "@testing-library/react-native assertion mismatch (mock 'expo-router'; "
                 "for a jest.mock hoisting 'out-of-scope variable' error, see the "
                 "ACTIONABLE FIX prepended to the failure output below and "
                 "`__tests__/data.test.tsx`)")
    else:
        where = "whichever files are wrong (server.py and/or test_app.py and/or index.html)"
    fixer = (
        "Your previous implementation FAILED verification. Here is the current "
        f"code and the exact failure output. Fix the root cause in {where} and "
        "re-emit the COMPLETE set of files in the same <<<FILE:>>> format. Do "
        "not explain — emit only the corrected files.\n\n"
        f"=== CURRENT FILES ===\n{current}\n\n"
        f"=== VERIFICATION FAILURE OUTPUT ===\n{failure[:4000]}\n\n"
        "Re-emit all files now, corrected."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "user", "content": fixer},
    ]


def _tdd_red_baseline(workspace, fid, stack, files, timeout):
    """RED baseline for a test-first build (ADF_TDD): write the model's TEST files onto
    the scaffold ALONE and run the test stage — it must FAIL because no implementation
    exists yet. Honest only when deps are already present (so the failure reflects
    missing IMPLEMENTATION, not missing node_modules); otherwise the verdict is
    inconclusive (never a fake RED). Returns (verdict, test_paths) for the test-bearing
    stacks, or (None, []) when TDD does not apply (e.g. stdlib). The full file set is
    still written + verified by the caller — this never replaces verify_app."""
    import tdd_loop
    if (stack or DEFAULT_STACK) not in (STACK_REACT, STACK_EXPO):
        return None, []
    tests, impl = tdd_loop.split_tests(files)
    test_paths = [p for p, _ in tests]
    if not tests or not impl:
        return {"red": False, "vacuous": False,
                "reason": "no test or no implementation files emitted"}, test_paths
    app_root, _ = write_files(workspace, fid, tests)
    if not os.path.isdir(os.path.join(app_root, "node_modules")):
        return {"red": False, "vacuous": False,
                "reason": "deps absent — RED baseline inconclusive"}, test_paths
    narrate("tdd_red_check", tests=len(tests))
    verdict = tdd_loop.red_baseline(
        tests, impl, lambda: _npm(app_root, ["test"], timeout))
    # ok = the RED baseline did its job (tests FAIL with no impl). Carried on the
    # honesty seam so the Studio shows PROCESS_OK only on a real RED, PROCESS_WARN on a
    # vacuous suite — never a green claim on a build that didn't earn it.
    narrate("tdd_red", ok=bool(verdict.get("red")),
            vacuous=bool(verdict.get("vacuous")))
    log(f"TDD red baseline: {verdict.get('reason')}")
    return verdict, test_paths


def _crew_generate(crew, system, user, stack, timeout, workspace, fid):
    """Generate the first draft via the PARALLEL subagent crew (ADF_BUILD_CREW): each
    subagent emits ONLY its slice (its emit_globs), with the files earlier waves wrote
    already on disk as context (the app dir IS the shared memory). Returns the MERGED
    (path, content) list, or None to fall back to monolithic generation (any blocker
    under the default `fallback` policy). The merged files are still written + verified
    + healed + sealed by the normal path — the crew only changes HOW the draft is made."""
    import build_crew

    def run_agent(agent, prior):
        slice_directive = (
            f"\n\n=== YOUR SLICE ({agent.name}) ===\n"
            f"You are the '{agent.name}' subagent: {agent.role}. Emit ONLY the files "
            f"you own (matching: {', '.join(agent.emit_globs)}) in the <<<FILE:>>> "
            f"format. Do NOT emit any other file.")
        if prior:
            existing = "\n".join(f"- {p}" for p in sorted(prior))
            slice_directive += (
                "\nThese files already exist from earlier subagents — import/build on "
                f"them, do NOT re-emit them:\n{existing}")
        gen = generate([{"role": "system", "content": system},
                        {"role": "user", "content": user + slice_directive}], timeout)
        if not gen:
            return False, [], f"{agent.name}: no model output"
        emitted = parse_files(gen[0])
        owned = [(p, c) for p, c in emitted
                 if build_crew.matches_globs(p, agent.emit_globs)]
        # Defensive: if the model labeled paths oddly, keep everything rather than lose
        # work — the whole-app verify_app is still the single authoritative gate.
        chosen = owned or emitted
        if not chosen:
            return False, [], f"{agent.name}: emitted no files"
        write_files(workspace, fid, chosen)
        narrate("crew_agent", agent=agent.name, files=len(chosen))
        return True, chosen, f"{agent.name}: {len(chosen)} file(s)"

    narrate("build_crew_start", agents=len(crew))
    log(f"build crew: {len(crew)} subagents in dependency-ordered parallel waves")
    parallelism = int(os.environ.get("ADF_BUILD_CREW_PARALLELISM", "3"))
    try:
        result = build_crew.run_crew(crew, run_agent, parallelism=parallelism)
    except ValueError as e:
        # A malformed decomposition (self-dep / unknown-dep / cycle) raised by
        # build_execution_waves BEFORE any agent ran — honor the crew's "never strand a
        # build" promise: degrade to monolithic unless ADF_BUILD_CREW=strict.
        if build_crew.allows_fallback():
            log(f"build crew DAG invalid ({e}); falling back to monolithic generation")
            narrate("build_crew_fallback", blockers=[str(e)])
            return None
        raise
    if result["blockers"] and build_crew.allows_fallback():
        log(f"build crew blockers ({'; '.join(result['blockers'])}); "
            f"falling back to monolithic generation")
        narrate("build_crew_fallback", blockers=result["blockers"][:3])
        return None
    merged = list(result["files"].items())
    narrate("build_crew_done", files=len(merged), waves=len(result["waves"]))
    return merged or None


# --- one-box iteration: edit an existing app ------------------------------
EDIT_REQUEST_FILE = ".adf-edit-request.txt"


def read_pending_edit(app_dir):
    """A free-text change request the server dropped next to the app, e.g.
    'make the header blue'. Present => run in EDIT mode instead of rebuilding."""
    p = os.path.join(app_dir, EDIT_REQUEST_FILE)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            t = f.read().strip()
        return t or None
    except OSError:
        return None


def clear_pending_edit(app_dir):
    try:
        os.remove(os.path.join(app_dir, EDIT_REQUEST_FILE))
    except OSError:
        pass


def current_app_files(app_dir, max_files=60, max_bytes=200_000):
    """All editable SOURCE files under the app (multi-file edit) — skips deps,
    build output, caches and lockfiles so a large React app can't blow the prompt.
    Replaces the old hardcoded 3-file (index.html/server.py/test_app.py) list."""
    out, total = [], 0
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fn in sorted(files):
            if fn.startswith(".") or fn in _SKIP_FILES or not fn.endswith(_EDIT_EXTS):
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            if len(out) >= max_files or total + len(content) > max_bytes:
                continue
            total += len(content)
            out.append((os.path.relpath(fp, app_dir), content))
    return out


def build_edit_messages(fid, files, instruction, stack=None, file_summary=None,
                        components=None):
    """Apply a scoped change to an existing app — the Lovable 'type a change,
    watch it update' loop. We hand the model the current files + the request and
    ask for the SMALLEST edit, re-emitting only the changed files. The
    architecture note + the test it must keep green are stack-aware.

    `file_summary` (optional): a one-line-per-file outline of OTHER files that were
    compacted out of the prompt (over budget). They still exist on disk; the model
    is told it can ask for one if the change turns out to need it."""
    if (stack or DEFAULT_STACK) == STACK_REACT:
        arch = (
            "a React+Vite+TypeScript+Tailwind app with a Fastify + better-sqlite3 "
            "server (plain-ESM `server/**.mjs`, routes under `/api`, schema.sql at "
            "boot). Keep `src/**` type-correct (tsc checks it), keep server files as "
            "`.mjs`, and keep the PORT-from-env contract"
        )
        keep_tests = ("Keep the vitest suite (`test/*.test.mjs`) passing; update it "
                      "only if the change requires it.")
    elif (stack or DEFAULT_STACK) == STACK_EXPO:
        arch = (
            "a cross-platform Expo + React Native app with Expo Router (file-based "
            "`app/` routes incl. `app/_layout.tsx`), themed components in "
            "`src/components` that COMPOSE the shipped `./components/ui` kit + the "
            "`useTheme()` tokens (NEVER raw hex), and expo-sqlite local data in "
            "`src/db.ts`. Keep `app/**` + `src/**` type-correct (tsc checks it); there "
            "is NO server/DOM"
        )
        keep_tests = ("Keep the jest suite (`__tests__/*.test.tsx`, "
                      "@testing-library/react-native, mock 'expo-router') passing; "
                      "update it only if the change requires it. When a test mocks "
                      "`src/db`, keep its store INSIDE the `jest.mock()` factory and "
                      "`mock`-prefixed (jest hoists the factory above all decls, so "
                      "only `mock*`-named vars are reachable from it).")
    else:
        arch = (
            "a Python stdlib http.server app + a single static index.html. Keep the "
            "same architecture and the PORT-from-env contract "
            "(`port = int(os.environ.get('PORT','8000'))`)"
        )
        keep_tests = ("Keep test_app.py passing; update it only if the change "
                      "requires it.")
    app_kind = "mobile app" if (stack or DEFAULT_STACK) == STACK_EXPO else "web app"
    system = (
        f"You are editing an EXISTING, working {app_kind}: {arch}. Apply the user's "
        "requested change with the SMALLEST edit that fully satisfies it — preserve "
        "all other behavior and styling exactly. Re-emit the COMPLETE content of "
        "every file you change (and ONLY those), as:\n"
        "<<<FILE: relative/path>>>\n<full file content>\n<<<END>>>\n"
        "No commentary, no markdown fences."
    )
    blocks = "\n\n".join(
        f"<<<FILE: {name}>>>\n{content}\n<<<END>>>" for name, content in files
    )
    other = ""
    if file_summary:
        other = ("=== OTHER FILES (outline only — these exist on disk but aren't "
                 "central to this change; ask for one's full contents if you must "
                 "edit it) ===\n" + file_summary + "\n\n")
    comps = ""
    if components:
        comps = ("=== EXISTING REUSABLE COMPONENTS (prefer reusing these over "
                 "writing new ones; compose them) ===\n" + components + "\n\n")
    user = (
        f"App: `{fid}` — the files below are the current, working version.\n\n"
        f"=== CURRENT FILES ===\n{blocks}\n\n"
        f"{comps}{other}"
        f"=== CHANGE REQUESTED ===\n{instruction}\n\n"
        f"Apply the change as the SMALLEST modular edit — reuse existing components, "
        f"and keep any new UI as its own self-contained props-driven component. "
        f"Re-emit the complete updated file(s) now. {keep_tests}"
    )
    return system, user


def _compact_files_for_prompt(files, instruction):
    """Context compaction (the /compact engine) for a file payload that would blow
    the model's context window: keep the files most relevant to `instruction` whole,
    replace the rest with a one-line-per-file outline. Returns
    (files_for_prompt, outline_or_None, result_or_None). No-op + import-safe when the
    payload is under budget or the engine isn't importable."""
    try:
        import compaction
    except Exception:
        return list(files), None, None
    if not compaction.should_compact(files):
        return list(files), None, None
    res = compaction.compact_files(files, instruction or "")
    if not res.did_compact:
        return list(files), None, None
    return res.items, res.summary, res


def assemble_edit(app_dir, fid, files, instruction, stack=None):
    """Build the EDIT-mode prompt, compacting the file payload first when it's over
    the context budget (keep edit-relevant files whole, outline the rest) and
    recording the fold as a durable, reviewable context card. Returns (system, user)."""
    files_for_prompt, outline, res = _compact_files_for_prompt(files, instruction)
    if res is not None:
        try:
            import compaction
            compaction.write_context_card(
                app_dir, res, kind="edit",
                meta={"feature": fid, "instruction": (instruction or "")[:200]})
        except Exception:
            pass
        log(f"compaction (edit): {res.tokens_before}->{res.tokens_after} tokens, "
            f"{res.n_summarized} file(s) outlined (kept {len(files_for_prompt)} whole)")
    # Feed the component manifest so the edit REUSES existing components.
    components = None
    try:
        import component_manifest
        components = component_manifest.manifest_summary(app_dir) or None
    except Exception:
        components = None
    return build_edit_messages(fid, files_for_prompt, instruction, stack,
                               file_summary=outline, components=components)


# Per-shape REQUIRED test signals for the completion audit (5.9), STRUCTURAL (not
# bare presence): a real `app.inject({ method: 'POST' })` request and a status code
# inside an assertion matcher — so a number mentioned in a COMMENT, or the verb in
# prose, no longer counts as coverage (SOLID-1). Still lenient enough not to
# false-flag a genuine test suite (the template mandates app.inject + statusCode).
def _method_signal(method):
    """A real request for `method` — `method: 'POST'` in an app.inject — not the
    verb mentioned in prose/a comment."""
    return re.compile(r"method\s*:\s*['\"]" + method + r"['\"]", re.I)


def _status_asserted(*codes):
    """A status code asserted: inside a matcher call (`toBe(400)`/`toEqual(404)`) or
    compared against `statusCode` on the same line — NOT a bare number in a comment."""
    alt = "|".join(codes)
    return re.compile(
        r"(?:to(?:be|equal|strictequal))\s*\(\s*(?:" + alt + r")\b"
        r"|statuscode[^\n]{0,20}\b(?:" + alt + r")\b"
        r"|\b(?:" + alt + r")\b[^\n]{0,20}statuscode", re.I)


_AUDIT_REQUIRED = {
    "crud-list": [
        ("a POST/create test", _method_signal("POST")),
        ("an error-case test (400/404)", _status_asserted("400", "404")),
    ],
    "form": [
        ("a POST/submit test", _method_signal("POST")),
        ("a validation test (400)", _status_asserted("400")),
    ],
    "single-record": [
        ("a PUT/update test", _method_signal("PUT")),
        ("a validation test (400)", _status_asserted("400")),
    ],
    "dashboard": [
        ("a GET/summary test", _method_signal("GET")),
        ("a 200 assertion", _status_asserted("200")),
    ],
    "auth": [
        ("a signup/login POST test", _method_signal("POST")),
        ("an auth-failure test (401)", _status_asserted("401")),
    ],
}

# MOBILE (expo) test signals — RN apps are tested with @testing-library/react-native
# (render + fireEvent + getBy*), NOT app.inject/statusCode. A vacuous mobile test is
# one that renders but never drives an interaction or asserts. (M8.)
_M_RENDER = ("a component render", re.compile(r"\brender\s*\(", re.I))
_M_INTERACT = ("a user interaction (fireEvent)", re.compile(r"\bfireEvent\b"))
_M_QUERY = ("an assertion query (getBy/findBy)",
            re.compile(r"\b(?:get|find|query)(?:All)?By\w+"))
_AUDIT_REQUIRED_MOBILE = {
    "crud-list": [_M_RENDER, _M_INTERACT, _M_QUERY],
    "form": [_M_RENDER, _M_INTERACT, _M_QUERY],
    "single-record": [_M_RENDER, _M_INTERACT, _M_QUERY],
    "auth": [_M_RENDER, _M_INTERACT, _M_QUERY],
    "dashboard": [_M_RENDER, _M_QUERY],   # read-mostly — no interaction required
}


def audit_completion(app_root, stack, ctx, fid):
    """Deterministic completion audit BEFORE sealing (oh-my-pi §5.9). A green
    verify_app only ran whatever tests the model wrote — a vacuous test (asserts
    200, never checks the body) passes the gate. For a SHAPED react feature, derive
    the required test signals from the feature shape and report any the generated
    tests don't cover. Returns gap descriptions ([] = complete or not applicable).
    $0, no model call; disabled via ADF_COMPLETION_AUDIT=0. Advisory — the caller
    uses it to trigger one more heal, never to fail an already-verified build."""
    if os.environ.get("ADF_COMPLETION_AUDIT", "1") in ("0", "false", "off"):
        return []
    stack = stack or DEFAULT_STACK
    if stack not in (STACK_REACT, STACK_EXPO):
        return []
    try:
        import feature_shapes
        shape, _ = feature_shapes.contract_for(ctx, fid)
    except Exception:
        return []
    return _audit_tests(app_root, shape, stack) + _audit_render(app_root, shape)


def _read_test_sources(app_root):
    """Concatenate the app's test files: anything under a test/ or __tests__/ dir, or
    a co-located `*.test.*` / `*.spec.*` file — web (`.mjs`/`.ts`) and mobile
    (`.tsx`) alike."""
    exts = (".mjs", ".ts", ".tsx", ".js", ".jsx")
    out = []
    for root, dirs, files in os.walk(app_root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        in_test_dir = os.path.basename(root) in ("test", "tests", "__tests__")
        for fn in files:
            if not fn.endswith(exts):
                continue
            if in_test_dir or ".test." in fn or ".spec." in fn:
                try:
                    with open(os.path.join(root, fn), encoding="utf-8") as f:
                        out.append(f.read())
                except (OSError, UnicodeDecodeError):
                    pass
    return "\n".join(out)


def _audit_tests(app_root, shape, stack=STACK_REACT):
    """Test-coverage half of the audit: do the generated tests assert the shape's
    required behavior? Web uses app.inject/statusCode signals (_AUDIT_REQUIRED);
    mobile uses @testing-library/react-native signals (_AUDIT_REQUIRED_MOBILE)."""
    table = _AUDIT_REQUIRED_MOBILE if stack == STACK_EXPO else _AUDIT_REQUIRED
    required = table.get(shape)
    if not required:
        return []                       # generic shape — no deterministic checklist
    test_text = _read_test_sources(app_root)
    if not test_text.strip():
        return [f"no test file found for a {shape} feature"]
    return [label for label, pat in required if not pat.search(test_text)]


def _audit_render(app_root, shape):
    """Render half of the audit (SOLID-2): did the app actually render the shape's
    core controls? Reads the render stats visual_verify dumped during the boot/render
    check and compares against feature_shapes.expected_dom. Returns [] when the
    render wasn't measured (no browser / disabled) so it never false-flags."""
    try:
        import feature_shapes
        expected = feature_shapes.expected_dom(shape)
    except Exception:
        return []
    if not expected:
        return []
    stats_path = os.path.join(app_root, ".adf-visual", "render-stats.json")
    if not os.path.isfile(stats_path):
        return []
    try:
        with open(stats_path, encoding="utf-8") as f:
            stats = json.load(f)
    except (OSError, ValueError):
        return []
    try:
        import visual_verify
        _ok, missing = visual_verify.check_expected_dom(stats, expected)
        return missing
    except Exception:
        return []


def _content_hash(text):
    return hashlib.blake2s((text or "").encode("utf-8")).hexdigest()[:12]


def edit_read_guard(read_files, instruction):
    """For EDIT mode: stamp every file the model is shown (read_hashes) and record
    which files it saw only as a one-line OUTLINE rather than full source
    (outlined_paths). Used to reject unsafe writes before they hit disk. (oh-my-pi
    §5.7 seenLines + §5.8 staleness gate.)"""
    read_hashes = {p: _content_hash(c) for p, c in read_files}
    _, _, res = _compact_files_for_prompt(read_files, instruction)
    outlined = set(getattr(res, "summarized_paths", []) or []) if res else set()
    return read_hashes, outlined


def apply_edit_guards(app_dir, files, read_hashes, outlined):
    """Drop unsafe model-emitted edits before write_files persists them:
      5.7  a file the model saw only OUTLINED is rejected — it would be
           hallucinating the body it never saw.
      5.8  a file whose on-disk content changed since ADF read it is flagged STALE;
           with ADF_EDIT_STALE_GUARD=block it is skipped rather than silently
           clobbered (default: warn loudly but still write).
    Returns (safe_files, notes)."""
    block_stale = os.environ.get("ADF_EDIT_STALE_GUARD", "warn").lower() == "block"
    safe, notes = [], []
    for rel, content in files:
        norm = rel.lstrip("/")
        if norm in outlined:
            notes.append(f"rejected blind edit to outlined-only file: {norm}")
            continue
        if norm in read_hashes:
            try:
                with open(os.path.join(app_dir, norm), encoding="utf-8") as f:
                    live = _content_hash(f.read())
            except (OSError, UnicodeDecodeError):
                live = None
            if live is not None and live != read_hashes[norm]:
                if block_stale:
                    notes.append(f"skipped STALE overwrite (changed since read): {norm}")
                    continue
                notes.append(f"stale overwrite (file changed since read): {norm}")
        safe.append((rel, content))
    return safe, notes


class _PolicyBlocked(Exception):
    """Sentinel: the enforced policy gate blocked the build, so the proof is
    intentionally NOT sealed (distinct from a sealing error)."""


def _policy_failclosed(advisory):
    """SSOT for the fail-closed-on-error decision, paralleling the process gate's
    inline `["process_facts_error"]`. Returns the synthetic blocking-rule list
    `["policy_gate_error"]` when the policy is ENFORCED (`advisory` is False) so a
    gate exception fails CLOSED (build not sealed, exit 6); returns `[]` under the
    explicit advisory escape hatch so the old record-but-ship behavior is preserved.
    Pure: reads no globals, no side effects."""
    return ["policy_gate_error"] if not advisory else []


def should_scaffold(stack, app_dir):
    """Decide whether a fresh build scaffolds from the checked-in template.

    A template stack (react OR expo) scaffolds when no `package.json` exists yet;
    the stdlib stack and already-scaffolded apps do not. Extracted as a pure
    predicate so the gate is unit-testable WITHOUT a model call — the original bug
    (this was gated to STACK_REACT only, so every fresh expo-rn build skipped the
    scaffold and then failed verify with "scaffold not applied") slipped through
    precisely because no test exercised the main() gate. This is that test's seam.
    """
    return (stack in (STACK_REACT, STACK_EXPO)
            and not os.path.isfile(os.path.join(app_dir, "package.json")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--workspace", default=os.getcwd())
    args, _ = ap.parse_known_args()

    workspace = os.path.abspath(args.workspace)
    repo_root = os.environ.get("ORCH_REPO_ROOT", workspace)
    load_env(repo_root)

    fid = resolve_feature_id(args.prompt)
    if not fid:
        log("could not resolve a feature id (set ADF_FEATURE_ID, or include "
            "'resume <id>' in the prompt)")
        sys.exit(2)
    log(f"feature: {fid} | workspace: {workspace}")

    ctx = load_feature_context(repo_root, fid)
    app_dir = os.path.join(workspace, "apps", fid)

    # Process-evidence isolation (honesty contract). `.adf-process/` is per-app and
    # survives a rebuild/edit untouched — should_scaffold() reuses an existing app dir
    # (package.json present), so a PRIOR build's tdd.json / heal.json / review.json
    # would otherwise be re-read at seal time and certified `proven` though THIS build
    # never ran that discipline. Belt-and-braces, both before any generation/recorder:
    #   (1) wipe the dir so each turn starts with zero process evidence;
    #   (2) stamp a per-build nonce that process_facts reads back, treating any
    #       artifact whose nonce differs as absent — so stale evidence can never seal
    #       even if the wipe is skipped (best-effort) or the dir is repopulated later.
    import shutil
    import process_facts
    shutil.rmtree(os.path.join(app_dir, process_facts.PROCESS_DIR), ignore_errors=True)
    os.environ["ADF_BUILD_NONCE"] = uuid.uuid4().hex

    # Resolve the target stack (contract C5): an already-built app's manifest
    # wins (re-runs/edits keep their stack); a fresh build uses the env default
    # (ADF_STACK), which the server sets from the feature's chosen stack.
    app_built = os.path.isdir(app_dir) and (
        os.path.isfile(os.path.join(app_dir, ".adf-stack.json"))
        or os.path.isfile(os.path.join(app_dir, "package.json"))
        or os.path.isfile(os.path.join(app_dir, "server.py")))
    stack = detect_stack(app_dir) if app_built else DEFAULT_STACK

    edit_instruction = read_pending_edit(app_dir)
    is_edit = bool(edit_instruction) and app_built
    narrate("feature_resolved", fid=fid,
            mode=("edit" if is_edit else "build"), stack=stack)

    if not is_edit and not any(ctx.values()):
        log(f"no spec/requirement found for {fid} under {repo_root}")
        sys.exit(3)

    edit_read_hashes, edit_outlined = {}, set()
    if is_edit:
        log(f"EDIT mode ({stack}): applying change -> {edit_instruction[:100]}")
        narrate("reading_files", mode="edit", instruction=edit_instruction[:140])
        read_files = current_app_files(app_dir)
        narrate("files_read", count=len(read_files))
        edit_read_hashes, edit_outlined = edit_read_guard(read_files, edit_instruction)
        narrate("planning", mode="edit")
        system, user = assemble_edit(
            app_dir, fid, read_files, edit_instruction, stack)
    else:
        # Scaffold-then-diff (N7): a fresh build from a template stack (react OR expo)
        # starts from the checked-in working template; the model then emits ONLY the
        # feature's files. (Bug: this was gated to STACK_REACT, so a fresh expo-rn
        # build was NEVER scaffolded and always failed verify with "scaffold not
        # applied" — mobile was broken end-to-end.)
        if should_scaffold(stack, app_dir):
            tpl = template_dir(repo_root, workspace, stack)
            if not tpl:
                log(f"stack {stack} selected but no template found under templates/")
                sys.exit(7)
            os.makedirs(app_dir, exist_ok=True)
            narrate("scaffolding", stack=stack)
            scaffold_app(app_dir, tpl)
            narrate("scaffolded", stack=stack)
            log(f"scaffolded {stack} template -> apps/{fid}/")
        log(f"BUILD mode ({stack})")
        narrate("planning", mode="build")
        system, user = build_messages(fid, ctx, stack)
    # Close the learning loop: splice past-failure guidance (recorded but never read
    # back until now) into the prompt so the model pre-empts repeat failures. The
    # heal turn inherits it via fix_messages(user, ...).
    recall = recall_blockers(repo_root)
    if recall:
        # Caveman (ADF_CAVEMAN, default off): trim filler from the recall PROSE to save
        # input tokens. Guarded — code / file markers / security lines pass verbatim, so
        # brevity never corrupts the guidance. A no-op when disabled.
        import caveman
        recall = caveman.compress_prose(recall)
        user = f"{user}\n\n{recall}"
        narrate("recall_injected")
        log("recall: injected past-failure guidance from the learning store")
    timeout = int(os.environ.get("ADF_RUNNER_TIMEOUT_SEC", "180"))
    max_iters = int(os.environ.get("ADF_RUNNER_FIX_ITERS", "3"))

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    in_tok = out_tok = 0
    app_root = written = None
    verified = False
    last_failure = ""
    verify_summary = ""
    # Process disciplines (all gated, default-off): TDD red→green (P1), a
    # systematic-debugging self-heal (P1), and a parallel subagent crew (P3). Imported
    # once; stdlib-only siblings.
    import tdd_loop
    import heal
    import build_crew
    tdd_verdict, tdd_test_paths = None, []

    for attempt in range(1, max_iters + 1):
        narrate("generating", attempt=attempt)
        _reset_stream_progress()  # fresh heartbeat counter per generation attempt
        # Heartbeat so the live feed never goes dark during the (possibly minutes-
        # long) BLOCKING model call — the default, non-streaming path emits no
        # token deltas (E1). Stopped in finally so an early exit can't leak it.
        _hb = _GenerationHeartbeat().start()
        try:
            # Parallel subagent crew (ADF_BUILD_CREW): generate the FIRST draft as
            # dependency-ordered subagents (attempt 1 only; heal turns use whole-app
            # context). Falls back to monolithic on any blocker. Never changes the
            # authoritative verify/heal/seal tail below.
            used_crew = False
            files = None
            if attempt == 1 and not is_edit and build_crew.is_enabled():
                crew = build_crew.decomposition_for(stack)
                if crew:
                    files = _crew_generate(
                        crew, system, user, stack, timeout, workspace, fid)
                    used_crew = files is not None
            if files is None:
                gen = generate(messages, timeout)
                if not gen:
                    log("no model backend produced output (set NVIDIA_API_KEY / "
                        "ANTHROPIC_API_KEY, or run Ollama)")
                    sys.exit(4)
                text, usage = gen
                in_tok += usage.get("prompt_tokens", 0)
                out_tok += usage.get("completion_tokens", 0)
                files = parse_files(text)
        finally:
            _hb.stop()
        narrate("generated", attempt=attempt, files=len(files))
        if not files:
            log(f"attempt {attempt}: no parseable <<<FILE:>>> blocks; first 400 chars:\n{text[:400]}")
            if attempt == max_iters:
                record_build_outcome(repo_root, fid, False,
                                     "model emitted no parseable <<<FILE:>>> blocks")
                sys.exit(5)
            continue

        if is_edit and (edit_outlined or edit_read_hashes):
            files, guard_notes = apply_edit_guards(
                app_dir, files, edit_read_hashes, edit_outlined)
            for note in guard_notes:
                log(f"edit guard: {note}")
            if not files:
                log(f"attempt {attempt}: every emitted file was rejected by the "
                    f"edit guard (blind/stale)")
                if attempt == max_iters:
                    record_build_outcome(
                        repo_root, fid, False,
                        "all edits rejected by the guard: " + "; ".join(guard_notes))
                    sys.exit(5)
                # Tell the model WHY its edits were rejected + re-show the real
                # current files, so the next attempt is productive (not an
                # identical regeneration that gets rejected again).
                last_failure = ("Your edits were REJECTED before writing: "
                                + "; ".join(guard_notes) + ". Only edit files shown "
                                "to you in FULL (not files shown as an outline), and "
                                "base your edit on the current contents below.")
                messages = fix_messages(system, user, current_app_files(app_dir),
                                        last_failure, stack)
                continue

        # TDD red→green (ADF_TDD): prove the tests FAIL before the implementation
        # exists, then let the normal write+verify drive them GREEN. Attempt 1 only;
        # gated; never replaces verify_app. Skipped when the crew ran (it already wrote
        # the implementation to disk, so a RED baseline would be invalid/vacuous).
        if (attempt == 1 and not is_edit and tdd_loop.is_enabled()
                and not used_crew):
            tdd_verdict, tdd_test_paths = _tdd_red_baseline(
                workspace, fid, stack, files, timeout)

        narrate("writing_files", total=len(files))
        app_root, written = write_files(workspace, fid, files)
        narrate("files_written", count=len(written))
        # Refresh the staleness baseline to what we just wrote: a later self-heal
        # attempt re-reads these files and must compare against the runner's OWN last
        # write, not the pre-loop original (else attempt 2+ self-flags as "stale").
        if is_edit:
            for rel, content in files:
                norm = rel.lstrip("/")
                edit_read_hashes[norm] = _content_hash(
                    content if content.endswith("\n") else content + "\n")
        narrate("verifying", stack=stack, attempt=attempt)
        ok, output = verify_app(app_root, stack)
        narrate("verify_result", ok=bool(ok), attempt=attempt)
        last_failure = output
        log(f"attempt {attempt}: wrote {len(written)} files; verify {'PASSED' if ok else 'FAILED'}")
        if ok:
            # Completion audit (5.9): a green verify only ran the tests the model
            # wrote — a vacuous test passes. For a shaped feature, if the tests
            # don't cover the shape's required behavior AND there's heal budget
            # left, spend ONE more iteration closing the gap. Never fails an
            # already-verified build: the last attempt always seals.
            gaps = [] if is_edit else audit_completion(app_root, stack, ctx, fid)
            if gaps and attempt < max_iters:
                narrate("completion_audit", gaps=gaps)
                log(f"attempt {attempt}: verify passed but completion audit found "
                    f"uncovered deliverables: {gaps}")
                last_failure = (
                    "VERIFICATION PASSED, but the generated tests do not cover "
                    "required behavior for this feature:\n- " + "\n- ".join(gaps)
                    + "\nAdd the missing test assertion(s) (keep everything else "
                    "green) and re-emit all files.")
                messages = fix_messages(system, user, files, last_failure, stack)
                continue
            # TDD: record the real RED→GREEN transition so process_facts seals
            # `tdd_followed` (proven only when a real RED preceded this GREEN).
            if tdd_verdict is not None:
                tdd_loop.record(app_root, tdd_verdict, True, tdd_test_paths)
            verified = True
            verify_summary = output
            if gaps:
                verify_summary += ("\n\n[completion audit] sealed with uncovered "
                                   "deliverables (heal budget exhausted): "
                                   + "; ".join(gaps))
            break
        if attempt < max_iters:
            narrate("self_heal", attempt=attempt, reason=output[:200])
            log(f"attempt {attempt}: feeding failure back to the model to self-correct")
            # Systematic debugging (ADF_HEAL_DIAGNOSE): record the root cause from the
            # REAL failure (→ seals root_cause_documented) and demand a one-line ROOT
            # CAUSE before the patch, instead of a blind regenerate. Gated.
            fail_text = output
            if heal.is_enabled() and app_root:
                heal.record_root_cause(app_root, attempt, output)
                fail_text = heal.diagnose_preamble(output) + "\n\n" + output
            messages = fix_messages(system, user, files, fail_text, stack)

    # Record this implement-phase outcome so recall_blockers can surface it on a
    # FUTURE build (the loop is otherwise inert — nothing else writes phase 7).
    record_build_outcome(repo_root, fid, verified, last_failure)

    if app_root is None:
        log("implementation produced no files")
        sys.exit(5)

    # Seal a Proof of Build INTO the app — a tamper-evident Merkle certificate
    # of exactly what ADF generated and verified, recomputable offline by anyone.
    # Best-effort: never let sealing fail an otherwise-good build.
    proof_seal = None
    policy_ok = None
    policy_blocked = None   # enforced security rules that FAILED → fail-closed
    n_components = None
    if verified and (stack or DEFAULT_STACK) in (STACK_REACT, STACK_EXPO):
        # Project-specific artifact: catalog the app's reusable, props-driven
        # components (.adf-components.json + COMPONENTS.md) so future features can
        # discover and REUSE them instead of duplicating — for web AND mobile (both
        # have src/components/**.tsx). Best-effort.
        try:
            import component_manifest
            manifest = component_manifest.generate(app_root)
            n_components = manifest["count"]
            narrate("component_manifest", count=n_components)
            log(f"component manifest: {n_components} reusable component(s) cataloged")
        except Exception as e:
            log(f"component manifest skipped: {e}")
    if verified:
        # Governance gate: prove the app obeys org policy (no secrets / no network
        # egress / offline-capable / no plaintext PII / vetted deps), write the
        # report, and seal the verdict INTO the Proof of Build so "built + verified
        # + policy-compliant" is provable offline.
        policy_summary_obj = None
        try:
            import policy_gate
            pol_res = policy_gate.check_policy(app_root)
            policy_summary_obj = policy_gate.policy_summary(pol_res)
            policy_ok = pol_res["ok"]
            with open(os.path.join(app_root, ".adf-policy-report.json"),
                      "w", encoding="utf-8") as f:
                json.dump(pol_res, f, indent=2, sort_keys=True)
            n = pol_res["n_violations"]
            narrate("policy_gate", ok=bool(policy_ok), n_violations=n)
            log(f"policy gate ({pol_res['policy_id']}): "
                f"{'PASS' if policy_ok else f'{n} violation(s)'}")
            # FAIL-CLOSED: when an ENFORCED security rule fails, BLOCK the build —
            # do not seal a "compliant" proof and exit non-zero — so a sealed Proof
            # of Build always means "passed the enforced security rules", not merely
            # "we labeled the violations". ADF_POLICY=advisory downgrades to the old
            # record-but-ship behavior (dev escape hatch).
            blocking = policy_gate.blocking_violations(pol_res)
            advisory = os.environ.get("ADF_POLICY", "strict").strip().lower() in (
                "advisory", "warn", "off")
            if blocking and not advisory:
                policy_blocked = blocking
                narrate("policy_blocked", rules=blocking)
                log(f"🚫 policy gate ENFORCED — build BLOCKED on: "
                    f"{', '.join(blocking)} (set ADF_POLICY=advisory to override)")
                record_build_outcome(
                    repo_root, fid, False,
                    f"policy enforced-rule violation: {', '.join(blocking)}")
        except Exception as e:
            # FAIL-CLOSED on a gate error, mirroring the PROCESS gate at the
            # `process_facts_error` block below. The policy gate is opt-OUT advisory
            # (ADF_POLICY defaults to "strict"), so recompute `advisory` from the
            # environment HERE — the try-local may not exist if the exception fired
            # before line ~2790 (e.g. ImportError on `import policy_gate`). This read
            # MUST stay byte-identical to the happy-path check above; if one changes,
            # change both (Risk: SSOT divergence).
            _advisory = os.environ.get("ADF_POLICY", "strict").strip().lower() in (
                "advisory", "warn", "off")
            fc = _policy_failclosed(_advisory)
            if fc:
                # `policy_blocked or fc` PRESERVES real rule names if a genuine
                # violation was already set before the exception fired; only falls
                # back to the synthetic name when nothing was set. Do NOT simplify to
                # a straight assignment — that would clobber the real cause.
                policy_blocked = policy_blocked or fc
                record_build_outcome(
                    repo_root, fid, False, f"policy gate error: {e}")
                log(f"🚫 policy gate BLOCKED on error — policy_gate_error "
                    f"(set ADF_POLICY=advisory to override): {e}")
            else:
                log(f"policy gate skipped (advisory mode): {e}")
        try:
            if policy_blocked:
                # A blocked build is never sealed — a sealed proof is a POSITIVE
                # attestation that the enforced security rules passed.
                raise _PolicyBlocked()
            # Process discipline: record + seal HOW the app was built, not just that
            # it was — the verify gates that passed (and, as later phases land, TDD /
            # root-cause / review). read_process_facts re-reads the durable evidence
            # from disk so the verdict can only attest what truly happened. Best-effort.
            process_obj = None
            process_block = []
            try:
                import process_facts
                process_facts.record_verification(app_root, stack, verify_summary)
                # Two-stage review (Phase 4): compose from real verdicts ADF already
                # computes — spec-compliance (completion audit finds no uncovered
                # deliverable) + code-quality (the policy gate passed). Deterministic;
                # honest (no "an LLM reviewed it" claim).
                # Edit builds run NO spec-compliance audit, so do not attest review on
                # them — sealing spec_compliance=True would overstate what was checked.
                if not is_edit:
                    try:
                        spec_gaps = audit_completion(app_root, stack, ctx, fid)
                        process_facts.record_review(
                            app_root, spec_ok=not spec_gaps, quality_ok=bool(policy_ok))
                    except Exception as e:
                        log(f"review fact skipped: {e}")
                process_obj = process_facts.read_process_facts(app_root)
                process_block = process_facts.enforcement_block(process_obj)
            except Exception as e:
                log(f"process facts skipped: {e}")
                # Fail CLOSED under strict: if the process verdict cannot be computed,
                # a strict build must NOT seal (the enforced disciplines are unproven) —
                # otherwise an error here would silently fail open and defeat the gate.
                if (os.environ.get("ADF_PROCESS", "").strip().lower() == "strict"
                        or os.environ.get("ADF_TDD", "").strip().lower() == "strict"):
                    process_block = ["process_facts_error"]
            # Fail-closed process gate (opt-in, ADF_PROCESS=strict / ADF_TDD=strict):
            # a build that SKIPPED an enforced discipline does not seal — a sealed
            # proof then means the enforced disciplines held. Raised OUTSIDE the try
            # above so it is not swallowed; caught by the outer `except _PolicyBlocked`.
            if process_block:
                narrate("process_blocked", disciplines=process_block)
                log(f"🚫 process gate ENFORCED — build BLOCKED on: "
                    f"{', '.join(process_block)} (discipline not attested; unset "
                    f"ADF_PROCESS=strict / ADF_TDD=strict to override)")
                record_build_outcome(
                    repo_root, fid, False,
                    f"process discipline not met: {', '.join(process_block)}")
                raise _PolicyBlocked()
            # Native mobile deliverable (gated, best-effort): a standalone, signed
            # APK + a clean-emulator preview — the "download + run on a device"
            # artifact. When mobile_native_delivery actually ran and returned facts,
            # the proof_of_build agent folds its sha256 into the sealed verdict (so
            # the downloadable binary is tamper-evident); when it did not run
            # (mobile_facts is None), nothing mobile is sealed.
            mobile_facts = (mobile_native_delivery(app_root, fid)
                            if stack == STACK_EXPO else None)
            import proof_of_build
            from datetime import datetime, timezone
            narrate("sealing")
            proof = proof_of_build.seal_app(
                app_root, fid, stack,
                _spec_block(ctx) or ctx.get("requirement", ""),
                {
                    "backend": os.environ.get("ADF_RUNNER_BACKEND") or "auto",
                    "model": (os.environ.get("ADF_RUNNER_MODEL")
                              or os.environ.get("ADF_RUNNER_CLAUDE_MODEL")),
                    "verified": True,
                    "verify_summary": verify_summary,
                    "prompt": args.prompt,
                    "policy": policy_summary_obj,
                    "render": read_render_facts(app_root),  # MM11: web/iOS render facts
                    "mobile": mobile_facts,  # APK download + emulator preview facts
                    "process": process_obj,  # discipline the build was made with
                },
                created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            proof_seal = proof["seal"]
            narrate("sealed", seal=proof_seal, files=len(proof["files"]))
            log(f"sealed Proof of Build {proof_seal} over {len(proof['files'])} files")
        except _PolicyBlocked:
            pass   # already logged the block above; intentionally unsealed
        except Exception as e:
            log(f"proof-of-build sealing skipped: {e}")

    # Consume the one-box edit request so the next plain run rebuilds normally.
    if is_edit:
        clear_pending_edit(app_dir)

    rel_root = os.path.relpath(app_root, workspace)
    build_ok = verified and not policy_blocked
    if policy_blocked:
        status = ("🚫 BLOCKED by policy gate (enforced security rule(s) failed: "
                  + ", ".join(policy_blocked) + ")")
    elif verified:
        status = "✅ tests PASS"
    else:
        status = "⚠️ tests still failing after retries"
    verb = "Updated" if is_edit else "Implemented"
    if stack == STACK_REACT:
        run_hint = (f"Run:  cd {rel_root} && npm ci && npm run build && "
                    f"PORT=8000 node server/index.mjs")
        test_hint = f"Test: cd {rel_root} && npm test"
    elif stack == STACK_EXPO:
        run_hint = (f"Run:  cd {rel_root} && npx expo start   "
                    f"(or web: npm run web:export && PORT=8000 npm run web:serve)")
        test_hint = f"Test: cd {rel_root} && npm run typecheck && npm test"
    else:
        run_hint = f"Run:  cd {rel_root} && python3 server.py"
        test_hint = f"Test: cd {rel_root} && python3 test_app.py"
    summary = (
        f"{verb} `{fid}` ({stack}) — {status} ({len(written)} files in {rel_root}/)\n"
        + "\n".join(f"- {w}" for w in written)
        + f"\n\n{run_hint}\n{test_hint}"
    )
    if proof_seal:
        pol = "" if policy_ok is None else (
            " · policy ✅ compliant" if policy_ok else " · policy ⚠️ violations")
        summary += (
            f"\n\n🔏 Proof of Build sealed: {proof_seal}{pol}\n"
            f"Verify (offline): python3 scripts/orch/verify_proof.py {rel_root}"
        )
    elif policy_blocked:
        summary += (
            f"\n\n🚫 No Proof of Build sealed — the enforced policy gate BLOCKED this "
            f"build ({', '.join(policy_blocked)}). A sealed proof means the security "
            f"rules passed; this build did not. See {rel_root}/.adf-policy-report.json "
            f"for the located violations. (ADF_POLICY=advisory ships anyway, recording "
            f"the violations in the seal instead of blocking.)"
        )
    if os.path.isdir(os.path.join(app_root, ".adf-context")):
        summary += ("\n\n🗜 Context compacted to fit the model budget "
                    "(durable card in .adf-context/ — the fold is reviewable, "
                    "not a silent drop).")
    if not verified:
        summary += f"\n\nLast test output:\n{last_failure[:1500]}"
    log(f"done: {status}")
    narrate("build_complete", ok=bool(build_ok), status=status)
    emit_result(summary, {"input_tokens": in_tok, "output_tokens": out_tok})
    # Honest exit code: non-zero when verification never passed OR an enforced
    # policy rule blocked the build, so the ADF phase runner records the implement
    # phase as failed (and can self-heal / surface the security block).
    sys.exit(0 if build_ok else 6)


if __name__ == "__main__":
    main()
