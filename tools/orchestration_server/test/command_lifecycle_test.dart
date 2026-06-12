import 'dart:io';

import 'package:orchestration_server/feature_store.dart';
import 'package:test/test.dart';

void main() {
  late String repoRoot;
  late FeatureStore store;
  const id = 'command-lifecycle-test';

  setUp(() {
    repoRoot = Directory.current.path;
    while (!Directory('$repoRoot/.cursor/orchestration').existsSync()) {
      final parent = Directory(repoRoot).parent;
      if (parent.path == repoRoot) throw StateError('repo root not found');
      repoRoot = parent.path;
    }
    store = FeatureStore(repoRoot);
    if (!store.featureExists(id)) {
      store.createFeature(id: id, requirement: 'cmd lifecycle', track: 'S');
    }
  });

  tearDown(() {
    if (store.featureExists(id)) {
      Directory(store.featurePath(id)).deleteSync(recursive: true);
    }
    final specDir = Directory('$repoRoot/specs/$id');
    if (specDir.existsSync()) specDir.deleteSync(recursive: true);
  });

  test('updateCommandMeta streams then finalizes a reply', () {
    final cmd = store.appendCommand(id, prompt: 'what phase?', execute: false);
    final cid = cmd['id'] as String;

    store.updateCommandMeta(id, cid,
        assistantReply: 'Working on', llmSource: 'streaming');
    var current =
        store.listCommands(id).firstWhere((c) => c['id'] == cid);
    expect(current['llm_source'], 'streaming');
    expect(current['assistant_reply'], 'Working on');

    store.updateCommandMeta(id, cid,
        assistantReply: 'Phase 2 of 9 — specify.', llmSource: 'cursor-cli');
    current = store.listCommands(id).firstWhere((c) => c['id'] == cid);
    expect(current['llm_source'], 'cursor-cli');
    expect(current['assistant_reply'], contains('Phase 2'));
  });

  test('markCommandExecuted stamps status and time', () {
    final cmd = store.appendCommand(id, prompt: 'run it', execute: true);
    final cid = cmd['id'] as String;
    store.markCommandExecuted(id, cid, status: 'executed');
    final current = store.listCommands(id).firstWhere((c) => c['id'] == cid);
    expect(current['status'], 'executed');
    expect(current['executed_at'], isNotNull);
  });

  test('listCommands respects the limit window', () {
    for (var i = 0; i < 8; i++) {
      store.appendCommand(id, prompt: 'msg $i', execute: false);
    }
    final window = store.listCommands(id, limit: 3);
    expect(window.length, 3);
    expect(window.last['prompt'], 'msg 7');
  });

  test('clearStuckCommands cancels orphaned running commands', () {
    final cmd = store.appendCommand(id, prompt: 'stuck', execute: true);
    final cid = cmd['id'] as String;
    store.markCommandExecuted(id, cid, status: 'running');
    store.clearStuckCommands(id);
    final current = store.listCommands(id).firstWhere((c) => c['id'] == cid);
    expect(current['status'], 'cancelled');
  });
}
