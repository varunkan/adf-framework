import 'dart:io';

import 'package:orchestration_server/adf_brain.dart';
import 'package:orchestration_server/learning_store.dart';
import 'package:test/test.dart';

void main() {
  late Directory temp;
  late LearningStore store;

  setUp(() {
    temp = Directory.systemTemp.createTempSync('adf-learnings');
    store = LearningStore(temp.path);
  });

  tearDown(() => temp.deleteSync(recursive: true));

  test('records outcomes and computes success rate', () {
    store.record(featureId: 'f1', phase: 2, kind: 'success');
    store.record(featureId: 'f2', phase: 2, kind: 'success');
    store.record(
      featureId: 'f3',
      phase: 4,
      kind: 'failure',
      blockers: ['missing directory: specs/f3/tasks'],
    );
    final stats = store.stats();
    expect(stats['successes'], 2);
    expect(stats['failures'], 1);
    expect(stats['success_rate'], closeTo(0.667, 0.001));
  });

  test('knownBlockers ranks repeated failures first', () {
    for (var i = 0; i < 3; i++) {
      store.record(
        featureId: 'f$i',
        phase: 4,
        kind: 'failure',
        blockers: ['cycle detected in task-graph.yaml'],
      );
    }
    store.record(
      featureId: 'fx',
      phase: 4,
      kind: 'failure',
      blockers: ['missing required file: tasks.md'],
    );
    final known = store.knownBlockers(4);
    expect(known.first, 'cycle detected in task-graph.yaml');
    expect(known, hasLength(2));
  });

  test('deterministic brain is free and always returns null', () async {
    final brain = DeterministicBrain();
    expect(brain.billsTokens, isFalse);
    expect(await brain.complete(system: 's', user: 'u'), isNull);
  });

  test('brain selector falls back to deterministic without ollama', () async {
    final selector = BrainSelector(
      ollama: OllamaBrain(host: 'http://127.0.0.1:1'),
    );
    final brain = await selector.select();
    expect(brain.name, 'deterministic');
    final desc = await selector.describe();
    expect(desc['token_cost'], 'zero');
  });
}
