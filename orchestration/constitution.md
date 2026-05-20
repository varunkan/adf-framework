# Project Constitution — AI POS Orchestration v3.0 (ADF)

Governing principles for Spec Kit + BMAD discipline reviews + Superpowers + Grok determinism. Amend only via explicit user approval.

**Also read:** [ADF.md](ADF.md), [grok-determinism.md](grok-determinism.md) (Principles A–E).

## 0. Greenfield features

Standalone products (e.g. URL shortener, new services) may live outside `lib/` when declared in `specs/<feature-id>/spec.md` (`package_root`, `source_paths`). Do not place greenfield code in POS paths without explicit scope.

## 1. Source of truth order

1. [ADF.md](ADF.md) — system map  
2. This constitution  
3. [grok-determinism.md](grok-determinism.md) — deterministic execution (A–E)  
4. `specs/<feature-id>/spec.md` (what / why)  
5. `specs/<feature-id>/plan.md` (how)  
6. `specs/<feature-id>/tasks.md`, `task-graph.yaml`, `tasks/*.md` (DAG + micro-tasks)  
7. `.cursor/orchestration/features/<id>/04-test-plan.md`, `05-test-cases.md`, `06-traceability-matrix.md`  
8. Production code under declared `source_paths` (default `lib/` for POS)  
9. Tests under `testcases/` (POS) or paths declared in spec

## 2. RACI

| Role | Owner |
|------|--------|
| Conductor | `orch-orchestrator` |
| Artifact builder | Spec Kit (`speckit-*`) |
| Discipline reviewer | BMAD (`reviewers[]` via `orch-review-coordinator`) |
| Implementation discipline | Superpowers (prompt-only) |
| POS test design | `orch-test-architect`, `orch-test-author` |
| Machine verification | `orch-verifier` + `scripts/orch/*` |

**Anti-duplication:** one builder + required BMAD reviewers per phase per [framework-routing.yaml](framework-routing.yaml).

## 3. BMAD discipline reviews

Every spec is reviewed from **PM/PO** (`bmad-agent-pm` + charter) and **PRD validation** (`bmad-validate-prd`) before phase 2 approval. Other phases use Architect, QA, Dev, Tech Writer reviewers per routing.

## 4. Superpowers discipline

- **TDD**: red → green → refactor  
- **YAGNI**, **evidence over claims**  
- Phase 6–8: `test-driven-development`, `verification-before-completion`  
- Heal: `systematic-debugging` (max 3 attempts)

## 5. Coverage policy (zero margin on scope)

| Gate | Definition |
|------|------------|
| **R100** | Every `FR|NFR|US-*` in `spec.md` → `TC-*` in traceability matrix |
| **L100-feature** | 100% line coverage on `lib/` files in `tasks.md` |
| **L100-repo** | 100% line coverage on all `lib/**/*.dart` (minus [coverage_baseline.json](../../scripts/orch/coverage_baseline.json) until backfill complete) |
| **Lint** | Zero `flutter analyze` issues (`--fatal-infos`) |
| **Security** | Zero violations from `security_gate.sh` |
| **Performance** | Zero violations from `performance_gate.sh` |

Phase 8 requires **all** machine gates PASS.

## 6. Track adaptation

| Track | When | Notes |
|-------|------|-------|
| **S** | Bug fix, ≤1 file | Light phases 1,2,5; bundle approval 1–2 optional |
| **M** | Normal feature | Full pipeline |
| **L/XL** | Cross-cutting | Full; never skip BMAD review on phases 7, 9 |

## 7. Self-healing limits

- **Self-Healer**: max 3 attempts; never weaken tests or gates  
- **Self-Corrector**: max 2; spec changes need user ACK  

## 8. Flutter / POS specifics

- Tests: `testcases/`; `pump_app.dart` provider scope  
- Order lifecycle: integration tests when touching order screens/service  

## 9. ADF v3 artifacts

On feature start, run `./scripts/orch/seed_adf_artifacts.sh <feature-id>`. Before approve on phases 2–4, run `./scripts/orch/validate_adf_artifacts.sh <feature-id> --phase <N>`.

## 10. Version

- Constitution **v3.0.0** — 2026-05-17 (ADF v3 / PGAD)
