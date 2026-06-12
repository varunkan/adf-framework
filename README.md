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

## Zero-cost mode

ADF runs at three cost tiers — pick per project, switch any time:

| Tier | Marginal cost | Notes |
|------|---------------|-------|
| Deterministic artifact engine | 0 tokens | Phases 1–6 structure generated without an LLM, guaranteed to pass machine gates |
| Local Ollama runner | $0 | Fully offline: `adf install -t . -i generic -r ollama` |
| Flat-rate subscription runners | Monthly plan only | `claude` / `cursor` under existing subscriptions, no per-message credits |

Compared with credit-billed app builders:

| | ADF | Credit-billed builders |
|---|-----|------------------------|
| Marginal cost per feature | $0 or flat-rate | Credits per message |
| Offline capable | Yes (Ollama runner) | No |
| Code ownership | Plain Git repo in your project | Platform-hosted |
| Audit trail | Phase artifacts + machine gates in-repo | Chat history |

Cost meter: every feature exposes `/features/<id>/cost`, and the dashboard shows a live LLM-cost chip per feature.

## Machine interface (agents operating ADF)

The pipeline is operable end-to-end by other agents and automation — the dashboard is a window, not a requirement. Every operation is a CLI call with machine-readable output, so an orchestrating agent (or a cron job) can create a feature, run all nine phases unattended, and check gate state without a human in the loop. The same surface is exposed over MCP, so any MCP-capable agent can drive ADF as a set of tools.

```bash
adf feature new "Add CSV export" --autopilot   # create + run all phases unattended
adf feature status <feature-id>                # machine-readable phase + gate state
adf feature audit <feature-id>                 # export the audit bundle
```

See [docs/MACHINE.md](docs/MACHINE.md) for the full machine-operation contract.
See [tools/adf_mcp/README.md](tools/adf_mcp/README.md) to register ADF as an MCP server.

Audit bundles are self-contained and verifiable offline with `scripts/orch/verify_audit_bundle.py` — no network, no LLM, no running services required.

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
