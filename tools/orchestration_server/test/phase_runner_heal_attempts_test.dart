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
    // Unset / invalid / negative all fall back to the safe default of 3.
    expect(runnerWith(<String, String>{}).maxHealAttempts, 3);
    expect(runnerWith({'ORCH_MAX_HEAL_ATTEMPTS': '-2'}).maxHealAttempts, 3);
    expect(runnerWith({'ORCH_MAX_HEAL_ATTEMPTS': 'abc'}).maxHealAttempts, 3);
  });
}
