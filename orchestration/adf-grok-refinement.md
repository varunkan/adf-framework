# ADF ↔ Grok UAIDF refinement map

Grok refines ADF; it does not replace Spec Kit, BMAD, or `@orch-orchestrator`.

## Phase alignment (Grok 6 ↔ ADF 9)

| Grok | ADF phases | Gate | Human approve? |
|------|------------|------|----------------|
| 0 Init | 0 orchestrate | — | No |
| 1 Spec | 1 intake, 2 specify | problem_statement_approved, requirements_complete | **Yes** (1–2) |
| 2 Architecture | 3 plan | plan_covers_all_requirements | **Yes** (3) |
| 3 Task breakdown | 4 tasks | tasks_atomic_and_traced | Validator + BMAD |
| 4 Execution | 5–7 test_plan, test_cases, implement | tests_red, tests_green | BMAD; worktree per task |
| 5 Verification | 8 verify | all_quality_gates_pass | Machine gates |
| 6 Integration | 9 review | review_approved | **Yes** (9) |

## Per-phase approve checklist

Before dashboard **Approve**:

| Phase | Required artifacts | Validator | BMAD |
|-------|-------------------|-----------|------|
| 1 | `00-intake.md`, `requirement.md` | Optional | PASS |
| 2 | `specs/<id>/spec.md` | Shape | PASS |
| 3 | `specs/<id>/plan.md` | Shape | PASS |
| 4 | `task-graph.yaml`, `tasks/task-*.md`, `tasks.md` | **DAG topo** | PASS |
| 5 | `04-test-plan.md` | — | PASS |
| 6 | `05-test-cases.md`, `06-traceability-matrix.md` | Traceability prep | PASS |
| 7 | Tests green; worktree tasks done | Micro-task scope | PASS |
| 8 | `07-verification-report.md` | All 5 gate scripts | — |
| 9 | `08-review.md` | — | PASS |

Run validator:

```bash
./scripts/orch/validate_adf_artifacts.sh <feature-id> --phase <N>
```

## Anti-duplication

- Grok prompts (`meta-orchestrator`, `tdd-executor`) are **overlays** — see `prompt-registry.yaml`.
- Do not run Grok `orchestrator.py` instead of `phase_runner.dart`.
- One primary Spec Kit builder per phase per `framework-routing.yaml`.

## Log equivalence

| Grok | ADF |
|------|-----|
| `chatroom.log` | `commands.jsonl`, optional `specs/<id>/chatroom.log` |
| `audit-log.md` | `run-log.jsonl`, `otel-traces.jsonl` |
| traceability-matrix | `06-traceability-matrix.md` + `specs/<id>/` |
