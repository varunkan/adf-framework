# Traceability Matrix — {{FEATURE_ID}}

**R100 gate:** every `FR-*` / `NFR-*` / `US-*` below has ≥1 `test-*` and ≥1 task `T-*`.

## Grok index (original request → artifacts)

| Original request (from `requirement.md`) | Spec | Plan | Task IDs | Reviews | Status |
|------------------------------------------|------|------|----------|---------|--------|
| | `specs/{{FEATURE_ID}}/spec.md` | `specs/{{FEATURE_ID}}/plan.md` | task-001… | judge phase-N | IN PROGRESS |

| Req ID | Spec section | Task ID(s) | Test ID(s) | Production file(s):line(s) | Status |
|--------|--------------|------------|------------|----------------------------|--------|
| FR-001 | | T-001 | TC-001 | `lib/...dart` | pending |

## Line coverage ledger (L100)

Files in scope from `03-tasks.md`:

| File | Lines required | Test ID(s) proving execution | lcov % |
|------|----------------|------------------------------|--------|
| | | | |

## Sign-off

- [ ] Test Architect
- [ ] Verifier (R100 script pass)
- [ ] Verifier (L100 script pass)
