import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/autopilot.dart';
import 'package:orchestration_server/deterministic_artifacts.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  late Directory tempLearnings;
  const id = 'autopilot-harness-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    tempLearnings = Directory.systemTemp.createTempSync('adf-learn');
    if (!store.featureExists(id)) {
      store.createFeature(
        id: id,
        requirement: 'Show a daily sales total on the dashboard. '
            'Allow filtering by date range. '
            'Export the summary as CSV.',
        track: 'M',
      );
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    final specDir = Directory('$repoRoot/specs/$id');
    if (specDir.existsSync()) specDir.deleteSync(recursive: true);
    tempLearnings.deleteSync(recursive: true);
  });

  Autopilot buildAutopilot() {
    final engine = DeterministicArtifactEngine(
      store,
      brain: DeterministicBrain(),
    );
    final learnings = LearningStore(tempLearnings.path);
    return Autopilot(store, engine, ArtifactValidator(repoRoot), learnings);
  }

  test('autopilot completes phases 1-6 at zero token cost', () async {
    final summary = await buildAutopilot().run(id);

    expect(summary['phases_completed'], [1, 2, 3, 4, 5, 6]);
    expect(summary['stop_reason'], 'implementation_handoff');
    expect(summary['token_cost'], 'zero');
    expect(summary['brain'], 'deterministic');

    final state = store.readState(id);
    final gates = state['gates'] as Map<String, dynamic>;
    for (final g in [
      'problem_statement_approved',
      'requirements_complete',
      'plan_covers_all_requirements',
      'tasks_atomic_and_traced',
      'test_strategy_approved',
      'tests_red',
    ]) {
      expect(gates[g], isTrue, reason: 'gate $g should pass');
    }
    expect(state['current_phase'], 7);
  });

  test('generated artifacts pass the real machine validator', () async {
    await buildAutopilot().run(id);

    final spec = File('$repoRoot/specs/$id/spec.md').readAsStringSync();
    expect(spec, contains('Problem statement'));
    expect(spec, contains('REQ-001'));
    expect(spec, contains('REQ-003'));
    expect(spec, contains('The system SHALL'));
    expect(spec, isNot(contains('**Track:**')),
        reason: 'requirement metadata must not leak into EARS statements');

    final validation =
        await ArtifactValidator(repoRoot).check(id, phase: 4);
    expect(validation['pass'], isTrue,
        reason: 'blockers: ${validation['blockers']}');
    expect(validation['stdout'], contains('topological order'));
  });

  test('autopilot announces its run in the chat stream', () async {
    await buildAutopilot().run(id);
    final commands = store.listCommands(id);
    final announce = commands.lastWhere(
      (c) => c['llm_source'] == 'autopilot',
    );
    expect(announce['assistant_reply'], contains('Autopilot run finished'));
    expect(announce['assistant_reply'], contains('token cost: zero'));
  });
}
