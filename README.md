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
| Claude Code | `claude` | `.adf/orchestration`, `.claude/skills`, `CLAUDE.md` |
| Any other | `generic` | `.adf/orchestration`, `AGENTS.md` |

## Global install

```bash
adf-framework/bin/adf install --global
~/.adf/current/bin/adf install -t ~/myapp -i vscode
```

## CLI

- `adf install -t DIR -i IDE` — copy framework + IDE adapter
- `adf doctor -t DIR` — verify Dart, Git, orchestration paths
- `adf start [api|dashboard|all]` — run services
- `adf version`

## Prerequisites

Git, Dart 3.5+, Flutter (dashboard). Optional: `cursor-agent` for headless. External: BMAD skills, Spec Kit (`speckit-*`).

## Docs

See `docs/CLONE_AND_SETUP.md` and `package.yaml`.

## Agent commands

```
@orch-orchestrator start <feature-id>
@orch-orchestrator resume <feature-id>
@orch-orchestrator sync <feature-id>
```
