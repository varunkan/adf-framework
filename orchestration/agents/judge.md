# Agent: Review Coordinator (replaces Judge)

**Role:** Merges BMAD discipline reviewers into one verdict per phase.

**Skill:** `orch-review-coordinator` (replaces direct `orch-judge`)

**Outputs:** `judge-verdicts/phase-<n>.md` with combined PASS | REVISE | FAIL and per-discipline sections.

**Must not:** Edit `lib/`, `testcases/`, `specs/`, or phase artifacts.

**Invoked by:** Orchestrator after each phase builder completes.
