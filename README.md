# ADF v3

## Repository

```bash
git clone https://github.com/varunkan/adf-framework.git
cd adf-framework
bin/adf install -t /path/to/your-project -i cursor
```

Or add as a **git submodule** in your app:

```bash
git submodule add https://github.com/varunkan/adf-framework.git adf-framework
```

---

 — Agentic Development Framework (installable)

Proof-Governed Agentic Development: orchestration API, dashboard, 9-phase pipeline, BMAD reviews, machine gates. Install into any project; wire to Cursor, VS Code, Windsurf, Claude Code, or generic agents.

## Quick start

```bash
cd your-project
/path/to/adf-framework/bin/adf install -t . -i cursor
./adf-framework/bin/adf doctor
./adf-framework/bin/adf start all
```

Open http://localhost:3848 (dashboard) and http://localhost:3847 (API).

## Supported IDEs

| IDE | `-i` flag | Installed paths |
|-----|-----------|-----------------|
| Cursor | `cursor` | `.cursor/orchestration`, skills, hooks |
| VS Code | `vscode` | `.adf/orchestration`, `AGENTS.md`, Copilot instructions |
| Windsurf | `windsurf` | `.adf/orchestration`, `.windsurf/rules/adf.md` |
| Claude Code | `claude` | `.adf/orchestration`, `.claude/skills`, `CLAUDE.md`, `.adf/runner.env` |
| Any other | `generic` | `.adf/orchestration`, `AGENTS.md` |
| **All of the above** | `all` | every adapter, one project |

## Agent runners (IDE-independent)

The pipeline is driven by a pluggable headless **runner**, chosen at start via
`ADF_RUNNER` (written to `.adf/runner.env` by the installer):

| `-r` flag | Drives | Auth |
|-----------|--------|------|
| `cursor` | `cursor-agent --print` | `cursor-agent login` / `CURSOR_API_KEY` |
| `claude` | `claude -p` | `claude login` / `ANTHROPIC_API_KEY` |
| `custom` | any CLI via `ADF_RUNNER_BIN` | `ADF_RUNNER_API_KEY_ENV` |
| `auto` | custom→cursor→claude (first installed) | — |

```bash
adf install -t . -i claude  -r claude    # drive ADF with Claude Code
adf install -t . -i cursor  -r claude    # Cursor docs, Claude runner
adf install -t . -i generic -r custom    # any agent CLI
```

See [docs/RUNNERS.md](docs/RUNNERS.md) for the full matrix and env reference.

## Global install

```bash
adf-framework/bin/adf install --global
~/.adf/current/bin/adf install -t ~/myapp -i vscode
```

## CLI

- `adf install -t DIR -i IDE [-r RUNNER]` — copy framework + IDE adapter + runner.env
- `adf doctor -t DIR` — verify Dart, Git, runner, orchestration paths
- `adf start [api|dashboard|all]` — run services (auto-loads `.adf/runner.env`)
- `adf version`

## Prerequisites

Git, Dart 3.5+, Flutter (dashboard). One headless runner: `cursor-agent` **or** `claude` (Claude Code) **or** any agent CLI via `ADF_RUNNER_BIN`. External: BMAD skills, Spec Kit (`speckit-*`).

## Docs

See `docs/CLONE_AND_SETUP.md` and `package.yaml`.

## Agent commands

```
@orch-orchestrator start <feature-id>
@orch-orchestrator resume <feature-id>
@orch-orchestrator sync <feature-id>
```

## Dashboard chat + LLM

Dashboard messages are processed by `OrchestratorChatProcessor` before invoking the agent:

1. **LLM** interprets natural language (phase, gates, requirement context).
2. Returns an **assistant reply** in chat plus an **orchestrator command**.
3. Runs **cursor-agent** with the crafted prompt when the runner is ready.

Set one of:

```bash
export ORCH_LLM_API_KEY=sk-...          # or OPENAI_API_KEY / GROQ_API_KEY
export ORCH_LLM_MODEL=gpt-4o-mini       # optional
export ORCH_LLM_API_URL=https://api.openai.com/v1/chat/completions  # optional
```

Without an API key, a rule-based fallback still routes messages to `@orch-orchestrator`.
