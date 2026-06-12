import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/agent_crew.dart';
import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/deterministic_artifacts.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  late Directory tempLearnings;
  const id = 'agent-crew-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    tempLearnings = Directory.systemTemp.createTempSync('adf-crew');
    if (!store.featureExists(id)) {
      store.createFeature(
        id: id,
        requirement: 'Render the checkout screen. Print a receipt. '
            'Email the receipt to the customer.',
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

  AgentCrew buildCrew() => AgentCrew(
        store,
        DeterministicArtifactEngine(store, brain: DeterministicBrain()),
        ArtifactValidator(repoRoot),
        LearningStore(tempLearnings.path),
      );

  test('crew runs subagents in parallel dependency waves', () async {
    final summary = await buildCrew().run(id);

    final waves = (summary['waves'] as List).cast<List>();
    expect(waves.first, ['product-analyst']);
    expect(waves[1], ['spec-writer']);
    expect(
      waves[2].toSet(),
      {'architect', 'task-planner', 'test-architect'},
      reason: 'independent agents must run concurrently in one wave',
    );
    expect(waves.last, ['test-author']);
    expect(summary['parallelism'], 3);
    expect(summary['phases_completed'], [1, 2, 3, 4, 5, 6]);
    expect(summary['token_cost'], 'zero');
    expect(summary['stop_reason'], 'implementation_handoff');
  });

  test('crew sets gates and logs every subagent', () async {
    await buildCrew().run(id);

    final gates = store.readState(id)['gates'] as Map<String, dynamic>;
    expect(gates['tests_red'], isTrue);
    expect(store.readState(id)['current_phase'], 7);

    final log = File('${store.featurePath(id)}/crew-log.jsonl');
    expect(log.existsSync(), isTrue);
    expect(log.readAsLinesSync().where((l) => l.trim().isNotEmpty).length, 6);

    final announce = store
        .listCommands(id)
        .lastWhere((c) => c['llm_source'] == 'crew');
    expect(announce['assistant_reply'], contains('Multi-agent crew finished'));
    expect(announce['assistant_reply'], contains('6 subagents'));
  });
}
