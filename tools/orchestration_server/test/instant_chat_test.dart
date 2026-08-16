import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:orchestration_server/orchestrator_chat.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  late OrchestratorChatProcessor processor;
  const id = 'instant-chat-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.adf/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    processor = OrchestratorChatProcessor(store);
    if (!store.featureExists(id)) {
      store.createFeature(id: id, requirement: 'instant chat', track: 'S');
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    final specDir = Directory('$repoRoot/specs/$id');
    if (specDir.existsSync()) specDir.deleteSync(recursive: true);
  });

  test('progress question answers instantly with gates and next action',
      () async {
    final sw = Stopwatch()..start();
    final r = await processor.process(
      id,
      'what is the progress and what is next?',
      mode: ChatProcessMode.stateOnly,
    );
    sw.stop();
    expect(sw.elapsedMilliseconds, lessThan(1000));
    expect(r.source, 'state');
    expect(r.assistantReply, contains('progress'));
    expect(r.assistantReply, contains('Remaining'));
    expect(r.assistantReply, contains('Autopilot'));
  });

  test('artifacts question lists generated spec files', () async {
    File('$repoRoot/specs/$id/spec.md')
      ..parent.createSync(recursive: true)
      ..writeAsStringSync('# spec');
    final r = await processor.process(
      id,
      'show me the artifacts',
      mode: ChatProcessMode.stateOnly,
    );
    expect(r.source, 'state');
    expect(r.assistantReply, contains('specs/$id/spec.md'));
  });

  test('work requests are never intercepted by instant answers', () async {
    final r = await processor.process(
      id,
      'add OAuth login to the plan',
      mode: ChatProcessMode.stateOnly,
    );
    expect(r.source, 'fallback');
    expect(r.agentPrompt, contains('OAuth'));
  });

  test('describe questions bypass model tiers even in httpOnly mode',
      () async {
    // Unreachable Ollama port: if the instant tier did not answer first,
    // this would fall through to the (dead) model tiers instead of 'state'.
    final hermetic = OrchestratorChatProcessor(
      store,
      env: {'ORCH_OLLAMA_HOST': 'http://127.0.0.1:9'},
    );
    final sw = Stopwatch()..start();
    final r = await hermetic.process(
      id,
      'what does this feature do?',
      mode: ChatProcessMode.httpOnly,
    );
    sw.stop();
    expect(r.source, 'state');
    expect(r.assistantReply, contains('instant chat'));
    expect(r.latencyMs, isNotNull);
    expect(sw.elapsedMilliseconds, lessThan(1000));
  });
}
