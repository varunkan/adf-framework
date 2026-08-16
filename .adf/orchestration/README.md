# Orchestration root

Canonical location for orchestration state. `OrchestrationPaths` resolves here,
and the test suites locate the repo by walking up for this directory.

The legacy Cursor-specific path `.cursor/orchestration` was removed on
2026-08-16. Do not reintroduce it: while both existed, the Dart and Python
resolvers disagreed about which to use, so `LearningStore` wrote to
`.adf/orchestration/learnings.jsonl` while `agent_runner.py` read
`.cursor/orchestration/learnings.jsonl` — a file that did not exist. Learning
recall silently returned nothing on every build.

Feature state written here by local runs is disposable; see .gitignore.
