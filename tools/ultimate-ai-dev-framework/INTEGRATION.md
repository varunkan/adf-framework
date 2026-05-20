# UAIDF pack — ADF v3 integration

This directory is a **vendored copy** of the Grok `ultimate-ai-dev-framework` pack.

## Do not

- Run `orchestrator.py` instead of `@orch-orchestrator` / `phase_runner.dart`
- Replace Spec Kit or BMAD with Grok-only agents
- Collapse ADF 9 phases into Grok 6 in `state.json`

## Do

- Use prompts under `prompts/` via `.cursor/orchestration/prompt-registry.yaml`
- Merge templates from `.specify/` into `.cursor/orchestration/templates/` (already done in ADF)
- Read `MANIFEST.yaml` for version compatibility

## Upgrade procedure

1. Drop new zip into Downloads
2. Diff against this folder
3. Update `MANIFEST.yaml` version and `adf_compatibility`
4. Re-run `./scripts/orch/validate_adf_artifacts.sh` on a smoke feature

See [ADF.md](../../.cursor/orchestration/ADF.md) and [adf-grok-refinement.md](../../.cursor/orchestration/adf-grok-refinement.md).
