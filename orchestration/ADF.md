# ADF v3 — Agentic Development Framework (Proof-Governed Agentic Development)

ADF v3 unifies your orchestration stack (dashboard, Spec Kit, BMAD, machine gates) with **Grok UAIDF deterministic discipline** (Principles A–E).

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [WORKFLOW.md](WORKFLOW.md)

## Components

| Layer | Path | Role |
|-------|------|------|
| Conductor | `@orch-orchestrator` | Sole coordinator; never writes production code |
| Policy | `constitution.md`, `grok-determinism.md` | POS + deterministic execution rules |
| Routing | `framework-routing.yaml` | One builder + BMAD reviewers per phase |
| Artifacts | `specs/<id>/`, `.cursor/orchestration/features/<id>/` | Proof on disk |
| Validator | `scripts/orch/validate_adf_artifacts.sh` | Shape + DAG + micro-task scope |
| Worktrees | `scripts/orch/adf_worktree.sh` | Isolated workspace per micro-task (phase 7) |
| API | `tools/orchestration_server` (:3847) | Gates, runner, artifact checklist |
| UI | `tools/orchestration_dashboard` (:3848) | Chat, approve, pipeline |
| Grok reference | `tools/ultimate-ai-dev-framework/` | Vendored pack; not production conductor |

## Agent read order

1. `ADF.md` (this file)
2. `.cursor/orchestration/constitution.md`
3. `.cursor/orchestration/grok-determinism.md`
4. `.cursor/orchestration/framework-routing.yaml`
5. Feature `state.json` + `requirement.md`

## Greenfield vs brownfield

- **Brownfield (POS):** production code under `lib/`, tests under `testcases/`.
- **Greenfield:** standalone products (e.g. `test1` URL shortener) declare package paths in `spec.md`; do not assume POS `lib/` unless explicitly scoped.

## Phase flow (9 phases)

See `workflow.yaml` and `adf-grok-refinement.md` for Grok 6 ↔ ADF 9 mapping.

Phases 1–3 and 9 require **human** dashboard approval. Phases 4–8 auto-unblock when validator + BMAD verdict PASS (unless waived).

## Phase 7 micro-task execution

1. Read `specs/<id>/task-graph.yaml` for ready tasks (topological order).
2. `adf_worktree.sh create <id> <task-id>`
3. Run `speckit-implement` + **required** `uaidf-tdd-executor` overlay (tracks M/L/XL).
4. `validate_adf_artifacts.sh <id>`
5. `adf_worktree.sh destroy <id> <task-id>`
6. Repeat until graph complete.

## Version

- **ADF v3.0.0** — 2026-05-17 — Full Grok fidelity (PGAD)
