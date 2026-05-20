# AI POS — ADF v3 (Spec Kit + BMAD + Grok PGAD)

**Proof-Governed Agentic Development:** Spec Kit builds, BMAD reviews, Grok determinism (A–E), machine zero-defect gates.

## Quick start

```
@orch-orchestrator start <feature-id>
@orch-orchestrator resume <feature-id>
@orch-orchestrator sync <feature-id>
```

1. Read [ADF.md](.cursor/orchestration/ADF.md), [constitution](.cursor/orchestration/constitution.md), [grok-determinism](.cursor/orchestration/grok-determinism.md), and [framework-routing.yaml](.cursor/orchestration/framework-routing.yaml).
2. Seed artifacts: `./scripts/orch/seed_adf_artifacts.sh <feature-id>`
3. Validate before approve: `./scripts/orch/validate_adf_artifacts.sh <feature-id> --phase <N>`
2. Each phase: **Build** (Spec Kit) → **Review** (`orch-review-coordinator` + BMAD panel) → **Approve** → next.
3. Phase 8 runs five scripts (traceability, coverage, lint, security, performance).
4. No `lib/` edits until phase 7 and `gates.tests_red`.

## RACI

| Framework | Role | In pipeline |
|-----------|------|-------------|
| **orch-orchestrator** | Conductor, gates, approvals | Always |
| **Spec Kit** | `spec.md`, `plan.md`, `tasks.md`, implement | Phases 2–4, 7 |
| **BMAD** | Discipline reviewers (PM/PO, Architect, QA, Dev, …) | Every phase via coordinator |
| **Superpowers** | TDD, executing-plans, debugging | Phases 6–8, heal |
| **orch-test-*** | POS test plan, cases, matrix | Phases 5–6 |

**Do not double-run:** e.g. never `/speckit-specify` and `orch-spec-author` for the same phase.

## BMAD discipline panel (examples)

| Phase | BMAD reviewers |
|-------|----------------|
| 2 specify | PM/PO (`bmad-agent-pm`), `bmad-validate-prd` |
| 3 plan | `bmad-agent-architect`, `bmad-check-implementation-readiness` |
| 6 test_cases | edge-case hunter, `bmad-agent-dev` |
| 7 implement | `bmad-code-review`, `bmad-checkpoint-preview` |

Verdicts: `judge-verdicts/phase-N.md` (merged by coordinator).

## Quality gates (phase 8)

```bash
./scripts/orch/validate_traceability.sh <feature-id>
./scripts/orch/coverage_gate.sh <feature-id> 100 --mode=both
./scripts/orch/lint_gate.sh <feature-id>
./scripts/orch/security_gate.sh <feature-id>
./scripts/orch/performance_gate.sh <feature-id>
```

Repo-wide 100% coverage: shrink [coverage_baseline.json](scripts/orch/coverage_baseline.json) each PR.

## Ad-hoc (outside pipeline)

| Use | When |
|-----|------|
| `/bmad-create-prd`, sprint loops | Brownfield; outputs `_bmad-output/` |
| `/speckit-*` alone | Spike without orchestration feature folder |
| `/bmad-code-review` | Extra pre-merge review |

## Dashboard

| What | URL |
|------|-----|
| **REST API** | `http://127.0.0.1:3847` |
| **Dashboard (web)** | `http://localhost:3848` — `flutter run -d chrome --web-port=3848` |
| **Dashboard (macOS)** | Desktop app — `flutter run -d macos` (no browser URL) |

```bash
dart run tools/orchestration_server/bin/server.dart
cd tools/orchestration_dashboard && flutter run -d macos
# or web: flutter run -d chrome --web-port=3848
```

List screen shows **feature count** from `GET /features` response (`count` field).

Approve in UI → `@orch-orchestrator sync <id>` (requires BMAD PASS or waiver).

## OpenTelemetry (agent reasoning)

**Skill:** `orch-telemetry` — hooks capture thoughts, tools, subagents → `otel-traces.jsonl`.

```bash
python3 tools/orchestration_telemetry/bin/set_session.py <feature-id> --phase <N> --new-trace
python3 tools/orchestration_telemetry/bin/query_traces.py -f <feature-id> --reasoning-only
curl 'http://127.0.0.1:3847/features/<id>/traces?reasoning_only=true'
```

See [tools/orchestration_telemetry/README.md](tools/orchestration_telemetry/README.md). Hooks: [`.cursor/hooks.json`](.cursor/hooks.json).

**Hooks blocking tools?** Hooks must print exactly one JSON object on stdout (usually `{}`). Reload Cursor after hook changes. Emergency bypass: temporarily rename `.cursor/hooks.json` to `hooks.json.off`.

## Agents

| Agent | Skill |
|-------|-------|
| Orchestrator | `orch-orchestrator` |
| Telemetry | `orch-telemetry` |
| Review coordinator | `orch-review-coordinator` |
| Test architect / author | `orch-test-architect`, `orch-test-author` |
| Verifier | `orch-verifier` |
| Self-healer / corrector | `orch-self-healer`, `orch-self-corrector` |

Deprecated builders: `orch-spec-author`, `orch-architect`, `orch-task-decomposer`, `orch-implementer` → use Spec Kit.

Protocol: [protocol.md](.cursor/orchestration/protocol.md)
