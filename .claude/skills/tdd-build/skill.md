---
name: TDD Build
description: Use when generating or changing app code — write tests first, prove RED before GREEN, and let ADF seal that you did
---

## TDD Build

Tests come first, always. This is a system constraint in ADF, not a suggestion: the
implement phase can run a real RED→GREEN loop and SEAL the result into the Proof of
Build as the `tdd_followed` fact (`scripts/orch/tdd_loop.py`, `scripts/orch/process_facts.py`).

### The discipline (RED → GREEN → REFACTOR)

1. **RED** — write the failing test FIRST. In ADF this is mechanized: the model's
   emitted test files are written onto the scaffold ALONE (no implementation) and the
   test stage runs. It MUST fail. A suite that passes with no implementation is
   *vacuous* (asserts nothing) and earns no credit.
2. **GREEN** — write the minimum implementation to make the tests pass. The unchanged
   `verify_app` is the authoritative gate (build · test · boot · render).
3. **REFACTOR** — clean up while the suite stays green.

### How to run it in ADF

- Enable: `ADF_TDD=1` (or `ADF_TDD=strict` to BLOCK the seal when TDD was skipped —
  a vacuous/absent RED then fails to seal, via the same fail-closed path as the policy
  gate).
- The honest RED only runs when deps are already present (warm-cloned at scaffold), so
  a failure reflects missing IMPLEMENTATION, not missing `node_modules` — never a fake RED.
- Verify the attestation offline: `python3 scripts/orch/verify_proof.py --require-discipline tdd_followed <app-dir>`.

### Common mistakes

- "I'll test after." → The RED baseline catches this: no failing-first test ⇒ `tdd_followed`
  seals as `skipped`, and under strict mode the build does not seal at all.
- Writing tests that pass without the feature. → Reported as *vacuous*; fix the test to
  actually constrain the implementation.

### Hard gate

A `proven` `tdd_followed` fact requires a REAL failing test that a REAL implementation
turned green. It cannot be faked — a RED run cannot pass without code.
