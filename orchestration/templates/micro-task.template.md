---
id: task-NNN
feature_id: {{FEATURE_ID}}
max_duration_seconds: 90
depends_on: []
allowed_paths: []
---

# Micro-task: {{TITLE}}

## Pre-conditions

- [ ] Dependency tasks merged / N/A

## Objective

<!-- One clear outcome — completable in 30–90 seconds of agent time -->

## Post-conditions

- [ ] Tests pass for scope below
- [ ] Only files under `allowed_paths` changed

## Allowed paths

- `path/to/file`

## Verification checklist

- [ ] RED: failing test written and observed
- [ ] GREEN: minimal implementation
- [ ] REFACTOR: clean, tests green

## Commit message template

```
feat({{FEATURE_ID}}): <short description> [task-NNN]
```
