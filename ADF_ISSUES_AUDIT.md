# ADF Framework — Issues Audit

_Audit date: 2026-06-13 · Scope: `adf-framework/` (security, bugs/correctness, code quality, docs/config)_

> **Status: all findings below have been FIXED and verified (2026-06-13).** Fixes were applied to both the canonical sources (`.cursor/hooks/`, `scripts/orch/`) and the shipped `adf-framework/` copies. Remaining action that requires you: **rotate the Anthropic + NVIDIA API keys** (C1), since they sat in plaintext in `.env`.

Findings are ordered by severity. Each lists the location and a suggested fix. Line references were valid at audit time.

---

## Critical

### C1. Release packaging bundles live secrets (`.env`)
- **Where:** `scripts/package_release.sh`
- **Detail:** The tarball command excludes only `.git`, `dist`, `build`, `.dart_tool`. It does **not** exclude `.env`. `adf-framework/.env` currently holds **live** `ANTHROPIC_API_KEY` (`sk-…`), `NVIDIA_API_KEY` (`nvapi-…`), and model config in plaintext. A simulated package run confirmed `.env` is included in the archive. Anyone running `package_release.sh` (or `scripts/package_adf.sh`) while `.env` exists ships those keys to every recipient.
- **Note:** `.env` is correctly git-ignored and is **not** committed, and the two existing tarballs in `dist/` and `.release_artifacts/` do **not** contain it — so no leak has occurred yet. This is a latent landmine, not a past breach.
- **Fix:** Add `--exclude='.env' --exclude='.env.*' --exclude='*/runner.env' --exclude='**/otel-traces.jsonl'` to both `tar` invocations in `package_release.sh`. Rotate the Anthropic and NVIDIA keys regardless, since they have been sitting unencrypted in the working tree.

---

## High / Medium (security)

### S1. Telemetry hooks blanket-approve all gated operations
- **Where:** `hooks/orch-otel-ingest.sh`, `hooks/orch-log-subagent.sh`
- **Detail:** The OTEL ingest hook returns `{"permission":"allow"}` for `preToolUse`, `subagentStart`, `beforeShellExecution`, and `beforeMCPExecution`; `orch-log-subagent.sh` always returns `{"permission":"allow"}`. Once ADF hooks are installed (`hooks.json`), every shell command and MCP call is auto-approved — Cursor's per-action approval prompts are effectively disabled for any project that installs ADF.
- **Note:** This is partly intentional (the comment notes empty `{}` may be rejected and block the agent), but the side effect — silently granting blanket shell/MCP execution — should be a conscious, documented choice, not a side effect of a logging hook.
- **Fix:** Separate telemetry from authorization. Have the logging hook return `{}` (or omit the permission key) and only emit `allow` where the user has explicitly opted into unattended mode.

### S2. Release archive also ships runtime telemetry
- **Where:** `scripts/package_release.sh`
- **Detail:** Same missing excludes mean `**/otel-traces.jsonl` (captured prompts, tool I/O, local paths) and `.adf/runner.env` get bundled into releases. Covered by the C1 fix.

---

## Medium (bugs / correctness)

### B1. Gate scripts resolve the wrong root
- **Where:** `scripts/orch/security_gate.sh`, `coverage_gate.sh`, `lint_gate.sh`, `validate_adf_artifacts.sh`
- **Detail:** Each computes `ROOT="$(cd "$(dirname "$0")/../.." && pwd)"` — two levels above the script. For the framework-internal copies at `adf-framework/scripts/orch/`, that resolves to `adf-framework/`, so they scan `adf-framework/lib` / `adf-framework/coverage` instead of the POS project. They check POS-specific patterns (`DELETE FROM orders`, soft-delete, `flutter test testcases/`), so the project root is clearly the intended target. They ignore `ORCH_REPO_ROOT` and `lib/resolve_paths.sh`. They only behave correctly when run from the *project-root copy* (`ai_pos_system/scripts/orch/`, confirmed identical), making correct behavior depend on which copy you invoke.
- **Fix:** Resolve the root via `lib/resolve_paths.sh` / `ORCH_REPO_ROOT` rather than script-relative `../..`, or document that gates must be run only from the project-root copy.

### D1. Version mismatch across the package manifest
- **Where:** `package.yaml` (`version: 3.1.0`) vs `VERSION` (`3.2.0`), `tools/adf_mcp/pubspec.yaml` (`3.2.0`), `tools/adf_mcp/lib/mcp_server.dart` (`serverVersion = '3.2.0'`), and `tools/adf_mcp/test/mcp_server_test.dart` (asserts `3.2.0`).
- **Detail:** `package.yaml` is stale at 3.1.0 while every other source of truth says 3.2.0.
- **Fix:** Bump `package.yaml` to 3.2.0 (or generate it from `VERSION`).

---

## Low

### Q1. Leftover debug instrumentation shipped in hooks
- **Where:** `hooks/orch-otel-ingest.sh`, `hooks/orch-log-subagent.sh` (`#region agent log` blocks)
- **Detail:** Hardcoded `sessionId":"e6daa9"`, `runId":"pre-fix"`, writing to `.cursor/debug-e6daa9.log` on **every** hook invocation. This is one-off debugging that escaped into the shipped framework; it pollutes every consuming repo and adds a `python3` call per hook.
- **Fix:** Delete the `#region agent log` / `_agent_log` blocks.

### B2. `bin/adf doctor` calls `adf_resolve_repo_root` twice
- **Where:** `bin/adf` lines ~127–128
- **Detail:** `if ROOT="$(adf_resolve_repo_root 2>/dev/null)"; then ROOT="$(adf_resolve_repo_root)"` — runs the resolver twice (redundant subprocess) and the surrounding `if/else/fi` block is mis-indented, which obscures the control flow even though it is balanced.
- **Fix:** Drop the second call; reuse `$ROOT`. Re-indent the block.

### Q2. Undocumented `ollama` runner option
- **Where:** `install/write_runner_env.sh` supports `ollama`, but `bin/adf` usage and `install/install.sh` advertise only `auto|cursor|claude|custom`. CI's installer smoke test (`.github/workflows/ci.yml`) covers only `cursor|claude|custom`.
- **Fix:** Document `ollama` in the CLI help / installer, and add it to the CI round-trip loop (and `auto`).

### B3. Stale hardcoded version fallback
- **Where:** `install/install.sh`: `VERSION="$(cat "$FRAMEWORK/VERSION" 2>/dev/null || echo 3.1.0)"`
- **Detail:** Fallback default is `3.1.0`; if the `VERSION` file is ever missing, installs misreport the version.
- **Fix:** Make the fallback match current (`3.2.0`) or fail loudly if `VERSION` is absent.

### D2. `package.yaml` component map omits the MCP server
- **Where:** `package.yaml` `components.tools` lists `server`, `dashboard`, `telemetry` but not `tools/adf_mcp/`.
- **Fix:** Add `mcp: tools/adf_mcp/` so the manifest reflects all shipped tools.

---

## Checked and clean
- No API keys leaked into any **git-tracked** file (`git grep` for `nvapi-`/`sk-ant-`/`sk-…` returned nothing).
- `.env` is git-ignored and untracked; existing release tarballs do not contain it.
- No `TODO`/`FIXME`/`HACK`/`BUG:` markers in tracked source.
- No build output or `dist/` artifacts committed; `.gitignore` patterns (`specs/`, `.specify/`, `.cursor/orchestration/`, `dist/`) have 0 tracked files each — no ignore-vs-track inconsistencies.
- All relative file links in `README.md` resolve.
- `tools/orchestration_server` and `tools/adf_mcp` ship real test suites and CI runs `dart analyze --fatal-infos` + tests on every push/PR.

## Suggested priority order
1. **C1** — exclude `.env`/telemetry from `package_release.sh` and rotate keys.
2. **S1** — decouple telemetry hooks from blanket `allow`.
3. **B1** — fix gate-script root resolution.
4. **D1 / Q1** — sync `package.yaml` version; strip debug blocks from hooks.
5. Remaining low-severity cleanup (B2, Q2, B3, D2).
