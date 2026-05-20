# Orchestration Protocol v3.0 (ADF / PGAD)

File-based handshake between **Cursor** (`@orch-orchestrator`), **BMAD discipline reviewers** (via `orch-review-coordinator`), **Grok determinism (A–E)**, and the **dev dashboard**.

Read [ADF.md](ADF.md) and [grok-determinism.md](grok-determinism.md) before every conductor spin.

## Feature directory layout

```
.cursor/orchestration/features/<feature-id>/
  requirement.md
  state.json
  approvals.json
  phase-request.json
  run-status.json
  run-log.jsonl
  commands.jsonl
  otel-traces.jsonl
  judge-verdicts/phase-1.md … phase-9.md
  00-intake.md, 04-test-plan.md, 05-test-cases.md, 06-traceability-matrix.md,
  07-verification-report.md, 08-review.md

specs/<feature-id>/          # Spec Kit (canonical SDD)
  spec.md, plan.md, tasks.md, task-graph.yaml, tasks/*.md, chatroom.log, lessons-learned.md
```

On feature start: `./scripts/orch/seed_adf_artifacts.sh <feature-id>`

## Agent context (Principle A)

- Conductor passes **≤4 files** per worker spin; list paths explicitly in `commands.jsonl`.
- No full chat history in prompts; use `requirement.md` + optional `chatroom.log` line.
- Runner logs `context_budget_warn` when prompt exceeds ~400 tokens.

## Phase 7 micro-tasks (Principles D + E)

1. Pick ready task from `task-graph.yaml` (topological order).
2. `adf_worktree.sh create <id> <task-id>` — set `run-status.json` `micro_task_id`.
3. Run `speckit-implement` + `uaidf-tdd-executor` (M/L/XL).
4. `validate_adf_artifacts.sh <id>`
5. `adf_worktree.sh destroy <id> <task-id>`

## state.json schema

```json
{
  "feature_id": "kebab-case-id",
  "track": "M",
  "spec_feature_dir": "specs/kebab-case-id",
  "coverage_mode": "repo_wide",
  "current_phase": 1,
  "phase_revision_count": 0,
  "pending_approval_phase": null,
  "last_judge_verdict": null,
  "awaiting_user": false,
  "gates": {
    "problem_statement_approved": false,
    "requirements_complete": false,
    "plan_covers_all_requirements": false,
    "tasks_atomic_and_traced": false,
    "test_strategy_approved": false,
    "tests_red": false,
    "tests_green": false,
    "r100": false,
    "l100": false,
    "l100_repo": false,
    "l100_feature": false,
    "lint_clean": false,
    "security_clean": false,
    "performance_clean": false,
    "all_quality_gates_pass": false,
    "review_approved": false
  },
  "completed_builders": {},
  "completed_reviewers": {},
  "heal_attempts": 0,
  "correct_attempts": 0,
  "files_in_scope": [],
  "status": "active",
  "loop_history": []
}
```

## Phase → builder / reviewer

See [framework-routing.yaml](framework-routing.yaml). Spec Kit builds phases 2–4, 7. BMAD `reviewers[]` per phase. Phase 8: machine scripts only.

| Phase | Name | Gate |
|-------|------|------|
| 1 | intake | problem_statement_approved |
| 2 | specify | requirements_complete |
| 3 | plan | plan_covers_all_requirements |
| 4 | tasks | tasks_atomic_and_traced |
| 5 | test_plan | test_strategy_approved |
| 6 | test_cases | tests_red |
| 7 | implement | tests_green |
| 8 | verify | all_quality_gates_pass |
| 9 | review | review_approved |

## judge-verdicts format

Merged by `orch-review-coordinator`:

```markdown
# Judge Verdict — Phase N
**Verdict:** PASS | REVISE | FAIL
**Reviewers:** bmad-agent-pm, bmad-validate-prd
**Coordinator:** orch-review-coordinator

## PM/PO (John)
**Reviewer verdict:** PASS
...
```

## Advancement rules

1. Builders complete artifacts.
2. Review coordinator merges BMAD discipline verdicts.
3. Phase 8: all scripts PASS → set machine gate booleans.
4. Orchestrator sets `awaiting_user: true`.
5. User approves → advance only if `last_judge_verdict == pass` OR `judge_waiver`.

## Revision feedback loop (REVISE / FAIL)

When `last_judge_verdict` is not `pass`:

1. Dashboard shows **Combined recommendation** from `judge-verdicts/phase-<n>.md` (section `## Combined recommendation`).
2. **Client must confirm** in the dashboard before revise (`client_confirmed: true` on `POST /approve` with `decision: revise`).
3. Orchestrator receives the combined recommendation as the authoritative feedback loop and must update:
   - `requirement.md`
   - `specs/<feature-id>/plan.md` (and spec/tasks as needed)
   - Phase artifacts (e.g. `00-intake.md`)
4. Re-run builders + BMAD review until verdict is **PASS**; only then may the client **Approve phase**.

`POST /features/<id>/approve` body for revise:

```json
{
  "phase": 1,
  "decision": "revise",
  "notes": "Optional client scope notes",
  "client_confirmed": true,
  "source": "dashboard"
}
```

## Quality scripts (phase 8)

```bash
./scripts/orch/validate_traceability.sh <id>
./scripts/orch/coverage_gate.sh <id> 100 --mode=both
./scripts/orch/lint_gate.sh <id>
./scripts/orch/security_gate.sh <id>
./scripts/orch/performance_gate.sh <id>
```

Repo-wide coverage uses [coverage_baseline.json](../../scripts/orch/coverage_baseline.json) for legacy allowlist.

## Dashboard API (local dev server)

| Endpoint | Purpose |
|----------|---------|
| `GET /runner/health` | cursor-agent path, auth, `ready` |
| `GET /features/<id>/pipeline` | Step-by-step plan from routing + state |
| `POST /features/<id>/commands` | Queue/execute Cursor prompt (`execute: true`) |
| `GET /features/<id>/commands` | Recent commands |
| `GET /features/<id>/run-log` | Runner stdout/stderr log |
| `POST /features/<id>/run` | Auto-run current phase |
| `POST /features/<id>/retry` | Re-queue after failure |
| `GET /features/<id>/artifact-checklist?phase=N` | ADF validator blockers before approve |

## commands.jsonl entry

```json
{"id":"…","prompt":"@orch-orchestrator resume …","step_id":"p1-builder-…","execute":true,"status":"executed","created_at":"…","executed_at":"…"}
```

## run-status.json

`status`: `queued` | `running` | `idle` | `awaiting_approval` | `needs_login` | `error`

Optional: `micro_task_id` — active worktree task for phase 7.

On `needs_login`, includes `error_code` and `recovery_steps[]`.
