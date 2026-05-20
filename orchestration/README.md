# ADF v3 — Orchestration Framework

**Spec Kit** builds · **BMAD** discipline reviews · **Grok determinism (A–E)** · **machine gates**.

Entry: [ADF.md](ADF.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [WORKFLOW.md](WORKFLOW.md) · [AGENTS.md](../../AGENTS.md) · Dispatch: [framework-routing.yaml](framework-routing.yaml)

```bash
./scripts/orch/seed_adf_artifacts.sh <feature-id>
./scripts/orch/validate_adf_artifacts.sh <feature-id> --phase 4
```

## Start

```text
@orch-orchestrator start
./scripts/orch/sync_speckit_feature.sh <feature-id>
```

## Phase flow

| Phase | Build | Review (BMAD) |
|-------|-------|----------------|
| 1 | orch-product-analyst | analyst + adversarial |
| 2 | speckit-specify | **PM/PO** + validate-prd |
| 3 | speckit-plan | architect + readiness |
| 4 | speckit-tasks | PM trace + adversarial |
| 5–6 | orch-test-* | QA edge + dev |
| 7 | speckit-implement | code-review + checkpoint |
| 8 | scripts (5 gates) | — |
| 9 | orch-code-reviewer | code-review + tech-writer |

## Quality gates

```bash
flutter test testcases/ --coverage
./scripts/orch/validate_traceability.sh <id>
./scripts/orch/coverage_gate.sh <id> 100 --mode=both
./scripts/orch/lint_gate.sh <id>
./scripts/orch/security_gate.sh <id>
./scripts/orch/performance_gate.sh <id>
```

### Repo-wide 100% coverage

[coverage_baseline.json](../../scripts/orch/coverage_baseline.json) allowlists legacy files below 100%. **Shrink the allowlist each feature PR** until empty.

## Ad-hoc toolchains

| Tool | Use outside pipeline |
|------|----------------------|
| `/bmad-*` create workflows | `_bmad-output/` only |
| `/speckit-*` | `specs/` spikes without feature state |
| Superpowers plugin | IDE discipline; referenced in phase prompts |

## Agent reasoning (OpenTelemetry)

```bash
python3 tools/orchestration_telemetry/bin/query_traces.py -f <id> --reasoning-only
```

Skill: `orch-telemetry` · Hooks capture `afterAgentThought` and tool calls.

## Install CLIs

- Spec Kit: `pipx install specify-cli` · `specify init --here --integration cursor-agent`
- BMAD: `npm i -g bmad-method` · `bmad install`
- Superpowers: `/add-plugin superpowers` or `~/.cursor/plugins/local/superpowers`
