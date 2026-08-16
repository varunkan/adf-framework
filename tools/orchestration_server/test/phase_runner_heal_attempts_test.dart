import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
  });

  PhaseRunner runnerWith(Map<String, String> env) =>
      PhaseRunner(store, env: env);

  test('maxHealAttempts honors ORCH_MAX_HEAL_ATTEMPTS, defaults to 3', () {
    expect(runnerWith({'ORCH_MAX_HEAL_ATTEMPTS': '1'}).maxHealAttempts, 1);
    expect(runnerWith({'ORCH_MAX_HEAL_ATTEMPTS': '0'}).maxHealAttempts, 0);
    expect(runnerWith({'ORCH_MAX_HEAL_ATTEMPTS': '5'}).maxHealAttempts, 5);
    // Unset / invalid / negative all fall back to the relentless default of 12.
    expect(runnerWith(<String, String>{}).maxHealAttempts, 12);
    expect(runnerWith({'ORCH_MAX_HEAL_ATTEMPTS': '-2'}).maxHealAttempts, 12);
    expect(runnerWith({'ORCH_MAX_HEAL_ATTEMPTS': 'abc'}).maxHealAttempts, 12);
  });

  test('retryNarration never announces a retry past the cap ("attempt 4 of 3")', () {
    // Before each retry, healSoFar is the count already used.
    expect(PhaseRunner.retryNarration(0, 3), contains('attempt 1 of 3'));
    expect(PhaseRunner.retryNarration(1, 3), contains('attempt 2 of 3'));
    expect(PhaseRunner.retryNarration(2, 3), contains('attempt 3 of 3'));
    // Exhausted → no retry will happen → no narration (the off-by-one bug fix).
    expect(PhaseRunner.retryNarration(3, 3), isNull);
    expect(PhaseRunner.retryNarration(4, 3), isNull);
    // Cap of 0 means never retry.
    expect(PhaseRunner.retryNarration(0, 0), isNull);
  });

  group('interruption resilience (orphaned-run watchdog)', () {
    test('staleRunSec defaults to 180, honors env, 0 disables', () {
      expect(runnerWith(<String, String>{}).staleRunSec, 180);
      expect(runnerWith({'ORCH_STALE_RUN_SEC': '60'}).staleRunSec, 60);
      expect(runnerWith({'ORCH_STALE_RUN_SEC': '0'}).staleRunSec, 0);
      expect(runnerWith({'ORCH_STALE_RUN_SEC': 'x'}).staleRunSec, 180);
    });

    // Default raised 8 -> 100 in da16923, which routed idle-incomplete builds
    // into progress-based healing instead of the orphan cap. The cap is now a
    // crash-loop backstop, not a build-length limit, so it is deliberately
    // generous (see phase_runner.dart:70-73). This test still asserted 8.
    test('maxOrphanResumes defaults to 100 and honors env', () {
      expect(runnerWith(<String, String>{}).maxOrphanResumes, 100);
      expect(runnerWith({'ORCH_MAX_ORPHAN_RESUMES': '3'}).maxOrphanResumes, 3);
    });

    test('ageSeconds measures staleness and tolerates junk/absent timestamps', () {
      final now = DateTime.parse('2026-06-22T12:00:00Z');
      expect(PhaseRunner.ageSeconds('2026-06-22T11:55:00Z', now), 300);
      expect(PhaseRunner.ageSeconds('2026-06-22T12:00:00Z', now), 0);
      expect(PhaseRunner.ageSeconds(null, now), isNull);
      expect(PhaseRunner.ageSeconds('not-a-date', now), isNull);
    });
  });

  group('parseUnittestResult (ADF verifies tests itself, never trusts the agent)',
      () {
    test('a clean pass is recognized', () {
      const out = 'test_a (m.T) ... ok\ntest_b (m.T) ... ok\n\n'
          '----------------------------------------------------------------------\n'
          'Ran 30 tests in 3.5s\n\nOK\n';
      final r = PhaseRunner.parseUnittestResult(out, 0);
      expect(r.count, 30);
      expect(r.passed, isTrue);
    });

    test('FAILED output is NOT green even with a parsed count', () {
      const out = 'Ran 30 tests in 3.5s\n\nFAILED (failures=2)\n';
      final r = PhaseRunner.parseUnittestResult(out, 1);
      expect(r.count, 30);
      expect(r.passed, isFalse);
    });

    test('ERROR output is not green', () {
      const out = 'Ran 5 tests in 0.1s\n\nERROR (errors=1)\n';
      expect(PhaseRunner.parseUnittestResult(out, 1).passed, isFalse);
    });

    test('exit 0 but zero tests is not a pass (nothing was verified)', () {
      const out = 'Ran 0 tests in 0.0s\n\nOK\n';
      expect(PhaseRunner.parseUnittestResult(out, 0).passed, isFalse);
    });

    test('a crash before any test (nonzero exit, no count) is not a pass', () {
      const out = 'Traceback (most recent call last): ImportError\n';
      final r = PhaseRunner.parseUnittestResult(out, 1);
      expect(r.count, 0);
      expect(r.passed, isFalse);
    });
  });
}
