# ADF v3 — Repository manifest (orchestration stack)

Paths required to **clone and run** ADF orchestration. Checked against repo at documentation time.

## Core orchestration

```text
.cursor/orchestration/
  ADF.md ARCHITECTURE.md WORKFLOW.md README.md
  constitution.md grok-determinism.md protocol.md
  adf-grok-refinement.md framework-routing.yaml prompt-registry.yaml
  agents/*.md
  templates/*
  features/                    # per-feature runtime (optional in template)
.cursor/skills/
  orch-orchestrator/SKILL.md
  orch-telemetry/SKILL.md
  orch-test-author/SKILL.md
  orch-self-healer/SKILL.md
  orch-code-reviewer/SKILL.md
  uaidf-tdd-executor/SKILL.md
  # Deprecated: orch-spec-author, orch-judge, orch-implementer, ...
.cursor/hooks.json
.cursor/hooks/orch-otel-ingest.sh
scripts/orch/
  seed_adf_artifacts.sh validate_adf_artifacts.sh validate_traceability.sh
  coverage_gate.sh lint_gate.sh security_gate.sh performance_gate.sh
  adf_worktree.sh setup_cursor_runner.sh coverage_baseline.json
scripts/start_orchestration_dashboard.sh
scripts/start_orchestration_api.sh
tools/orchestration_server/     # Dart package, bin/server.dart
tools/orchestration_dashboard/  # Flutter package
tools/orchestration_telemetry/  # optional
tools/ultimate-ai-dev-framework/
AGENTS.md
documents/adf/                  # documentation archive
```

## External (install separately)

```text
.agents/skills/bmad-*/SKILL.md   # BMAD Method
# Spec Kit skills in Cursor (speckit-*)
# Missing orch-* skills: see CLONE_AND_SETUP.md §5.3
```

## Optional POS app (not required for orchestration-only)

```text
lib/ testcases/ pubspec.yaml
products/                       # greenfield output
specs/                          # created per feature
```

## Ports

| Port | Service |
|------|---------|
| 3847 | Orchestration API |
| 3848 | Dashboard web |
