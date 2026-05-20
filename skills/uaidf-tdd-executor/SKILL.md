---
name: uaidf-tdd-executor
description: Grok TDD overlay for ADF phase 7 micro-tasks — strict RED→GREEN→REFACTOR in worktree.
---

# UAIDF TDD Executor (phase 7 overlay)

**Required** for tracks M, L, XL during implement phase. Read [grok-determinism.md](../../orchestration/grok-determinism.md) first.

## Files to read (max 4)

1. Current `specs/<feature-id>/tasks/task-NNN.md`
2. Relevant slice of `spec.md` (if needed)
3. Relevant slice of `plan.md` (if needed)
4. Target test file only

## Process (no deviation)

1. **RED** — write failing test; confirm failure
2. **GREEN** — smallest code to pass
3. **REFACTOR** — clean while green
4. Complete verification checklist in task file
5. Commit using task template message

## Rules

- Edit only files listed in task post-conditions
- Work inside active worktree (`adf_worktree.sh`)
- Stop if unclear — do not guess

Source prompt: `tools/ultimate-ai-dev-framework/prompts/tdd-executor.md`
