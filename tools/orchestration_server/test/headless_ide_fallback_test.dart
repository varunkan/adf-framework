import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/phase_runner.dart';
import 'package:test/test.dart';

/// Run with: ORCH_SKIP_HEADLESS_PROBE=1 dart test test/headless_ide_fallback_test.dart
void main() {
  late String repoRoot;
  late FeatureStore store;
  late PhaseRunner runner;
  const id = 'headless-ide-fallback-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      repoRoot = Directory(repoRoot).parent.path;
    }
    store = FeatureStore(repoRoot);
    runner = PhaseRunner(store);
    if (!store.featureExists(id)) {
      store.createFeature(id: id, requirement: 'headless fallback', track: 'M');
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    final specDir = Directory('$repoRoot/specs/$id');
    if (specDir.existsSync()) specDir.deleteSync(recursive: true);
  });

  test('enqueueCommand returns ide_only when ORCH_SKIP_HEADLESS_PROBE=1', () async {
    if (Platform.environment['ORCH_SKIP_HEADLESS_PROBE'] != '1') {
      markTestSkipped('Set ORCH_SKIP_HEADLESS_PROBE=1 to run headless fallback test');
    }

    runner.stop();
    final result = await runner.enqueueCommand(
      id,
      prompt: '@orch-orchestrator resume $id',
    );

    expect(result['mode'], 'ide_only');
    expect(result['success'], isTrue);
    expect(runner.isActive(id), isFalse);
    final run = store.readRunStatus(id);
    expect(run?['status'], 'idle');
    expect(run?['agent_active'], isNot(true));
    expect(run?['headless_unavailable'], isTrue);
    expect(run?['resume_mode'], 'cursor_ide');
  }, skip: Platform.environment['ORCH_SKIP_HEADLESS_PROBE'] != '1'
      ? 'ORCH_SKIP_HEADLESS_PROBE=1 not set'
      : false);
}
