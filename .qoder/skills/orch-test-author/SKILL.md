---
name: orch-test-author
description: >-
  Superpowers TDD red phase. Writes 05-test-cases.md, 06-traceability-matrix.md,
  and failing tests in testcases/. Use for phase 5b before implementation.
---

# Test Author

## Outputs

1. `05-test-cases.md` — table: TC-ID, type, steps, expected, covers FR-*
2. `06-traceability-matrix.md` from template
3. Test files under `testcases/` (red)

## TDD red gate

Run scoped tests; **expect failure** for the right reason (missing behavior, not syntax error).

```bash
flutter test testcases/unit/..._test.dart
```

Record output in feature folder notes.

## Traceability

Every FR-* → ≥1 TC-* → task T-* → file path (line coverage filled after green).

## Gate

`gates.tests_red` = true when Verifier confirms intentional failures.

## Do not

- Implement production code in this phase.
