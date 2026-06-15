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
import json
import os
import re
import ssl
import subprocess
import sys
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


def read_first(*paths):
    for p in paths:
        if p and os.path.isfile(p):
            try:
                return open(p, encoding="utf-8", errors="ignore").read()
            except OSError:
                pass
    return ""


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
DEFAULT_STACK = os.environ.get("ADF_STACK", STACK_STDLIB)

# Editable app source (multi-file edit). Everything else — deps, build output,
# caches, lockfiles — is excluded so big apps don't blow the prompt.
_EDIT_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".css", ".scss",
              ".sql", ".json", ".md", ".cjs", ".mjs")
_SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__", ".git", ".vite",
              "coverage", ".next", ".turbo"}
_SKIP_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}


def detect_stack(app_dir):
    """Infer the stack: the `.adf-stack.json` manifest is authoritative (contract
    C1); else package.json -> react; else stdlib. No language guessing."""
    manifest = os.path.join(app_dir, ".adf-stack.json")
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding="utf-8") as f:
                return json.load(f).get("stack") or STACK_STDLIB
        except (OSError, ValueError):
            pass
    if os.path.isfile(os.path.join(app_dir, "package.json")):
        return STACK_REACT
    return STACK_STDLIB


def build_messages(fid, ctx, stack=None):
    """Dispatch to the stack's generation prompt."""
    if (stack or DEFAULT_STACK) == STACK_REACT:
        return _react_build_messages(fid, ctx)
    return _stdlib_build_messages(fid, ctx)


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
    user = (
        f"Implement the feature `{fid}` as a real React+Vite+Tailwind app backed by a "
        f"Fastify + SQLite API.\n\n{_spec_block(ctx)}\n\n"
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
        "- `src/App.tsx` (+ small `src/components/*.tsx` as needed) — React + "
        "TypeScript with Tailwind, implementing the full UI and calling the API with "
        "relative `fetch('/api/...')`. `src/App.tsx` must be the default export "
        "rendered by the existing `src/main.tsx`. Keep it type-correct.\n"
        "- `test/<feature>.test.mjs` — Vitest importing "
        "`import { buildApp } from '../server/app.mjs'`, exercising the API via "
        "`app.inject({ method, url: '/api/...', payload })` (NO network/port): assert "
        "the main success path AND at least one validation/error case (400 or 404). "
        "The vitest config already points the db at an in-memory SQLite.\n\n"
        "CRITICAL: `npm run build` (`tsc --noEmit && vite build`) and `npm test` "
        "(vitest) MUST pass, and `node server/index.mjs` must boot. No placeholders. "
        "Emit all files now."
    )
    return system, user


# --- scaffold-then-diff (N7): copy the checked-in template, strip the sample --
# Stacks whose generation starts from a checked-in working template. stdlib has
# no template (single-file generation), so it maps to None.
_STACK_TEMPLATES = {STACK_REACT: "react-vite-sqlite"}
# Sample-feature files the scaffold ships to prove itself; removed before the
# generated feature is written so a stale `/api/items` + its test can't interfere.
_SCAFFOLD_SAMPLE_REMOVE = ("server/api/items.mjs", "test/api.test.mjs")


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
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            if fn in (".adf-deps",) or fn.endswith(".db"):
                continue
            src = os.path.join(root, fn)
            rel = os.path.relpath(src, tpl_dir)
            dest = os.path.join(app_dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
    for rel in _SCAFFOLD_SAMPLE_REMOVE:
        p = os.path.join(app_dir, rel)
        if os.path.isfile(p):
            os.remove(p)
    # Reset schema to a placeholder; the generated schema.sql replaces it (so no
    # leftover sample `items` table lingers in a fresh app's database).
    with open(os.path.join(app_dir, "schema.sql"), "w", encoding="utf-8") as f:
        f.write("-- schema for this app (generated at build time)\n")


_STACK_PROFILES = {
    STACK_STDLIB: {"name": STACK_STDLIB, "build_messages": _stdlib_build_messages},
    STACK_REACT: {"name": STACK_REACT, "build_messages": _react_build_messages},
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


def http_post_json(url, headers, payload, timeout):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    ctx = ssl_context() if url.startswith("https") else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode())


def _max_tokens():
    return int(os.environ.get("ADF_RUNNER_MAX_TOKENS", "8000"))


def call_nvidia(messages, timeout):
    key = (os.environ.get("NVIDIA_API_KEY") or os.environ.get("ORCH_NVIDIA_API_KEY") or "").strip()
    if not key:
        return None
    model = os.environ.get("ADF_RUNNER_MODEL", "meta/llama-3.3-70b-instruct")
    base = os.environ.get("ORCH_NVIDIA_BASE_URL", NVIDIA_BASE).rstrip("/")
    # Cap NVIDIA's read time so a slow free-tier response fails FAST to the next
    # backend instead of hanging the whole build for minutes.
    nv_timeout = min(timeout, int(os.environ.get("ADF_NVIDIA_TIMEOUT_SEC", "75")))
    log(f"using NVIDIA NIM model {model} (timeout {nv_timeout}s)")
    try:
        out = http_post_json(
            f"{base}/chat/completions",
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            {"model": model, "max_tokens": _max_tokens(), "temperature": 0.2,
             "messages": messages},
            nv_timeout,
        )
        choice = (out.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        return text, out.get("usage") or {}
    except (OSError, ValueError, KeyError) as e:
        log(f"NVIDIA call failed: {e}")
        return None


def call_anthropic(messages, timeout):
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        return None
    model = os.environ.get("ADF_RUNNER_CLAUDE_MODEL", "claude-opus-4-8")
    base = os.environ.get("ANTHROPIC_BASE_URL", ANTHROPIC_BASE).rstrip("/")
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    log(f"using Anthropic model {model}")
    try:
        out = http_post_json(
            f"{base}/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            {"model": model, "max_tokens": _max_tokens(), "system": system, "messages": turns},
            timeout,
        )
        blocks = out.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        u = out.get("usage") or {}
        return text, {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0)}
    except (OSError, ValueError, KeyError) as e:
        log(f"Anthropic call failed: {e}")
        return None


def call_ollama(messages, timeout):
    host = (os.environ.get("ORCH_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("ORCH_OLLAMA_MODEL", "llama3.2")
    log(f"using local Ollama model {model}")
    try:
        out = http_post_json(
            f"{host}/api/chat",
            {"Content-Type": "application/json"},
            {"model": model, "stream": False, "messages": messages},
            timeout,
        )
        return (out.get("message") or {}).get("content") or "", {}
    except (OSError, ValueError, KeyError) as e:
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


def generate(messages, timeout):
    """Try each configured backend in order; return (text, usage) or None.
    Headroom runs FIRST, before any backend dispatch.

    Backend order:
      - ADF_RUNNER_BACKEND=nvidia|anthropic|ollama pins exactly one.
      - Otherwise RELIABILITY-FIRST: if ANTHROPIC_API_KEY is set, Claude leads
        (it builds in one shot — no slow free-tier self-heal grind), with NVIDIA
        and Ollama as fallbacks. Set ADF_RUNNER_BACKEND=nvidia for the free path.
      - With no Claude key, fall back to NVIDIA (free) then Ollama (local)."""
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
        res = backend(messages, timeout)
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
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not content.endswith("\n"):
            content += "\n"
        open(dest, "w", encoding="utf-8").write(content)
        written.append(os.path.relpath(dest, workspace))
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
def _npm(app_root, args, timeout):
    """Run `npm <args>` in the app dir; returns (ok, combined_output)."""
    try:
        p = subprocess.run(
            ["npm", *args], cwd=app_root, capture_output=True, text=True,
            timeout=timeout, env=dict(os.environ),
        )
        return p.returncode == 0, (p.stdout + "\n" + p.stderr).strip()
    except FileNotFoundError:
        return False, "npm not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"npm {' '.join(args)} timed out after {timeout}s"


def _node_smoke_boot(app_root, secs=20):
    """Authoritative end-to-end check for the react stack: `node server/index.mjs`
    must start a server that honors PORT and answers GET `/` (the built SPA) and
    `/api/health` with 200 — the same contract AppRunner relies on."""
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
        env=dict(os.environ, PORT=str(port)),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.time() + secs
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                return False, f"`node server/index.mjs` exited on launch:\n{out[-1500:]}"
            try:
                for path in ("/", "/api/health"):
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}{path}", timeout=1
                    ) as r:
                        if r.status != 200:
                            raise OSError(f"{path} -> HTTP {r.status}")
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


def _react_verify(app_root, timeout=None):
    """Verify a React+Vite+Tailwind+SQLite app: install (once) → typecheck+build
    (`tsc --noEmit && vite build`) → vitest → boot. Each stage's failure is
    surfaced verbatim (and attributed) so the self-heal loop can fix the right
    file. Authoritative: a green here means the app really builds, tests, boots."""
    timeout = timeout or int(os.environ.get("ADF_REACT_VERIFY_TIMEOUT_SEC", "600"))
    if not os.path.isfile(os.path.join(app_root, "package.json")):
        return False, "package.json missing — react scaffold was not applied"
    # Install once (npm ci needs the committed lockfile); reuse on re-verify.
    if not os.path.isdir(os.path.join(app_root, "node_modules")):
        ok, out = _npm(app_root, ["ci", "--no-audit", "--no-fund"], timeout)
        if not ok:
            return False, f"DEPENDENCY INSTALL FAILED (npm ci):\n{out[-3000:]}"
    ok, out = _npm(app_root, ["run", "build"], timeout)
    if not ok:
        return False, f"BUILD FAILED (tsc --noEmit && vite build):\n{out[-3000:]}"
    ok, out = _npm(app_root, ["test"], timeout)
    if not ok:
        return False, f"TESTS FAILED (vitest):\n{out[-3000:]}"
    boot_ok, boot_msg = _node_smoke_boot(app_root)
    if not boot_ok:
        return False, f"BUILD + TESTS PASSED but SERVER BOOT FAILED:\n{boot_msg}"
    return True, f"build + vitest passed; {boot_msg}"


def verify_app(app_root, stack=None, timeout=None):
    """Dispatch verification to the stack's pipeline (contract C2). `stack` is
    resolved from the manifest when omitted. stdlib → unittest + python boot;
    react → npm build + vitest + node boot. Unknown stacks fall back to stdlib."""
    stack = stack or detect_stack(app_root)
    if stack == STACK_REACT:
        return _react_verify(app_root, timeout)
    return run_verification(app_root, timeout or 60)


# Wire the per-stack verify callables now that the pipelines are defined (the
# registry literal lives above, before these functions exist).
_STACK_PROFILES[STACK_STDLIB]["verify"] = run_verification
_STACK_PROFILES[STACK_REACT]["verify"] = _react_verify


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


def fix_messages(system, user, files, failure, stack=None):
    """Build the follow-up turn asking the model to fix the failing files. The
    hint about WHICH files may be wrong is stack-aware so the model fixes the
    right surface (server.mjs/vitest for react, server.py/test_app.py for stdlib)."""
    current = "\n".join(
        f"<<<FILE: {p}>>>\n{c}\n<<<END>>>" for p, c in files
    )
    failure = headroom_compress_log(failure)
    if (stack or DEFAULT_STACK) == STACK_REACT:
        where = ("whichever files are wrong (schema.sql, server/api/*.mjs, src/**.tsx, "
                 "and/or test/*.test.mjs). Common causes: a tsc type error in src, a "
                 "missing/renamed SQLite table or column, a route registered with the "
                 "wrong path (routes are relative to `/api`), or a vitest assertion "
                 "mismatch")
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


def build_edit_messages(fid, files, instruction, stack=None):
    """Apply a scoped change to an existing app — the Lovable 'type a change,
    watch it update' loop. We hand the model the current files + the request and
    ask for the SMALLEST edit, re-emitting only the changed files. The
    architecture note + the test it must keep green are stack-aware."""
    if (stack or DEFAULT_STACK) == STACK_REACT:
        arch = (
            "a React+Vite+TypeScript+Tailwind app with a Fastify + better-sqlite3 "
            "server (plain-ESM `server/**.mjs`, routes under `/api`, schema.sql at "
            "boot). Keep `src/**` type-correct (tsc checks it), keep server files as "
            "`.mjs`, and keep the PORT-from-env contract"
        )
        keep_tests = ("Keep the vitest suite (`test/*.test.mjs`) passing; update it "
                      "only if the change requires it.")
    else:
        arch = (
            "a Python stdlib http.server app + a single static index.html. Keep the "
            "same architecture and the PORT-from-env contract "
            "(`port = int(os.environ.get('PORT','8000'))`)"
        )
        keep_tests = ("Keep test_app.py passing; update it only if the change "
                      "requires it.")
    system = (
        f"You are editing an EXISTING, working web app: {arch}. Apply the user's "
        "requested change with the SMALLEST edit that fully satisfies it — preserve "
        "all other behavior and styling exactly. Re-emit the COMPLETE content of "
        "every file you change (and ONLY those), as:\n"
        "<<<FILE: relative/path>>>\n<full file content>\n<<<END>>>\n"
        "No commentary, no markdown fences."
    )
    blocks = "\n\n".join(
        f"<<<FILE: {name}>>>\n{content}\n<<<END>>>" for name, content in files
    )
    user = (
        f"App: `{fid}` — the files below are the current, working version.\n\n"
        f"=== CURRENT FILES ===\n{blocks}\n\n"
        f"=== CHANGE REQUESTED ===\n{instruction}\n\n"
        f"Apply the change and re-emit the complete updated file(s) now. {keep_tests}"
    )
    return system, user


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--workspace", default=os.getcwd())
    args, _ = ap.parse_known_args()

    workspace = os.path.abspath(args.workspace)
    repo_root = os.environ.get("ORCH_REPO_ROOT", workspace)
    load_env(repo_root)

    fid = feature_id_from_prompt(args.prompt)
    if not fid:
        log("could not resolve a feature id from the prompt")
        sys.exit(2)
    log(f"feature: {fid} | workspace: {workspace}")

    ctx = load_feature_context(repo_root, fid)
    app_dir = os.path.join(workspace, "apps", fid)

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

    if not is_edit and not any(ctx.values()):
        log(f"no spec/requirement found for {fid} under {repo_root}")
        sys.exit(3)

    if is_edit:
        log(f"EDIT mode ({stack}): applying change -> {edit_instruction[:100]}")
        system, user = build_edit_messages(
            fid, current_app_files(app_dir), edit_instruction, stack)
    else:
        # Scaffold-then-diff (N7): a fresh react build starts from the checked-in
        # working template; the model then emits ONLY the feature's files.
        if stack == STACK_REACT and not os.path.isfile(
                os.path.join(app_dir, "package.json")):
            tpl = template_dir(repo_root, workspace, stack)
            if not tpl:
                log(f"stack {stack} selected but no template found under templates/")
                sys.exit(7)
            os.makedirs(app_dir, exist_ok=True)
            scaffold_app(app_dir, tpl)
            log(f"scaffolded {stack} template -> apps/{fid}/")
        log(f"BUILD mode ({stack})")
        system, user = build_messages(fid, ctx, stack)
    timeout = int(os.environ.get("ADF_RUNNER_TIMEOUT_SEC", "180"))
    max_iters = int(os.environ.get("ADF_RUNNER_FIX_ITERS", "3"))

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    in_tok = out_tok = 0
    app_root = written = None
    verified = False
    last_failure = ""

    for attempt in range(1, max_iters + 1):
        gen = generate(messages, timeout)
        if not gen:
            log("no model backend produced output (set NVIDIA_API_KEY / ANTHROPIC_API_KEY, or run Ollama)")
            sys.exit(4)
        text, usage = gen
        in_tok += usage.get("prompt_tokens", 0)
        out_tok += usage.get("completion_tokens", 0)
        files = parse_files(text)
        if not files:
            log(f"attempt {attempt}: no parseable <<<FILE:>>> blocks; first 400 chars:\n{text[:400]}")
            if attempt == max_iters:
                sys.exit(5)
            continue

        app_root, written = write_files(workspace, fid, files)
        ok, output = verify_app(app_root, stack)
        last_failure = output
        log(f"attempt {attempt}: wrote {len(written)} files; verify {'PASSED' if ok else 'FAILED'}")
        if ok:
            verified = True
            break
        if attempt < max_iters:
            log(f"attempt {attempt}: feeding failure back to the model to self-correct")
            messages = fix_messages(system, user, files, output, stack)

    if app_root is None:
        log("implementation produced no files")
        sys.exit(5)

    # Consume the one-box edit request so the next plain run rebuilds normally.
    if is_edit:
        clear_pending_edit(app_dir)

    rel_root = os.path.relpath(app_root, workspace)
    status = "✅ tests PASS" if verified else "⚠️ tests still failing after retries"
    verb = "Updated" if is_edit else "Implemented"
    if stack == STACK_REACT:
        run_hint = (f"Run:  cd {rel_root} && npm ci && npm run build && "
                    f"PORT=8000 node server/index.mjs")
        test_hint = f"Test: cd {rel_root} && npm test"
    else:
        run_hint = f"Run:  cd {rel_root} && python3 server.py"
        test_hint = f"Test: cd {rel_root} && python3 test_app.py"
    summary = (
        f"{verb} `{fid}` ({stack}) — {status} ({len(written)} files in {rel_root}/)\n"
        + "\n".join(f"- {w}" for w in written)
        + f"\n\n{run_hint}\n{test_hint}"
    )
    if not verified:
        summary += f"\n\nLast test output:\n{last_failure[:1500]}"
    log(f"done: {status}")
    emit_result(summary, {"input_tokens": in_tok, "output_tokens": out_tok})
    # Honest exit code: non-zero when verification never passed, so the ADF
    # phase runner records the implement phase as failed (and can self-heal).
    sys.exit(0 if verified else 6)


if __name__ == "__main__":
    main()
