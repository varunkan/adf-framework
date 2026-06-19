#!/usr/bin/env python3
"""TDD red→green for ADF's implement phase — make code-gen test-first and PROVE it.

Gated by ADF_TDD. Superpowers' non-negotiable: tests come first. On a fresh build the
model's emitted TEST files are written onto the scaffold ALONE (no implementation) and
the test stage is run — it must be RED (fail). A suite that PASSES with no
implementation asserts nothing (vacuous) and earns no credit. Then the implementation
is written and the normal verifier runs to GREEN. The real failing→passing transition
is recorded as durable evidence so process_facts can seal `tdd_followed` — a fact that
cannot be faked (a RED run cannot pass without code), bound to two real run results.

Composes with, never replaces, verify_app: the authoritative GREEN gate is unchanged.
The module is pure + injection-based (the test runner is passed in) so the red→green
decision is unit-testable without a live build.
"""
import os
import re

# Same surface as _read_test_sources in agent_runner: a test/ or __tests__/ dir, a
# co-located *.test.* / *.spec.*, or a python test_*.py.
_TEST_PATH = re.compile(
    r"(^|/)(test|tests|__tests__)/|\.test\.|\.spec\.|(^|/)test_[^/]+\.py$")


def is_enabled(env=None):
    env = env if env is not None else os.environ
    return env.get("ADF_TDD", "").strip().lower() in ("1", "true", "on", "strict")


def is_strict(env=None):
    env = env if env is not None else os.environ
    return env.get("ADF_TDD", "").strip().lower() == "strict"


def is_test_file(path):
    return bool(_TEST_PATH.search((path or "").replace("\\", "/")))


def split_tests(files):
    """Partition emitted (path, content) pairs into (test_files, impl_files)."""
    tests, impl = [], []
    for p, c in files:
        (tests if is_test_file(p) else impl).append((p, c))
    return tests, impl


def red_baseline(test_files, impl_files, run_tests):
    """Decide the RED verdict. `run_tests` is an injected callable returning
    (ok, output) AFTER the test files (only) are on disk. Returns a verdict dict:

      red=True     → tests FAILED with no implementation (a real RED baseline)
      vacuous=True → tests PASSED with no implementation (they assert nothing)

    Never raises: a missing-impl/no-tests case is reported honestly (no claim), and a
    runner error is RED-inconclusive (red=False) rather than a fake pass."""
    if not test_files:
        return {"red": False, "vacuous": False, "reason": "no test files emitted"}
    if not impl_files:
        return {"red": False, "vacuous": False,
                "reason": "no implementation files emitted — not a TDD build"}
    try:
        ok, output = run_tests()
    except Exception as e:  # noqa: BLE001 — a flaky runner must not crash the build
        return {"red": False, "vacuous": False, "reason": f"test stage errored: {e}"}
    if ok:
        return {"red": False, "vacuous": True,
                "reason": "tests PASS with no implementation — vacuous (assert nothing)"}
    return {"red": True, "vacuous": False,
            "reason": "tests fail before implementation (RED)"}


def record(app_root, verdict, green_ok, test_paths):
    """Write the red→green transition evidence and return the sealable fact summary.
    Honest: proven ONLY when a real RED preceded a real GREEN. Best-effort write."""
    import process_facts
    proven = bool(verdict.get("red") and green_ok)
    fact = {
        "red": bool(verdict.get("red")),
        "green": bool(green_ok),
        "vacuous": bool(verdict.get("vacuous")),
        "test_files": sorted(test_paths or []),
        "reason": verdict.get("reason", ""),
        "proven": proven,
    }
    process_facts._write(app_root, "tdd.json", fact)
    return fact
