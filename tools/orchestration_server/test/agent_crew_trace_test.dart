import 'dart:convert';
import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/agent_crew.dart';
import 'package:orchestration_server/artifact_validator.dart';
import 'package:orchestration_server/deterministic_artifacts.dart';
import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:orchestration_server/orchestration_paths.dart';
import 'package:orchestration_server/trace_writer.dart';
import 'package:test/test.dart';

/// The crew must NARRATE itself live (no ~14s dead-air): it should emit trace
/// spans as each wave starts and each subagent completes, so the dashboard's
/// live-trace stream has something to show during the run.
void main() {
  late String repoRoot;
  late FeatureStore store;
  late Directory tempLearnings;
  late Directory traceDir;
  const id = 'agent-crew-trace-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    tempLearnings = Directory.systemTemp.createTempSync('adf-crew-trace');
    // Isolate trace output to a temp tree so we never touch the real repo log.
    traceDir = Directory.systemTemp.createTempSync('adf-trace');
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
    traceDir.deleteSync(recursive: true);
  });

  test('crew emits wave_start and one agent_done span per subagent', () async {
    final traces = TraceWriter(traceDir.path);
    final crew = AgentCrew(
      store,
      DeterministicArtifactEngine(store, brain: DeterministicBrain()),
      ArtifactValidator(repoRoot),
      LearningStore(tempLearnings.path),
      traces: traces,
    );
    await crew.run(id);

    final file = File(OrchestrationPaths(traceDir.path).otelTracesFile);
    expect(file.existsSync(), isTrue, reason: 'crew must write live trace spans');
    final names = file
        .readAsLinesSync()
        .where((l) => l.trim().isNotEmpty)
        .map((l) => (jsonDecode(l) as Map<String, dynamic>)['name'])
        .toList();

    expect(names, contains('crew.wave_start'));
    expect(
      names.where((n) => n == 'crew.agent_done').length,
      6,
      reason: 'one agent_done span per subagent (phases 1-6)',
    );
  });
}
