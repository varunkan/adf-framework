# ADF Documentation Archive

Copy of all ADF orchestration documents from `.cursor/orchestration/` plus related repo docs.

**Generated:** from repo `ai_pos_system`


## Start here (clone and run)

1. **[CLONE_AND_SETUP.md](CLONE_AND_SETUP.md)** — Full install, prerequisites, external deps, first feature, troubleshooting  
2. **[REPO_MANIFEST.md](REPO_MANIFEST.md)** — Required paths checklist  
3. Run `./documents/adf/verify_setup.sh` from repo root after install  

## Layout

| Path | Description |
|------|-------------|
| `orchestration/` | Full mirror of `.cursor/orchestration/` (md, yaml, json) |
| `related/AGENTS.md` | Repo agent entry (ADF quick start) |
| `related/orchestration-telemetry-README.md` | OpenTelemetry hooks |
| `related/uaidf-*` | Ultimate AI dev framework pack |

## Core docs (start here)

1. [orchestration/ADF.md](orchestration/ADF.md)
2. [orchestration/ARCHITECTURE.md](orchestration/ARCHITECTURE.md)
3. [orchestration/WORKFLOW.md](orchestration/WORKFLOW.md)
4. [orchestration/framework-routing.yaml](orchestration/framework-routing.yaml)

## File index

- `orchestration/ADF.md`
- `orchestration/ARCHITECTURE.md`
- `orchestration/README.md`
- `orchestration/WORKFLOW.md`
- `orchestration/adf-grok-refinement.md`
- `orchestration/agents/implementer.md`
- `orchestration/agents/judge.md`
- `orchestration/agents/product-analyst.md`
- `orchestration/agents/telemetry.md`
- `orchestration/agents/test-architect.md`
- `orchestration/agents/test-author.md`
- `orchestration/agents/verifier.md`
- `orchestration/constitution.md`
- `orchestration/features/_example/state.json`
- `orchestration/features/feature2/00-intake.md`
- `orchestration/features/feature2/04-test-plan.md`
- `orchestration/features/feature2/05-test-cases.md`
- `orchestration/features/feature2/06-traceability-matrix.md`
- `orchestration/features/feature2/07-verification-report.md`
- `orchestration/features/feature2/08-review.md`
- `orchestration/features/feature2/approvals.json`
- `orchestration/features/feature2/judge-verdicts/phase-1.md`
- `orchestration/features/feature2/judge-verdicts/phase-2.md`
- `orchestration/features/feature2/judge-verdicts/phase-3.md`
- `orchestration/features/feature2/judge-verdicts/phase-4.md`
- `orchestration/features/feature2/judge-verdicts/phase-5.md`
- `orchestration/features/feature2/judge-verdicts/phase-6.md`
- `orchestration/features/feature2/judge-verdicts/phase-7.md`
- `orchestration/features/feature2/judge-verdicts/phase-8.md`
- `orchestration/features/feature2/judge-verdicts/phase-9.md`
- `orchestration/features/feature2/last-agent-response.md`
- `orchestration/features/feature2/phase-request.json`
- `orchestration/features/feature2/requirement.md`
- `orchestration/features/feature2/run-status.json`
- `orchestration/features/feature2/state.json`
- `orchestration/features/headless-test-cli/approvals.json`
- `orchestration/features/headless-test-cli/requirement.md`
- `orchestration/features/headless-test-cli/run-status.json`
- `orchestration/features/headless-test-cli/state.json`
- `orchestration/features/ide-create-demo/approvals.json`
- `orchestration/features/ide-create-demo/requirement.md`
- `orchestration/features/ide-create-demo/run-status.json`
- `orchestration/features/ide-create-demo/state.json`
- `orchestration/features/smoke-quality-v1/00-intake.md`
- `orchestration/features/smoke-quality-v1/04-test-plan.md`
- `orchestration/features/smoke-quality-v1/05-test-cases.md`
- `orchestration/features/smoke-quality-v1/06-traceability-matrix.md`
- `orchestration/features/smoke-quality-v1/07-verification-report.md`
- `orchestration/features/smoke-quality-v1/08-review.md`
- `orchestration/features/smoke-quality-v1/approvals.json`
- `orchestration/features/smoke-quality-v1/judge-verdicts/phase-1.md`
- `orchestration/features/smoke-quality-v1/judge-verdicts/phase-2.md`
- `orchestration/features/smoke-quality-v1/judge-verdicts/phase-3.md`
- `orchestration/features/smoke-quality-v1/judge-verdicts/phase-4.md`
- `orchestration/features/smoke-quality-v1/judge-verdicts/phase-5.md`
- `orchestration/features/smoke-quality-v1/judge-verdicts/phase-6.md`
- `orchestration/features/smoke-quality-v1/judge-verdicts/phase-7.md`
- `orchestration/features/smoke-quality-v1/judge-verdicts/phase-8.md`
- `orchestration/features/smoke-quality-v1/judge-verdicts/phase-9.md`
- `orchestration/features/smoke-quality-v1/last-agent-response.md`
- `orchestration/features/smoke-quality-v1/requirement.md`
- `orchestration/features/smoke-quality-v1/run-status.json`
- `orchestration/features/smoke-quality-v1/state.json`
- `orchestration/features/test1/00-intake.md`
- `orchestration/features/test1/04-test-plan.md`
- `orchestration/features/test1/05-test-cases.md`
- `orchestration/features/test1/06-traceability-matrix.md`
- `orchestration/features/test1/07-verification-report.md`
- `orchestration/features/test1/08-review.md`
- `orchestration/features/test1/approvals.json`
- `orchestration/features/test1/judge-verdicts/phase-1.md`
- `orchestration/features/test1/judge-verdicts/phase-2.md`
- `orchestration/features/test1/judge-verdicts/phase-3.md`
- `orchestration/features/test1/judge-verdicts/phase-4.md`
- `orchestration/features/test1/judge-verdicts/phase-5.md`
- `orchestration/features/test1/judge-verdicts/phase-6.md`
- `orchestration/features/test1/judge-verdicts/phase-7.md`
- `orchestration/features/test1/judge-verdicts/phase-8.md`
- `orchestration/features/test1/judge-verdicts/phase-9.md`
- `orchestration/features/test1/last-agent-response.md`
- `orchestration/features/test1/phase-request.json`
- `orchestration/features/test1/requirement.md`
- `orchestration/features/test1/run-status.json`
- `orchestration/features/test1/state.json`
- `orchestration/features/test2/approvals.json`
- `orchestration/features/test2/requirement.md`
- `orchestration/features/test2/run-status.json`
- `orchestration/features/test2/state.json`
- `orchestration/features/testpayment/approvals.json`
- `orchestration/features/testpayment/requirement.md`
- `orchestration/features/testpayment/run-status.json`
- `orchestration/features/testpayment/state.json`
- `orchestration/framework-routing.yaml`
- `orchestration/grok-determinism.md`
- `orchestration/otel-session.json`
- `orchestration/prompt-registry.yaml`
- `orchestration/protocol.md`
- `orchestration/templates/01-spec.template.md`
- `orchestration/templates/05-test-cases.template.md`
- `orchestration/templates/06-traceability-matrix.template.md`
- `orchestration/templates/judge-verdict.template.md`
- `orchestration/templates/micro-task.template.md`
- `orchestration/templates/task-graph.template.yaml`
- `related/AGENTS.md`
- `related/orchestration-telemetry-README.md`
- `related/uaidf-INTEGRATION.md`
- `related/uaidf-MANIFEST.yaml`

**Total files:** 107
