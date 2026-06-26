import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

// Phase 3 — bounded cross-feature concurrency + per-feature app-port isolation.
// These prove the defect-free knobs/allocator WITHOUT spawning real builds.
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

  PhaseRunner runnerWith(Map<String, String> env) => PhaseRunner(store, env: env);

  group('Phase 3 — concurrency cap + port isolation', () {
    test('maxBuildParallelism defaults to 1 (serial = today), honors env, rejects junk', () {
      // Default 1 is the safety-critical invariant: unchanged single-feature behavior.
      expect(runnerWith(<String, String>{}).maxBuildParallelism, 1);
      expect(runnerWith({'ADF_BUILD_PARALLELISM': '2'}).maxBuildParallelism, 2);
      expect(runnerWith({'ADF_BUILD_PARALLELISM': '8'}).maxBuildParallelism, 8);
      // 0 / negative / junk all fall back to 1 (never 0 → never wedges the queue).
      expect(runnerWith({'ADF_BUILD_PARALLELISM': '0'}).maxBuildParallelism, 1);
      expect(runnerWith({'ADF_BUILD_PARALLELISM': '-3'}).maxBuildParallelism, 1);
      expect(runnerWith({'ADF_BUILD_PARALLELISM': 'x'}).maxBuildParallelism, 1);
    });

    test('appPortBase defaults to 8000 (the ADF convention), honors env', () {
      expect(runnerWith(<String, String>{}).appPortBase, 8000);
      expect(runnerWith({'ADF_APP_PORT_BASE': '9100'}).appPortBase, 9100);
      expect(runnerWith({'ADF_APP_PORT_BASE': 'bad'}).appPortBase, 8000);
    });

    test('lowestFreePort gives distinct ports per concurrent feature + reuses freed slots', () {
      // First active feature → base.
      expect(PhaseRunner.lowestFreePort(<int>{}, 8000, 2), 8000);
      // Second concurrent feature → next free port (no collision on :8000).
      expect(PhaseRunner.lowestFreePort({8000}, 8000, 2), 8001);
      // When the low slot frees, it is reused (deterministic, compact).
      expect(PhaseRunner.lowestFreePort({8001}, 8000, 2), 8000);
      // Honors a custom base.
      expect(PhaseRunner.lowestFreePort({9100}, 9100, 3), 9101);
      expect(PhaseRunner.lowestFreePort({9100, 9101}, 9100, 3), 9102);
    });
  });
}
