---
name: orch-implementer
description: >-
  DEPRECATED builder. Orchestrator dispatches speckit-implement after tests_red.
  Superpowers executing-plans + TDD apply in phase 7.
---

# Implementer (delegation stub)

**Do not use as a builder in the orchestration pipeline.**

Phase 7 builder: [`speckit-implement`](.cursor/skills/speckit-implement/SKILL.md)

Precondition: `gates.tests_red === true`

BMAD review: `bmad-code-review` + `bmad-checkpoint-preview` via coordinator.

Superpowers: `executing-plans`, `test-driven-development`.
