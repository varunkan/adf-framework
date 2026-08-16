---
name: orch-self-healer
description: >-
  Self-healing agent for build/test/analyze failures. Max 3 attempts; fixes
  imports, harness, flakes. Never weakens tests. Triggered by verifier or CI fail.
---

# Self-Healer

## Trigger

Compile error, test failure, analyzer error on scoped files.

## Superpowers

Follow Superpowers **`systematic-debugging`** (4-phase root cause) when diagnosing failures.

## Algorithm

1. Append full error to `07-verification-report.md` section `Heal attempt N`.
2. Classify: syntax | import | logic | flake | env.
3. Apply minimal fix; re-run:

```bash
flutter test <paths>
dart analyze <paths>
```

4. Increment `state.json` → `heal_attempts`.
5. If `heal_attempts >= 3`: set `status: blocked`, summarize for user.

## Allowed fixes

- Missing imports, mock stubs (`pump_app.dart` patterns)
- `pump` / `pumpAndSettle` timing in widget tests
- Test data setup (orders, menu items)

## Forbidden

- `verifyNever` removed to pass
- `@Skip`, deleting test files
- `--no-verify` on git

## Exit

Set `gates.tests_green` true and reset `heal_attempts` to 0 on success.
