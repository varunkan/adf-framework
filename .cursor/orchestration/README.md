# Orchestration root (test fixture + local runs)

`FeatureStore` locates a repo by walking up for `.cursor/orchestration`, so this
directory is what makes the orchestration-server tests runnable inside this repo.

It used to be absent here: while this framework was vendored as a submodule of
ai_pos_system, the walk-up escaped the framework and found the HOST repo's
`.cursor/orchestration` instead. 25 test files depended on that accident. Once
the framework became standalone (2026-08-16) the walk-up found nothing and every
one of those suites failed in `setUp` with "repo root not found".

Feature state written here by local runs is disposable; see .gitignore.

## Note: this is the LEGACY path

`OrchestrationPaths` resolves `.adf/orchestration` first and treats
`.cursor/orchestration` as legacy (see feature_store.dart:8-9). The 25 test files
hardcode the legacy marker in their own walk-up, which is why this directory —
not `.adf/orchestration` — is what makes them run. Migrating those tests to the
current path is worth doing; until then this must stay.
