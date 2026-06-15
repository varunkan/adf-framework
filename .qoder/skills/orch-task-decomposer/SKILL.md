---
name: orch-task-decomposer
description: >-
  DEPRECATED builder. Orchestrator dispatches speckit-tasks instead. Do not
  author 03-tasks.md locally when routing phase 4 is active.
---

# Task Decomposer (delegation stub)

**Do not use as a builder in the orchestration pipeline.**

Phase 4 builder: [`speckit-tasks`](.cursor/skills/speckit-tasks/SKILL.md) → `specs/<id>/tasks.md`

List every `lib/*.dart` path in tasks for L100 coverage gate.

BMAD review: `bmad-agent-pm` + `bmad-review-adversarial-general` via coordinator.
