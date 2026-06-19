---
name: Systematic Debug
description: Use when a build/test/verify fails — find the root cause BEFORE any fix, never blind-regenerate
---

## Systematic Debug

No fixes without a root cause first. ADF's self-heal can run this discipline and seal
`root_cause_documented` into the Proof of Build (`scripts/orch/heal.py`).

### The four phases

1. **Read the error.** Identify the failing stage from the verifier's attributed tag
   (`BUILD FAILED (tsc…)`, `TESTS FAILED (vitest)`, `… SERVER BOOT FAILED`). ADF
   classifies the cause deterministically from the REAL output — never from a guess.
2. **Pattern analysis.** Find the working reference (the stack template shape) and
   compare it against the broken file to isolate the difference.
3. **Hypothesis.** State the root cause in ONE line (`ROOT CAUSE: …`) before touching
   any file. Make the smallest change that addresses it — do not rewrite working files.
4. **Fix + verify.** Apply the single targeted fix and re-run the authoritative verifier.

### How to run it in ADF

- Enable: `ADF_HEAL_DIAGNOSE=1`. The fixer turn is prefixed with the failing stage +
  likely class and is required to begin with `ROOT CAUSE:`.
- Past failures are already recalled into the prompt (the learning store), so the fix
  pre-empts repeat failures.
- The diagnosed cause is recorded → `root_cause_documented` (advisory) appears in PROOF.md.

### Common mistakes

- Blind regenerate ("re-emit everything and hope"). → Wastes a heal iteration and often
  reintroduces the same bug. Diagnose first.
- Fixing a symptom, not the cause. → If you need multiple fixes for one failure, stop and
  question the architecture.

### Hard gate

The recorded cause is derived from the REAL captured failure string, never from model
prose claiming it understood the bug.
