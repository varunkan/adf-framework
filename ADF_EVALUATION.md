# ADF Framework — Evaluation & Claude Enablement

**Reviewed:** ADF v3.1.0 → shipped changes as **v3.2.0** · 2026-06-12

## What ADF is

ADF (Agentic Development Framework) is a proof-governed orchestration layer for
agentic coding. It coordinates a 9-phase pipeline (specify → plan → … → quality
gates) with a single conductor agent (`@orch-orchestrator`), BMAD discipline
reviewers, Spec Kit builders, and machine gates (traceability, coverage, lint,
security, performance). State and artifacts live on disk under `specs/<id>/` and
`orchestration/features/<id>/`; a Dart orchestration server (`:3847`) exposes
gates/runner/health endpoints and a Flutter dashboard (`:3848`) provides chat,
approvals, and pipeline views. Human approval is required at phases 1–3 and 9;
phases 4–8 auto-unblock when the validator and BMAD verdicts pass.

## Assessment

**Strengths.** The design is genuinely strong. The separation of conductor from
builders, proof-on-disk artifacts, a validator that checks DAG shape and
micro-task scope, isolated git worktrees per micro-task, and explicit quality
gates are all the right primitives for reliable agentic development. The install
system already abstracts IDEs (Cursor, VS Code, Windsurf, Claude Code, generic)
behind an adapter map, and the CLI (`adf install/doctor/start/studio/test`) is
clean. Documentation (ADF.md, AGENTS.md, ARCHITECTURE.md, WORKFLOW.md) is
thorough.

**The core gap.** Despite the IDE-agnostic install layer, the *execution
backbone was hard-wired to `cursor-agent`*. Every runtime path —
`agent_chat_runner.dart`, `phase_runner.dart`, `runner_health.dart`, and the
liveness/auth probes — resolved and shelled out specifically to `cursor-agent`
with Cursor-only flags (`--print --workspace --approve-mcps`). The existing
"claude" adapter only dropped a `CLAUDE.md` and symlinked skills; it did **not**
let the orchestration engine actually run on Claude. In practice the pipeline
and dashboard could only be driven by Cursor, regardless of the chosen IDE. This
was the single biggest portability limitation.

**Secondary observations.** Auth/health semantics assumed Cursor's `status`
verb; recovery hints were Cursor-specific; the server startup log and dashboard
copy named cursor-agent directly. None of these are architectural problems —
they're symptoms of the missing runner abstraction.

## What changed (v3.2.0)

The fix introduces a **pluggable runner backend** so the same pipeline runs on
any agent CLI, decoupled from the IDE adapter.

- **New `runner_backend.dart`** — a `RunnerBackend` abstraction with three
  implementations: `CursorBackend` (unchanged behavior), `ClaudeBackend`
  (`claude -p --output-format stream-json --verbose
  --dangerously-skip-permissions --add-dir`), and a fully generic
  `CustomBackend` driven by `ADF_RUNNER_BIN` / `ADF_RUNNER_ARGS` (with
  `{prompt}` / `{workspace}` placeholders) for any other CLI. Selection is via
  `ADF_RUNNER` (`auto|cursor|claude|custom`); `auto` prefers an installed
  custom runner, then cursor, then claude — so existing Cursor setups are
  unaffected.
- **`runner_health.dart` refactored** to delegate executable resolution, argv
  construction, auth/liveness probing, and stale-process cleanup to the active
  backend, while keeping every public method name (`resolveCursorAgent`,
  `probe`, `livenessProbe`, `killStalePrintAgents`) for backward compatibility.
  Probe output gains a `runner` field.
- **Call sites rerouted** — `phase_runner._spawnAgent` and
  `agent_chat_runner.converse` now build args through the backend, so Claude
  receives Claude flags and Cursor receives Cursor flags. The shared
  `stream-json` parser already handles both (terminal
  `{"type":"result","result":…}`), so logging, partial streaming, and the
  `[ACTION:…]` chat protocol work unchanged.
- **Installer is IDE- and runner-agnostic** — `adf install` gains `-r/--runner`
  and an `-i all` option; it writes a backend-specific `.adf/runner.env`
  (via `write_runner_env.sh`) and records `runner`/`ides` in
  `.adf-install.json`. `adf start` auto-loads `runner.env`; `adf doctor` reports
  the active runner and checks for `claude`.
- **Docs + tests** — new `docs/RUNNERS.md`, `install/runner.env.example`,
  updated README/ADF.md, and `runner_backend_test.dart` asserting per-backend
  argv. Repackaged as a downloadable `dist/adf-framework-3.2.0.tar.gz`.

## Using Claude now

```bash
npm install -g @anthropic-ai/claude-code
claude login                                  # or export ANTHROPIC_API_KEY=...
adf install -t . -i claude -r claude          # or: -i cursor -r claude
set -a && . .adf/runner.env && set +a
adf doctor && adf start all
```

The IDE adapter (`-i`) decides where docs/skills land; the runner (`-r`) decides
which agent executes the pipeline. They're independent — you can keep Cursor
docs but drive everything with Claude.

## Verification performed

Full local verification with Dart 3.9 / Flutter stable (2026-06-12):

- `tools/orchestration_server`: `dart analyze` — no issues; `dart test` —
  **88 passed, 1 skipped** (covers runner backends, runner health, integrity
  chain, agent crew, autopilot, learning store, preview service, figma
  connector, orchestrator chat, phase-runner resilience).
- `tools/orchestration_dashboard`: `flutter analyze` — no issues;
  `flutter test` — **22 passed** (studio shell, prompt hero, live preview,
  API client, feature list).
- Shell layer smoke-tested end to end: `write_runner_env.sh` for every runner
  (cursor/claude/custom), each generated `runner.env` sourced under `set -a`.

**Before first production use:** do one live `adf start` with
`ADF_RUNNER=claude` against a throwaway feature to confirm headless streaming
end to end (this needs a logged-in `claude` CLI, so it can't run in CI).

## Follow-ups (status)

1. ~~**Dashboard copy**~~ — done. `/runner/health` now returns `runner_label`
   and `login_command`; `runner_setup_card.dart` renders the active runner's
   name, login command, and recovery steps (Cursor-specific quick-setup only
   shows for the cursor runner).
2. **Per-runner liveness tuning** — operational note: Claude's cold-start can
   exceed Cursor's; if probes flap, set `ORCH_HEADLESS_ASSUME_READY=1` or raise
   the probe timeout.
3. ~~**CI matrix**~~ — done. `.github/workflows/ci.yml` runs `dart analyze
   --fatal-infos` + `dart test` (server), `flutter analyze` + `flutter test`
   (dashboard), and the `write_runner_env.sh` round-trip smoke for all three
   runners on every push/PR.
